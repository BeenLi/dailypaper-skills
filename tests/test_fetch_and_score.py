import importlib.util
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError


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

    def test_paper_lookup_keys_returns_arxiv_doi_and_title(self):
        paper = {
            "url": "https://arxiv.org/abs/2501.01234",
            "title": "FlashInfer: Communication-Aware LLM Serving.",
            "doi": "10.1145/Example",
        }

        keys = self.module.paper_lookup_keys(paper)

        self.assertIn("arxiv:2501.01234", keys)
        self.assertIn("doi:10.1145/example", keys)
        self.assertIn("title:flashinfercommunicationawarellmserving", keys)

    def test_dblp_paper_with_doi_url_emits_doi_key(self):
        paper = {
            "url": "https://doi.org/10.1109/HPCA68181.2026.11408444",
            "title": "Oaken: Fast and Efficient LLM Serving.",
        }

        keys = self.module.paper_lookup_keys(paper)

        self.assertIn("doi:10.1109/hpca68181.2026.11408444", keys)
        self.assertIn("title:oakenfastandefficientllmserving", keys)
        self.assertFalse(any(k.startswith("arxiv:") for k in keys))

    def test_history_dedup_skips_dblp_paper_whose_title_is_in_history(self):
        history = [
            {"id": "Oaken: Fast and Efficient LLM Serving.", "title": "Oaken: Fast and Efficient LLM Serving.", "date": "2026-04-14"},
            {"id": "10.1109/HPCA68181.2026.11408444", "title": "Some HPCA Paper.", "date": "2026-04-14"},
        ]
        history_keys, _ = self.module.build_history_index(history)

        new_dblp_paper = {
            "source": "dblp",
            "url": "https://dblp.org/...",
            "title": "Oaken: Fast and Efficient LLM Serving.",
            "score": 10,
        }

        self.assertTrue(self.module.paper_lookup_keys(new_dblp_paper) & history_keys)

    def test_history_dedup_skips_paper_recorded_by_doi(self):
        history = [
            {"id": "10.1109/HPCA68181.2026.11408444", "title": "Some HPCA Paper.", "date": "2026-04-14"},
        ]
        history_keys, _ = self.module.build_history_index(history)

        new_paper = {
            "source": "dblp",
            "url": "https://doi.org/10.1109/HPCA68181.2026.11408444",
            "title": "Some HPCA Paper.",
            "score": 8,
        }

        self.assertTrue(self.module.paper_lookup_keys(new_paper) & history_keys)

    def test_apply_age_decay_reduces_score_for_year_old_papers(self):
        target = date(2026, 5, 14)
        papers = [
            {"date": "2026-05-13", "score": 10},  # 1 day, no decay
            {"date": "2025-12-01", "score": 10},  # ~165 days, 0.75 → 7
            {"date": "2025-01-01", "score": 10},  # ~500 days, 0.35 → 3
        ]

        self.module.apply_age_decay(papers, target)

        self.assertEqual(papers[0]["score"], 10)
        self.assertEqual(papers[1]["score"], 7)
        self.assertEqual(papers[2]["score"], 3)

    def test_select_with_quota_caps_dblp_share(self):
        candidates = (
            [{"source": "dblp", "score": 20 - i, "title": f"d{i}"} for i in range(15)]
            + [{"source": "arxiv", "score": 5 - (i % 3), "title": f"a{i}"} for i in range(10)]
        )

        top = self.module.select_with_quota(candidates, top_n=10, dblp_max_ratio=0.4)

        dblp_count = sum(1 for p in top if p["source"] == "dblp")
        self.assertLessEqual(dblp_count, 4)
        self.assertEqual(len(top), 10)

    def test_fetch_url_retries_transient_rate_limit(self):
        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b"<feed />"

        attempts = []

        def fake_urlopen(req, timeout):
            attempts.append(req.full_url)
            if len(attempts) == 1:
                raise HTTPError(
                    req.full_url,
                    429,
                    "Too Many Requests",
                    {"Retry-After": "0"},
                    None,
                )
            return FakeResponse()

        with patch.object(self.module, "urlopen", side_effect=fake_urlopen), patch("time.sleep") as sleep:
            body = self.module.fetch_url("https://export.arxiv.org/api/query", timeout=1)

        self.assertEqual(body, "<feed />")
        self.assertEqual(len(attempts), 2)
        sleep.assert_called_once_with(0)


if __name__ == "__main__":
    unittest.main()
