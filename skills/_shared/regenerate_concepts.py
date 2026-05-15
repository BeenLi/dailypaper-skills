#!/usr/bin/env python3
"""Regenerate concept notes with the enhanced template.

For each concept in _concepts/, gather all paper notes that reference it
(via [[wikilink]] / alias / #section / table-cell forms), build an LLM
prompt that combines the existing concept body with the relevant paper
excerpts, and either:

  - print the prompts (--dry-run, default)
  - write prompts to a directory (--write-prompts <dir>)
  - run an external LLM and capture output to _concepts_regen/ (--apply --llm-cmd ...)
  - diff regenerated vs existing (--diff)
  - install regenerated over existing (--install [--force])

Notes:
- `--install` is the dangerous step (overwrite). It requires the Obsidian
  vault to have a clean git tree unless --force is passed.
- LLM is invoked via subprocess.run([list, of, args]); never shell=True.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

from scan_missing_concepts import (
    clean_wikilink_target,
    extract_wikilinks,
    iter_note_files,
    normalize_name,
    parse_aliases,
    parse_frontmatter,
)


CONCEPT_TYPE_DIFF_SECTIONS = {
    "data-structure": ["## 内存视图 / 字段布局"],
    "algorithm": ["## 步骤", "## 复杂度"],
    "mechanism": ["## 状态与触发条件", "## 关键参数"],
    "architecture": ["## 组件与接口"],
    "hardware": ["## 接口与典型参数"],
    "software-abstraction": ["## API 与生命周期"],
    "metric": ["## 测量方法"],
    "theory-model": ["## 假设与失效边界"],
}

MAX_REFS_PER_CONCEPT = 3
MAX_TOKENS_PER_REF = 500  # rough char budget (~chars ≈ tokens for CJK heavy text)


@dataclass
class ConceptInfo:
    name: str
    path: Path
    concept_type: str
    aliases: set[str]
    body: str
    lookup_keys: set[str] = field(default_factory=set)


def parse_concept_type(frontmatter: str) -> str:
    match = re.search(r"^concept_type\s*:\s*(\S+)", frontmatter, re.MULTILINE)
    return match.group(1).strip() if match else ""


def load_concepts(concepts_root: Path) -> list[ConceptInfo]:
    concepts: list[ConceptInfo] = []
    for path in sorted(concepts_root.rglob("*.md")):
        if path.name.startswith("_index_"):
            continue
        text = path.read_text(encoding="utf-8")
        frontmatter = parse_frontmatter(text)
        body = text[len(frontmatter) + 8 :] if frontmatter else text  # skip "---\n...\n---\n"
        aliases = parse_aliases(frontmatter)
        ct = parse_concept_type(frontmatter)
        name = path.stem
        lookup = {normalize_name(name)} | {normalize_name(a) for a in aliases if a}
        concepts.append(
            ConceptInfo(
                name=name,
                path=path,
                concept_type=ct,
                aliases=aliases,
                body=body.strip(),
                lookup_keys=lookup,
            )
        )
    return concepts


def find_paper_references(
    concept: ConceptInfo,
    notes_root: Path,
    concepts_root: Path,
    max_refs: int = MAX_REFS_PER_CONCEPT,
) -> list[tuple[Path, str]]:
    """Find paper notes that wikilink to this concept, return up to max_refs.

    Each tuple is (path, excerpt). Excerpt is the paragraph (paragraph =
    chunk separated by blank lines) that contains the wikilink, trimmed
    to MAX_TOKENS_PER_REF chars.
    """
    refs: list[tuple[Path, str]] = []
    for note_path in iter_note_files(notes_root, concepts_root):
        text = note_path.read_text(encoding="utf-8")
        # extract every wikilink, normalize, check against our concept's lookup keys
        wikilinks = extract_wikilinks(text)
        hit = any(normalize_name(link) in concept.lookup_keys for link in wikilinks)
        if not hit:
            continue
        excerpt = extract_excerpt_around_link(text, concept.lookup_keys)
        if excerpt:
            refs.append((note_path, excerpt))
        if len(refs) >= max_refs:
            break
    return refs


def extract_excerpt_around_link(text: str, lookup_keys: set[str]) -> str:
    """Pull out the paragraph(s) that contain a wikilink to one of lookup_keys."""
    paragraphs = re.split(r"\n\s*\n", text)
    matched = []
    for para in paragraphs:
        para_links = extract_wikilinks(para)
        if any(normalize_name(link) in lookup_keys for link in para_links):
            matched.append(para.strip())
        if sum(len(p) for p in matched) > MAX_TOKENS_PER_REF:
            break
    excerpt = "\n\n".join(matched)
    if len(excerpt) > MAX_TOKENS_PER_REF:
        excerpt = excerpt[:MAX_TOKENS_PER_REF].rsplit("\n", 1)[0] + "\n[... 截断]"
    return excerpt


def build_prompt(concept: ConceptInfo, refs: list[tuple[Path, str]]) -> str:
    diff_sections = CONCEPT_TYPE_DIFF_SECTIONS.get(concept.concept_type, [])
    diff_section_lines = "\n".join(f"  - `{s}`" for s in diff_sections) or "  (无 — concept_type 未识别)"

    refs_block_lines: list[str] = []
    for path, excerpt in refs:
        refs_block_lines.append(f"### 论文: {path.stem}\n\n{excerpt}\n")
    refs_block = "\n".join(refs_block_lines) if refs_block_lines else "(本 concept 暂无论文笔记反向引用)"

    return f"""你是 systems 论文笔记系统的 concept 编辑助手。

# 任务
用增强模板**重写**下面这篇 concept 笔记。保留现有内容、扩充至 60-100 行。

# 概念基本信息
- 名称: {concept.name}
- concept_type: {concept.concept_type}
- aliases: {sorted(concept.aliases)}

# 已有 concept 内容(必须保留并扩充,不可删减论文引用 / 公式 / 现有要点)
{concept.body}

# 引用本 concept 的论文笔记摘录(只能从这里找证据)
{refs_block}

# 输出格式(严格按模板)
```markdown
---
type: concept
aliases: {sorted(concept.aliases)}
concept_type: {concept.concept_type}
---

# {concept.name}

## 定义
一句话定义。只解释 what，不解释 why。

## 动机与痛点
为什么会出现这个 concept？它解决什么瓶颈？跟之前的做法相比，核心改进是什么？

## 直观例子
mini walk-through / 伪代码 / ASCII 状态图 / Mermaid 任选一种。

## 核心要点
3-5 条，每条解释原理，不只是 fact 列表。

{chr(10).join(diff_sections)}
按上面差异化段名补内容。

## 边界与对比
- 什么情况不适用
- 跟最容易混淆的近邻 concept 的差别

## 代表工作与具体用法
- [[PaperX]]: 它怎么用这个 concept？用出什么效果？
- 只列从"论文笔记摘录"段能找到证据的 paper

## 相关概念
- [[xxx]]: 和本概念的关系（组成/替代/协作/前置）

## 学习索引
- 入门 paper / 综述: 必须有标题或 URL
- 经典 blog / 教科书章节: 必须有 URL
- 找不到任何证据 → 整段写 `TODO: 待人工补充学习材料`
```

# 硬规则
1. **不可凭空编造**: 动机 / 直观例子 / 学习索引必须从已有 body 或论文摘录推断
2. **代表工作只能来自上面"论文笔记摘录"段**,不可凭印象添加 paper 名
3. **学习索引**: 没具体 URL / 标题就整段写 TODO,不允许凭印象列 blog
4. **差异化段(按 concept_type='{concept.concept_type}')必加**:
{diff_section_lines}
5. **architecture** 类必须用 Mermaid `flowchart LR`,不许 ASCII 替代
6. **长度上限 120 行**,超过说明在凑长度,请收敛

# 重要: 直接输出新版 markdown 全文,不要额外解释、不要包 markdown fence
"""


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def run_llm(llm_cmd: list[str], prompt: str, timeout: int = 600) -> str:
    """Call external LLM via subprocess.run([...]), never shell=True."""
    result = subprocess.run(
        llm_cmd,
        input=prompt,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"LLM exit {result.returncode}: {result.stderr[:300]}")
    return result.stdout.strip()


def regen_dir_for(concepts_root: Path) -> Path:
    return concepts_root.parent / "_concepts_regen"


def ensure_vault_git_clean(notes_root: Path) -> tuple[bool, str]:
    """Return (clean, message). Best-effort: if notes_root not in a git repo, treat as clean."""
    try:
        result = subprocess.run(
            ["git", "-C", str(notes_root), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return True, "git not installed; skipping clean check"
    if result.returncode != 0:
        return True, "vault not under git; skipping clean check"
    if result.stdout.strip():
        return False, result.stdout
    return True, "clean"


def cmd_dry_run(concepts: list[ConceptInfo], notes_root: Path, concepts_root: Path) -> int:
    for concept in concepts:
        refs = find_paper_references(concept, notes_root, concepts_root)
        prompt = build_prompt(concept, refs)
        print(f"### {concept.path.relative_to(concepts_root)} (refs={len(refs)}, prompt_chars={len(prompt)})")
        print(prompt)
        print()
    return 0


def cmd_write_prompts(
    concepts: list[ConceptInfo],
    notes_root: Path,
    concepts_root: Path,
    out_dir: Path,
) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    for concept in concepts:
        refs = find_paper_references(concept, notes_root, concepts_root)
        prompt = build_prompt(concept, refs)
        target = out_dir / f"{concept.concept_type}__{concept.name}.prompt.md"
        target.write_text(prompt, encoding="utf-8")
        print(f"wrote {target} (refs={len(refs)}, chars={len(prompt)})")
    return 0


def cmd_apply(
    concepts: list[ConceptInfo],
    notes_root: Path,
    concepts_root: Path,
    llm_cmd: list[str],
) -> int:
    regen_root = regen_dir_for(concepts_root)
    regen_root.mkdir(parents=True, exist_ok=True)
    manifest: dict = {"items": []}
    for concept in concepts:
        refs = find_paper_references(concept, notes_root, concepts_root)
        prompt = build_prompt(concept, refs)
        rel = concept.path.relative_to(concepts_root)
        target = regen_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            out = run_llm(llm_cmd, prompt)
        except (subprocess.TimeoutExpired, RuntimeError) as exc:
            print(f"FAIL {rel}: {exc}", file=sys.stderr)
            continue
        target.write_text(out, encoding="utf-8")
        manifest["items"].append(
            {
                "rel": str(rel),
                "original_sha": hash_text(concept.path.read_text(encoding="utf-8")),
                "regen_sha": hash_text(out),
                "refs_count": len(refs),
            }
        )
        print(f"regen ok: {rel} (refs={len(refs)}, out_chars={len(out)})")
    (regen_root / ".install_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"wrote manifest with {len(manifest['items'])} items")
    return 0


def cmd_diff(concepts: list[ConceptInfo], concepts_root: Path) -> int:
    regen_root = regen_dir_for(concepts_root)
    if not regen_root.exists():
        print(f"no regen dir at {regen_root}", file=sys.stderr)
        return 1
    for concept in concepts:
        rel = concept.path.relative_to(concepts_root)
        regen_path = regen_root / rel
        if not regen_path.exists():
            print(f"[missing in regen] {rel}")
            continue
        result = subprocess.run(
            ["diff", "-u", str(concept.path), str(regen_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.stdout:
            print(f"### diff: {rel}")
            print(result.stdout)
    return 0


def cmd_install(
    concepts: list[ConceptInfo],
    notes_root: Path,
    concepts_root: Path,
    force: bool,
) -> int:
    regen_root = regen_dir_for(concepts_root)
    manifest_path = regen_root / ".install_manifest.json"
    if not manifest_path.exists():
        print(f"no manifest at {manifest_path}; run --apply first", file=sys.stderr)
        return 1
    clean, msg = ensure_vault_git_clean(notes_root)
    if not clean and not force:
        print(f"vault not clean; refusing to install. Pass --force to override.\n{msg}", file=sys.stderr)
        return 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    installed = 0
    for item in manifest["items"]:
        regen_path = regen_root / item["rel"]
        target = concepts_root / item["rel"]
        if not regen_path.exists():
            print(f"SKIP {item['rel']}: regen file missing", file=sys.stderr)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(regen_path, target)
        installed += 1
    print(f"installed {installed} / {len(manifest['items'])} concepts")
    return 0


def default_paths() -> tuple[Path, Path]:
    if str(_SHARED_DIR) not in sys.path:
        sys.path.insert(0, str(_SHARED_DIR))
    from user_config import concepts_dir, paper_notes_dir

    return paper_notes_dir(), concepts_dir()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    default_notes, default_concepts = default_paths()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notes-root", type=Path, default=default_notes)
    parser.add_argument("--concepts-root", type=Path, default=default_concepts)

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="print prompts to stdout (default)")
    mode.add_argument("--write-prompts", type=Path, help="write prompts to a directory")
    mode.add_argument("--apply", action="store_true", help="run external LLM and write regen files")
    mode.add_argument("--diff", action="store_true", help="show diff between regen and existing")
    mode.add_argument("--install", action="store_true", help="overwrite _concepts/ with _concepts_regen/")

    parser.add_argument(
        "--llm-cmd",
        nargs="+",
        help="external LLM CLI as token list (e.g. --llm-cmd claude -p). Required with --apply.",
    )
    parser.add_argument("--force", action="store_true", help="bypass git clean check on --install")
    parser.add_argument("--only", help="restrict to a single concept name (case-insensitive)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    concepts = load_concepts(args.concepts_root)
    if args.only:
        target = normalize_name(args.only)
        concepts = [c for c in concepts if target in c.lookup_keys]
        if not concepts:
            print(f"no concept matches '{args.only}'", file=sys.stderr)
            return 1

    if args.write_prompts:
        return cmd_write_prompts(concepts, args.notes_root, args.concepts_root, args.write_prompts)
    if args.apply:
        if not args.llm_cmd:
            print("--apply requires --llm-cmd <list of args>", file=sys.stderr)
            return 1
        return cmd_apply(concepts, args.notes_root, args.concepts_root, args.llm_cmd)
    if args.diff:
        return cmd_diff(concepts, args.concepts_root)
    if args.install:
        return cmd_install(concepts, args.notes_root, args.concepts_root, args.force)
    # default: dry-run
    return cmd_dry_run(concepts, args.notes_root, args.concepts_root)


if __name__ == "__main__":
    raise SystemExit(main())
