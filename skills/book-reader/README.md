# book-reader

一个“逐页/逐章读书并做笔记”的 Skill 项目：把 PDF/EPUB/MOBI/TXT 书籍解析为结构化文本（JSON），再按批次提炼知识点，最终输出为本地 Markdown 读书笔记。

## 功能

- 支持 PDF/EPUB/MOBI/TXT（含 .md/.markdown 纯文本）
- 逐页/逐章抽取正文，尽量跳过目录、索引、版权页等非内容部分
- 适合长书：按 5–8 页/章分批提炼知识点，可选阶段性摘要
- 最终产出：本地 Markdown 文件（如 `workspace/book_notes.md`）

## 目录结构

```
.
├── SKILL.md
└── scripts
    └── extract_book.py
```

## 环境要求

- Python 3.9+（建议 3.11+）

### Python 依赖

`scripts/extract_book.py` 会按格式动态 import 对应依赖：

```bash
python3 -m pip install -r requirements.txt
```

### 扫描版 PDF（可选）

如果 PDF 是扫描图片（提取不到正文），需要先 OCR。推荐开源方案：

- ocrmypdf + tesseract

示例（以你本机/运行环境实际安装方式为准）：

```bash
ocrmypdf --language chi_sim+eng input.pdf output_ocr.pdf
```

## 快速开始（脚本）

把书籍文件放到本地可访问路径，然后运行提取脚本生成 JSON：

```bash
python3 scripts/extract_book.py path/to/book.pdf -o workspace/book_extracted.json
```

可选限制处理的页/章数：

```bash
python3 scripts/extract_book.py path/to/book.epub -o workspace/book_extracted.json --max-pages 20
```

输出 JSON 结构示例：

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
    {"page_number": 1, "title": "Chapter 1", "text": "..."}
  ]
}
```

## 使用方式（Skill）

本项目的核心流程定义在 [SKILL.md](./SKILL.md)：

1. 准备书籍文件（本地路径或可公开访问的 http/https 直链下载到 `workspace/`）
2. 运行 `scripts/extract_book.py` 提取为 `workspace/book_extracted.json`
3. 按批次从 JSON 中读取正文并提炼知识点
4. 汇总生成最终读书笔记并保存为本地 Markdown 文件

## 常见问题

### 依赖安装失败怎么办？

优先确认 Python 版本，再按需安装依赖：

```bash
python3.11 -V
pip install pymupdf ebooklib mobi beautifulsoup4
```

### content_pages 很少或为 0？

常见原因：

- 扫描版 PDF（需要先 OCR）
- 文件损坏或加密/权限限制
- 目录/索引页占比过高（可先用 `--max-pages` 抽样验证）
