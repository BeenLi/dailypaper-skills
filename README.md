# dailypaper-skills

面向 `computer architecture / networking / distributed systems / LLM systems` 的 Codex skills 集合。目标是把论文发现、论文阅读、Zotero 文献库和 Obsidian 笔记库连成一条可维护的本地工作流。

> 📺 [论文流水线效果演示（旧视频）](http://xhslink.com/o/1dhQCn40EWY) — 展示的是同一套工作流的早期版本。

## 这个仓库解决什么问题

- 每天抓取 systems / LLM infra 相关论文，生成带判断的推荐列表。
- 对单篇论文生成 Obsidian 兼容的 Markdown 笔记。
- 从 Zotero 读取论文、PDF、元数据和 collection path，并按 Zotero collection 层级保存笔记。
- 自动维护概念库：用 `[[wikilink]]` 连接论文与概念，并按 concept type 归类。
- 生成 / 刷新论文目录页和概念目录页。

输出结构大致如下：

```text
ObsidianVault/
├── DailyPapers/
│   ├── YYYY-MM-DD-论文推荐.md
│   └── .history.json
└── PaperNotes/
    ├── Research Topics/.../{MethodName}.md
    ├── _concepts/{concept_type}/{ConceptName}.md
    ├── _inbox/{MethodName}.md
    └── _index_*.md
```

核心模板：[`skills/paper-reader/assets/paper-note-template.md`](skills/paper-reader/assets/paper-note-template.md)

## 快速使用

最常用的入口只有两个：

```text
今日论文推荐
读一下这篇论文 https://arxiv.org/abs/2509.24527
```

常见变体：

```text
过去3天论文推荐
过去一周论文推荐

读一下这篇论文 ~/Downloads/paper.pdf
快速看一下这篇论文 https://arxiv.org/abs/2509.24527
批判性分析这篇论文 ~/Downloads/paper.pdf

读一下 Zotero 里的 vLLM
读一下 Zotero item 2487
批量读一下 Zotero 里 Link & Fabric Integration 分类下的论文

更新索引
```

`今日论文推荐` 默认只做“抓取 + 点评”，**不会自动精读生成论文笔记**。如果某篇值得细看，再运行 `读一下 论文标题` 或 `跑一下论文笔记`。

## 安装

前置环境：

- Codex CLI
- Obsidian
- Python 3.10+（推荐 3.13，本仓库测试使用 Python 3.13）
- `poppler` / `poppler-utils`（提供 `pdftotext`、`pdfimages`）
- Zotero（可选，但推荐）
- `mmdc`（可选，用于校验 Mermaid 图）

安装 skills：

```bash
mkdir -p ~/.codex/skills
cp -R ./skills/* ~/.codex/skills/
```

如果你是在本仓库内持续开发，也可以用软链接，避免每次修改后重复复制：

```bash
mkdir -p ~/.codex/skills
ln -sfn "$PWD/skills/paper-reader" ~/.codex/skills/paper-reader
ln -sfn "$PWD/skills/daily-papers" ~/.codex/skills/daily-papers
ln -sfn "$PWD/skills/daily-papers-fetch" ~/.codex/skills/daily-papers-fetch
ln -sfn "$PWD/skills/daily-papers-review" ~/.codex/skills/daily-papers-review
ln -sfn "$PWD/skills/daily-papers-notes" ~/.codex/skills/daily-papers-notes
ln -sfn "$PWD/skills/generate-mocs" ~/.codex/skills/generate-mocs
ln -sfn "$PWD/skills/_shared" ~/.codex/skills/_shared
```

初始化 Obsidian 目录：

```bash
VAULT=~/ObsidianVault
mkdir -p "$VAULT/DailyPapers" \
  "$VAULT/PaperNotes/_concepts" \
  "$VAULT/PaperNotes/_inbox"
```

## 配置

共享配置位于：

```text
~/.codex/skills/_shared/user-config.json
```

建议不要直接改默认模板，而是在同目录创建 `user-config.local.json` 覆盖个人路径和关键词。加载顺序是：

1. `user-config.py` 内置默认值
2. `user-config.json`
3. `user-config.local.json`

核心配置项：

| 配置项 | 说明 |
|---|---|
| `paths.obsidian_vault` | Obsidian vault 根路径 |
| `paths.paper_notes_folder` | 论文笔记目录名，默认 `PaperNotes` |
| `paths.daily_papers_folder` | 每日推荐目录名，默认 `DailyPapers` |
| `paths.concepts_folder` | 概念库目录名，默认 `_concepts` |
| `paths.zotero_db` | Zotero `zotero.sqlite` 路径 |
| `paths.zotero_storage` | Zotero 附件目录 |
| `daily_papers.keywords` | 论文打分主关键词 |
| `daily_papers.negative_keywords` | 命中后直接排除的方向 |
| `daily_papers.domain_boost_keywords` | systems 相关性加分词 |
| `daily_papers.arxiv_categories` | arXiv API 查询分类 |
| `daily_papers.min_score` | 候选最低分 |
| `daily_papers.top_n` | 单日候选上限 |
| `automation.auto_refresh_indexes` | 是否自动刷新 MOC |
| `automation.git_commit` | 是否自动 commit Obsidian vault |
| `automation.git_push` | 是否自动 push，只有 `git_commit=true` 时才生效 |
| `mocs.filename_prefix` | MOC 文件名前缀，当前推荐 `_index_` |

## 核心工作流

### 每日论文推荐

`daily-papers` 是面向用户的一句话入口。内部自动串联：

1. `daily-papers-fetch`
   - 抓 DBLP proceedings / journal pages、会议 program pages、arXiv API。
   - 候选不足时补 Semantic Scholar。
   - 按配置关键词打分、去重、历史过滤。
   - 输出 `/tmp/daily_papers_top30.json` 和 `/tmp/daily_papers_enriched.json`。
2. `daily-papers-review`
   - 读取富化后的候选。
   - 按主推 / 备选 / 可跳过分流。
   - 保存 `{DailyPapers}/YYYY-MM-DD-论文推荐.md`。
   - 更新 `.history.json` 做 30 天去重。

默认不执行 `daily-papers-notes`，避免一次推荐直接生成大量长笔记。

### 单篇论文阅读

`paper-reader` 支持：

- 本地 PDF
- arXiv 链接
- DOI / 网页链接
- Zotero item
- Zotero 搜索
- Zotero collection 批量处理

保存规则：

- 文件名使用主方法名 / 系统名：`{MethodName}.md`
- 有 Zotero collection 时保存到 `{PaperNotes}/{selected_collection_path}/{MethodName}.md`
- 没有 collection 时保存到 `{PaperNotes}/_inbox/{MethodName}.md`
- `zotero_item_id`、`doi`、`arxiv_id` 写入 frontmatter，用于后续精确去重
- 批量模式默认跳过已有笔记，避免重新分类或误移动

Zotero 默认只读。系统只读取论文、PDF、元数据和 collection path；如果发现分类不合理，只给建议，不主动修改 Zotero 数据库。

### 概念库

概念笔记放在 `{PaperNotes}/_concepts/` 下，按概念本身性质归为 8 类：

| concept_type | 示例 |
|---|---|
| `data-structure` | `KV Cache`, `BFloat16`, `Bloom Filter` |
| `algorithm` | `AllReduce`, `Huffman Coding`, `Raft` |
| `mechanism` | `PagedAttention`, `Kernel Fusion`, `Continuous Batching` |
| `architecture` | `LLM Serving`, `Parameter Server` |
| `hardware` | `Tensor Core`, `RDMA`, `NVLink`, `HBM` |
| `software-abstraction` | `CUDA`, `NCCL`, `MPI`, `vLLM Engine` |
| `metric` | `TTFT`, `SLO`, `MPKI`, `Goodput` |
| `theory-model` | `Roofline Model`, `Amdahl's Law`, `Little's Law` |

规则来源：[`skills/paper-reader/references/concept-categories.md`](skills/paper-reader/references/concept-categories.md)

离线扫描缺失概念：

```bash
python3 skills/_shared/scan_missing_concepts.py --dry-run
python3 skills/_shared/scan_missing_concepts.py --with-seed --output /tmp/missing_concepts.csv
```

扫描逻辑会排除 `_concepts/`、`_inbox/`、`_index_*.md`，并排除论文笔记之间的互链，避免把论文标题误报成 missing concept。

### 目录页

`generate-mocs` 调用两个共享脚本：

```bash
python3 skills/_shared/generate_concept_mocs.py
python3 skills/_shared/generate_paper_mocs.py
```

脚本递归扫描目录，生成 `_index_*.md` 目录页。重复运行应保持幂等。

## 仓库结构

```text
skills/
├── daily-papers/          # 每日推荐编排入口
├── daily-papers-fetch/    # 抓取与富化说明
├── daily-papers-review/   # 推荐点评说明
├── daily-papers-notes/    # 可选批量精读与链接回填
├── generate-mocs/         # 手动刷新目录页入口
├── paper-reader/          # 单篇 / Zotero 论文阅读主 skill
│   ├── assets/
│   │   ├── paper-note-template.md
│   │   ├── zotero_helper.py
│   │   └── reorganize_notes.py
│   └── references/
│       ├── concept-categories.md
│       ├── image-troubleshooting.md
│       ├── quality-standards.md
│       └── zotero-guide.md
└── _shared/
    ├── user_config.py
    ├── user-config.json
    ├── generate_concept_mocs.py
    ├── generate_paper_mocs.py
    ├── moc_builder.py
    └── scan_missing_concepts.py
```

测试：

```bash
pytest tests/
```

## 常用维护命令

```bash
# 跑全量测试
pytest tests/

# 检查每日候选抓取
python3 skills/daily-papers/fetch_and_score.py > /tmp/daily_papers_top30.json
cat /tmp/daily_papers_top30.json | python3 skills/daily-papers/enrich_papers.py /tmp/daily_papers_enriched.json

# 扫缺失概念
python3 skills/_shared/scan_missing_concepts.py --dry-run

# 刷新 MOC
python3 skills/_shared/generate_concept_mocs.py
python3 skills/_shared/generate_paper_mocs.py
```

## FAQ

**今日论文推荐会自动生成精读笔记吗？**

不会。默认只生成推荐文件。精读需要用户显式运行 `读一下 论文标题` 或 `跑一下论文笔记`。

**为什么用 Zotero collection path 保存笔记？**

Zotero 是文献来源的权威组织结构。按 collection path 落盘可以避免用关键词猜分类，也能让 Obsidian 目录和 Zotero 目录保持一致。

**如果一篇论文已经有笔记，怎么判断重复？**

优先用 frontmatter 中的 `zotero_item_id`、`doi`、`arxiv_id` 精确匹配，再退到规范化标题 / 方法名匹配。批量模式默认跳过已有笔记。

**不用 Zotero 可以吗？**

可以。每日推荐不依赖 Zotero；单篇阅读也支持 arXiv 链接和本地 PDF。Zotero 只用于本地文献库检索、PDF 定位和 collection path。

**不用 Obsidian 可以吗？**

可以。输出本质是 Markdown 文件；只是 `[[wikilink]]`、目录页和图谱在 Obsidian 里更好用。

**默认会动 git 吗？**

不会。`git_commit` 和 `git_push` 默认关闭。

## 免责声明

这是个人研究工作流的开源整理。AI 生成的推荐、点评和笔记可能有事实错误或遗漏，应作为阅读辅助而不是研究判断的替代品。

## License

Apache-2.0. See [`LICENSE`](LICENSE).
