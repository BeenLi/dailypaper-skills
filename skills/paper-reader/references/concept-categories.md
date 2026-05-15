# 概念归类规则

概念库位置：`{CONCEPTS_PATH}`

**分类维度**：概念库**按概念本身的性质（concept type）分类**，不按它服务的系统层或论文研究领域分类。原因是同一个算法 / 数据结构 / 度量口径会跨多个系统层被引用，按概念本质分能避免跨主题查找失败。

写新概念前先用 `ls {CONCEPTS_PATH}` 查看 8 个 type 目录，再按下表选定 `concept_type`。

## Type 维度 vocabulary（8 类，单一信源）

| 子目录 | concept_type 取值 | 归类标准 | 示例 |
|--------|---|---|---|
| `data-structure/` | `data-structure` | 数据格式 / 表示 / 结构 | BFloat16, FP8, INT4, KV Cache, Radix Tree |
| `algorithm/` | `algorithm` | **脱离系统也成立**的纯计算逻辑 | Huffman Coding, Arithmetic Coding, ANS, AllReduce |
| `mechanism/` | `mechanism` | **绑定系统上下文**的运行时策略 | PagedAttention, Kernel Fusion, Micro-Batching, Request Admission Control |
| `architecture/` | `architecture` | 宏观系统架构 / 服务模式 | LLM Serving, Parameter Server, Agentic AI Serving, CPU-GPU Heterogeneous Serving |
| `hardware/` | `hardware` | 硬件部件 / 计算单元 / 物理互联 | Tensor Core, SIMT, NVLink, HBM, Systolic Array |
| `software-abstraction/` | `software-abstraction` | OS / 框架层接口与协议 | CUDA, MPI, NCCL, vLLM Engine, OpenMP |
| `metric/` | `metric` | 评估指标 / 测量口径 | SLO, TTFT, Tail Latency, Compute Intensity, MPKI |
| `theory-model/` | `theory-model` | 性能数学模型 + 纯数学 / 统计基础 | Roofline Model, Amdahl's Law, Error Function, Unimodal Distribution |

## 判定原则

### algorithm vs mechanism 边界

**"脱离系统也成立?"**

- 成立 → `algorithm`（如 Huffman Coding，作为信息论算法独立存在）
- 不成立 → `mechanism`（如 PagedAttention，必须有 attention runtime 才有意义）

### 跨类如何选

边缘案例按"最直接刻画本质"选：

| 案例 | 选 | 不选的原因 |
|---|---|---|
| `KV Cache` | `data-structure` | 本质是结构，而非机制 |
| `BFloat16` | `data-structure` | 本质是数值表示，而非硬件 |
| `Roofline Model` | `theory-model` | 本质是性能模型，而非指标 |
| `Compute Intensity` | `metric` | 本身是 FLOPs/Byte 测量值，是 Roofline 的输入 |
| `Kernel Fusion` | `mechanism` | 编译器+运行时联合执行，绑定系统上下文 |
| `Tensor Core` | `hardware` | 硬件部件 |

### 过滤默认规则

- 宁可漏判几个通用词，也不要误杀真正的 systems concept；不确定就创建，后续再靠 review 折回或删除。
- `Admission Control`、`Kernel Fusion`、`RDMA`、`NVLink`、`PCIe`、`NUMA`、`HBM`、`CXL`、`AllReduce`、`NCCL`、`CUDA` 这类 systems 基石术语即使在论文中被当作常识，也应作为 concept 候选。
- 数据集 / 仿真器不作为 concept。数据集、benchmark suite、仿真器和纯实验环境名称如果需要长期维护，应进入单独资料库；当前不创建 concept。
- `Service-Level Objective` / `SLO` 仅在 systems paper 实际定义 SLO 数值、违约条件或调度目标时创建或保留；泛泛业务目标不建 concept。

### paper-method 处理规约（采纳 qa 判定原则）

**paper-method 不作为正式 `concept_type`**。它描述的是概念的"生命周期状态"，不是本质属性。

判定与处理：

| 情形 | 处理 |
|---|---|
| 论文首创 + 仅本论文实验 | 落到最接近的 `concept_type`，并在 frontmatter 加 `tags: [status/paper-specific]` 标记 |
| 论文具名实现 + 前人工作 / 被多篇当 baseline | 直接升格为通用 concept，不加 `status/paper-specific`；在论文笔记里讲清该论文的具名实现细节 |
| 完全是前人工作 + 该论文只是引用 | 不该独立成 concept，只在论文笔记内提及或链接已有 concept |

晋升判定：至少 2 篇**作者无重叠**的独立工作（不是同实验室后续）使用该概念，且不再附加"X 论文的"前缀。

## Systems Concept Seed Vocabulary

这些词是 systems 论文里容易被作者当常识略过的触发词。写论文笔记时，正文首次出现这些术语必须写成 `[[概念名]]`；离线扫描脚本也会用本表发现“应该有 concept、但笔记里没有 wikilink”的盲点。

| concept_type | seed terms |
|---|---|
| data-structure | HBM, SRAM, DRAM, CXL Memory Pool, Bloom Filter, Trie, B-tree |
| hardware | RDMA, NVLink, PCIe, InfiniBand, NUMA, SMT, Cache Coherence, TLB, Branch Predictor, Out-of-Order, ROB, BTB, Systolic Array |
| algorithm | AllReduce, AllGather, Reduce-Scatter, Consistent Hashing, Paxos, Raft |
| mechanism | Speculative Execution, Pipelining, Prefetching, Speculative Decoding, Continuous Batching, Disaggregated Prefill, Tensor Parallelism |
| architecture | Parameter Server, Map-Reduce, Mixture of Experts |
| software-abstraction | CUDA, NCCL, MPI, OpenMP, vLLM Engine, TVM, MLIR, Triton, Ray |
| metric | MPKI, IPC, Bandwidth Utilization, Effective FLOPs, Goodput, p99 |
| theory-model | Amdahl's Law, Gustafson's Law, Little's Law, USL Model |

## 概念笔记模板（增强版）

每篇 concept 笔记由 **8 个统一段** + **1 个按 concept_type 加的差异化段** 组成。长度目标 **60-100 行**(超过 120 行说明在凑长度,请收敛)。

```markdown
---
type: concept
aliases: [中文别名, 英文别名]
concept_type: <从上表 8 类选一>
tags: [status/paper-specific]  # 仅在 paper-specific 时加
---

# 概念名称

## 定义
一句话定义。只解释 what,不解释 why。

## 动机与痛点
为什么会出现这个 concept?它在解决什么瓶颈或抽象漏洞?跟它之前人们怎么做相比,核心改进是什么?

## 直观例子
用 1 个具体场景把 concept "走一遍"。可以是 mini walk-through(算一个小例子)、伪代码、ASCII 状态图、或 Mermaid。目标:读者读完此段能说出"哦,它是 X 样子的"。

## 核心要点
3-5 条,每条用一两句解释**原理**,不只是 fact 列表。

<!-- 按 concept_type 加差异化段,见下面 §按 concept_type 差异化段 -->

## 边界与对比
- 什么情况**不**适用 / 反模式
- 跟最容易混淆的近邻 concept 的关键差别(用 1-2 个 `[[xxx]]` 对比)

## 代表工作与具体用法
- [[Paper1]]: 它怎么使用这个 concept?用出了什么效果(具体数字 / 设计决策)?
- [[Paper2]]: 同上

## 相关概念
- [[concept1]]: 和本概念的**关系**(组成 / 替代 / 协作 / 前置)
- [[concept2]]: 同上

## 学习索引
- 入门 paper / 综述:1-2 个(必须有具体 URL 或论文标题,不要凭印象列)
- 经典 blog / 教科书章节:1-2 个(必须有 URL)
- 关键 GitHub 实现(可选)

> 学习索引段允许整段写 `TODO: 待人工补充学习材料`,不要硬凑虚构内容。
```

## 按 concept_type 差异化段(必加)

放在 `## 核心要点` 之后、`## 边界与对比` 之前。8 个 concept_type 对应的差异化段如下:

| concept_type | 差异化段名 | 内容要点 |
|---|---|---|
| `data-structure` | `## 内存视图 / 字段布局` | 字段分布、字节大小、对齐、布局图 |
| `algorithm` | `## 步骤` + `## 复杂度` | 伪代码 / 步骤列表;时空复杂度;典型变体 |
| `mechanism` | `## 状态与触发条件` + `## 关键参数` | 触发条件、状态转移、可调参数 |
| `architecture` | `## 组件与接口` | **必须** Mermaid `flowchart LR` 画组件图(遵守 `~/.claude/skills/mermaid-rules/SKILL.md`:label 引号包裹、节点 ID 语义化、配色 ≤5);不允许 ASCII 状态图替代;描述接口契约;生成后用 `mmdc -i x.mmd -o x.png` 或 https://mermaid.live 校验 |
| `hardware` | `## 接口与典型参数` | 指令 / API 接口、峰值算力 / 带宽、典型规格、演进史 |
| `software-abstraction` | `## API 与生命周期` | 关键 API 签名、初始化-使用-销毁的生命周期 |
| `metric` | `## 测量方法` | 怎么测、单位、典型范围、好 / 坏阈值参考 |
| `theory-model` | `## 假设与失效边界` | 模型假设、适用域、什么时候失效 |

## 与论文笔记目录的关系

- 论文笔记目录（`{NOTES_PATH}/<Zotero collection path>/<Method>.md`）**与本分类完全解耦**。论文按 Zotero collection path 落盘，概念按 concept_type 落盘，两套目录互相独立。
- Obsidian wikilink 不带路径，跨目录引用没问题。
