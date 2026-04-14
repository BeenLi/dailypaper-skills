# Repository Guidelines

## Project Structure & Module Organization

This repository packages Codex skills plus a small set of Python helpers for a paper-reading workflow. Core assets live under `skills/`: `daily-papers/` orchestrates the daily pipeline, `paper-reader/` handles single-paper reads, `generate-mocs/` rebuilds Obsidian index pages, and the step-specific `daily-papers-fetch/`, `daily-papers-review/`, and `daily-papers-notes/` skills support debugging and reruns. Shared Python modules and config live in `skills/_shared/`. User-facing docs are in `README.md` and `ARCHITECTURE.md`; note templates live in `obsidian-templates/`.

## Build, Test, and Development Commands

There is no package build step. Development is mainly script execution and skill validation.

- `python3 skills/daily-papers/fetch_and_score.py --days 7 > /tmp/daily_papers_top30.json`: fetch and score candidates.
- `python3 skills/daily-papers/enrich_papers.py /tmp/daily_papers_top30.json > /tmp/daily_papers_enriched.json`: enrich paper metadata.
- `python3 skills/paper-reader/paper_daemon.py --list`: inspect Zotero collections supported by the batch reader.
- `python3 skills/paper-reader/paper_daemon.py --status`: check batch-processing progress.
- `python3 skills/_shared/generate_paper_mocs.py` and `python3 skills/_shared/generate_concept_mocs.py`: regenerate Obsidian MOCs after note changes.

## Coding Style & Naming Conventions

Follow the existing Python style: 4-space indentation, standard-library-first imports, `snake_case` for functions and files, `UPPER_CASE` for module constants. Keep scripts dependency-light and runnable with `python3` directly. Skill folders use kebab-case names and must expose a top-level `SKILL.md`. Update templates and Markdown docs in concise, instruction-first prose.

## Testing Guidelines

There is no committed `pytest` or lint configuration in this repo. Validate changes by running the affected script directly and checking generated JSON or Markdown output in `/tmp` or the target Obsidian vault. For config-related edits, verify both default loading from `skills/_shared/user-config.json` and local override behavior via `user-config.local.json`.

## Commit & Pull Request Guidelines

Recent history uses short, imperative commits such as `feat: compatible with codex & humanoid keywords`. Prefer prefixes like `feat:`, `fix:`, and `docs:` with a specific scope. PRs should explain the workflow impact, list changed skills/scripts, mention any config or vault-path assumptions, and include sample output or screenshots when note structure or generated pages change.

## Configuration & Safety Notes

Do not hardcode machine-specific paths outside the shared config layer. Keep user-specific settings in `skills/_shared/user-config.local.json` rather than editing defaults unless the change is meant for all contributors. When touching automation flags like `git_commit` or `git_push`, document the behavior change clearly because these settings affect a user’s Obsidian vault, not just this repo.
