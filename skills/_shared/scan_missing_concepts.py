#!/usr/bin/env python3
"""Scan paper notes for wikilinks that do not have concept notes yet."""

from __future__ import annotations

import argparse
import csv
import io
import re
import sys
from collections import defaultdict
from pathlib import Path


CSV_FIELDS = ["concept_name", "refs_count", "example_papers", "candidate_type"]
WIKILINK_RE = re.compile(r"(?<!!)\[\[([^\]\n]+)\]\]")


def normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip()).casefold()


def clean_wikilink_target(raw_target: str) -> str:
    target = raw_target.split("|", 1)[0].split("#", 1)[0].strip()
    if target.endswith(".md"):
        target = target[:-3]
    return target.strip()


def extract_wikilinks(text: str) -> set[str]:
    links: set[str] = set()
    for match in WIKILINK_RE.finditer(text):
        target = clean_wikilink_target(match.group(1))
        if target:
            links.add(target)
    return links


def parse_frontmatter(text: str) -> str:
    if not text.startswith("---"):
        return ""
    match = re.match(r"(?s)^---\s*\n(.*?)\n---(?:\n|$)", text)
    return match.group(1) if match else ""


def _strip_yaml_scalar(value: str) -> str:
    return value.strip().strip("\"'")


def parse_aliases(frontmatter: str) -> set[str]:
    aliases: set[str] = set()
    lines = frontmatter.splitlines()
    for index, line in enumerate(lines):
        match = re.match(r"^aliases\s*:\s*(.*)$", line)
        if not match:
            continue

        inline_value = match.group(1).strip()
        if inline_value.startswith("[") and inline_value.endswith("]"):
            for alias in inline_value[1:-1].split(","):
                cleaned = _strip_yaml_scalar(alias)
                if cleaned:
                    aliases.add(cleaned)
            return aliases
        if inline_value and inline_value not in {"[]", "null"}:
            aliases.add(_strip_yaml_scalar(inline_value))
            return aliases

        for child in lines[index + 1 :]:
            stripped = child.strip()
            if not stripped:
                continue
            if not (child.startswith((" ", "\t")) or stripped.startswith("-")):
                break
            if stripped.startswith("-"):
                cleaned = _strip_yaml_scalar(stripped[1:])
                if cleaned:
                    aliases.add(cleaned)
        return aliases
    return aliases


def load_existing_concepts(concepts_root: Path) -> set[str]:
    existing: set[str] = set()
    if not concepts_root.exists():
        return existing

    for path in concepts_root.rglob("*.md"):
        existing.add(normalize_name(path.stem))
        frontmatter = parse_frontmatter(path.read_text(encoding="utf-8"))
        for alias in parse_aliases(frontmatter):
            existing.add(normalize_name(alias))
    return existing


def should_scan_note(path: Path, notes_root: Path, concepts_root: Path) -> bool:
    if path.name.startswith("_index"):
        return False
    try:
        path.relative_to(concepts_root)
        return False
    except ValueError:
        pass
    relative_parts = path.relative_to(notes_root).parts
    return "_inbox" not in relative_parts


def iter_note_files(notes_root: Path, concepts_root: Path):
    for path in sorted(notes_root.rglob("*.md")):
        if should_scan_note(path, notes_root, concepts_root):
            yield path


def load_existing_paper_notes(notes_root: Path, concepts_root: Path) -> set[str]:
    return {normalize_name(path.stem) for path in iter_note_files(notes_root, concepts_root)}


def parse_seed_vocabulary(reference_path: Path) -> dict[str, str]:
    if not reference_path.exists():
        return {}

    text = reference_path.read_text(encoding="utf-8")
    section_match = re.search(
        r"(?ms)^##\s+Systems Concept Seed Vocabulary\b(.*?)(?=^##\s+|\Z)",
        text,
    )
    if not section_match:
        return {}

    seed_types: dict[str, str] = {}
    for line in section_match.group(1).splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or set(stripped.replace("|", "").strip()) <= {"-"}:
            continue
        columns = [column.strip() for column in stripped.strip("|").split("|")]
        if len(columns) < 2:
            continue
        concept_type = columns[0]
        if concept_type.lower() in {"concept_type", "type", "子目录"}:
            continue
        seed_terms = columns[1]
        for term in re.split(r",|，", seed_terms):
            cleaned = term.strip()
            if cleaned:
                seed_types[cleaned] = concept_type
    return seed_types


def scan_missing_concepts(
    notes_root: Path,
    concepts_root: Path,
    reference_path: Path,
    include_seed: bool = False,
) -> list[dict]:
    existing = load_existing_concepts(concepts_root)
    existing_papers = load_existing_paper_notes(notes_root, concepts_root)
    seed_types = parse_seed_vocabulary(reference_path)
    refs_by_concept: dict[str, set[str]] = defaultdict(set)
    display_names: dict[str, str] = {}

    for note_path in iter_note_files(notes_root, concepts_root):
        links = extract_wikilinks(note_path.read_text(encoding="utf-8"))
        for link in links:
            normalized = normalize_name(link)
            display_names.setdefault(normalized, link)
            refs_by_concept[normalized].add(note_path.stem)

    rows_by_name: dict[str, dict] = {}
    for normalized, refs in refs_by_concept.items():
        if normalized in existing or normalized in existing_papers:
            continue
        concept_name = display_names[normalized]
        rows_by_name[normalized] = {
            "concept_name": concept_name,
            "refs_count": len(refs),
            "example_papers": "; ".join(sorted(refs)[:5]),
            "candidate_type": seed_types.get(concept_name, ""),
        }

    if include_seed:
        linked_or_existing = set(refs_by_concept) | existing
        for seed_name, concept_type in seed_types.items():
            normalized = normalize_name(seed_name)
            if normalized in linked_or_existing or normalized in rows_by_name:
                continue
            rows_by_name[normalized] = {
                "concept_name": seed_name,
                "refs_count": 0,
                "example_papers": "",
                "candidate_type": concept_type,
            }

    return sorted(
        rows_by_name.values(),
        key=lambda row: (-int(row["refs_count"]), row["candidate_type"], row["concept_name"].casefold()),
    )


def render_csv(rows: list[dict]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=CSV_FIELDS)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return output.getvalue()


def default_paths() -> tuple[Path, Path, Path]:
    shared_dir = Path(__file__).resolve().parent
    if str(shared_dir) not in sys.path:
        sys.path.insert(0, str(shared_dir))

    from user_config import concepts_dir, paper_notes_dir

    notes_root = paper_notes_dir()
    concepts_root = concepts_dir()
    reference_path = shared_dir.parent / "paper-reader" / "references" / "concept-categories.md"
    return notes_root, concepts_root, reference_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    default_notes_root, default_concepts_root, default_reference_path = default_paths()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notes-root", type=Path, default=default_notes_root)
    parser.add_argument("--concepts-root", type=Path, default=default_concepts_root)
    parser.add_argument("--reference", type=Path, default=default_reference_path)
    parser.add_argument("--with-seed", action="store_true", help="include seed terms missing from notes and concepts")
    parser.add_argument("--output", type=Path, help="write CSV output to this path")
    parser.add_argument("--dry-run", action="store_true", help="print CSV output to stdout even when --output is set")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    rows = scan_missing_concepts(args.notes_root, args.concepts_root, args.reference, args.with_seed)
    csv_text = render_csv(rows)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(csv_text, encoding="utf-8")
    if args.dry_run or not args.output:
        print(csv_text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
