---
name: daily-papers-fetch
description: |
  论文抓取（3 步流水线的第 1 步）。抓取 systems 方向最新论文，打分筛选，富化信息，
  输出到 /tmp/daily_papers_enriched.json 供后续 skill 使用。

  触发词："论文抓取"、"跑一下论文抓取"
  支持多天模式："过去3天论文推荐"、"过去一周论文推荐"、"过去一周的论文"、"抓 3 天的论文"、"最近5天"
---

> **开始前**: 先说一声 "开始抓取论文 🐕" 并告知今天日期。如果是多天模式，告知抓取范围。

# 论文抓取 (Fetch + Score + Enrich)

面向 `computer architecture / networking / distributed systems / compiler-runtime / LLM systems` 的论文抓取入口。

## Step 0: 读取共享配置

先读取 `../_shared/user-config.json`，如果 `../_shared/user-config.local.json` 存在，再用它覆盖默认值。

显式生成并在后续统一使用这些变量：

- `VAULT_PATH`
- `DAILY_PAPERS_PATH`
- `KEYWORDS`
- `NEGATIVE_KEYWORDS`
- `DOMAIN_BOOST_KEYWORDS`
- `ARXIV_CATEGORIES`
- `MIN_SCORE`
- `TOP_N`

其中：

- `DAILY_PAPERS_PATH = {VAULT_PATH}/{daily_papers_folder}`
- 所有关键词、分类、阈值都以共享配置为准

## 解析天数

从用户输入中解析 `--days N` 参数：

- "过去一周"、"最近7天"、"一周的论文" → `--days 7`
- "过去3天"、"最近三天"、"抓3天" → `--days 3`
- "过去两周" → `--days 14`
- 无特殊指定 / "跑一下论文抓取" → 默认当天

## 工作流程

### Phase 1+2: 抓取 + 打分 + 合并去重

运行：

```bash
python3 ../daily-papers/fetch_and_score.py > /tmp/daily_papers_top30.json
python3 ../daily-papers/fetch_and_score.py --days N > /tmp/daily_papers_top30.json
```

脚本负责：

- 优先抓取 `DBLP proceedings / journal pages`
- 补抓最近会议的 `program pages`
- 抓 `arXiv API`
- 候选不足时再用 `Semantic Scholar` 做补充
- 关键词打分、历史去重、Top-N 选择

默认目标 venue 包括：

- `ISCA`、`MICRO`、`HPCA`、`ASPLOS`
- `NSDI`、`SIGCOMM`、`OSDI`、`USENIX ATC`、`EuroSys`
- `SC`、`MLSys`

### Phase 3: 批量富化

运行：

```bash
cat /tmp/daily_papers_top30.json | python3 ../daily-papers/enrich_papers.py /tmp/daily_papers_enriched.json
```

脚本自动并发抓取 arXiv HTML/PDF 页面，补全：

- `figure_url`
- `authors`
- `affiliations`
- `section_headers`
- `captions`
- `has_real_world`
- `method_names`
- `method_summary`

## 输出

完成后检查 `/tmp/daily_papers_enriched.json` 是否存在且为有效 JSON 数组。告知用户：

- 抓取了多少篇论文
- 富化成功多少篇
- 提示运行下一步：`跑一下论文点评`

## 注意事项

- 默认不再依赖 Hugging Face daily / trending。
- systems 方向的候选优先来自 venue 页面与 arXiv，不是热榜。
- 如果 DBLP 或 program page 不可用，允许退化到 arXiv + Semantic Scholar。
- 不做 git 操作，不生成推荐文件，只输出临时 JSON。
