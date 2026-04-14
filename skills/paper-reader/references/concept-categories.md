# 概念自动归类规则

概念库位置：`{CONCEPTS_PATH}`

先用 `ls {CONCEPTS_PATH}` 查看已有子目录，再按下表分类：

| 子目录 | 归类标准 | 示例 |
|--------|----------|------|
| `1-Computer Architecture and Accelerators` | 芯片架构、加速器、微架构、张量核心、映射与放置 | Tensor Core, Systolic Array, Warp Scheduler |
| `2-Memory and Storage Systems` | cache、HBM、KV cache、memory hierarchy、CXL、存储分层 | KV Cache, HBM3, Page Cache, CXL Memory Pool |
| `3-Networking and Interconnects` | RDMA、collective、交换机、拓扑、传输协议、互连优化 | RDMA, AllReduce, ECN, NVLink, Clos |
| `4-Distributed Systems` | 集群调度、容错、多租户、分布式执行、服务系统 | Scheduler, Placement Policy, Checkpointing, vLLM |
| `5-Compilers and Runtime Systems` | 编译器、中间表示、kernel fusion、runtime、自动调优 | MLIR, TVM, Triton, Kernel Fusion |
| `6-Performance, Evaluation and Benchmarking` | profiling、trace、benchmark、roofline、测量方法 | Roofline Model, MLPerf, Perf Counter |
| `0-uncategorized` | **仅在完全无法判断时**才用，应尽量避免 | — |

## 归类原则

- 优先看概念服务的系统层次，而不是论文应用场景。
- `LLM training / inference / serving` 不单独建一级目录；相关概念按主要落点归到架构、内存、网络、分布式或运行时。
- 跨层概念优先归到“最直接决定性能瓶颈”的那一层。

## 概念笔记模板

```markdown
---
type: concept
aliases: [中文别名, 英文别名]
---

# 概念名称

## 定义
{一句话定义}

## 数学形式 / 系统模型
$$公式$$

## 核心要点
1. ...
2. ...

## 代表工作
- [[Paper1]]: ...
- [[Paper2]]: ...

## 相关概念
- [[相关概念1]]
- [[相关概念2]]
```
