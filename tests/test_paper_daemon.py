import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "skills" / "paper-reader" / "paper_daemon.py"


def load_module():
    spec = importlib.util.spec_from_file_location("paper_daemon", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class PaperDaemonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def test_process_collection_cleans_temporary_zotero_db_on_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            temp_db = Path(tmp) / "zotero_readonly_test.sqlite"
            temp_db.write_text("temporary db", encoding="utf-8")

            with (
                patch.object(self.module, "copy_zotero_db", return_value=str(temp_db)),
                patch.object(self.module, "get_collection_id_and_path", return_value=(1, "Research Topics")),
                patch.object(self.module, "get_papers_in_collection", side_effect=RuntimeError("boom")),
            ):
                with self.assertRaises(RuntimeError):
                    self.module.process_collection("Research Topics")

            self.assertFalse(temp_db.exists())

    def test_process_collection_passes_planned_target_path_to_codex(self):
        with tempfile.TemporaryDirectory() as tmp:
            temp_db = Path(tmp) / "zotero_readonly_test.sqlite"
            temp_db.write_text("temporary db", encoding="utf-8")
            pdf_path = Path(tmp) / "paper.pdf"
            pdf_path.write_text("pdf", encoding="utf-8")
            paper_notes_root = Path(tmp) / "PaperNotes"
            captured = {}

            def fake_call_codex(*args):
                captured["args"] = args
                return True, ""

            with (
                patch.object(self.module, "PAPER_NOTES_ROOT", str(paper_notes_root)),
                patch.object(self.module, "copy_zotero_db", return_value=str(temp_db)),
                patch.object(self.module, "get_collection_id_and_path", return_value=(1, "Research Topics")),
                patch.object(
                    self.module,
                    "get_papers_in_collection",
                    return_value=[
                        {
                            "item_id": 100,
                            "title": "ASPLOS Paper",
                            "source_collection_path": "Venues/ASPLOS: Architectural Support",
                        }
                    ],
                ),
                patch.object(self.module, "load_progress", return_value={"completed": [], "failed": [], "current": None, "started_at": None}),
                patch.object(self.module, "save_progress"),
                patch.object(self.module, "get_paper_online_source", return_value={}),
                patch.object(self.module, "get_pdf_path", return_value=str(pdf_path)),
                patch.object(self.module, "call_codex", side_effect=fake_call_codex),
            ):
                self.module.process_collection("Research Topics")

            self.assertEqual(len(captured["args"]), 4)
            save_plan = captured["args"][3]
            self.assertEqual(
                save_plan["target_path"],
                str(paper_notes_root / "Venues" / "ASPLOS_ Architectural Support" / "ASPLOS Paper.md"),
            )
            self.assertEqual(
                save_plan["frontmatter_updates"]["zotero_collection"],
                "Venues/ASPLOS_ Architectural Support",
            )

    def test_process_collection_skips_existing_note_by_zotero_item_id_even_when_filename_differs(self):
        with tempfile.TemporaryDirectory() as tmp:
            temp_db = Path(tmp) / "zotero_readonly_test.sqlite"
            temp_db.write_text("temporary db", encoding="utf-8")
            paper_notes_root = Path(tmp) / "PaperNotes"
            existing = paper_notes_root / "_inbox" / "Old Saved Title.md"
            existing.parent.mkdir(parents=True)
            existing.write_text("---\nzotero_item_id: 100\ntitle: Old Saved Title\n---\n", encoding="utf-8")
            progress = {"completed": [], "failed": [], "current": None, "started_at": None}

            with (
                patch.object(self.module, "PAPER_NOTES_ROOT", str(paper_notes_root)),
                patch.object(self.module, "copy_zotero_db", return_value=str(temp_db)),
                patch.object(self.module, "get_collection_id_and_path", return_value=(1, "Research Topics")),
                patch.object(
                    self.module,
                    "get_papers_in_collection",
                    return_value=[
                        {
                            "item_id": 100,
                            "title": "Completely Different Zotero Title",
                            "source_collection_path": "Research Topics/LLM Infrastructure",
                        }
                    ],
                ),
                patch.object(self.module, "load_progress", return_value=progress),
                patch.object(self.module, "save_progress"),
                patch.object(self.module, "get_paper_online_source", return_value={}),
                patch.object(self.module, "get_pdf_path", return_value=None),
                patch.object(self.module, "call_codex") as call_codex,
            ):
                self.module.process_collection("Research Topics")

        call_codex.assert_not_called()
        self.assertIn(100, progress["completed"])

    def test_process_collection_infers_method_name_for_save_path_from_title_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            temp_db = Path(tmp) / "zotero_readonly_test.sqlite"
            temp_db.write_text("temporary db", encoding="utf-8")
            pdf_path = Path(tmp) / "paper.pdf"
            pdf_path.write_text("pdf", encoding="utf-8")
            paper_notes_root = Path(tmp) / "PaperNotes"
            captured = {}

            def fake_call_codex(*args):
                captured["args"] = args
                return True, ""

            with (
                patch.object(self.module, "PAPER_NOTES_ROOT", str(paper_notes_root)),
                patch.object(self.module, "copy_zotero_db", return_value=str(temp_db)),
                patch.object(self.module, "get_collection_id_and_path", return_value=(1, "Research Topics")),
                patch.object(
                    self.module,
                    "get_papers_in_collection",
                    return_value=[
                        {
                            "item_id": 100,
                            "title": "EBPC: Efficient Bufferless Packet Compression",
                            "source_collection_path": "Research Topics/Compression",
                        }
                    ],
                ),
                patch.object(self.module, "load_progress", return_value={"completed": [], "failed": [], "current": None, "started_at": None}),
                patch.object(self.module, "save_progress"),
                patch.object(self.module, "get_paper_online_source", return_value={"arxiv_id": "2501.01234", "doi": "10.1145/example"}),
                patch.object(self.module, "get_pdf_path", return_value=str(pdf_path)),
                patch.object(self.module, "call_codex", side_effect=fake_call_codex),
            ):
                self.module.process_collection("Research Topics")

            save_plan = captured["args"][3]

        self.assertEqual(
            save_plan["target_path"],
            str(paper_notes_root / "Research Topics" / "Compression" / "EBPC.md"),
        )
        self.assertEqual(save_plan["frontmatter_updates"]["doi"], "10.1145/example")
        self.assertEqual(save_plan["frontmatter_updates"]["arxiv_id"], "2501.01234")


if __name__ == "__main__":
    unittest.main()
