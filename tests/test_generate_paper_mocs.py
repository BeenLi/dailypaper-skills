import io
import importlib.util
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "skills" / "_shared" / "generate_paper_mocs.py"


def load_module():
    spec = importlib.util.spec_from_file_location("generate_paper_mocs_under_test", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class GeneratePaperMocsTest(unittest.TestCase):
    def setUp(self):
        self.module = load_module()

    def test_paper_mocs_exclude_00_assets_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "Vault"
            root = vault / "PaperNotes"
            topic = root / "Topic"
            assets = topic / "00_assets"
            assets.mkdir(parents=True)
            (topic / "Paper.md").write_text("paper", encoding="utf-8")

            with patch.object(self.module, "obsidian_vault_path", return_value=vault), patch.object(
                self.module, "paper_notes_dir", return_value=root
            ), patch.object(
                self.module, "paths_config", return_value={"concepts_folder": "_concepts"}
            ), patch.object(
                self.module, "moc_filename_prefix", return_value="_index_"
            ):
                with redirect_stdout(io.StringIO()):
                    exit_code = self.module.main()

            topic_moc = topic / "_index_Topic.md"
            assets_moc = assets / "_index_00_assets.md"

            self.assertEqual(exit_code, 0)
            self.assertTrue(topic_moc.exists())
            self.assertFalse(assets_moc.exists())
            self.assertNotIn("00_assets", topic_moc.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
