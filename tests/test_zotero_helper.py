import importlib.util
import io
import re
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "skills" / "paper-reader" / "assets" / "zotero_helper.py"
GENERATE_PAPER_MOCS = REPO_ROOT / "skills" / "_shared" / "generate_paper_mocs.py"


def load_module():
    spec = importlib.util.spec_from_file_location("zotero_helper", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def create_fixture_db(db_path: Path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.executescript(
        """
        CREATE TABLE collections (
            collectionID INTEGER PRIMARY KEY,
            collectionName TEXT NOT NULL,
            parentCollectionID INTEGER
        );
        CREATE TABLE collectionItems (
            collectionID INTEGER NOT NULL,
            itemID INTEGER NOT NULL,
            orderIndex INTEGER DEFAULT 0
        );
        CREATE TABLE items (
            itemID INTEGER PRIMARY KEY,
            itemTypeID INTEGER NOT NULL,
            key TEXT
        );
        CREATE TABLE fields (
            fieldID INTEGER PRIMARY KEY,
            fieldName TEXT NOT NULL
        );
        CREATE TABLE itemDataValues (
            valueID INTEGER PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE itemData (
            itemID INTEGER NOT NULL,
            fieldID INTEGER NOT NULL,
            valueID INTEGER NOT NULL
        );
        CREATE TABLE itemAttachments (
            itemID INTEGER NOT NULL,
            parentItemID INTEGER NOT NULL,
            path TEXT,
            contentType TEXT
        );
        CREATE TABLE creators (
            creatorID INTEGER PRIMARY KEY,
            creatorDataID INTEGER NOT NULL
        );
        CREATE TABLE creatorData (
            creatorDataID INTEGER PRIMARY KEY,
            firstName TEXT,
            lastName TEXT,
            shortName TEXT,
            fieldMode INTEGER DEFAULT 0
        );
        CREATE TABLE itemCreators (
            itemID INTEGER NOT NULL,
            creatorID INTEGER NOT NULL,
            creatorTypeID INTEGER,
            orderIndex INTEGER DEFAULT 0
        );
        """
    )

    cursor.executemany(
        "INSERT INTO collections VALUES (?, ?, ?)",
        [
            (1, "Research Topics", None),
            (2, "Lossless Communication Compression", 1),
            (3, "Link & Fabric Integration", 2),
            (4, "Protocol Design", 2),
            (5, "Reading Queue", None),
        ],
    )

    fields = {
        "title": 1,
        "date": 2,
        "url": 3,
        "DOI": 4,
        "publicationTitle": 5,
        "extra": 6,
    }
    cursor.executemany("INSERT INTO fields VALUES (?, ?)", [(v, k) for k, v in fields.items()])

    value_id = 1

    def add_value(item_id: int, field_name: str, value: str):
        nonlocal value_id
        cursor.execute("INSERT INTO itemDataValues VALUES (?, ?)", (value_id, value))
        cursor.execute(
            "INSERT INTO itemData VALUES (?, ?, ?)",
            (item_id, fields[field_name], value_id),
        )
        value_id += 1

    cursor.executemany(
        "INSERT INTO items VALUES (?, ?, ?)",
        [
            (100, 1, "EBPCITEM"),
            (101, 1, "PARENT"),
            (102, 1, "PROTO"),
            (103, 1, "QUEUE"),
            (200, 14, "PDFKEY"),
        ],
    )
    add_value(100, "title", "EBPC: Efficient Bufferless Packet Compression")
    add_value(100, "date", "2025")
    add_value(100, "url", "https://arxiv.org/abs/2501.01234")
    add_value(100, "DOI", "10.1145/example")
    add_value(100, "publicationTitle", "SIGCOMM")
    add_value(100, "extra", "arXiv: 2501.01234")
    add_value(101, "title", "Parent Collection Paper")
    add_value(101, "date", "2024-12")
    add_value(102, "title", "Protocol Child Paper")
    add_value(103, "title", "Queue Paper")

    cursor.executemany(
        "INSERT INTO collectionItems VALUES (?, ?, ?)",
        [
            (2, 100, 0),
            (3, 100, 0),
            (2, 101, 0),
            (4, 102, 0),
            (5, 103, 0),
        ],
    )

    cursor.execute(
        "INSERT INTO itemAttachments VALUES (?, ?, ?, ?)",
        (200, 100, "storage:ebpc.pdf", "application/pdf"),
    )

    cursor.executemany(
        "INSERT INTO creatorData VALUES (?, ?, ?, ?, ?)",
        [
            (1, "Ada", "Lovelace", None, 0),
            (2, "Grace", "Hopper", None, 0),
        ],
    )
    cursor.executemany("INSERT INTO creators VALUES (?, ?)", [(1, 1), (2, 2)])
    cursor.executemany(
        "INSERT INTO itemCreators VALUES (?, ?, ?, ?)",
        [(100, 1, 1, 0), (100, 2, 1, 1)],
    )

    conn.commit()
    return conn


class ZoteroHelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def write_note(self, root: Path, relative_path: str, frontmatter: str = "", body: str = "body") -> Path:
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        if frontmatter:
            path.write_text(f"---\n{frontmatter.strip()}\n---\n\n{body}\n", encoding="utf-8")
        else:
            path.write_text(body, encoding="utf-8")
        return path

    def test_nested_collections_return_full_paths_and_item_lists_all_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "zotero.sqlite"
            storage = Path(tmp) / "storage"
            (storage / "PDFKEY").mkdir(parents=True)
            (storage / "PDFKEY" / "ebpc.pdf").write_text("pdf", encoding="utf-8")
            conn = create_fixture_db(db_path)
            try:
                self.assertEqual(
                    self.module.get_collection_path(conn, 3),
                    "Research Topics/Lossless Communication Compression/Link & Fabric Integration",
                )

                item = self.module.build_item_record(conn, 100, storage_dir=storage)
            finally:
                conn.close()

        self.assertEqual(item["item_id"], 100)
        self.assertEqual(item["title"], "EBPC: Efficient Bufferless Packet Compression")
        self.assertEqual(item["authors"], ["Ada Lovelace", "Grace Hopper"])
        self.assertEqual(item["year"], "2025")
        self.assertEqual(item["venue"], "SIGCOMM")
        self.assertEqual(item["doi"], "10.1145/example")
        self.assertEqual(item["arxiv_id"], "2501.01234")
        self.assertEqual(
            item["pdf_path"],
            str(Path(tmp) / "storage" / "PDFKEY" / "ebpc.pdf"),
        )
        self.assertEqual(
            item["collection_paths"],
            [
                "Research Topics/Lossless Communication Compression",
                "Research Topics/Lossless Communication Compression/Link & Fabric Integration",
            ],
        )

    def test_recursive_collection_uses_most_specific_source_collection_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "zotero.sqlite"
            conn = create_fixture_db(db_path)
            try:
                items = self.module.resolve_items_for_collection(
                    conn,
                    2,
                    recursive=True,
                    storage_dir=Path(tmp) / "storage",
                )
            finally:
                conn.close()

        by_id = {item["item_id"]: item for item in items}
        self.assertEqual(set(by_id), {100, 101, 102})
        self.assertEqual(
            by_id[100]["source_collection_path"],
            "Research Topics/Lossless Communication Compression/Link & Fabric Integration",
        )
        self.assertEqual(
            by_id[101]["source_collection_path"],
            "Research Topics/Lossless Communication Compression",
        )
        self.assertEqual(
            by_id[102]["source_collection_path"],
            "Research Topics/Lossless Communication Compression/Protocol Design",
        )

    def test_copy_db_uses_unique_temporary_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "zotero.sqlite"
            create_fixture_db(db_path).close()

            first = self.module.copy_db(db_path)
            second = self.module.copy_db(db_path)
            try:
                self.assertNotEqual(first.temp_copy_path, second.temp_copy_path)
                self.assertNotEqual(first.temp_copy_path, Path("/tmp/zotero_readonly.sqlite"))
                self.assertTrue(first.temp_copy_path.exists())
                self.assertTrue(second.temp_copy_path.exists())
            finally:
                self.module.close_copied_db(first)
                self.module.close_copied_db(second)

            self.assertFalse(first.temp_copy_path.exists())
            self.assertFalse(second.temp_copy_path.exists())

    def test_note_destination_preserves_collection_hierarchy_and_uses_inbox_without_collection(self):
        root = Path("/vault/PaperNotes")

        self.assertEqual(
            self.module.build_note_path(
                root,
                "Research Topics/Lossless Communication Compression/Link & Fabric Integration",
                "EBPC",
            ),
            root
            / "Research Topics"
            / "Lossless Communication Compression"
            / "Link & Fabric Integration"
            / "EBPC.md",
        )
        self.assertEqual(
            self.module.build_note_path(root, "", "EBPC"),
            root / "_inbox" / "EBPC.md",
        )

    def test_note_save_plan_moves_existing_note_and_updates_frontmatter(self):
        root = Path("/vault/PaperNotes")
        existing = root / "4-Distributed Systems" / "EBPC.md"

        plan = self.module.plan_note_save(
            root,
            "EBPC",
            "Research Topics/Lossless Communication Compression/Link & Fabric Integration",
            existing_paths=[existing],
        )

        self.assertEqual(plan["action"], "move")
        self.assertEqual(plan["existing_path"], str(existing))
        self.assertEqual(
            plan["target_path"],
            str(
                root
                / "Research Topics"
                / "Lossless Communication Compression"
                / "Link & Fabric Integration"
                / "EBPC.md"
            ),
        )
        self.assertEqual(
            plan["frontmatter_updates"],
            {
                "zotero_collection": "Research Topics/Lossless Communication Compression/Link & Fabric Integration"
            },
        )

    def test_note_save_plan_uses_sanitized_collection_in_frontmatter(self):
        root = Path("/vault/PaperNotes")

        plan = self.module.plan_note_save(
            root,
            "ASPLOS Paper",
            "Venues/ASPLOS: Architectural Support",
            existing_paths=[],
        )

        self.assertEqual(
            plan["target_path"],
            str(root / "Venues" / "ASPLOS_ Architectural Support" / "ASPLOS Paper.md"),
        )
        self.assertEqual(
            plan["frontmatter_updates"]["zotero_collection"],
            "Venues/ASPLOS_ Architectural Support",
        )

    def test_batch_note_save_plan_skips_existing_note_even_when_elsewhere(self):
        root = Path("/vault/PaperNotes")
        existing = root / "4-Distributed Systems" / "EBPC.md"

        plan = self.module.plan_note_save(
            root,
            "EBPC",
            "Research Topics/Lossless Communication Compression/Link & Fabric Integration",
            existing_paths=[existing],
            batch=True,
        )

        self.assertEqual(plan["action"], "skip")
        self.assertEqual(plan["existing_path"], str(existing))

    def test_note_index_includes_inbox_and_excludes_concepts_and_mocs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "PaperNotes"
            inbox_note = self.write_note(root, "_inbox/Old Title.md", "zotero_item_id: 100\ntitle: Old Title")
            self.write_note(root, "_concepts/System Concept.md", "zotero_item_id: 100\ntitle: Not A Paper")
            self.write_note(root, "Research Topics/_index_Research Topics.md", "zotero_item_id: 100\ntitle: MOC")

            matches = self.module.find_matching_notes(root, zotero_item_id=100)

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].path, inbox_note)
        self.assertEqual(matches[0].match_level, "zotero_item_id")

    def test_matching_prefers_zotero_id_then_doi_then_arxiv_with_normalization(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "PaperNotes"
            by_id = self.write_note(
                root,
                "A/By Zotero.md",
                "zotero_item_id: 100\ndoi: 10.1145/not-this\narxiv_id: 2501.00001",
            )
            by_doi = self.write_note(root, "B/By DOI.md", "doi: 10.1145/Example")
            by_arxiv = self.write_note(root, "C/By arXiv.md", "arxiv_id: 2501.01234v2")

            self.assertEqual(
                self.module.find_matching_notes(root, zotero_item_id=100, doi="10.1145/example")[0].path,
                by_id,
            )
            doi_match = self.module.find_matching_notes(root, doi="https://doi.org/10.1145/example")[0]
            arxiv_match = self.module.find_matching_notes(root, arxiv_id="2501.01234")[0]

        self.assertEqual(doi_match.path, by_doi)
        self.assertEqual(doi_match.match_level, "doi")
        self.assertEqual(arxiv_match.path, by_arxiv)
        self.assertEqual(arxiv_match.match_level, "arxiv_id")

    def test_plan_note_save_moves_high_confidence_match_when_path_drifted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "PaperNotes"
            existing = self.write_note(root, "Old/EBPC.md", "zotero_item_id: 100\ntitle: EBPC")
            matches = self.module.find_matching_notes(root, zotero_item_id=100)

            single_plan = self.module.plan_note_save(
                root,
                "EBPC",
                "Research Topics/Compression",
                zotero_item_id=100,
                matches=matches,
            )
            batch_plan = self.module.plan_note_save(
                root,
                "EBPC",
                "Research Topics/Compression",
                zotero_item_id=100,
                matches=matches,
                batch=True,
            )

        self.assertEqual(single_plan["action"], "move")
        self.assertEqual(single_plan["existing_path"], str(existing))
        self.assertEqual(batch_plan["action"], "skip")
        self.assertEqual(batch_plan["existing_path"], str(existing))

    def test_multiple_notes_with_same_zotero_id_returns_conflict_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "PaperNotes"
            first = self.write_note(root, "A/First.md", "zotero_item_id: 100")
            second = self.write_note(root, "B/Second.md", "zotero_item_id: 100")
            matches = self.module.find_matching_notes(root, zotero_item_id=100)

            plan = self.module.plan_note_save(
                root,
                "First",
                "Research Topics",
                zotero_item_id=100,
                matches=matches,
            )

        self.assertTrue(all(match.conflict for match in matches))
        self.assertEqual({match.path for match in matches}, {first, second})
        self.assertEqual(plan["action"], "conflict")
        self.assertEqual(set(plan["candidate_paths"]), {str(first), str(second)})

    def test_method_name_fallback_requires_weak_metadata_when_provided(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "PaperNotes"
            thermometer = self.write_note(
                root,
                "Architecture/Thermometer.md",
                "method_name: Thermometer\nyear: 2022\nvenue: ISCA",
            )

            self.assertEqual(
                self.module.find_matching_notes(root, method_name="Thermometer", year="2025", venue="ASPLOS"),
                [],
            )
            matches = self.module.find_matching_notes(root, method_name="Thermometer", year="2022", venue="ISCA")

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].path, thermometer)
        self.assertEqual(matches[0].match_level, "method_name")
        self.assertEqual(matches[0].confidence, "high")

    def test_legacy_note_without_frontmatter_falls_back_to_filename_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "PaperNotes"
            legacy = self.write_note(root, "Legacy/EBPC.md")

            matches = self.module.find_matching_notes(root, method_name="EBPC")

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].path, legacy)
        self.assertEqual(matches[0].confidence, "low")

    def test_template_includes_doi_and_arxiv_id_frontmatter_slots(self):
        template = (REPO_ROOT / "skills" / "paper-reader" / "assets" / "paper-note-template.md").read_text(encoding="utf-8")

        self.assertIn("doi:", template)
        self.assertIn("arxiv_id:", template)

    def test_legacy_commands_do_not_expose_json_flags(self):
        for command in ("papers", "search", "info", "find-collection"):
            result = subprocess.run(
                [sys.executable, str(MODULE_PATH), command, "--help"],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertNotIn("--json", result.stdout)

    def test_legacy_commands_emit_deprecation_warning_and_continue(self):
        cases = [
            (["papers", "2"], "list_papers_in_collection"),
            (["search", "EBPC"], "search_paper"),
            (["info", "100"], "get_paper_info"),
            (["find-collection", "Systems"], "find_collection_by_name"),
        ]

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "zotero.sqlite"
            db_path.write_text("sqlite", encoding="utf-8")

            for argv, handler_name in cases:
                stderr = io.StringIO()
                stdout = io.StringIO()
                fake_conn = object()
                with (
                    patch.object(sys, "argv", [str(MODULE_PATH), *argv]),
                    patch.object(self.module, "ZOTERO_DB", db_path),
                    patch.object(self.module, "copy_db", return_value=fake_conn),
                    patch.object(self.module, "close_copied_db"),
                    patch.object(self.module, handler_name) as handler,
                    redirect_stderr(stderr),
                    redirect_stdout(stdout),
                ):
                    self.module.main()

                self.assertIn("DEPRECATED", stderr.getvalue())
                self.assertIn("zotero_helper.py resolve", stderr.getvalue())
                handler.assert_called_once()

    def test_internal_docs_and_callers_use_resolve_not_legacy_zotero_commands(self):
        pattern = re.compile(r"zotero_helper\.py\s+(papers|search|info|find-collection)\b")
        offenders = []
        scan_roots = [REPO_ROOT / "skills", REPO_ROOT / "tests"]
        skip_paths = {MODULE_PATH, Path(__file__).resolve()}

        for root in scan_roots:
            for path in root.rglob("*"):
                if path in skip_paths or path.suffix not in {".md", ".py"}:
                    continue
                text = path.read_text(encoding="utf-8")
                for match in pattern.finditer(text):
                    offenders.append(f"{path.relative_to(REPO_ROOT)}:{match.group(1)}")

        self.assertEqual(offenders, [])

    def test_paper_mocs_exclude_inbox(self):
        text = GENERATE_PAPER_MOCS.read_text(encoding="utf-8")

        self.assertIn('"_inbox"', text)


if __name__ == "__main__":
    unittest.main()
