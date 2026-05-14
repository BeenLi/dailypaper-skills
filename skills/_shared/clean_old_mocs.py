#!/usr/bin/env python3
"""
clean_old_mocs: 清理使用旧命名规则（<目录名>.md，与目录同名）生成的 MOC 索引文件。

背景：moc_builder 支持 mocs.filename_prefix 之后，旧 MOC 文件不会被自动覆盖也不会被删除。
此脚本会找到所有"与所在目录同名且内容明显是脚本生成 MOC"的 .md 文件，默认 dry-run 列出，
传 --apply 才真正删除。安全网：只删带有 `generated_by: dailypaper-skills` frontmatter 标记的文件。

用法：
    python3 clean_old_mocs.py            # dry-run，列出候选
    python3 clean_old_mocs.py --apply    # 真正删除
    python3 clean_old_mocs.py --apply --force  # 跳过 frontmatter 校验（慎用）
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

from user_config import (
    concepts_dir,
    moc_filename_prefix,
    paper_notes_dir,
    paths_config,
)


MOC_MARKER = "generated_by: dailypaper-skills"


def _is_generated_moc(path: Path) -> bool:
    try:
        head = path.read_text(encoding="utf-8", errors="ignore")[:512]
    except OSError:
        return False
    return MOC_MARKER in head


def _walk(root: Path, excluded: set[str]) -> list[Path]:
    out: list[Path] = []
    if not root.exists():
        return out
    queue = [root]
    while queue:
        cur = queue.pop(0)
        out.append(cur)
        for child in sorted(cur.iterdir(), key=lambda p: p.name):
            if not child.is_dir():
                continue
            if child.name.startswith(".") or child.name in excluded:
                continue
            queue.append(child)
    return out


def _candidates(root: Path, excluded: set[str], current_prefix: str) -> list[Path]:
    """Old-style MOCs are `<dirname>.md` (no prefix) sitting in their own directory."""
    found: list[Path] = []
    for d in _walk(root, excluded):
        legacy = d / f"{d.name}.md"
        if not legacy.is_file():
            continue
        # If user has prefix="" then "legacy name" == "current name" — that's the active MOC, skip.
        if current_prefix == "":
            continue
        found.append(legacy)
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="真正删除文件；默认仅 dry-run")
    parser.add_argument(
        "--force",
        action="store_true",
        help="跳过 frontmatter 校验（不要求 generated_by: dailypaper-skills 标记，慎用）",
    )
    parser.add_argument("--papers-only", action="store_true", help="只扫论文目录")
    parser.add_argument("--concepts-only", action="store_true", help="只扫概念目录")
    args = parser.parse_args()

    prefix = moc_filename_prefix()
    if prefix == "":
        print(
            "⚠️  当前 mocs.filename_prefix 为空字符串，说明 MOC 命名还是 <目录名>.md。\n"
            "    此时活跃 MOC 就是旧规则下的文件，没有需要清理的对象。\n"
            "    先在 user-config.json 设好 mocs.filename_prefix 再跑此脚本。",
            file=sys.stderr,
        )
        return 1

    excluded_for_papers = {paths_config()["concepts_folder"]}

    candidates: list[Path] = []
    if not args.concepts_only:
        candidates.extend(_candidates(paper_notes_dir(), excluded_for_papers, prefix))
    if not args.papers_only:
        candidates.extend(_candidates(concepts_dir(), set(), prefix))

    if not candidates:
        print("没有找到旧规则下的 MOC 文件（<目录名>.md）。")
        return 0

    eligible: list[Path] = []
    skipped: list[tuple[Path, str]] = []
    for path in candidates:
        if args.force or _is_generated_moc(path):
            eligible.append(path)
        else:
            skipped.append((path, "缺少 frontmatter 标记（generated_by: dailypaper-skills）"))

    mode = "APPLY (deleting)" if args.apply else "DRY-RUN"
    print(f"[{mode}] 当前 prefix='{prefix}'；找到 {len(candidates)} 个旧 MOC 候选。\n")

    if eligible:
        print(f"将{'删除' if args.apply else '会删除（dry-run）'}以下 {len(eligible)} 个文件：")
        for path in eligible:
            print(f"  - {path}")
        print()

    if skipped:
        print(f"跳过 {len(skipped)} 个文件（不像是脚本生成的 MOC；想强删用 --force）：")
        for path, reason in skipped:
            print(f"  - {path}  [{reason}]")
        print()

    if args.apply and eligible:
        deleted = 0
        for path in eligible:
            try:
                path.unlink()
                deleted += 1
            except OSError as exc:
                print(f"删除失败：{path}: {exc}", file=sys.stderr)
        print(f"已删除 {deleted}/{len(eligible)} 个文件。")
    elif not args.apply:
        print("（dry-run，未删除任何文件。加 --apply 真正执行。）")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
