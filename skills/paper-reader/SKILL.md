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
| Zotero item | "读一下 Zotero item 2487" | `assets/zotero_helper.py resolve --item-id 2487` |
| Zotero 搜索 | "读一下 Zotero 里的 EBPC" | `assets/zotero_helper.py resolve --query "EBPC"` → 多候选时让用户选 item |
| Zotero collection | "批量读 Zotero collection \"Link & Fabric Integration\"" | `assets/zotero_helper.py resolve --collection "Link & Fabric Integration" --recursive` |
| 无 PDF | Zotero 条目无附件 | 从网上获取（见下方） |

无 PDF 时优先：`arXiv HTML > arXiv PDF > DOI > WebSearch 标题`。

### Zotero 读取规则

- Zotero 默认只读，只用来解析论文来源、PDF、元数据和 collection 路径。
- 单篇搜索返回多个候选 item 时，列出 `item_id / title / year / venue / collection_paths`，让用户选择。
- 单篇 item 位于多个 collection 时，让用户选择本次保存使用的 `selected_collection_path`。
- 批量从 collection 进入时，使用 helper 返回的 `source_collection_path`；递归父 collection 时，优先使用 item 在该 subtree 下最具体的 child collection。
- 如果 Zotero 分类明显不对，只提出建议；确认后才调用 `zotero_helper.py move`、`add-to-collection` 或 `remove-from-collection`。

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
2. 技术术语首次出现要加 `[[概念]]` 链接；`references/concept-categories.md` 的 seed list 命中词，首次出现必须写成 `[[概念名]]`，即使作者把它当常识。
3. 不用 ASCII 流程图；改用结构化 Markdown 和必要公式。
4. 公式必须有名称和 LaTeX，并用自然段解释建模对象、变量角色及其支撑的设计或结论。
5. 图片优先外链 arXiv HTML / 项目主页；如果图源是本地 PDF，则从 PDF 裁切图片并存放到笔记同目录下的 `00_assets/<note-name>_<原图片名>`，笔记中使用 `![[00_assets/<note-name>_<原图片名>]]`。
6. Figure / Table / 单个公式必须嵌入对应叙事小节，不要默认用 H3/H4 图表或公式标题把素材提升为 Obsidian 大纲章节；图片标题写进图片引用的题注/alt 文本（如 `![Figure 3: ...](...)`），不要在图片上方单独写 `**Figure ...**` 标题；只有“核心结果”“消融实验”“附录图”等语义小节可以使用 `###`，只有按论文结构或 Agent 理解提炼出的机制子小节才可以使用 `####`。
7. 论文笔记正文禁止使用 Obsidian task 语法（`- [ ]` / `- [x]`）；核查项、复现步骤、风险项一律写成普通 bullet 或 Markdown table，避免污染 Obsidian Tasks。

本地图片命名规则：`note-name ≤ 48 字符` 时直接使用 `<note-name>_` 前缀；note-name 太长时使用 `截断前 40 字符 + 8 位 hash` 作为前缀，形如 `VeryLongNoteNamePrefix_xxxxxxxx_figure.png`，避免文件名过长和重名。

### systems 方向额外要求

- 讲清 bottleneck、优化对象、工作负载、系统假设。
- 对 runtime / compiler / networking / memory / scheduling 这类关键机制，优先按数据流或执行流程解释。
- 读 LLM systems 论文时，不要把重点写成模型能力；重点是计算、存储、通信和调度机制。
- 笔记必须包含 `实验设置`、`核心结果`、`Overhead 与兼容性`、`经验与可迁移启示`、`复现`。
- `实验设置` 的 `模拟器与微架构参数` 小节必须根据论文 evaluation platform 画一张 Mermaid 测试系统连接关系图，展示 client / driver / runtime / worker / accelerator / memory / network / storage / simulator 等组件如何连接、需要哪些硬件资源；可以删减和图重复的参数表细节，不要为了完整性硬塞 CPU pipeline、BTB、ROB 等微架构参数，除非它们就是评测对象。
- `复现` 小节里的核查内容使用 `### 复现核查表`，优先写成 `项目 / 结论 / 证据或缺口` 三列表格；不要使用英文 checklist 标题，也不要用 `- [ ]` task list。
- 必须明确写出 baseline 是否公平、实验设置是否足够复现、部署假设是否现实。

## 4. Obsidian 保存

### 文件命名

只用方法名/系统名：`{方法名}.md`。不确定时保存到 `_inbox/`。

### 保存路径

按选定 Zotero collection 层级保存：`{NOTES_PATH}/{selected_collection_path}/{MethodName}.md`

collection path 每一段只做文件名安全清洗，不改变 Zotero 原有层级语义。没有 collection 的 item 保存到 `{NOTES_PATH}/_inbox/{MethodName}.md`。

一篇论文默认一份笔记：

- 单篇显式读取：同路径已有笔记时允许覆盖或更新；同名笔记已在别处时，移动到目标 collection 路径并更新 frontmatter。
- 批量从 collection 进入时：默认跳过已有 notes，不按关键词重新分类。

### YAML frontmatter

```yaml
---
title: "论文标题"
method_name: "MethodName"
authors: [Author1, Author2]
year: 2025
venue: EuroSys
tags: [llm-serving, distributed-systems, scheduling]
zotero_item_id: 2487
zotero_collection: Research Topics/Lossless Communication Compression/Link & Fabric Integration
doi: 10.1145/example
arxiv_id: 2501.01234
image_source: online  # online / mixed / local；本地 PDF 裁图全部使用本地图片时填 local
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
2. 在 `{CONCEPTS_PATH}` 下**递归**查找是否已存在（不要只看顶层）
3. 不存在的按 `references/concept-categories.md` 的 8 类 `concept_type` 归类后创建

新建 concept 必须按 `references/concept-categories.md` 的**增强模板**生成：含「动机与痛点 / 直观例子 / 边界与对比 / 学习索引」4 个新必选段，加上按 `concept_type` 加的差异化段（如 architecture 必须含 Mermaid 组件图、algorithm 必须含步骤+复杂度等）。长度目标 60-100 行。`学习索引` 找不到证据时允许整段写 `TODO`，不要硬凑。

概念按性质分类（`data-structure / algorithm / mechanism / architecture / hardware / software-abstraction / metric / theory-model`），**不**按论文研究领域分类。仅被本论文使用的方法名优先折回论文笔记，不独立成 concept（详见 `references/concept-categories.md`）。

过滤默认规则：

- 宁可漏判几个通用词，也不要误杀真正的 systems concept；不确定就创建，后续再 review。
- `Admission Control`、`Kernel Fusion`、`RDMA`、`NVLink`、`PCIe`、`NUMA`、`HBM`、`CXL`、`AllReduce`、`NCCL`、`CUDA` 等 seed list 或 systems 基石术语必须保留为候选。
- 数据集 / 仿真器不作为 concept；不要为数据集、benchmark suite、仿真器、纯实验环境名称创建 concept。
- paper-method 按三档处理：论文首创且仅本论文实验 → `status/paper-specific`；论文具名实现且前人工作 / 被多篇当 baseline → 通用 concept；完全是前人工作且该论文只是引用 → 不独立建 concept。

## 6. 完成后自检

- 所有 Figure 都在笔记中？
- 所有公式都在笔记中？
- 所有 Table 完整保留？
- Template 检查：是否对照 `assets/paper-note-template.md` 验证必备章节与层级？尤其 `## 关键机制拆解` 到下一个 `##` 之间，所有 `###` 是否都匹配 `### 机制N：...`，且 Algorithm / pipeline / 公式解释 / 图表解读 / 实现细节没有与机制并列？
- Obsidian 大纲是否干净：没有把普通 `Figure X` / `Table X` / 单个公式提升成 `###` 或 `####` 章节？`####` 是否只用于机制内部的语义子小节？
- `系统组成与职责` 小节是否包含 `#### 模块关系图`，且其下方有 Mermaid 模块关系图和自然段解释？不能只用 `系统架构与执行流`、论文原图或组件表替代；生成后要用 `mmdc` 校验 Mermaid（若环境可用）。
- `实验设置` 的 `模拟器与微架构参数` 小节是否包含 evaluation platform Mermaid 连接关系图，并说明测试系统形态与硬件资源需求？是否删除了和图重复、且对读者理解测试系统无帮助的参数细节？
- 正文是否没有 `- [ ]` / `- [x]` 这类 Obsidian task 语法？
- 关键术语有 `[[概念]]` 内联链接？
- 概念库已更新？
- 图片可用？本地 PDF 裁图是否写入 `00_assets/`，并按 `<note-name>_<原图片名>` 或长 note-name hash 规则命名？
- 系统假设、瓶颈和性能结果是否解释清楚？
- `Overhead 与兼容性` 是否写清面积、额外延时、资源占用或工程复杂度？
- `经验与可迁移启示` 是否写清可迁移 lesson、评测方法和 related work 价值？
- `复现` 是否写清环境依赖、关键配置、workload/data、核查表和风险缺口？
- baseline 是否公平、实验设置是否足够复现？
- `速查卡片` 是否严格保留 `assets/paper-note-template.md` 的 `[!summary]` callout 结构，并包含 `核心 / 方法 / 结果 / 适用场景 / 未来工作 / 引用建议` 六项；不要改成表格或自由问答格式。

## 7. 批量处理

支持 Zotero collection 批量处理（默认递归子 collection）。流程：递归获取论文 → 去重 → 用 `source_collection_path` 规划保存路径 → 跳过已有笔记 → 逐篇处理 → 汇总。

## 参考文件

- `references/zotero-guide.md`
- `references/image-troubleshooting.md`
- `references/concept-categories.md`
- `references/quality-standards.md`
