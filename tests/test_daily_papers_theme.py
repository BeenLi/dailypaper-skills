import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / "skills" / "_shared" / "user-config.json"
ORCHESTRATOR_SKILL = REPO_ROOT / "skills" / "daily-papers" / "SKILL.md"
FETCH_SKILL = REPO_ROOT / "skills" / "daily-papers-fetch" / "SKILL.md"
REVIEW_SKILL = REPO_ROOT / "skills" / "daily-papers-review" / "SKILL.md"


class DailyPapersThemeTests(unittest.TestCase):
    def test_config_uses_llm_arch_network_storage_theme(self):
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        daily = config["daily_papers"]

        keywords = set(daily["keywords"])
        boosts = set(daily["domain_boost_keywords"])
        negatives = set(daily["negative_keywords"])

        required_keywords = {
            "llm serving",
            "llm inference",
            "kv cache",
            "rdma",
            "interconnect",
            "memory hierarchy",
            "storage system",
            "accelerator architecture",
        }
        for keyword in required_keywords:
            self.assertIn(keyword, keywords)

        required_boosts = {
            "llm",
            "serving",
            "inference",
            "memory",
            "storage",
            "rdma",
            "interconnect",
            "accelerator",
        }
        for keyword in required_boosts:
            self.assertIn(keyword, boosts)

        forbidden_theme_terms = {
            "humanoid",
            "whole-body control",
            "loco-manipulation",
            "human-scene interaction",
            "human-object interaction",
            "human motion generation",
            "egocentric perception",
            "vision-language action",
            "vision-language navigation",
            "dexterous manipulation",
            "sim-to-real",
            "robot simulation",
            "embodied ai",
            "robot",
            "manipulation",
            "locomotion",
        }
        self.assertTrue(forbidden_theme_terms.isdisjoint(keywords))
        self.assertTrue(forbidden_theme_terms.isdisjoint(boosts))

        required_negative_terms = {
            "humanoid",
            "whole-body control",
            "egocentric perception",
            "dexterous manipulation",
            "embodied ai",
            "vision-language action",
        }
        for keyword in required_negative_terms:
            self.assertIn(keyword, negatives)

        self.assertEqual(daily["top_n"], 20)

    def test_fetch_and_review_skills_use_narrow_llm_systems_theme(self):
        fetch_text = FETCH_SKILL.read_text(encoding="utf-8")
        review_text = REVIEW_SKILL.read_text(encoding="utf-8")

        for text in (fetch_text, review_text):
            self.assertIn("LLM", text)
            self.assertIn("architecture", text)
            self.assertIn("network", text)
            self.assertIn("storage", text)

            self.assertNotIn("humanoid", text)
            self.assertNotIn("whole-body control", text)
            self.assertNotIn("egocentric", text)
            self.assertNotIn("dexterous", text)
            self.assertNotIn("HOI", text)
            self.assertNotIn("HSI", text)

        self.assertIn("只聚焦", review_text)
        self.assertIn("主推（1-2 篇）", review_text)
        self.assertIn("备选（最多 3 篇）", review_text)
        self.assertIn("不要凑满 20 篇", review_text)
        self.assertIn("没有 `has_hardware_eval` 的论文默认不进主推", review_text)
        self.assertIn("没有 `has_end_to_end_eval` 的 serving 论文只能做备选", review_text)
        self.assertIn("有 `has_real_workload` 的论文在同分情况下优先级更高", review_text)

    def test_daily_papers_workflow_defaults_to_lightweight_recommendation(self):
        orchestrator = ORCHESTRATOR_SKILL.read_text(encoding="utf-8")
        review_text = REVIEW_SKILL.read_text(encoding="utf-8")

        self.assertIn("默认只串联论文抓取和推荐生成两步", orchestrator)
        self.assertIn("不自动调用 `daily-papers-notes`", orchestrator)
        self.assertIn("是否精读交给用户决定", orchestrator)
        self.assertNotIn("第 2 步完成后，自动调用 `daily-papers-notes` skill。", orchestrator)

        self.assertIn("主推（1-2 篇）", review_text)
        self.assertIn("备选（最多 3 篇）", review_text)
        self.assertIn("不要凑满 20 篇", review_text)
        self.assertIn("每篇只写 2 句", review_text)


if __name__ == "__main__":
    unittest.main()
