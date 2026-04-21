---
name: paper-reader
description: |
  Use when user asks to "read paper", "analyze paper", "summarize paper",
  "读论文", "分析文献", "帮我看一下这篇paper", "论文笔记", or provides a PDF file
  that appears to be an academic paper. Specialized for systems / architecture /
  networking / LLM systems papers.

  Also supports Zotero integration: "读一下这篇论文 ...", "快速看一下这篇论文 ...",
  "批判性分析这篇论文 ...", "读一下 Zotero 里的 XXX", "批量读一下 Zotero 里 Distributed Systems 分类下的论文"

  **重要触发词**: "读一下 XXX"、"读一下这篇"、"帮我读" → 必须调用此 skill
---

> **开始前**: 先跟用户打个招呼 🐕

# 学术论文阅读助手 (Paper Reader)

面向 `systems / architecture / networking / LLM systems` 的论文阅读与 Obsidian 笔记保存。

## Step 0: 读取共享配置

先读取 `../_shared/user-config.json`，如果 `../_shared/user-config.local.json` 存在，再用它覆盖默认值。

显式生成并统一使用：

- `VAULT_PATH`
- `NOTES_PATH`
- `CONCEPTS_PATH`
- `ZOTERO_DB`
- `ZOTERO_STORAGE`
- `AUTO_REFRESH_INDEXES`
- `GIT_COMMIT_ENABLED`
- `GIT_PUSH_ENABLED`

## 1. 接收论文

| 输入方式 | 示例 | 处理方法 |
|----------|------|----------|
| PDF 路径 | `/path/to/paper.pdf` | 直接 Read |
| arXiv 链接 | `https://arxiv.org/abs/xxxx` | WebFetch |
| Zotero 分类 | "Distributed Systems 分类的论文" | 查询数据库 → 列出 → 用户选择 |
| Zotero 搜索 | "Zotero 里的 vLLM" | 搜索标题 → 找到 PDF |
| 无 PDF | Zotero 条目无附件 | 从网上获取（见下方） |

无 PDF 时优先：`arXiv HTML > arXiv PDF > DOI > WebSearch 标题`。

## 2. 阅读模式

| 模式 | 触发词 | 输出 |
|------|--------|------|
| **快速摘要** | "快速看一下"、"quick" | 3-5 句核心贡献 |
| **完整解析** | "详细分析"、默认 | 结构化笔记（用模板） |
| **批判分析** | "批判性分析"、"critique" | 方法论优缺点评估 |
| **知识提取** | "提取公式"、"技术细节" | 公式 + 系统机制拆解 |

## 3. 笔记生成

严格遵循 `assets/paper-note-template.md`。

### 核心质量规则

1. 所有 Figure、公式、Table 都必须出现。
2. 技术术语首次出现要加 `[[概念]]` 链接。
3. 不用 ASCII 流程图；改用结构化 Markdown 和必要公式。
4. 公式必须有名称、LaTeX、含义、符号说明。
5. 图片优先外链 arXiv HTML / 项目主页，失败再本地下载。

### systems 方向额外要求

- 讲清 bottleneck、优化对象、工作负载、系统假设。
- 对 runtime / compiler / networking / memory / scheduling 这类关键机制，优先按数据流或执行流程解释。
- 读 LLM systems 论文时，不要把重点写成模型能力；重点是计算、存储、通信和调度机制。
- 笔记必须包含 `实验设置`、`核心结果`、`Overhead 与兼容性`、`复现与借鉴价值`。
- 必须明确写出 baseline 是否公平、实验设置是否足够复现、部署假设是否现实。

## 4. Obsidian 保存

### 文件命名

只用方法名/系统名：`{方法名}.md`。不确定时保存到 `_inbox/`。

### 保存路径

按 Zotero 分类层级：`{NOTES_PATH}/{zotero_collection_path}/{方法名}.md`

默认一级目录应落在以下骨架下：

- `1-Computer Architecture and Accelerators`
- `2-Memory and Storage Systems`
- `3-Networking and Interconnects`
- `4-Distributed Systems`
- `5-Compilers and Runtime Systems`
- `6-Performance, Evaluation and Benchmarking`

### YAML frontmatter

```yaml
---
title: "论文标题"
method_name: "MethodName"
authors: [Author1, Author2]
year: 2025
venue: EuroSys
tags: [llm-serving, distributed-systems, scheduling]
zotero_collection: 4-Distributed Systems
image_source: online
created: YYYY-MM-DD
---
```

其中 `method_name` 在 systems / LLM 论文中表示**主系统名 / 运行时名 / 内核名 / 架构名**。
优先使用标题冒号前的显式名称（如 `WindServe`, `Oaken`, `ZipServ`）；没有明确系统名时，宁可保守使用论文标题，也不要强行臆造缩写。
元信息表格中的 `主对比基线` 应优先填写论文主实验里的核心 baseline，不要把附录扩展比较和互补方法混写成同级主基线。

第一个 tag 应是最核心主题。

## 5. 概念库维护

每篇论文读完后必须：

1. 扫描所有 `[[概念]]` 链接
2. 检查概念笔记是否存在
3. 不存在的按 `references/concept-categories.md` 自动归类并创建

## 6. 完成后自检

- [ ] 所有 Figure 都在笔记中？
- [ ] 所有公式都在笔记中？
- [ ] 所有 Table 完整保留？
- [ ] 关键术语有 `[[概念]]` 内联链接？
- [ ] 概念库已更新？
- [ ] 图片可用？
- [ ] 系统假设、瓶颈和性能结果是否解释清楚？
- [ ] `Overhead 与兼容性` 是否写清面积、额外延时、资源占用或工程复杂度？
- [ ] `复现与借鉴价值` 是否写清可复用机制、related work 价值和复现风险？
- [ ] baseline 是否公平、实验设置是否足够复现？

## 7. 批量处理

支持 Zotero 分类批量处理（默认递归子分类）。流程：递归获取论文 → 去重 → 跳过已有笔记 → 逐篇处理 → 汇总。

## 参考文件

- `references/zotero-guide.md`
- `references/image-troubleshooting.md`
- `references/concept-categories.md`
- `references/quality-standards.md`
