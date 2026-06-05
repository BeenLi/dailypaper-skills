#!/usr/bin/env python3
"""
Paper Reading Daemon - 后台论文阅读守护进程

功能：
1. 从 Zotero 获取指定分类的论文列表（递归子分类）
2. 调用 Codex 逐篇处理
3. 遇到 rate limit 时自动等待并重试
4. 支持断点续传

用法：
    # 启动守护进程处理 systems 分类
    screen -S paper-daemon
    python3 paper_daemon.py -c "Distributed Systems"

    # 查看进度
    python3 paper_daemon.py --status
"""

import os
import sys
import json
import sqlite3
import shlex
import subprocess
import time
import argparse
import logging
import re
import shutil
import tempfile
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

_SHARED_DIR = Path(__file__).resolve().parents[1] / "_shared"
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))
_ASSETS_DIR = Path(__file__).resolve().parent / "assets"
if str(_ASSETS_DIR) not in sys.path:
    sys.path.insert(0, str(_ASSETS_DIR))

from user_config import concepts_dir, obsidian_vault_path, paper_notes_dir, zotero_db_path, zotero_storage_dir
from zotero_helper import build_note_index, find_matching_notes, infer_method_name, plan_note_save

# 配置
ZOTERO_DB = str(zotero_db_path())
ZOTERO_STORAGE = str(zotero_storage_dir())
OBSIDIAN_VAULT = str(obsidian_vault_path())
PAPER_NOTES_ROOT = str(paper_notes_dir())
CONCEPTS_ROOT = str(concepts_dir())
_DAEMON_STATE_DIR = os.path.expanduser(os.environ.get("PAPER_DAEMON_STATE_DIR", "~/.codex"))
_CODEX_BIN = os.environ.get("PAPER_DAEMON_CODEX_BIN", "codex")
_CODEX_WORKDIR = os.environ.get("PAPER_DAEMON_CODEX_WORKDIR", OBSIDIAN_VAULT)
_CODEX_MODEL = os.environ.get("PAPER_DAEMON_CODEX_MODEL", "").strip()
_CODEX_EXTRA_ARGS = os.environ.get("PAPER_DAEMON_CODEX_ARGS", "")
PROGRESS_FILE = os.path.join(_DAEMON_STATE_DIR, "paper_daemon_progress.json")
LOG_FILE = os.path.join(_DAEMON_STATE_DIR, "paper_daemon.log")
PID_FILE = os.path.join(_DAEMON_STATE_DIR, "paper_daemon.pid")

# Rate limit 配置
INITIAL_WAIT = 60          # 初始等待时间（秒）
MAX_WAIT = 21600           # 最大等待时间（6小时）
WAIT_MULTIPLIER = 2        # 等待时间倍数
BETWEEN_PAPERS_WAIT = 5    # 论文之间的等待时间（秒）
QUOTA_WAIT_TIME = 1800     # 命中配额上限时的默认等待时间（30分钟）

# 设置日志
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def acquire_lock() -> bool:
    """获取进程锁，防止重复运行"""
    if os.path.exists(PID_FILE):
        with open(PID_FILE, 'r') as f:
            old_pid = f.read().strip()
        # 检查进程是否还在运行
        try:
            os.kill(int(old_pid), 0)
            return False  # 进程还在运行
        except (OSError, ValueError):
            pass  # 进程已结束，可以继续

    # 写入当前 PID
    with open(PID_FILE, 'w') as f:
        f.write(str(os.getpid()))
    return True


def release_lock():
    """释放进程锁"""
    if os.path.exists(PID_FILE):
        os.remove(PID_FILE)


def wait_for_quota_reset(wait_seconds: Optional[int] = None):
    """等待配额重置或人工恢复后再继续。"""
    if wait_seconds is None:
        wait_seconds = QUOTA_WAIT_TIME
    wait_minutes = max(1, wait_seconds // 60)
    logger.info(f"⏳ 配额受限，等待 {wait_minutes} 分钟...")
    time.sleep(wait_seconds)


def detect_limit_error(output: str) -> Optional[str]:
    """识别限额/限速错误类型"""
    text = output.lower()
    if 'rate limit' in text or 'too many requests' in text:
        return 'RATE_LIMIT'
    if 'hit your limit' in text or 'usage limit' in text or 'resets' in text:
        return 'QUOTA_LIMIT'
    return None


def parse_reset_wait_seconds(message: str) -> Optional[int]:
    """
    解析 "resets 9pm (Asia/Shanghai)" 等提示，计算等待秒数
    """
    match = re.search(
        r'resets\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?(?:\s*\(([^)]+)\))?',
        message,
        re.IGNORECASE
    )
    if not match:
        return None

    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    ampm = (match.group(3) or '').lower()
    tz_name = match.group(4) or 'Asia/Shanghai'

    if ampm == 'pm' and hour < 12:
        hour += 12
    if ampm == 'am' and hour == 12:
        hour = 0

    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        return None

    now = datetime.now(tz)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target = target + timedelta(days=1)

    wait_seconds = int((target - now).total_seconds())
    return max(60, wait_seconds)


def copy_zotero_db() -> str:
    """复制 Zotero 数据库以避免锁定"""
    fd, tmp_db = tempfile.mkstemp(prefix="zotero_readonly_", suffix=".sqlite")
    os.close(fd)
    shutil.copy2(ZOTERO_DB, tmp_db)
    return tmp_db


def get_collection_id_and_path(db_path: str, collection_name: str) -> tuple[Optional[int], Optional[str]]:
    """根据分类名称获取 ID 和完整路径"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("SELECT collectionID, collectionName, parentCollectionID FROM collections")
    collections = {row[0]: {'name': row[1], 'parent': row[2]} for row in cursor.fetchall()}

    def get_path(cid):
        path_parts = []
        current = cid
        while current:
            if current in collections:
                path_parts.insert(0, collections[current]['name'])
                current = collections[current]['parent']
            else:
                break
        return '/'.join(path_parts)

    for cid, info in collections.items():
        if info['name'].lower() == collection_name.lower():
            conn.close()
            return cid, get_path(cid)
        if collection_name.lower() in info['name'].lower():
            conn.close()
            return cid, get_path(cid)

    conn.close()
    return None, None


def get_all_child_collections(db_path: str, collection_id: int) -> list[int]:
    """递归获取所有子分类ID（包含自身）"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT collectionID, parentCollectionID FROM collections")
    all_collections = cursor.fetchall()
    conn.close()

    children_map = {}
    for cid, parent_id in all_collections:
        if parent_id not in children_map:
            children_map[parent_id] = []
        children_map[parent_id].append(cid)

    result = [collection_id]
    def collect_children(cid):
        if cid in children_map:
            for child_id in children_map[cid]:
                result.append(child_id)
                collect_children(child_id)

    collect_children(collection_id)
    return result


def get_papers_in_collection(db_path: str, collection_id: int) -> list[dict]:
    """获取分类下的所有论文（递归包含子分类）"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    collection_ids = get_all_child_collections(db_path, collection_id)
    placeholders = ','.join('?' * len(collection_ids))
    cursor.execute("SELECT collectionID, collectionName, parentCollectionID FROM collections")
    collections = {row[0]: {'name': row[1], 'parent': row[2]} for row in cursor.fetchall()}

    def get_path(cid: int) -> str:
        path_parts = []
        current = cid
        while current:
            info = collections.get(current)
            if not info:
                break
            path_parts.insert(0, info['name'])
            current = info['parent']
        return '/'.join(path_parts)

    def depth(cid: int) -> int:
        return len([part for part in get_path(cid).split('/') if part])

    query = f"""
        SELECT i.itemID, idv.value as title, ci.collectionID
        FROM items i
        JOIN collectionItems ci ON i.itemID = ci.itemID
        JOIN itemData id ON i.itemID = id.itemID
        JOIN itemDataValues idv ON id.valueID = idv.valueID
        JOIN fields f ON id.fieldID = f.fieldID
        WHERE ci.collectionID IN ({placeholders}) AND f.fieldName = 'title' AND i.itemTypeID != 14
        ORDER BY i.itemID
    """
    cursor.execute(query, collection_ids)
    logger.info(f"递归查询，包含 {len(collection_ids)} 个分类")

    titles: dict[int, str] = {}
    source_candidates: dict[int, list[int]] = {}
    for item_id, title, source_collection_id in cursor.fetchall():
        titles[item_id] = title
        source_candidates.setdefault(item_id, []).append(source_collection_id)

    papers = []
    for item_id, candidate_ids in source_candidates.items():
        source_collection_id = sorted(candidate_ids, key=lambda cid: (-depth(cid), get_path(cid)))[0]
        papers.append(
            {
                'item_id': item_id,
                'title': titles[item_id],
                'source_collection_path': get_path(source_collection_id),
            }
        )
    conn.close()
    return sorted(papers, key=lambda paper: paper['title'])


def get_pdf_path(db_path: str, item_id: int) -> Optional[str]:
    """获取论文的 PDF 路径"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT ia.path, items.key
        FROM itemAttachments ia
        JOIN items ON ia.itemID = items.itemID
        WHERE ia.parentItemID = ? AND ia.contentType = 'application/pdf'
    """, (item_id,))

    row = cursor.fetchone()
    conn.close()

    if row:
        path, key = row
        if path and path.startswith('storage:'):
            filename = path.replace('storage:', '')
            return os.path.join(ZOTERO_STORAGE, key, filename)
    return None


def get_paper_online_source(db_path: str, item_id: int) -> Optional[dict]:
    """
    获取论文的在线来源信息（arXiv ID、DOI、URL）
    用于处理没有 PDF 的论文
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 获取论文的各种字段
    cursor.execute("""
        SELECT f.fieldName, idv.value
        FROM itemData id
        JOIN fields f ON id.fieldID = f.fieldID
        JOIN itemDataValues idv ON id.valueID = idv.valueID
        WHERE id.itemID = ?
    """, (item_id,))

    fields = {row[0]: row[1] for row in cursor.fetchall()}
    conn.close()

    result = {}

    # 检查 arXiv ID (可能在 extra 字段或 archiveID)
    extra = fields.get('extra', '')
    if 'arXiv:' in extra:
        # 格式: arXiv:2401.12345
        match = re.search(r'arXiv[:\s]+(\d{4}\.\d{4,5})', extra, re.IGNORECASE)
        if match:
            result['arxiv_id'] = match.group(1)

    # 检查 DOI
    doi = fields.get('DOI', '')
    if doi:
        result['doi'] = doi

    # 检查 URL
    url = fields.get('url', '')
    if url:
        result['url'] = url
        # 尝试从 URL 提取 arXiv ID
        if 'arxiv.org' in url and 'arxiv_id' not in result:
            match = re.search(r'arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})', url)
            if match:
                result['arxiv_id'] = match.group(1)

    return result if result else None

def load_progress() -> dict:
    """加载进度"""
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, 'r') as f:
            return json.load(f)
    return {'completed': [], 'failed': [], 'current': None, 'started_at': None}


def save_progress(progress: dict):
    """保存进度"""
    os.makedirs(os.path.dirname(PROGRESS_FILE), exist_ok=True)
    with open(PROGRESS_FILE, 'w') as f:
        json.dump(progress, f, indent=2, ensure_ascii=False)


def call_codex(paper_source: dict, collection_path: str, item_id: int, save_plan: Optional[dict] = None) -> tuple[bool, str]:
    """
    调用 Codex 处理论文

    paper_source 可以包含:
    - pdf_path: 本地 PDF 路径
    - arxiv_id: arXiv ID (如 2401.12345)
    - doi: DOI
    - url: 论文 URL
    - title: 论文标题 (用于搜索)
    """

    arxiv_id = paper_source.get('arxiv_id', '')
    notes_root = PAPER_NOTES_ROOT
    concepts_root = CONCEPTS_ROOT

    # 构建来源信息
    source_lines = []
    if paper_source.get('pdf_path'):
        source_lines.append(f"PDF 路径: {paper_source['pdf_path']}")
    if arxiv_id:
        source_lines.append(f"arXiv ID: {arxiv_id}")
        source_lines.append(f"arXiv 页面: https://arxiv.org/abs/{arxiv_id}")
        source_lines.append(f"arXiv PDF: https://arxiv.org/pdf/{arxiv_id}.pdf")
        source_lines.append(f"arXiv HTML (图片): https://arxiv.org/html/{arxiv_id}")
    if paper_source.get('doi'):
        source_lines.append(f"DOI: {paper_source['doi']}")
        source_lines.append(f"DOI 链接: https://doi.org/{paper_source['doi']}")
    if paper_source.get('url'):
        source_lines.append(f"URL: {paper_source['url']}")
    if paper_source.get('title'):
        source_lines.append(f"论文标题: {paper_source['title']}")

    source_info = '\n'.join(source_lines)
    if save_plan:
        save_instruction = f"""Zotero 来源 collection 路径: {collection_path}
Obsidian 保存计划:
- action: {save_plan.get('action')}
- 保存到目标路径: {save_plan.get('target_path')}
- 已有笔记路径: {save_plan.get('existing_path') or '无'}
- frontmatter 更新: {json.dumps(save_plan.get('frontmatter_updates', {}), ensure_ascii=False)}

请严格写入“保存到目标路径”，不要自行决定保存位置；collection_path 只用于理解 Zotero 来源，frontmatter 使用上面的更新值。"""
    else:
        save_instruction = f"""Zotero 来源 collection 路径: {collection_path}
Obsidian 保存计划: 未提供。必须先调用 `zotero_helper.py note-path` 规划 target_path 后再写入。"""

    # 如果没有 PDF，添加特殊说明
    no_pdf_instruction = ""
    if not paper_source.get('pdf_path'):
        fallback_steps = []
        if arxiv_id:
            fallback_steps.extend(
                [
                    f"1. **arXiv HTML 版本**（推荐）: 用 WebFetch 读取 https://arxiv.org/html/{arxiv_id}，可直接获取图片 URL",
                    f"2. **arXiv 摘要页**: 用 WebFetch 读取 https://arxiv.org/abs/{arxiv_id}",
                    f"3. **arXiv PDF**: 下载 https://arxiv.org/pdf/{arxiv_id}.pdf 到本地后用 Read 读取",
                ]
            )
        if paper_source.get('doi'):
            fallback_steps.append(f"{len(fallback_steps) + 1}. **DOI 页面**: 跳转到 https://doi.org/{paper_source['doi']} 读取")
        if paper_source.get('url'):
            fallback_steps.append(f"{len(fallback_steps) + 1}. **原始 URL**: 读取 {paper_source['url']}")
        if not fallback_steps:
            fallback_steps.append("1. 根据标题搜索在线来源，再优先读取可直接获取图片的 HTML 版本")

        no_pdf_instruction = f"""
## 无本地 PDF - 在线获取（重要）

这篇论文没有本地 PDF，请按以下优先级获取内容：

{chr(10).join(fallback_steps)}

优先使用 HTML 版本，因为可以直接获取在线图片链接！
"""

    local_pdf_image_instruction = ""
    if paper_source.get('pdf_path'):
        target_note_name = "note-name"
        if save_plan and save_plan.get("target_path"):
            target_note_name = Path(save_plan["target_path"]).stem
        local_pdf_image_instruction = f"""
## 本地 PDF 图片裁切规则（重要）

这篇论文有本地 PDF。如果图源是本地，请从 PDF 裁切图片，并存放到笔记同目录下：

```text
00_assets/<note-name>_<原图片名>
```

- 当前 note-name: `{target_note_name}`
- note-name ≤ 48 字符：直接用 `<note-name>_` 作为前缀。
- note-name 太长：使用 `截断前 40 字符 + 8 位 hash` 作为前缀，形如 `VeryLongNoteNamePrefix_xxxxxxxx_figure.png`。
- 笔记正文用 `![[00_assets/<note-name>_<原图片名>]]` 引用本地图片。
- 如果所有图片都来自本地 PDF，frontmatter 写 `image_source: local`；如果在线和本地混用，写 `image_source: mixed`。
"""

    prompt = f"""请使用 `paper-reader` skill 读取并分析这篇论文，生成完整的结构化笔记。

{source_info}
Zotero ItemID: {item_id}
{save_instruction}
{no_pdf_instruction}
{local_pdf_image_instruction}

## 质量要求（重要）

参考高质量笔记风格，必须包含：

1. **元信息表格**: 机构、日期、项目主页、主对比基线
2. **内联概念链接**: 在正文中使用 `[[KV Cache]]`、`[[Roofline Model]]`、`[[AllReduce]]` 链接概念，不只是在文末；`skills/paper-reader/references/concept-categories.md` 的 seed list 命中词，首次出现必须写成 `[[概念名]]`
3. **公式格式**: 每个公式后用自然段解读它建模的系统现象、变量角色，以及它支撑的设计或结论；必要时在段落中解释符号
4. **图片格式**: 图片引用自身包含题注/alt（如 `![Figure X: 英文标题 / 中文标题](...)`）+ 自然段解读；不要在图片上方单独写 `**Figure ...**` 标题；优先在线 URL，本地图源必须用 `![[00_assets/<note-name>_<原图片名>]]`；说明图片在论文论证链中的作用、关键趋势或定量证据，禁止保留填空式模板标签；不要把普通 Figure / Table 写成 `###` 大纲标题
5. **系统结构**: `系统架构与执行流` 优先使用 Obsidian Mermaid（默认 `flowchart LR`），随后用自然段解释边界、输入输出、离线/在线分工和支撑的设计或结论
6. **组件与实现**: `系统组成与职责` 必须包含 `#### 模块关系图`，其下方放 Mermaid 模块关系图并用自然段解释模块依赖；不能只用 `系统架构与执行流`、论文原图或组件表替代；`实现改动清单` 按硬件 / software runtime / characterization 条件生成，不要对纯软件论文强行写硬件表
7. **关键机制**: 在 `## 关键机制拆解` 到下一个 `##` 之间，所有 `###` 标题必须是 `### 机制N：...`；`####` 只能用于按论文结构或 Agent 理解提炼出的机制内部语义子小节，例如设计动机、机制流程、算法流程、pipeline stage、实现要点、参数权衡；普通单张 Figure / Table / 单个公式不要单独写成 `####` 小节，必须嵌入机制说明或参数与权衡的自然段；不要单独拆出公式或图示小节；Figure、公式、Mermaid 必须嵌入机制说明或参数与权衡的叙事位置
8. **实验平台**: `实验设置` 的 `模拟器与微架构参数` 小节必须根据论文 evaluation platform 画一张 Mermaid 测试系统连接关系图，展示 client / benchmark driver / scheduler or runtime / worker / accelerator / memory / network / storage / simulator 的连接关系和硬件资源需求；可以删减和图重复的参数表细节，不要硬塞 CPU pipeline、BTB、ROB 等微架构参数，除非它们就是评测对象
9. **批判性思考**: 优点、局限与隐含假设、可能失效场景、潜在改进方向
10. **经验与复现**: 单独写 `经验与可迁移启示` 和 `复现`；复现包含环境依赖、关键配置 / workload / data、`复现核查表`、风险与缺口；核查表使用普通 Markdown table 或普通 bullet，禁止使用 `- [ ]` / `- [x]` task list
11. **关联笔记分类**: 分为 "方法相关"、"理论 / 指标相关"、"系统 / 硬件相关"
12. **速查卡片**: Obsidian `[!summary]` 格式的快速参考
13. **结构约束**: 不要单独写 `## 关键公式` 或 `## 关键图表`；公式和图片必须嵌入“问题定义与瓶颈 / 系统设计总览 / 关键机制拆解 / 实验设置 / 核心结果 / Overhead 与兼容性”这些章节里；生成后做 template check，确认大纲层级遵循 `assets/paper-note-template.md`
14. **相关工作定位**: 表头使用“论文 / 外部链接 / 关系 / 差异”；`论文` 列优先写 `[[笔记名]]`，没有内部笔记时写纯标题；`外部链接` 列写 `[arXiv](...)` / `[DOI](...)` / `[Paper](...)`，没有就留空

## 处理规则

1. **图片优先在线链接**：先检查 arXiv HTML 版本 (arxiv.org/html/xxx)，有则用在线图片 URL；如果图源是本地 PDF，则从 PDF 裁切到 `00_assets/<note-name>_<原图片名>`
2. **不要生成 Obsidian task**：论文笔记正文禁止出现 `- [ ]` / `- [x]`；复现核查、后续步骤和风险项都写成普通表格或普通 bullet

## 概念库更新（必须执行）

**每篇论文处理完后，必须为新遇到的技术概念创建笔记！**

### 概念库位置
{concepts_root}

### 需要创建概念笔记的情况
1. 论文中首次遇到的技术术语（如 KV Cache, Roofline Model, AllReduce, Kernel Fusion, RDMA）
2. 论文提出的新方法名（如果是通用概念）
3. 在笔记中使用了 [[概念]] 链接但该概念笔记不存在
4. seed list 命中但概念库不存在的 systems 基石术语（如 RDMA, NVLink, PCIe, NUMA, HBM, CXL, AllReduce, NCCL, CUDA）

### 过滤默认规则

- 宁可漏判几个通用词，也不要误杀真正的 systems concept；不确定就创建，后续再 review。
- `Admission Control`、`Kernel Fusion`、`RDMA`、`NVLink`、`PCIe`、`NUMA`、`HBM`、`CXL`、`AllReduce`、`NCCL`、`CUDA` 等 seed list 或 systems 基石术语必须保留为候选。
- 数据集 / 仿真器不作为 concept；不要为数据集、benchmark suite、仿真器、纯实验环境名称创建 concept。

### 概念笔记格式（增强版，长度目标 60-100 行）

每篇 concept 笔记 8 个统一段 + 1 个按 concept_type 加的差异化段。**禁止凭空编造**：动机 / 直观例子只能从论文证据推断，找不到证据就写 TODO；学习索引允许整段写 `TODO: 待人工补充学习材料`。

```markdown
---
type: concept
aliases: [别名1, 别名2]
concept_type: <从下面 8 类选一>
tags: [status/paper-specific]  # 仅在仅被本论文使用时加，否则省略
---

# 概念名称

## 定义
一句话定义。只解释 what，不解释 why。

## 动机与痛点
为什么会出现这个 concept？它解决什么瓶颈？跟之前的做法相比，核心改进是什么？

## 直观例子
用 1 个具体场景走一遍 concept。可以是 mini walk-through、伪代码、ASCII 状态图或 Mermaid。

## 核心要点
3-5 条，每条解释原理，不只是 fact 列表。

<!-- 按 concept_type 加差异化段：data-structure → 内存视图；algorithm → 步骤+复杂度；
     mechanism → 状态与触发条件+关键参数；architecture → 组件与接口(必 Mermaid)；
     hardware → 接口与典型参数；software-abstraction → API 与生命周期；
     metric → 测量方法；theory-model → 假设与失效边界 -->

## 边界与对比
- 什么情况不适用 / 反模式
- 和最容易混淆的近邻 concept 的差别

## 代表工作与具体用法
- [[论文1]]: 它怎么用这个 concept？用出什么效果？
- [[论文2]]: 同上

## 相关概念
- [[相关概念1]]: 和本概念的关系（组成/替代/协作/前置）

## 学习索引
- 入门 paper / 综述：必须有具体标题或 URL；找不到就整段 `TODO: 待人工补充学习材料`
- 经典 blog / 教科书章节：必须有 URL
- 关键 GitHub 实现（可选）
```

详细模板和按 concept_type 差异化段说明见 `skills/paper-reader/references/concept-categories.md`。

### 分类规则（单一信源）

概念**按概念本身的性质**分类，不按论文研究领域分类。完整归类标准、判定原则、paper-method 处理规约见 `skills/paper-reader/references/concept-categories.md`。

`concept_type` 必须从下面 8 类中选：

- `data-structure`：数据格式 / 表示 / 结构（BFloat16, KV Cache, FP8）
- `algorithm`：脱离系统也成立的纯计算逻辑（Huffman Coding, Arithmetic Coding）
- `mechanism`：绑定系统上下文的运行时策略（PagedAttention, Kernel Fusion, Micro-Batching）
- `architecture`：宏观系统架构 / 服务模式（LLM Serving, Parameter Server）
- `hardware`：硬件部件 / 计算单元 / 物理互联（Tensor Core, SIMT, NVLink, HBM）
- `software-abstraction`：OS / 框架层接口与协议（CUDA, MPI, NCCL, vLLM Engine）
- `metric`：评估指标 / 测量口径（SLO, TTFT, Tail Latency）
- `theory-model`：性能数学模型 + 纯数学基础（Roofline Model, Error Function）

**algorithm vs mechanism**：脱离系统是否成立？成立 → algorithm，不成立 → mechanism。

**paper-method 三档处理**：
- 论文首创 + 仅本论文实验：落到最接近的 `concept_type`，并加 `tags: [status/paper-specific]`
- 论文具名实现 + 前人工作 / 被多篇当 baseline：直接升格为通用 concept，不加 `status/paper-specific`；在论文笔记里讲清该论文的具名实现细节
- 完全是前人工作 + 该论文只是引用：不该独立成 concept，只在论文笔记内提及或链接已有 concept

**禁止**自创新的顶级目录（如 "1-生成模型 / 论文方法名" 等）。

### 执行步骤
1. 分析完论文后，列出笔记中所有 [[概念]] 链接
2. 用 `ls {concepts_root}` 查看已有的 8 个 concept_type 目录；对每个概念**递归**查找是否已存在
3. 对于不存在的概念，按上面 8 类选定 `concept_type`，落到对应子目录
4. paper-method 按上面的三档规则处理；不要把纯前人工作或仅被引用的 baseline 独立成 concept
5. 使用 Write 工具写入概念笔记

## Zotero 与保存规则（重要）

- Zotero 默认只读；不要移动、添加或删除 Zotero collection。
- 如果你判断 Zotero 分类明显不对，只在笔记末尾或执行总结中提出建议和理由，不要调用修改 Zotero 的命令。
- `zotero_item_id` 与 `zotero_collection` 必须按“frontmatter 更新”中的值写入 frontmatter。
- 不要把未清洗的 Zotero 来源 collection 路径直接写入 `zotero_collection`。

## 保存位置

- “保存到目标路径”是唯一权威写入位置。
- 不要用 `{notes_root}/{collection_path}/` 自行拼路径；Python 侧已完成 collection path 清洗与冲突处理。
- 文件名只用方法名 / 系统名；如果保存计划已给出文件名，沿用目标路径。
- 不确定方法名时保存为保守的论文标题，但仍必须先经过保存计划规划路径。

请直接开始处理，不需要确认。提取所有公式、图片和表格。"""

    try:
        cmd = [
            _CODEX_BIN,
            'exec',
            '--full-auto',
            '--skip-git-repo-check',
            '-C',
            _CODEX_WORKDIR,
        ]
        if _CODEX_MODEL:
            cmd.extend(['--model', _CODEX_MODEL])
        if _CODEX_EXTRA_ARGS:
            cmd.extend(shlex.split(_CODEX_EXTRA_ARGS))
        cmd.append(prompt)

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=900  # 15分钟超时（因为要提取图片）
        )

        output = result.stdout + result.stderr

        limit_type = detect_limit_error(output)
        if limit_type == 'RATE_LIMIT':
            return False, 'RATE_LIMIT'
        if limit_type == 'QUOTA_LIMIT':
            return False, f'QUOTA_LIMIT|{output[:200]}'

        if result.returncode == 0:
            return True, ''
        else:
            return False, output[:500]

    except subprocess.TimeoutExpired:
        return False, 'TIMEOUT'
    except Exception as e:
        return False, str(e)


def process_collection(collection_name: str, resume: bool = True):
    """处理整个分类的论文"""
    logger.info(f"=== 开始处理分类: {collection_name} ===")

    db_path = copy_zotero_db()
    try:
        collection_id, collection_path = get_collection_id_and_path(db_path, collection_name)
        if not collection_id:
            logger.error(f"找不到分类: {collection_name}")
            return

        logger.info(f"分类路径: {collection_path} (ID: {collection_id})")

        papers = get_papers_in_collection(db_path, collection_id)
        logger.info(f"分类下共有 {len(papers)} 篇论文")

        progress = load_progress() if resume else {'completed': [], 'failed': [], 'current': None, 'started_at': None}
        if not progress['started_at']:
            progress['started_at'] = datetime.now().isoformat()

        # 获取已有笔记索引。包含 _inbox，排除 _concepts 和 _index_ MOC。
        note_index = build_note_index(Path(PAPER_NOTES_ROOT))
        logger.info(f"Obsidian 中已有 {len(note_index.records)} 篇可查重论文笔记")

        # 过滤待处理论文
        pending = []
        skipped_existing = 0
        for paper in papers:
            item_id = paper['item_id']
            title = paper['title']
            source_collection_path = paper.get('source_collection_path') or collection_path

            if item_id in progress['completed']:
                continue

            online_source = get_paper_online_source(db_path, item_id) or {}
            method_name = infer_method_name(title)
            matches = find_matching_notes(
                Path(PAPER_NOTES_ROOT),
                zotero_item_id=item_id,
                doi=online_source.get('doi'),
                arxiv_id=online_source.get('arxiv_id'),
                title=title,
                method_name=method_name,
                index=note_index,
            )
            save_plan = plan_note_save(
                Path(PAPER_NOTES_ROOT),
                method_name,
                source_collection_path,
                batch=True,
                zotero_item_id=item_id,
                doi=online_source.get('doi'),
                arxiv_id=online_source.get('arxiv_id'),
                title=title,
                matches=matches,
            )

            # 检查是否已有笔记
            if save_plan["action"] == "conflict":
                logger.warning(f"跳过 (查重冲突，需要人工处理): {title[:50]} -> {save_plan.get('candidate_paths')}")
                skipped_existing += 1
                continue
            if save_plan["action"] == "skip":
                logger.info(f"跳过 (已有笔记): {title[:50]}")
                skipped_existing += 1
                progress['completed'].append(item_id)  # 标记为已完成
                continue

            pdf_path = get_pdf_path(db_path, item_id)
            paper_source = {'title': title, **online_source}

            if pdf_path and os.path.exists(pdf_path):
                paper_source['pdf_path'] = pdf_path
            else:
                # 尝试获取在线来源
                if online_source:
                    logger.info(f"无本地 PDF，使用在线来源: {list(online_source.keys())}")
                else:
                    logger.warning(f"跳过 (无PDF且无在线来源): {title[:50]}")
                    continue

            pending.append({**paper, 'source': paper_source, 'source_collection_path': source_collection_path, 'save_plan': save_plan})

        if skipped_existing > 0:
            logger.info(f"跳过已有笔记: {skipped_existing} 篇")
            save_progress(progress)

        logger.info(f"待处理: {len(pending)} 篇")

        wait_time = INITIAL_WAIT

        for i, paper in enumerate(pending):
            item_id = paper['item_id']
            title = paper['title']
            paper_source = paper['source']
            source_collection_path = paper.get('source_collection_path') or collection_path
            save_plan = paper['save_plan']

            source_type = "PDF" if paper_source.get('pdf_path') else "在线"
            logger.info(f"\n[{i+1}/{len(pending)}] 处理 ({source_type}): {title[:60]}...")
            progress['current'] = {'item_id': item_id, 'title': title}
            save_progress(progress)

            success, error = call_codex(paper_source, source_collection_path, item_id, save_plan)

            if success:
                logger.info(f"✓ 完成: {title[:50]}")
                progress['completed'].append(item_id)
                progress['current'] = None
                save_progress(progress)
                wait_time = INITIAL_WAIT

                if i < len(pending) - 1:
                    time.sleep(BETWEEN_PAPERS_WAIT)

            elif error == 'RATE_LIMIT':
                logger.warning(f"⏳ Rate limit, 等待 {wait_time} 秒...")
                time.sleep(wait_time)
                wait_time = min(wait_time * WAIT_MULTIPLIER, MAX_WAIT)
                pending.insert(i + 1, paper)  # 重新加入队列

            elif error.startswith('QUOTA_LIMIT'):
                reset_wait = parse_reset_wait_seconds(error)
                if reset_wait:
                    logger.warning(f"⏳ 用量上限，等待到重置（约 {reset_wait // 60} 分钟）...")
                    time.sleep(reset_wait)
                else:
                    wait_for_quota_reset()
                pending.insert(i + 1, paper)  # 重新加入队列

            elif error == 'TIMEOUT':
                logger.error(f"✗ 超时: {title[:50]}")
                progress['failed'].append({'item_id': item_id, 'title': title, 'error': 'TIMEOUT'})
                save_progress(progress)

            else:
                logger.error(f"✗ 失败: {title[:50]} - {error[:100]}")
                progress['failed'].append({'item_id': item_id, 'title': title, 'error': error[:200]})
                save_progress(progress)

        progress['current'] = None
        progress['finished_at'] = datetime.now().isoformat()
        save_progress(progress)

        logger.info("\n=== 处理完成 ===")
        logger.info(f"成功: {len(progress['completed'])} 篇")
        logger.info(f"失败: {len(progress['failed'])} 篇")
    finally:
        Path(db_path).unlink(missing_ok=True)


def show_status():
    """显示当前进度"""
    progress = load_progress()
    print("\n=== Paper Daemon 状态 ===")
    print(f"开始时间: {progress.get('started_at', 'N/A')}")
    print(f"完成时间: {progress.get('finished_at', '进行中...')}")
    print(f"已完成: {len(progress.get('completed', []))} 篇")
    print(f"失败: {len(progress.get('failed', []))} 篇")

    current = progress.get('current')
    if current:
        print(f"当前处理: {current.get('title', 'N/A')[:60]}")

    if progress.get('failed'):
        print("\n失败的论文:")
        for item in progress['failed'][:5]:
            print(f"  - {item['title'][:50]}: {item['error'][:50]}")


def main():
    parser = argparse.ArgumentParser(description='Paper Reading Daemon')
    parser.add_argument('--collection', '-c', type=str, help='Zotero 分类名称')
    parser.add_argument('--status', '-s', action='store_true', help='显示当前状态')
    parser.add_argument('--no-resume', action='store_true', help='不恢复之前的进度')
    parser.add_argument('--list', '-l', action='store_true', help='列出所有 Zotero 分类')

    args = parser.parse_args()

    if args.status:
        show_status()
        return

    if args.list:
        db_path = copy_zotero_db()
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT c.collectionName, COUNT(ci.itemID) as count
            FROM collections c
            LEFT JOIN collectionItems ci ON c.collectionID = ci.collectionID
            GROUP BY c.collectionID
            HAVING count > 0
            ORDER BY c.collectionName
        """)
        print("\n=== Zotero 分类 ===")
        for name, count in cursor.fetchall():
            print(f"  {name}: {count} 篇")
        conn.close()
        return

    if not args.collection:
        parser.print_help()
        return

    # 检查是否已有进程在运行
    if not acquire_lock():
        logger.error("另一个 paper_daemon 进程正在运行！请先停止它或删除 ~/.codex/paper_daemon.pid")
        return

    try:
        process_collection(args.collection, resume=not args.no_resume)
    finally:
        release_lock()


if __name__ == '__main__':
    main()
