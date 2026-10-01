---
name: book-reader
description: AI 逐页读书技能：将 PDF/EPUB/MOBI/TXT 书籍按页/章解析提取文本，分批提炼知识点，生成阶段性摘要，并输出带全书思维导图的结构化本地 Markdown 读书笔记。
  当用户提到读书笔记、分析/总结一本书、阅读并提取要点、PDF/EPUB/MOBI/TXT 摘要或知识提取、
  “帮我读这本书/看看这本书/分析这本 PDF”、给一本书画思维导图、summarize this book、extract knowledge from PDF/book 等场景时使用本技能；
  即使用户未明确提到“skill”，只要目标是从书籍文件产出笔记/总结也应触发。
---

# AI 逐页读书技能

## 它做什么

这个技能把一本书（支持 PDF、EPUB、MOBI、TXT 格式）拆成"逐页分析 → 知识累积 → 分段总结 → 最终报告"四个阶段，模拟一个认真的读者从头到尾研读一本书的过程。最终产出一份结构化、高质量的读书笔记，以本地 Markdown 文件形式交付。

- PyMuPDF/ebooklib/mobi 做多格式解析
- 输出为本地 Markdown 文件
- 原生支持中英文书籍

## 支持格式

| 格式   | 扩展名                | 解析方式                          | 分页单位  |
| ---- | ------------------ | ----------------------------- | ----- |
| PDF  | .pdf               | PyMuPDF (fitz) 逐页提取；缺失时回退到 pypdf | 页     |
| EPUB | .epub              | 优先 ebooklib；缺失时回退到 zip 读取 html/xhtml（不保证章节顺序完美） | 章节    |
| MOBI | .mobi              | mobi lib 转换后解析（缺失时建议先转 EPUB）    | 章节    |
| 纯文本  | .txt / .text / .md | 按章节标记或固定行数切分                  | 章节/段落 |

## 依赖安装

不同运行环境可能没有预装解析依赖。优先使用同一套 Python 来安装依赖，避免 `pip` 指向错误解释器。

```bash
python3 -m pip install -r ~/.claude/skills/book-reader/requirements.txt
```

如果你不想装全量依赖，也可以按格式按需安装：

```bash
python3 -m pip install pymupdf
python3 -m pip install pypdf
python3 -m pip install ebooklib beautifulsoup4
python3 -m pip install mobi
```

如果运行环境无法安装依赖（例如受限容器/无网络），先在可联网环境完成“文本提取”（得到 `book_extracted.json`），再把 JSON 复制到目标环境继续后续流程。

## 完整工作流

### Phase 0 — 获取书籍文件

根据用户输入方式获取文件到 `workspace/`：

| 用户提供方式          | 处理方法                                                          |
| --------------- | ------------------------------------------------------------- |
| 上传文件            | 将文件保存到 `workspace/`，并拿到可访问的本地路径                               |
| URL（http/https） | 使用 `curl` 或 `wget` 下载到 `workspace/`                           |
| 在线文档/网盘中的附件     | 先获取“可公开访问的下载直链（http/https）”，再用 `curl`/`wget` 下载到 `workspace/` |

下载后确认文件存在且可读：

```bash
file workspace/book.pdf  # 确认文件类型
```

### Phase 1 — 文本提取

使用打包的多格式提取脚本，自动检测格式并逐页/逐章解析，跳过目录、索引、版权页等非内容部分：

```bash
# 安装依赖（如需要）
python3 -m pip install -r ~/.claude/skills/book-reader/requirements.txt

# 提取文本
python3 ~/.claude/skills/book-reader/scripts/extract_book.py <book_path> -o workspace/book_extracted.json
```

脚本输出的 JSON 结构：

```json
{
  "metadata": {
    "filename": "book.epub",
    "format": "epub",
    "total_pages": 42,
    "processed_pages": 42,
    "content_pages": 38,
    "skipped_pages": 4
  },
  "pages": [
    {"page_number": 1, "title": "Chapter 1: Introduction", "text": "..."},
    {"page_number": 2, "title": "Chapter 2: Main Theory", "text": "..."}
  ]
}
```

每个 page 对象包含：

- `page_number`：在原书中的页码或章节序号
- `title`：章节标题（EPUB/MOBI 会提取 HTML 标题；PDF 显示页码；TXT 按章节标记或段落标题）
- `text`：纯文本内容

验证提取结果：如果 `content_pages` 为 0 或极少，可能是扫描版 PDF（需 OCR）或文件损坏，应告知用户。

### Phase 2 — 逐批知识提取

这是核心步骤。读取提取的 JSON，按内容分批次进行知识点提取。

**分批策略**：将所有 content pages 分成若干批次（每批约 5-8 页/章节），逐批让 AI 分析并提取知识点。这样做而非逐页调用是为了在保持上下文连贯性的同时控制调用次数。

对每批内容，你需要：

1. **判断内容类型**：实质性内容（理论、论证、案例）还是辅助内容（前言致谢、过渡段落）
2. **提取知识点**：每个知识点应该是一个完整的、可独立理解的陈述
3. **保留重要引用**：原文中特别精彩或关键的句子
4. **标注术语**：首次出现的专业术语及其定义
5. **记录示例**：书中给出的关键示例及其说明

**知识点提取时的思考方式**（根据书籍语言使用对应语言输出）：

你是一位认真的读书者，正在逐页研读一本书。对于每批页面内容：

- 提取**核心知识点**：每个用一句完整的话概括，确保脱离上下文也能理解
- 提取**关键引用**：值得记录的原文精彩句子（如有）
- 提取**术语定义**：新出现的专业术语及其解释（如有）
- 提取**重要示例**：书中给出的案例或示例（如有）
- 如果这几页主要是过渡性内容、重复内容或无实质信息，简要说明并跳过

每批提取完成后，将知识点累积到一个列表中，供后续批次参考（只需传最近的 10-15 个知识点作为上下文即可，避免内容过长）。

### Phase 3 — 阶段性摘要（可选但推荐）

如果书籍超过 50 页/章内容，建议每处理完 30-50 页生成一次阶段性摘要：

1. 到目前为止的主要主题和论点
2. 关键概念之间的关系
3. 作者的核心观点走向

### Phase 4 — 生成最终读书笔记

所有内容处理完成后，汇总所有知识点和阶段性摘要，生成最终报告。

**最终报告模板**（`## 思维导图` 为必填小节，生成方法见 Phase 4.5；mermaid 块外层模板用四个反引号只是为了嵌套，笔记里照常用三个）：

````markdown
# 📚 《{书名}》读书笔记

## 书籍概览
- **书名**：{从元数据或首页提取}
- **格式**：{PDF/EPUB/MOBI/TXT}
- **规模**：{total_pages} 页/章（分析了 {content_pages} 个内容单元）
- **分析日期**：{当前日期}

## 思维导图

```mermaid
%%{init: {"flowchart": {"nodeSpacing": 8, "rankSpacing": 50, "curve": "stepBefore"}}}%%
flowchart LR
  Root(["{书名短称}"]):::hub
  Root --- Part1["{主题块} ChX–Y"]:::c1
    Part1 --- P1A["{核心结论}"]:::c1
  classDef hub fill:#1f3a93,color:#fff,stroke:#1f3a93
  classDef c1 fill:#fff4b3,color:#222,stroke:#999
```

{2-4 句：跨分支依赖关系与建议阅读路径}

## 核心主题
{书籍的 3-5 个核心主题，每个用一段话描述}

## 章节要点
{按章节/部分组织的知识点摘要}

### {章节标题}
- 主要论点：...
- 关键知识点：...
- 重要引用：...

## 关键概念与术语

| 术语 | 定义 | 出处 |
|------|------|------|
| ... | ... | ... |

## 精华摘录
{最值得记忆的原文段落或句子，用引用格式}

## 全书总结
{完整连贯的全书总结，涵盖主要论点、逻辑链条和结论}

## 延伸思考
{基于书籍内容提出的 2-3 个思考问题}
````

### Phase 4.5 — 绘制并校验全书思维导图

`## 章节要点` 写完后再画导图：导图是章节要点的压缩，不是另起炉灶。导图画成左根右叶的树状图（Mermaid `flowchart LR`，不用 `mindmap`），严格按 `references/mindmap-rules.md` 执行：

1. 把全书按论证主线合并成 3–5 个主题块（第 1 层），每块 3–5 个结论型节点（第 2 层）。全图目标 18–26 个节点，硬上限 30 个。
2. 套用 `references/mindmap-rules.md` §2 的语法模板，`init` 行、`---` 连线、`hub`/`cN` 配色都照抄。
3. 浅色、深色主题各实际渲染一次，两张图都用 Read 打开，按 §3 检查树形、颜色、深色可读性、文字完整和高度。不通过就修，修完重新渲染、重新检查。
4. 在导图下方写说明段，依次写：跨分支依赖、阅读路径、因预算省略的主题。
5. 超长书籍按 §5 处理，在 `_detail/` 详细版中补充各分支子图。
6. 汇报时如实写明导图是“已渲染校验（N 个节点）”还是“未能渲染”。

### Phase 5 — 输出为本地 Markdown 文件

将最终报告保存到 Obsidian 的 BookRead 目录（`BOOK_NOTES_PATH`）：

```
BOOK_NOTES_PATH = "/Users/beenli/Library/Mobile Documents/iCloud~md~obsidian/Documents/ob-career/001-input/BookRead"
```

- 文件名：`{BOOK_NOTES_PATH}/{书名}.md`（书名来自元数据或首页；清理 `/ \ : * ? " < > |` 等非法字符）；无法确定书名时用 `{BOOK_NOTES_PATH}/_inbox/{原文件名}.md`
- 在报告最前面加 YAML frontmatter，方便 Obsidian 检索：

```yaml
---
title: "{书名}"
author: [{作者}]
format: {pdf/epub/mobi/txt}
source_file: "{原书路径}"
tags: [book-notes]
created: {YYYY-MM-DD}
---
```

- 同名笔记已存在时，先告知用户并确认是覆盖还是另存为 `{书名}_v2.md`
- `workspace/` 只放中间产物（下载的书、`book_extracted.json`、阶段性摘要），不要写入 Obsidian
- 笔记正文不要使用 Obsidian task 语法（`- [ ]` / `- [x]`）

向用户返回 Obsidian 中的笔记路径。

## 关键注意事项

### 书籍长度处理策略

| 书籍规模 | 内容单元数   | 策略                      |
| ---- | ------- | ----------------------- |
| 短篇   | < 30    | 逐页分析，不需要阶段性摘要           |
| 中篇   | 30-100  | 每 5-8 页一批，每 40 页阶段性摘要   |
| 长篇   | 100-300 | 每 8-10 页一批，每 50 页阶段性摘要  |
| 超长篇  | > 300   | 每 10-15 页一批，每 60 页阶段性摘要 |

### 语言检测

从前几页内容自动检测书籍语言。所有知识提取和摘要生成应使用与书籍相同的语言，除非用户明确要求特定语言输出。

### 错误处理

- **文件无法打开**：告知用户文件可能损坏或格式不受支持
- **内容页为 0**：可能是扫描版 PDF（需 OCR）或空文件
- **MOBI 转换失败**：建议用户先转为 EPUB 格式
- **依赖缺失**：运行 `pip install pymupdf ebooklib mobi beautifulsoup4`
- **文件写入失败**：改用更短的文件名重试写入 `BOOK_NOTES_PATH`；仍失败再保存到 `workspace/` 并告知用户

### 与用户的交互

在处理过程中主动向用户报告进度：

- "正在解析 {格式} 文件... 共 {N} 页/章"
- "已提取 {M}/{N} 内容单元的知识点"
- "正在生成最终读书笔记..."
- "思维导图（树状）已渲染校验：浅色和深色主题，{N} 个节点"
- "读书笔记已生成，已保存到 Obsidian：{markdown\_path}"

## 目录结构

```
book-reader/
├── SKILL.md              # 本文件
├── scripts/
│   └── extract_book.py   # 多格式文本提取脚本（PDF/EPUB/MOBI/TXT）
└── references/
    └── mindmap-rules.md  # 树状思维导图的结构、节点预算、语法模板与看图检查项
```
