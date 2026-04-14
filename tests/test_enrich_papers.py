import importlib.util
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "skills" / "daily-papers" / "enrich_papers.py"


def load_module():
    spec = importlib.util.spec_from_file_location("enrich_papers", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class EnrichPapersTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    async def test_dblp_paper_uses_arxiv_title_search_fallback(self):
        paper = {
            "title": "Oaken: Fast and Efficient LLM Serving with Online-Offline Hybrid KV Cache Quantization.",
            "authors": "A. Author",
            "abstract": "",
            "url": "https://doi.org/10.1145/example",
            "source": "dblp",
            "venue": "ISCA 2025",
        }

        arxiv_match = {
            "arxiv_id": "2501.12345",
            "title": paper["title"],
            "abstract": "This paper studies efficient LLM serving with hybrid KV cache quantization.",
            "authors": ["A. Author", "B. Author"],
            "affiliations": ["Example University"],
            "url": "https://arxiv.org/abs/2501.12345",
            "pdf": "https://arxiv.org/pdf/2501.12345",
            "date": "2025-01-20",
            "category": "cs.AR",
        }

        with patch.object(self.module, "search_arxiv_by_title", AsyncMock(return_value=arxiv_match)), \
             patch.object(self.module, "curl_fetch", AsyncMock(return_value="")), \
             patch.object(self.module, "search_semantic_scholar_by_title", AsyncMock(return_value={})), \
             patch.object(self.module, "fetch_doi_landing_metadata", AsyncMock(return_value={})):
            enriched = await self.module.enrich_one(paper, self.module.asyncio.Semaphore(1))

        self.assertEqual(enriched["arxiv_id"], "2501.12345")
        self.assertEqual(enriched["url"], "https://arxiv.org/abs/2501.12345")
        self.assertEqual(enriched["pdf"], "https://arxiv.org/pdf/2501.12345")
        self.assertEqual(enriched["authors"], "A. Author, B. Author")
        self.assertEqual(enriched["affiliations"], "Example University")

    async def test_semantic_scholar_fallback_populates_abstract_and_method_summary(self):
        paper = {
            "title": "Resource-Aware Distributed Training Job Placement for GPU Cluster Defragmentation.",
            "authors": "A. Author",
            "abstract": "",
            "url": "https://doi.org/10.1145/example2",
            "source": "dblp-journal",
            "venue": "IEEE/ACM ToN",
        }

        semantic_match = {
            "abstract": (
                "We present a distributed training placement system that reduces GPU cluster fragmentation "
                "with resource-aware scheduling and placement policies."
            ),
            "authors": ["A. Author", "C. Author"],
            "url": "https://www.semanticscholar.org/paper/example",
            "external_ids": {"DOI": "10.1145/example2"},
            "venue": "IEEE/ACM ToN",
        }

        with patch.object(self.module, "search_arxiv_by_title", AsyncMock(return_value={})), \
             patch.object(self.module, "curl_fetch", AsyncMock(return_value="")), \
             patch.object(self.module, "search_semantic_scholar_by_title", AsyncMock(return_value=semantic_match)), \
             patch.object(self.module, "fetch_doi_landing_metadata", AsyncMock(return_value={})):
            enriched = await self.module.enrich_one(paper, self.module.asyncio.Semaphore(1))

        self.assertEqual(
            enriched["abstract"],
            semantic_match["abstract"],
        )
        self.assertEqual(enriched["authors"], "A. Author, C. Author")
        self.assertTrue(enriched["method_summary"])
        self.assertIn("resource-aware scheduling", enriched["method_summary"].lower())

    async def test_doi_metadata_fallback_populates_abstract_before_semantic_scholar(self):
        paper = {
            "title": "Compression-Aware Gradient Splitting for Collective Communications in Distributed Training.",
            "authors": "",
            "abstract": "",
            "url": "https://doi.org/10.1109/hpca.2026.123456",
            "source": "dblp",
            "venue": "HPCA 2026",
        }

        doi_metadata = {
            "title": paper["title"],
            "abstract": (
                "We propose a compression-aware gradient splitting mechanism for distributed training "
                "that reduces communication overhead in collective operations."
            ),
            "authors": ["A. Author", "B. Author"],
            "affiliations": ["Example Lab"],
            "url": paper["url"],
        }

        with patch.object(self.module, "search_arxiv_by_title", AsyncMock(return_value={})), \
             patch.object(self.module, "curl_fetch", AsyncMock(return_value="")), \
             patch.object(self.module, "fetch_doi_metadata", AsyncMock(return_value=doi_metadata)), \
             patch.object(self.module, "search_semantic_scholar_by_title", AsyncMock(return_value={})), \
             patch.object(self.module, "fetch_doi_landing_metadata", AsyncMock(return_value={})):
            enriched = await self.module.enrich_one(paper, self.module.asyncio.Semaphore(1))

        self.assertEqual(enriched["abstract"], doi_metadata["abstract"])
        self.assertEqual(enriched["authors"], "A. Author, B. Author")
        self.assertEqual(enriched["affiliations"], "Example Lab")
        self.assertTrue(enriched["method_summary"])

    async def test_semantic_scholar_doi_fallback_preferred_for_abstract(self):
        paper = {
            "title": "WindServe: Efficient Phase-Disaggregated LLM Serving with Stream-based Dynamic Scheduling.",
            "authors": "",
            "abstract": "",
            "url": "https://doi.org/10.1145/example3",
            "source": "dblp",
            "venue": "ISCA 2025",
        }

        semantic_match = {
            "abstract": (
                "WindServe is a phase-disaggregated LLM serving system that uses stream-based dynamic "
                "scheduling to improve throughput and latency under bursty workloads."
            ),
            "authors": ["A. Author", "D. Author"],
            "url": "https://www.semanticscholar.org/paper/example3",
            "external_ids": {"DOI": "10.1145/example3"},
            "venue": "ISCA 2025",
            "tldr": "A phase-disaggregated serving system with dynamic scheduling for LLM workloads.",
        }

        doi_metadata = {
            "title": paper["title"],
            "abstract": "A shorter DOI abstract.",
            "authors": ["A. Author"],
            "affiliations": ["Publisher Metadata Lab"],
            "url": paper["url"],
            "doi": "10.1145/example3",
        }

        with patch.object(self.module, "search_arxiv_by_title", AsyncMock(return_value={})), \
             patch.object(self.module, "curl_fetch", AsyncMock(return_value="")), \
             patch.object(self.module, "fetch_doi_metadata", AsyncMock(return_value=doi_metadata)), \
             patch.object(self.module, "search_semantic_scholar_by_doi", AsyncMock(return_value=semantic_match)), \
             patch.object(self.module, "search_semantic_scholar_by_title", AsyncMock(return_value={})), \
             patch.object(self.module, "fetch_doi_landing_metadata", AsyncMock(return_value={})):
            enriched = await self.module.enrich_one(paper, self.module.asyncio.Semaphore(1))

        self.assertEqual(enriched["abstract"], semantic_match["abstract"])
        self.assertEqual(enriched["authors"], "A. Author, D. Author")
        self.assertIn("phase-disaggregated", enriched["method_summary"].lower())

    async def test_openalex_doi_fallback_reconstructs_abstract(self):
        paper = {
            "title": "AutoCCL: Automated Collective Communication Tuning for Accelerating Distributed and Parallel DNN Training.",
            "authors": "",
            "abstract": "",
            "url": "https://doi.org/10.1145/example4",
            "source": "dblp",
            "venue": "NSDI 2025",
        }

        openalex_match = {
            "abstract": "AutoCCL automates collective communication tuning for distributed training systems.",
            "authors": ["A. Author", "E. Author"],
            "affiliations": ["OpenAlex Systems Lab"],
            "url": "https://openalex.org/W1234567890",
            "doi": "10.1145/example4",
        }

        with patch.object(self.module, "search_arxiv_by_title", AsyncMock(return_value={})), \
             patch.object(self.module, "curl_fetch", AsyncMock(return_value="")), \
             patch.object(self.module, "fetch_doi_metadata", AsyncMock(return_value={})), \
             patch.object(self.module, "search_semantic_scholar_by_doi", AsyncMock(return_value={})), \
             patch.object(self.module, "search_semantic_scholar_by_title", AsyncMock(return_value={})), \
             patch.object(self.module, "search_openalex_by_doi", AsyncMock(return_value=openalex_match)), \
             patch.object(self.module, "search_openalex_by_title", AsyncMock(return_value={})), \
             patch.object(self.module, "fetch_doi_landing_metadata", AsyncMock(return_value={})):
            enriched = await self.module.enrich_one(paper, self.module.asyncio.Semaphore(1))

        self.assertEqual(enriched["abstract"], openalex_match["abstract"])
        self.assertEqual(enriched["authors"], "A. Author, E. Author")
        self.assertEqual(enriched["affiliations"], "OpenAlex Systems Lab")
        self.assertTrue(enriched["method_summary"])

    def test_extract_primary_method_name_prefers_title_prefix_before_colon(self):
        method_name = self.module.extract_primary_method_name(
            "<html></html>",
            "WindServe: Efficient Phase-Disaggregated LLM Serving with Stream-based Dynamic Scheduling.",
        )
        self.assertEqual(method_name, "WindServe")

    def test_extract_primary_method_name_falls_back_to_title_when_not_confident(self):
        title = "Compression-Aware Gradient Splitting for Collective Communications in Distributed Training."
        method_name = self.module.extract_primary_method_name("<html></html>", title)
        self.assertEqual(method_name, title.rstrip("."))

    async def test_html_enrichment_populates_llm_system_eval_flags_and_method_name(self):
        paper = {
            "title": "InstAttention: In-Storage Attention Offloading for Cost-Effective Long-Context LLM Inference.",
            "authors": "",
            "abstract": "",
            "url": "https://doi.org/10.1145/example5",
            "source": "dblp",
            "venue": "ASPLOS 2026",
        }

        html = """
        <html>
          <body>
            <h2>Evaluation</h2>
            <p>We evaluate InstAttention on NVIDIA H100 GPU servers and a 16-node GPU cluster.</p>
            <p>Our end-to-end serving evaluation reports request latency and tokens per second.</p>
            <p>We replay a production trace collected from an online LLM serving system.</p>
          </body>
        </html>
        """

        arxiv_match = {
            "arxiv_id": "2604.12345",
            "title": paper["title"],
            "abstract": "",
            "authors": [],
            "affiliations": [],
            "url": "https://arxiv.org/abs/2604.12345",
            "pdf": "https://arxiv.org/pdf/2604.12345",
        }

        async def fake_curl_fetch(url, sem, timeout=30, retries=3):
            if "arxiv.org/html/2604.12345" in url:
                return html
            return ""

        with patch.object(self.module, "search_arxiv_by_title", AsyncMock(return_value=arxiv_match)), \
             patch.object(self.module, "curl_fetch", AsyncMock(side_effect=fake_curl_fetch)), \
             patch.object(self.module, "fetch_doi_metadata", AsyncMock(return_value={})), \
             patch.object(self.module, "search_semantic_scholar_by_doi", AsyncMock(return_value={})), \
             patch.object(self.module, "search_semantic_scholar_by_title", AsyncMock(return_value={})), \
             patch.object(self.module, "search_openalex_by_doi", AsyncMock(return_value={})), \
             patch.object(self.module, "search_openalex_by_title", AsyncMock(return_value={})), \
             patch.object(self.module, "fetch_doi_landing_metadata", AsyncMock(return_value={})):
            enriched = await self.module.enrich_one(paper, self.module.asyncio.Semaphore(1))

        self.assertEqual(enriched["method_name"], "InstAttention")
        self.assertTrue(enriched["has_hardware_eval"])
        self.assertTrue(enriched["has_end_to_end_eval"])
        self.assertTrue(enriched["has_real_workload"])


if __name__ == "__main__":
    unittest.main()
