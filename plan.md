# Concept 库改进计划

> 起草于 2026-05-15。来源：qa 审查报告（rep_e8b1b3951b03）针对 concept 触发逻辑、过滤规则、生成产物、paper-specific 判定和离线兜底的反馈。
>
> 当前状态：concept 库已完成"按 topic 改为按 concept_type 8 类"的迁移（commit 待执行：重构概念库分类）。本文档汇总 qa 进一步审查发现的问题与可执行的下一步。
>
> 2026-05-15 落地更新：完整包 A1+A2+A3+B1+B2+B3 已实现；review 后补修 `scan_missing_concepts.py` 排除论文笔记互相引用的假阳性，并将 daemon prompt 中的 CV 示例换为 systems 示例。

---

## 1. 现状摘要

- 24 篇 concept 笔记按 8 类 `concept_type` 分布：data-structure(2) / algorithm(4) / mechanism(6) / architecture(3) / hardware(2) / metric(4) / theory-model(3) / software-abstraction(0)。
- 触发完全靠 LLM prompt 顺手扫：
  - `paper-reader` 单篇：写完论文笔记后扫 `[[concept]]` wikilink。
  - `daily-papers-notes` 批量：从今日推荐 + `enriched.json.method_name(s)` 抽。
- 过滤规则在 prompt 里："跳过通用词 / 论文自身名 / 公司名 / 人名"，"保留方法 / 模型 / 数据集 / 框架 / 技术术语"。
- paper-specific 判定：单论文使用 → 加 `tags:[status/paper-specific]`；多篇独立论文引用 → 晋升。

## 2. qa 审查发现的 5 个问题

| # | 问题 | 严重度 |
|---|---|---|
| Q1 | trigger 漏关键概念：`[[wikilink]]` + `method_name` 强依赖论文笔记的显式 link 习惯。RDMA / NVLink / PCIe 这类高频背景词常被作者当常识不加 link，永远进不来 | 🔴 高 |
| Q2 | filter 主观：`Admission Control` / `Kernel Fusion` 容易被 LLM 误判通用词跳过 | 🟠 中 |
| Q3 | 实际生成偏 LLM Serving 严重：基石概念（RDMA, HBM, AllReduce, CXL, CUDA, NCCL）缺失；`software-abstraction` 长期为 0 不正常 | 🔴 高 |
| Q4 | paper-specific 判定过简：未区分"论文首创" vs "前人工作被该论文用作 baseline" | 🟡 低 |
| Q5 | 缺独立离线扫描脚本：当前不能完全靠 LLM 顺手扫；需扫所有论文笔记 + 对比 seed dictionary | 🔴 高 |

qa 在产物中具体点名：

- `Lossless Compression`：太宽泛，应删
- `Service-Level Objective`：偏业务指标（我们部分不同意，systems 论文里 SLO 是 GA 性能口径，建议保留，详见 A1）
- `ZipGEMM`（已 paper-specific）：应折叠回 ZipServ 论文笔记
- `TCA-TBE`（已 paper-specific，本计划同步处理）

## 3. 行动项

### Phase A — 立刻可做（改规则 / 删 concept，不动代码）

#### A1. 处理 3 篇不该独立的 concept

| 笔记 | 处理 | 触碰文件 |
|---|---|---|
| `_concepts/mechanism/ZipGEMM.md` | 删；把要点合并回对应的 ZipServ 论文笔记 | Obsidian vault |
| `_concepts/mechanism/TCA-TBE.md` | 同上 | Obsidian vault |
| `_concepts/algorithm/Lossless Compression.md` | 删；已有 Arithmetic Coding / Huffman / ANS 三具体算法足够 | Obsidian vault |
| `_concepts/metric/Service-Level Objective.md` | **保留**（部分不同意 qa），但加约束：仅在系统 paper 实际定义 SLO 数值时再创建 | 不动 |

**验收**：`_concepts/` 笔记数 24 → 21；ZipServ 论文笔记里有 ZipGEMM / TCA-TBE 的实现细节段。

**工作量**：~30 分钟（手动）。

#### A2. paper-specific 判定细化

更新 `skills/paper-reader/references/concept-categories.md` 的 paper-method 处理规约，从二档改成三档：

| 情形 | 处理 |
|---|---|
| 论文首创 + 仅本论文实验 | `tags:[status/paper-specific]` |
| 论文具名实现 + 前人工作 / 被多篇当 baseline | **直接升格为通用 concept**，不加 tag；在该论文笔记里讲"具名实现细节" |
| 完全是前人工作 + 该论文只是引用 | **不该独立成 concept**，只在论文笔记内提及 |

同步 `paper_daemon.py` `call_codex` prompt 的对应段。

**验收**：reference 和 daemon prompt 都用三档；触发 systems_template tests 不破坏现有断言。

**工作量**：~20 分钟。

#### A3. 过滤规则放宽 + 数据集/仿真器排除

- 改 paper-reader / daily-papers-notes / daemon prompt 的过滤默认行为：**"宁可漏判几个通用词、不要误杀真正的 systems concept；不确定就创建"**。
- 显式排除数据集 / 仿真器作为 concept：它们偏应用，**不**作为 concept 笔记；如果一定要记，应放专门的"datasets" 或 "benchmarks" 资料库（暂不建）。
- 同时给 LLM 一个"systems concept 兜底白名单"提示，列 RDMA / NVLink / PCIe / NUMA / HBM / CXL / AllReduce / NCCL / CUDA 等高频被遗漏术语。

**验收**：手动检查改后 prompt 输出，对 `Admission Control` / `Kernel Fusion` 这类不再被跳过。

**工作量**：~20 分钟。

---

### Phase B — 短期（写代码）

#### B1. `scan_missing_concepts.py` 离线扫描脚本

**目标**：扫所有论文笔记里的 `[[xxx]]` wikilink，输出"出现但无 concept 笔记"的清单。

**位置**：`skills/_shared/scan_missing_concepts.py`

**逻辑**：

```python
1. walk PaperNotes/**/*.md（排除 _concepts/、_inbox/、_index_*.md）
2. 提所有 [[xxx]] wikilink
3. 收已有 concept = {concept_dir/file_stem} ∪ {frontmatter.aliases}
4. 收已有 paper note = {paper_note/file_stem}，排除论文笔记互相引用
5. diff: missing = wikilink_set - concept_set - paper_note_set
6. 二期：对比 seed list（见 B2），找"应该有但没出现 wikilink 也没 concept"的
7. 输出 CSV: concept_name | refs_count | example_papers | candidate_type，其中 example_papers 最多列 5 篇
```

**CLI**：
- `--dry-run`（默认）：打印 missing 清单
- `--output missing.csv`：写文件
- `--with-seed`：开启 seed list 对比模式

**验收**：跑一次产出 CSV，refs_count >= 2 的项至少 5 个；产出中不应包含已有论文笔记标题；至少 1 个 `software-abstraction` 候选能被 seed list 或扫描识别；人工 review 后可手动补 concept。

**当前验收记录**：review 修复后真实 vault 扫描得到 11 个 missing，refs_count >= 2 的 8 个；已排除 3 个论文标题假阳性；`MPI` 被识别为 `software-abstraction` 候选。

**工作量**：1-2 小时。

#### B2. Systems concept seed list

**目标**：在 `concept-categories.md` 加一节 "Systems Concept Seed Vocabulary"，按 8 类列**应该有 concept 笔记的种子词**。

**用途**：
1. paper-reader / daemon prompt 写论文笔记时**提示**：见到 seed list 上的术语必须加 `[[wikilink]]`（详见 B3）。
2. B1 脚本对比"应该有但没出现 wikilink 也没 concept"的盲点。

**初版内容**（详细列表见 A3 改 prompt 时同步）：

```
data-structure:    HBM, SRAM, DRAM, CXL Memory Pool, Bloom Filter, Trie, B-tree
hardware:          RDMA, NVLink, PCIe, InfiniBand, NUMA, SMT, Cache Coherence,
                   TLB, Branch Predictor, Out-of-Order, ROB, BTB, Systolic Array
algorithm:         AllReduce, AllGather, Reduce-Scatter, Consistent Hashing,
                   Paxos, Raft
mechanism:         Speculative Execution, Pipelining, Prefetching,
                   Speculative Decoding, Continuous Batching,
                   Disaggregated Prefill, Tensor Parallelism
architecture:      Parameter Server, Map-Reduce, Mixture of Experts
software-abstr.:   CUDA, NCCL, MPI, OpenMP, vLLM Engine, TVM, MLIR, Triton, Ray
metric:            MPKI, IPC, Bandwidth Utilization, Effective FLOPs, Goodput, p99
theory-model:      Amdahl's Law, Gustafson's Law, Little's Law, USL Model
```

**验收**：seed list 落进 reference；B1 脚本能读取；新建概念时 LLM prompt 能引用。

**工作量**：~30 分钟（vocabulary 列定）。

#### B3. 论文笔记 wikilink 硬约束

**目标**：堵 trigger 端漏洞。论文笔记里凡出现在 seed list 的术语，**首次出现必须包成 `[[xxx]]`**，即使是常识也不例外。否则 concept 永远不会被触发。

**触碰**：`skills/paper-reader/SKILL.md` §3 / §5；`paper_daemon.py` `call_codex` prompt；`skills/daily-papers-notes/SKILL.md` Step 1。

**验收**：让 LLM 写一个含 RDMA 的论文笔记，应该自动 `[[RDMA]]` 而不是裸文本。

**工作量**：~30 分钟。

---

### Phase C — 长期（暂不做，留方向）

#### C1. TF-IDF / NER 候选挖掘

扫论文笔记取高频名词，对比 seed list，自动挖掘隐藏 concept 候选。工作量大、收益边际，**B1 跑稳后再考虑**。

#### C2. concept-paper 反向回填脚本

scan 所有论文笔记里出现的 `[[ConceptName]]`，自动更新 concept 笔记里 `## 代表工作` 列表。当前靠 LLM 手填易漏。

---

## 4. 优先级与组合建议

| 包 | 含 | 工作量 | 收益 |
|---|---|---|---|
| **最小** | A1 + A2 + A3 | ~70 min | 修 qa 直接指出的产物问题；规则更鲁棒 |
| **中** | 最小 + B3 | ~100 min | 加上 trigger 端 wikilink 硬约束 |
| **完整** | 最小 + B1 + B2 + B3 | ~3-4 h | 闭环 trigger / filter / 兜底 |

**推荐先做完整包**：A1+A2+A3 是规则层面的清理，B1+B2+B3 是工程兜底，二者配合才能根治"systems 基石概念缺失"。

## 5. 与已 commit 改动的关系

最近相关 commit：
- `9e3c573` 统一概念分类信源到 concept-categories.md（用 systems 主线 1-6）
- 未 commit 的"按 concept_type 8 类重构"（包含 SKILL.md / paper_daemon.py / concept-categories.md 三个文件改动 + 24 篇 Obsidian 笔记的 frontmatter / 目录迁移）

本计划是上述重构之后的下一步迭代，**不**回退已有改动。

### 提交建议

- 若要保留清晰历史，拆成两类提交：
  1. vault 内容清理：A1 删除 / 合并 paper-specific concept。
  2. skill 与脚本改造：A2+A3+B1+B2+B3 规则、prompt、scan 脚本与测试。
- 若本轮只在仓库内提交，至少包含：`skills/_shared/scan_missing_concepts.py`、`tests/test_scan_missing_concepts.py`、`skills/paper-reader/SKILL.md`、`skills/paper-reader/paper_daemon.py`、`skills/paper-reader/references/concept-categories.md`、`skills/daily-papers-notes/SKILL.md`、相关测试与本计划文档。

## 6. 不在本计划范围

- 不动论文笔记目录结构（按 Zotero collection path 落盘的方案保留）。
- 不引入新的 concept 类别（坚守 8 类 vocabulary）。
- 不做多语言 alias 自动翻译。
- 不接入外部 systems dictionary（如 ACM Computing Classification System），手维护 seed list 即可。

---

*等用户选定要执行的包后再动手。本文档不作为最终文档，验收完成后内容应回填到 `concept-categories.md` 和（如需要）`ARCHITECTURE.md`。*
