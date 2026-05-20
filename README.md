# dailypaper-skills

面向 `computer architecture / networking / distributed systems / LLM systems` 的 Codex skills 集合。目标是把每日论文发现、单篇精读、Zotero 文献库和 Obsidian 笔记库连成一条本地工作流。

演示：[论文流水线效果演示（旧视频）](http://xhslink.com/o/1dhQCn40EWY)

## 核心能力

- 抓取 DBLP、会议页面、arXiv 和 Semantic Scholar fallback 的近期 systems / LLM infra 论文。
- 按本地关键词配置打分、去重、生成每日推荐。
- 从 PDF、arXiv / DOI / 网页链接、Zotero item / 搜索 / collection 生成论文笔记。
- 按 Zotero collection path 保存笔记；无 collection 时保存到 `_inbox`。
- 维护 `[[wikilink]]` 概念库，并按 `concept_type` 分类。
- 刷新论文目录页和概念目录页。

典型 Obsidian 输出：

```text
ObsidianVault/
├── DailyPapers/YYYY-MM-DD-论文推荐.md
└── PaperNotes/
    ├── Research Topics/.../{MethodName}.md
    ├── _concepts/{concept_type}/{ConceptName}.md
    ├── _inbox/{MethodName}.md
    └── _index_*.md
```

## 快速入口

最常用：

```text
今日论文推荐
读一下这篇论文 https://arxiv.org/abs/2509.24527
更新索引
```

常见变体：

```text
过去3天论文推荐
过去一周论文推荐
读一下这篇论文 ~/Downloads/paper.pdf
快速看一下这篇论文 https://arxiv.org/abs/2509.24527
批判性分析这篇论文 ~/Downloads/paper.pdf
读一下 Zotero item 2487
读一下 Zotero 里的 vLLM
批量读一下 Zotero 里 Link & Fabric Integration 分类下的论文
```

`今日论文推荐` 默认只做“抓取 + 点评”，不会自动生成精读笔记。某篇值得细看时，再运行 `读一下 ...` 或 `跑一下论文笔记`。

## 安装与配置

前置环境：

- Codex CLI
- Python 3.10+；当前测试环境为 Python 3.13
- Obsidian
- Zotero，可选但推荐
- `poppler` / `poppler-utils`，提供 `pdftotext`、`pdfimages`
- `mmdc`，可选，用于校验 Mermaid 图

复制 skills：

```bash
mkdir -p ~/.codex/skills
cp -R ./skills/* ~/.codex/skills/
```

开发本仓库时建议软链接：

```bash
mkdir -p ~/.codex/skills
for d in paper-reader daily-papers daily-papers-fetch daily-papers-review daily-papers-notes generate-mocs _shared; do
  ln -sfn "$PWD/skills/$d" "$HOME/.codex/skills/$d"
done
```

初始化 Obsidian 目录：

```bash
VAULT=~/ObsidianVault
mkdir -p "$VAULT/DailyPapers" "$VAULT/PaperNotes/_concepts" "$VAULT/PaperNotes/_inbox"
```

共享配置位于：

```text
~/.codex/skills/_shared/user-config.json
```

建议用同目录的 `user-config.local.json` 放个人路径和关键词覆盖。加载顺序为 `user_config.py` 默认值、`user-config.json`、`user-config.local.json`。

| 配置组 | 说明 |
|---|---|
| `paths.*` | Obsidian vault、论文笔记目录、每日推荐目录、概念库目录、Zotero DB / storage |
| `daily_papers.keywords` | 论文打分主关键词 |
| `daily_papers.negative_keywords` | 标题命中时触发 `-999` 硬排除；只在摘要中出现不会直接排除 |
| `daily_papers.domain_boost_keywords` | systems 相关性加分词 |
| `daily_papers.arxiv_categories` / `min_score` / `top_n` | arXiv 查询范围、最低分、单日候选上限 |
| `automation.*` | 是否自动刷新 MOC、commit、push；`git_push` 只有 `git_commit=true` 时生效 |
| `mocs.filename_prefix` | MOC 文件名前缀，常用 `_index_` |

## 工作流

### 每日论文推荐

`daily-papers` 是用户入口，内部串联：

1. `daily-papers-fetch`：抓取、打分、去重、富化候选，输出 `/tmp/daily_papers_enriched.json`。
2. `daily-papers-review`：生成 `{DailyPapers}/YYYY-MM-DD-论文推荐.md`，并更新 `.history.json`。

默认不执行 `daily-papers-notes`，避免一次推荐直接生成大量长笔记。

### 单篇论文阅读

`paper-reader` 支持本地 PDF、arXiv / DOI / 网页链接、Zotero item、Zotero 搜索和 Zotero collection 批量处理。

保存规则：

- 文件名使用主方法名 / 系统名：`{MethodName}.md`
- 有 Zotero collection 时保存到 `{PaperNotes}/{collection_path}/{MethodName}.md`
- 无 collection 时保存到 `{PaperNotes}/_inbox/{MethodName}.md`
- `zotero_item_id`、`doi`、`arxiv_id` 写入 frontmatter，用于精确去重
- 批量模式默认跳过已有笔记

Zotero 默认只读。只有用户明确要求移动、添加或移除 collection 时，才会修改 Zotero 数据库。

论文笔记模板：[`skills/paper-reader/assets/paper-note-template.md`](skills/paper-reader/assets/paper-note-template.md)

### 概念库与目录页

概念笔记放在 `{PaperNotes}/_concepts/`，按概念性质分类：

```text
data-structure / algorithm / mechanism / architecture
hardware / software-abstraction / metric / theory-model
```

概念分类规则和模板：[`skills/paper-reader/references/concept-categories.md`](skills/paper-reader/references/concept-categories.md)

常用命令：

```bash
python3 skills/_shared/scan_missing_concepts.py --dry-run
python3 skills/_shared/scan_missing_concepts.py --with-seed --output /tmp/missing_concepts.csv
python3 skills/_shared/generate_concept_mocs.py
python3 skills/_shared/generate_paper_mocs.py
```

扫描器会排除 `_concepts/`、`_inbox/`、`_index_*.md` 和论文笔记之间的互链。

## 仓库结构

```text
skills/
├── daily-papers/          # 每日推荐一句话入口
├── daily-papers-fetch/    # 抓取、打分、富化
├── daily-papers-review/   # 推荐点评生成
├── daily-papers-notes/    # 可选批量精读
├── generate-mocs/         # 手动刷新目录页
├── paper-reader/          # 单篇论文阅读与 Zotero 集成
└── _shared/               # 配置、MOC 生成、概念扫描
```

## 开发维护

```bash
pytest tests/
python3 skills/daily-papers/fetch_and_score.py > /tmp/daily_papers_top30.json
cat /tmp/daily_papers_top30.json | python3 skills/daily-papers/enrich_papers.py /tmp/daily_papers_enriched.json
```

Zotero helper 兼容期规则：

- 新文档和脚本使用 `zotero_helper.py resolve ...` 和 `zotero_helper.py note-path ...`
- 旧命令 `papers`、`search`、`info`、`find-collection` 暂时保留，会打印 deprecation warning；下一次相关清理时移除

## 注意事项

- 去重优先使用 `zotero_item_id`、`doi`、`arxiv_id`，再退到规范化标题 / 方法名匹配。
- 不用 Zotero 也可以跑每日推荐和 PDF / arXiv 论文阅读；Zotero 主要用于本地文献检索、PDF 定位和 collection path。
- `git_commit` 和 `git_push` 默认关闭。
- AI 生成的推荐、点评和笔记可能有事实错误或遗漏，应作为阅读辅助，不应替代研究判断。

## License

Apache-2.0. See [`LICENSE`](LICENSE).
