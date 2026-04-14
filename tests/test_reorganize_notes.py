import importlib.util
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "skills" / "paper-reader" / "assets" / "reorganize_notes.py"


def load_module():
    spec = importlib.util.spec_from_file_location("reorganize_notes", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ReorganizeNotesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def test_architecture_tags_map_to_architecture_bucket(self):
        category = self.module.determine_category(
            ["accelerator", "gpu", "llm-training"],
            "An Accelerator Architecture for Transformer Inference",
        )

        self.assertEqual(category, "1-Computer Architecture and Accelerators")

    def test_networking_tags_map_to_network_bucket(self):
        category = self.module.determine_category(
            ["rdma", "collective-communication", "datacenter-network"],
            "RDMA-Aware Scheduling for Distributed Training",
        )

        self.assertEqual(category, "3-Networking and Interconnects")

    def test_benchmark_tags_map_to_performance_bucket(self):
        category = self.module.determine_category(
            ["benchmark", "profiling", "throughput"],
            "A Benchmark Suite for LLM Inference Systems",
        )

        self.assertEqual(category, "6-Performance, Evaluation and Benchmarking")


if __name__ == "__main__":
    unittest.main()
