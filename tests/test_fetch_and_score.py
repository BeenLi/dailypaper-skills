import importlib.util
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "skills" / "daily-papers" / "fetch_and_score.py"


def load_module():
    spec = importlib.util.spec_from_file_location("fetch_and_score", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FetchAndScoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def test_score_paper_rewards_systems_relevance(self):
        paper = {
            "title": "A GPU Cluster Runtime for RDMA-Optimized LLM Serving",
            "abstract": (
                "We present a distributed systems runtime for LLM serving with "
                "RDMA-aware scheduling, collective communication optimization, "
                "and KV cache offloading across GPU clusters."
            ),
        }

        score = self.module.score_paper(paper)

        self.assertGreaterEqual(score, 4)

    def test_score_paper_rejects_pure_agent_paper(self):
        paper = {
            "title": "A Browser Agent for Automatic Web Shopping",
            "abstract": (
                "We build an LLM agent for browsing websites, completing forms, "
                "and executing shopping workflows with better success rate."
            ),
        }

        score = self.module.score_paper(paper)

        self.assertLess(score, 0)

    def test_parse_dblp_proceedings_html_extracts_entries(self):
        html = """
        <html>
          <body>
            <ul class="publ-list">
              <li class="entry inproceedings">
                <span class="title">FlashInfer: Communication-Aware LLM Serving.</span>
                <span itemprop="author">Alice Smith</span>
                <span itemprop="author">Bob Lee</span>
                <nav class="publ">
                  <ul>
                    <li class="ee"><a href="https://doi.org/10.1145/example">DOI</a></li>
                  </ul>
                </nav>
              </li>
            </ul>
          </body>
        </html>
        """

        entries = self.module.parse_dblp_proceedings_html(html, venue="eurosys", year=2026)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["title"], "FlashInfer: Communication-Aware LLM Serving.")
        self.assertEqual(entries[0]["authors"], "Alice Smith, Bob Lee")
        self.assertEqual(entries[0]["source"], "dblp")
        self.assertEqual(entries[0]["venue"], "EuroSys 2026")

    def test_parse_dblp_proceedings_html_handles_realistic_cite_block(self):
        html = """
        <html><body>
        <ul class="publ-list">
          <li class="entry inproceedings">
            <cite>
              <span class="title" itemprop="name">Hardware-Accelerated Memory Disaggregation for LLM Serving</span>.
              <span itemprop="author"><a>Alice Smith</a></span>
              <span itemprop="author"><a>Bob Lee</a></span>
            </cite>
            <nav class="publ"><ul><li class="drop-down"><div><a href="https://doi.org/10.1145/test">doi</a></div></li></ul></nav>
          </li>
        </ul>
        </body></html>
        """

        entries = self.module.parse_dblp_proceedings_html(html, venue="ISCA", year=2025)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["title"], "Hardware-Accelerated Memory Disaggregation for LLM Serving.")

    def test_extract_program_titles_skips_session_headers(self):
        html = """
        <html><body>
          <h2>Session 1A: LLM Serving: Throughput Optimization</h2>
          <h3>FlashServe: Fast and Elastic LLM Serving in GPU Clusters</h3>
        </body></html>
        """

        titles = self.module.extract_program_titles(html)

        self.assertEqual(titles, ["FlashServe: Fast and Elastic LLM Serving in GPU Clusters"])


if __name__ == "__main__":
    unittest.main()
