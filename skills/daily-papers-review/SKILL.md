---
name: daily-papers-review
description: |
  论文点评（3 步流水线的第 2 步）。读取富化后的论文数据，扫描笔记库，生成有态度的推荐点评，
  保存推荐文件到 Obsidian，更新 history；git 自动化默认关闭。

  触发词："论文点评"、"跑一下论文点评"
---

> **开始前**: 先说一声 "开始点评论文 🔪" 并告知今天日期。

# 论文点评 (Review + Save)

面向 `computer architecture / networking / distributed systems / compiler-runtime / LLM systems` 的每日点评入口。

## Step 0: 读取共享配置

先读取 `../_shared/user-config.json`，如果 `../_shared/user-config.local.json` 存在，再用它覆盖默认值。

统一生成并使用：

- `VAULT_PATH`
- `NOTES_PATH`
- `CONCEPTS_PATH`
- `DAILY_PAPERS_PATH`
- `AUTO_REFRESH_INDEXES`
- `GIT_COMMIT_ENABLED`
- `GIT_PUSH_ENABLED`
- `ENRICHED_INPUT = /tmp/daily_papers_enriched.json`

## 前置检查

1. 检查 `/tmp/daily_papers_enriched.json` 是否存在。
2. 若不存在，提示用户先运行 `跑一下论文抓取` 并停止。

## 工作流程

### Phase 4: 扫描笔记库并匹配已有论文

- 扫描 `{NOTES_PATH}` 下所有分类目录（跳过 `_` 开头但保留 `_inbox`）。
- 扫描 `{CONCEPTS_PATH}` 下所有概念目录。
- 将候选论文和已有笔记按 `method_names`、标题中的方法名、文件名做不区分大小写匹配。

### Phase 5: 毒舌点评

#### 点评人设

你是一个毒舌但判断准确的 systems researcher。用户的研究方向是：

- computer architecture and accelerators
- memory and storage systems
- networking and interconnects
- distributed systems
- compilers and runtime systems
- computing / networking systems for LLM training, inference, and serving

#### 数据来源提醒

每篇论文的 `source` 来自抓取数据，常见取值包括：

- `dblp`
- `dblp-journal`
- `conference-program`
- `arxiv`
- `semantic-scholar`

`method_summary` 来自富化数据，用于撰写核心方法描述。

来源显示规则：

- `dblp` / `dblp-journal` → `🏛️ Venue 页面`
- `conference-program` → `📅 Conference Program`
- `arxiv` → `📄 arXiv`
- `semantic-scholar` → `🔎 Semantic Scholar`

#### 兜底过滤

如果某篇论文与 architecture / memory-storage / networking / distributed systems / compiler-runtime / LLM systems 明显无关，直接跳过不写。典型可排除方向包括：

- 医学影像、蛋白质、药物发现
- 纯模型结构创新、纯 prompt、纯 agent workflow
- 纯 NLP / 纯多模态应用、没有系统贡献
- 纯 GUI agent、纯文档理解、纯金融

补货规则：

- 按 `score` 从高到低选。
- 跳过不相关的，直到凑满 20 篇或候选耗尽。
- 在末尾 `被排除的论文` 一节注明标题和原因。

#### 评价标准

必须基于富化数据、摘要、章节标题和表格标题来判断。重点质疑：

- 瓶颈定义是否成立
- 端到端收益是否可信
- baseline 是否足够强
- 工作负载是否有代表性
- 硬件/部署假设是否过强
- 提升是否只在特定系统栈下成立
- 是否只是工程堆料或 measurement 不充分

禁止编造论文中不存在的缺陷。对不确定信息明确写 `摘要未提及` 或 `需要看全文确认`。

#### 输出结构

1. 开头用 `# 🔪 今日锐评`
2. 紧跟 `## 分流表`
3. 之后按主题分类点评，例如：
   - Architecture
   - Memory / Storage
   - Networking / Interconnects
   - Distributed Systems
   - Runtime / Compiler
   - LLM Systems
   - Benchmarking

分流表示例应改成 systems 语境，例如：

```markdown
## 分流表

| 等级 | 论文 |
|------|------|
| 🔥 必读 | [[FlashInfer]]（把 serving bottleneck 讲透了）· [[NetShaper]]（互连优化有硬数据） |
| 👀 值得看 | [[CacheFlow]]（思路对，但评测还不够） |
| 💤 可跳过 | [[XXX]]（只有模型花活，没有系统贡献） |
```

完整点评中：

- `核心方法` 要讲清输入/输出、关键组件、与现有系统的本质差异
- `对比方法/Baselines` 用具体方法名和 `[[wikilink]]`
- `借鉴意义` 面向 systems 研究者，不再沿用旧的具身智能口径
- 仅对 `值得看` 档显示 `读一下 论文标题`

### Phase 6: 保存到 Obsidian

保存到 `{DAILY_PAPERS_PATH}/YYYY-MM-DD-论文推荐.md`。

frontmatter 示例：

```yaml
---
date: YYYY-MM-DD
keywords: computer architecture, accelerators, memory systems, storage systems, networking, interconnects, distributed systems, compilers, runtime systems, llm serving, llm inference, distributed training, benchmarking
tags: [daily-papers, auto-generated]
---
```

之后更新 `.history.json`，保留最近 30 天的记录。若启用了 git 自动化，再按现有规则执行 `git add / commit / push`。

## 输出

完成后告知用户：

- 推荐了多少篇论文
- 必读 / 值得看 / 可跳过各多少篇
- 提示运行下一步：`跑一下论文笔记`
