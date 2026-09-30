#!/usr/bin/env python3
"""Find / fix Obsidian Markdown text that should be backslash-escaped.

Covers the two most common rendering bugs in generated notes:

* array-index text such as ``C[i][j]`` / ``addr[42:39]`` -> ``C\\[i\\]\\[j\\]``
  (otherwise parsed as reference-style links);
* literal dollar signs such as ``$200`` / ``$HOME`` -> ``\\$200``
  (two of them on one line turn the text between into inline LaTeX).
* Obsidian tags triggered by accident, such as ``#SMs`` / ``#include`` ->
  ``\\#SMs`` (a ``#`` at line start or after whitespace, followed by a
  non-numeric tag name, becomes a clickable tag). Intentional tags are kept;
  see ``is_intentional_tag``.

Code (fenced / inline), math (``$...$`` / ``$$...$$``), wikilinks, Markdown
links, URLs, HTML comments and YAML frontmatter are left untouched. The fix is
idempotent: already-escaped text is never escaped twice.

See the "Markdown 特殊符号转义" section of the vault ``AGENTS.md`` for the full
rule set (``*``, ``|`` in tables, ``==``, ``<placeholder>`` ...),
which this script does not rewrite automatically.

Usage::

    python3 md_escape_check.py PATH [PATH ...]          # report, exit 1 on hits
    python3 md_escape_check.py --fix PATH [PATH ...]    # rewrite files in place

PATH may be a Markdown file or a directory (searched recursively for *.md,
skipping auto-generated ``_index_*.md``).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PROTECTED = re.compile(
    r"(```.*?```"                                              # fenced code
    r"|``(?:[^`\n]|`(?!`))+?``"                               # ``inline `code` ``
    r"|`[^`\n]+`"                                              # `inline code`
    r"|\$\$.*?\$\$"                                            # display math
    r"|(?<![\\\w])\$(?=\S)[^$\n]+?(?<=\S)\$(?![\w$])"          # inline math $x$
    r"|!?\[\[[^\n]+?\]\]"                                      # wikilink / embed
    r"|<!--.*?-->"                                             # html comment
    r"|\A---\n.*?\n---\n"                                      # frontmatter
    r"|\[[^\]\n]*\]\([^)\n]*\)"                                # [text](url)
    r"|https?://\S+)",                                         # bare url
    re.S,
)

# `[...]` directly after an identifier char, `)` or another `]`: C[i][j], f(x)[0]
INDEX = re.compile(r"(?<=[A-Za-z0-9_\)\]])\[([^\[\]\n]{1,24})\](?!\()")
# a `$` that starts a word/number and is not already escaped: $200, $HOME
DOLLAR = re.compile(r"(?<!\\)\$(?=[0-9A-Za-z])")
# Obsidian tag: `#` at line start or after whitespace, then [\w/-]+ that is
# not purely numeric (`#1` is not a tag). `# Heading` has a space, so no match.
TAG = re.compile(r"(?:(?<=^)|(?<=\s))#(?!\d+(?![\w/-]))([\w/-]+)", re.M)


# Inline tags the vault uses on purpose. Everything else that looks like a tag
# in body text is treated as accidental (`#SMs` = "number of SMs") and escaped.
# Add a namespace / name here when a new tag scheme is introduced.
INTENTIONAL_TAG_PREFIXES = (
    "t/",  # task time estimates in 003-daily/任务清单.md: #t/2h, #t/halfday
)
INTENTIONAL_TAGS = frozenset({
    "book-notes",
})


def is_intentional_tag(tag: str) -> bool:
    """Return True if ``#<tag>`` is a real Obsidian tag that must stay a tag.

    ``tag`` is the name without the leading ``#``, e.g. ``"t/2h"`` or ``"SMs"``.
    Whitelist only: guessing from the tag's shape would misfire both ways
    (lower-case ``#include`` is code, CamelCase could be a real tag).
    """
    return tag in INTENTIONAL_TAGS or tag.startswith(INTENTIONAL_TAG_PREFIXES)


def _fix_plain(text: str) -> str:
    text = INDEX.sub(lambda m: "\\[" + m.group(1) + "\\]", text)
    text = DOLLAR.sub(r"\\$", text)
    return TAG.sub(
        lambda m: m.group(0) if is_intentional_tag(m.group(1)) else "\\" + m.group(0),
        text,
    )


def _plain_segments(source: str):
    """Yield (offset, text, is_plain) chunks covering the whole source."""
    pos = 0
    for match in PROTECTED.finditer(source):
        if match.start() > pos:
            yield pos, source[pos:match.start()], True
        yield match.start(), match.group(0), False
        pos = match.end()
    if pos < len(source):
        yield pos, source[pos:], True


def check(source: str) -> list[tuple[int, str]]:
    """Return (line_number, context) for every unescaped occurrence."""
    hits = []
    for offset, text, plain in _plain_segments(source):
        if not plain:
            continue
        for pattern in (INDEX, DOLLAR, TAG):
            for m in pattern.finditer(text):
                if pattern is TAG and is_intentional_tag(m.group(1)):
                    continue
                line = source.count("\n", 0, offset + m.start()) + 1
                context = text[max(0, m.start() - 15): m.end() + 5].replace("\n", " ")
                hits.append((line, context))
    return sorted(hits)


def fix(source: str) -> str:
    """Return source with plain-text index brackets and dollars escaped."""
    return "".join(
        _fix_plain(text) if plain else text
        for _, text, plain in _plain_segments(source)
    )


def iter_markdown(paths: list[str]):
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            yield from sorted(
                p for p in path.rglob("*.md") if not p.name.startswith("_index_")
            )
        else:
            yield path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="+", help="Markdown files or directories")
    parser.add_argument("--fix", action="store_true", help="rewrite files in place")
    args = parser.parse_args(argv)

    total = 0
    for path in iter_markdown(args.paths):
        source = path.read_text(encoding="utf-8")
        hits = check(source)
        if not hits:
            continue
        total += len(hits)
        print(f"== {path}  ({len(hits)})")
        for line, context in hits:
            print(f"   L{line}: {context}")
        if args.fix:
            path.write_text(fix(source), encoding="utf-8")

    if args.fix:
        print(f"fixed {total} occurrence(s)" if total else "nothing to fix")
        return 0
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
