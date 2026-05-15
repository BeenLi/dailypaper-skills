import csv
import importlib.util
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "skills" / "_shared" / "scan_missing_concepts.py"


def load_module():
    spec = importlib.util.spec_from_file_location("scan_missing_concepts", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ScanMissingConceptsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def make_tree(self):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name) / "PaperNotes"
        notes = root / "Systems"
        concepts = root / "_concepts"
        reference = Path(tmp.name) / "concept-categories.md"
        notes.mkdir(parents=True)
        concepts.mkdir(parents=True)
        return tmp, root, notes, concepts, reference

    def test_reports_wikilinks_without_existing_concept_or_alias(self):
        tmp, root, notes, concepts, reference = self.make_tree()
        self.addCleanup(tmp.cleanup)

        (notes / "Paper A.md").write_text(
            "Uses [[RDMA]] with [[Kernel Fusion|fused kernels]] and [[Existing Alias]].",
            encoding="utf-8",
        )
        (notes / "Paper B.md").write_text("Also mentions [[RDMA#Transport]].", encoding="utf-8")
        alias_dir = concepts / "mechanism"
        alias_dir.mkdir()
        (alias_dir / "Existing Concept.md").write_text(
            "---\naliases: [Existing Alias]\nconcept_type: mechanism\n---\n",
            encoding="utf-8",
        )
        reference.write_text("", encoding="utf-8")

        rows = self.module.scan_missing_concepts(root, concepts, reference, include_seed=False)

        self.assertEqual([row["concept_name"] for row in rows], ["RDMA", "Kernel Fusion"])
        self.assertEqual(rows[0]["refs_count"], 2)
        self.assertEqual(rows[0]["example_papers"], "Paper A; Paper B")
        self.assertEqual(rows[1]["refs_count"], 1)

    def test_excludes_concepts_inbox_and_index_notes(self):
        tmp, root, notes, concepts, reference = self.make_tree()
        self.addCleanup(tmp.cleanup)

        (notes / "Real Paper.md").write_text("[[AllReduce]]", encoding="utf-8")
        inbox = root / "_inbox"
        inbox.mkdir()
        (inbox / "Draft.md").write_text("[[Draft Only]]", encoding="utf-8")
        (root / "_index_systems.md").write_text("[[Index Only]]", encoding="utf-8")
        concept_dir = concepts / "hardware"
        concept_dir.mkdir()
        (concept_dir / "Concept Note.md").write_text("[[Concept Body Only]]", encoding="utf-8")
        reference.write_text("", encoding="utf-8")

        rows = self.module.scan_missing_concepts(root, concepts, reference, include_seed=False)

        self.assertEqual([row["concept_name"] for row in rows], ["AllReduce"])

    def test_excludes_wikilinks_that_target_existing_paper_notes(self):
        tmp, root, notes, concepts, reference = self.make_tree()
        self.addCleanup(tmp.cleanup)

        (notes / "Paper A.md").write_text(
            "Compares against [[Paper B]] and uses [[RDMA]].",
            encoding="utf-8",
        )
        (notes / "Paper B.md").write_text("Mentions [[RDMA]].", encoding="utf-8")
        reference.write_text("", encoding="utf-8")

        rows = self.module.scan_missing_concepts(root, concepts, reference, include_seed=False)

        self.assertEqual([row["concept_name"] for row in rows], ["RDMA"])
        self.assertEqual(rows[0]["example_papers"], "Paper A; Paper B")

    def test_includes_seed_vocabulary_when_requested(self):
        tmp, root, notes, concepts, reference = self.make_tree()
        self.addCleanup(tmp.cleanup)

        (notes / "Paper A.md").write_text("[[RDMA]] appears, [[HBM]] is already known.", encoding="utf-8")
        hardware = concepts / "hardware"
        hardware.mkdir()
        (hardware / "HBM.md").write_text("---\nconcept_type: hardware\n---\n", encoding="utf-8")
        reference.write_text(
            """## Systems Concept Seed Vocabulary

| concept_type | seed terms |
|---|---|
| hardware | RDMA, HBM, NVLink |
| software-abstraction | CUDA, NCCL |
""",
            encoding="utf-8",
        )

        rows = self.module.scan_missing_concepts(root, concepts, reference, include_seed=True)

        self.assertEqual(
            [(row["concept_name"], row["refs_count"], row["candidate_type"]) for row in rows],
            [
                ("RDMA", 1, "hardware"),
                ("NVLink", 0, "hardware"),
                ("CUDA", 0, "software-abstraction"),
                ("NCCL", 0, "software-abstraction"),
            ],
        )

    def test_writes_csv_output(self):
        rows = [
            {
                "concept_name": "RDMA",
                "refs_count": 2,
                "example_papers": "Paper A; Paper B",
                "candidate_type": "hardware",
            }
        ]

        text = self.module.render_csv(rows)
        parsed = list(csv.DictReader(text.splitlines()))

        self.assertEqual(parsed[0]["concept_name"], "RDMA")
        self.assertEqual(parsed[0]["refs_count"], "2")


if __name__ == "__main__":
    unittest.main()
