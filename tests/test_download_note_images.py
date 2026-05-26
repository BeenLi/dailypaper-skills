import asyncio
import hashlib
import importlib.util
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "skills" / "daily-papers" / "download_note_images.py"


def load_module():
    spec = importlib.util.spec_from_file_location("download_note_images", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class DownloadNoteImagesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def test_localized_images_use_00_assets_and_note_name_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            note = Path(tmp) / "EBPC.md"
            note.write_text(
                "---\nimage_source: online\n---\n\n![Figure 1](https://example.com/images/figure1.png)\n",
                encoding="utf-8",
            )

            async def fake_check_url(url, sem):
                return False

            async def fake_download_image(url, dest, sem):
                dest.write_bytes(b"x" * 2048)
                return True

            with patch.object(self.module, "check_url", side_effect=fake_check_url), patch.object(
                self.module, "download_image", side_effect=fake_download_image
            ), redirect_stdout(io.StringIO()):
                result = asyncio.run(self.module.process_note(note))

            expected = note.parent / "00_assets" / "EBPC_figure1.png"
            text = note.read_text(encoding="utf-8")

            self.assertEqual(result["localized"], 1)
            self.assertTrue(expected.exists())
            self.assertIn("![[00_assets/EBPC_figure1.png]]", text)
            self.assertIn("image_source: mixed", text)

    def test_long_note_names_use_40_char_prefix_and_hash(self):
        note_name = "VeryLongNoteNamePrefix_" + "A" * 40
        expected_hash = hashlib.sha1(note_name.encode("utf-8")).hexdigest()[:8]

        local_name = self.module.local_asset_name(Path(f"{note_name}.md"), "figure.png")

        self.assertEqual(local_name, f"{note_name[:40]}_{expected_hash}_figure.png")
        self.assertLessEqual(len(local_name), 40 + 1 + 8 + 1 + len("figure.png"))


if __name__ == "__main__":
    unittest.main()
