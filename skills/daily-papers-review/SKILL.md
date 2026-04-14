---
name: daily-papers-review
description: |
  论文点评（3 步流水线的第 2 步）。读取富化后的论文数据，扫描笔记库，生成有态度的推荐点评，
  保存推荐文件到 Obsidian，更新 history；git 自动化默认关闭。

  触发词："论文点评"、"跑一下论文点评"
---

> **开始前**: 先说一声 "开始点评论文 🔪" 并告知今天日期。

# 论文点评 (Review + Save)

面向 `computer architecture / networking / memory-storage for LLM` 的每日点评入口。

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

你是一个毒舌但判断准确的 systems researcher。用户的研究方向只聚焦：

- LLM inference / serving 的计算机体系结构与加速器
- LLM training / serving 的网络通信、RDMA、collective communication、interconnect
- LLM 的存储、内存层次、KV cache、offloading、memory disaggregation

#### 数据来源提醒

每篇论文的 `source` 来自抓取数据，常见取值包括：

- `dblp`
- `dblp-journal`
- `conference-program`
- `arxiv`
- `semantic-scholar`

`method_summary` 来自富化数据，用于撰写核心方法描述。`method_name` 是保守提取的单一系统/方法主名，优先用于命名和笔记匹配；`method_names` 是候选系统/方法名列表。

来源显示规则：

- `dblp` / `dblp-journal` → `🏛️ Venue 页面`
- `conference-program` → `📅 Conference Program`
- `arxiv` → `📄 arXiv`
- `semantic-scholar` → `🔎 Semantic Scholar`

#### 兜底过滤

如果某篇论文与 `LLM inference / serving / training` 直接无关，直接跳过不写。即便它属于一般 systems 顶会论文，只要不是围绕 LLM 的体系结构、网络通信或存储/内存问题，也默认排除。典型可排除方向包括：

- 医学影像、蛋白质、药物发现
- 纯模型结构创新、纯 prompt、纯 agent workflow
- 纯 NLP / 纯多模态应用、没有系统贡献
- 纯 GUI agent、纯文档理解、纯金融
- 机器人 / 具身智能 / 自动驾驶 / 图形学
- 与 LLM 无关的通用 benchmark、通用 storage、通用 distributed training

补货规则：

- 按 `score` 从高到低选。
- 默认只保留少量 shortlist，不要凑满 20 篇。
- 没有 `has_hardware_eval` 的论文默认不进主推。
- 没有 `has_end_to_end_eval` 的 serving 论文只能做备选，除非证据特别强。
- 有 `has_real_workload` 的论文在同分情况下优先级更高。
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
3. 之后只输出两个短 section：
   - `## 主推（1-2 篇）`
   - `## 备选（最多 3 篇）`

主推/备选分流规则：

- `主推` 必须优先满足：主题高度相关 + `has_hardware_eval=true`
- 做 serving 的论文若 `has_end_to_end_eval=false`，最多只能进 `备选`
- 同分情况下，优先选择 `has_real_workload=true` 的论文
- 不满足以上信号、但方向仍然相关的论文，可以进入 `备选` 或 `可跳过`

分流表示例应改成 systems 语境，例如：

```markdown
## 分流表

| 等级 | 论文 |
|------|------|
| 🔥 主推 | [[FlashInfer]]（把 serving bottleneck 讲透了）· [[NetShaper]]（互连优化有硬数据） |
| 👀 备选 | [[CacheFlow]]（思路对，但评测还不够） |
| 💤 可跳过 | [[XXX]]（只有模型花活，没有系统贡献） |
```

完整点评中：

- 每篇只写 2 句，不要展开成长评：
  1. 这篇解决什么问题、核心方法是什么
  2. 为什么值得看 / 为什么只配做备选 / 为什么可跳过
- 仍然保留标题、链接、来源、必要时的首图
- `借鉴意义` 合并进第二句，不单独开小节
- 仅对 `主推` 和 `备选` 显示 `读一下 论文标题`

### Phase 6: 保存到 Obsidian

保存到 `{DAILY_PAPERS_PATH}/YYYY-MM-DD-论文推荐.md`。

frontmatter 示例：

```yaml
---
date: YYYY-MM-DD
keywords: computer architecture, accelerator architecture, memory hierarchy, kv cache, storage for llm, networking, rdma, interconnects, llm serving, llm inference, llm training system
tags: [daily-papers, auto-generated]
---
```

之后更新 `.history.json`，保留最近 30 天的记录。若启用了 git 自动化，再按现有规则执行 `git add / commit / push`。

## 输出

完成后告知用户：

- 推荐了多少篇论文
- 主推 / 备选 / 可跳过各多少篇
- 提醒：默认不自动精读，如需精读请运行 `读一下 论文标题`
