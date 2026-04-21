import unittest
from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parents[1]
ASSET_TEMPLATE = REPO_ROOT / "skills" / "paper-reader" / "assets" / "paper-note-template.md"
OBSIDIAN_TEMPLATE = REPO_ROOT / "obsidian-templates" / "论文笔记模板.md"
PAPER_READER_SKILL = REPO_ROOT / "skills" / "paper-reader" / "SKILL.md"
DAILY_PAPERS_NOTES_SKILL = REPO_ROOT / "skills" / "daily-papers-notes" / "SKILL.md"


class SystemsTemplateTests(unittest.TestCase):
    def test_asset_template_uses_systems_sections(self):
        text = ASSET_TEMPLATE.read_text(encoding="utf-8")

        required_sections = [
            "## 这篇论文为什么重要",
            "## 问题定义与瓶颈",
            "## 系统设计总览",
            "## 关键机制拆解",
            "## 实验设置",
            "## 核心结果",
            "## Overhead 与兼容性",
            "## 批判性思考",
            "## 关联笔记",
            "## 速查卡片",
            "## 复现与借鉴价值",
            "## 复现线索",
        ]
        for section in required_sections:
            self.assertIn(section, text)

        forbidden_sections = [
            "## 关键公式",
            "## 关键图表",
            "## 局限与隐含假设",
        ]
        for section in forbidden_sections:
            self.assertNotRegex(text, rf"(?m)^{re.escape(section)}(?:\s|$)")

    def test_asset_template_removes_cv_robotics_defaults(self):
        text = ASSET_TEMPLATE.read_text(encoding="utf-8")

        forbidden_phrases = [
            "语言指令",
            "动作块",
            "损失函数",
            "数据集",
            "可视化结果",
            "模型架构",
        ]
        for phrase in forbidden_phrases:
            self.assertNotIn(phrase, text)

    def test_obsidian_template_matches_systems_structure(self):
        text = OBSIDIAN_TEMPLATE.read_text(encoding="utf-8")

        self.assertIn("## Overhead 与兼容性", text)
        self.assertIn("## 复现与借鉴价值", text)
        self.assertIn("## 相关工作定位", text)
        self.assertIn("## 批判性思考", text)
        self.assertIn("## 关联笔记", text)
        self.assertIn("## 速查卡片", text)
        self.assertNotRegex(text, r"(?m)^## 关键公式(?:\s|$)")
        self.assertNotRegex(text, r"(?m)^## 关键图表(?:\s|$)")
        self.assertNotIn("### 损失函数", text)
        self.assertNotIn("### 数据集", text)
        self.assertIn("| 论文 | 外部链接 | 关系 | 差异 |", text)
        self.assertIn("| 主对比基线 |  |", text)

    def test_related_work_table_requires_internal_and_external_link_slots(self):
        asset_text = ASSET_TEMPLATE.read_text(encoding="utf-8")
        obsidian_text = OBSIDIAN_TEMPLATE.read_text(encoding="utf-8")

        for text in (asset_text, obsidian_text):
            self.assertIn("| 论文 | 外部链接 | 关系 | 差异 |", text)
            self.assertIn("`论文` 列优先写", text)
            self.assertIn("`外部链接` 列写", text)

    def test_paper_reader_skill_mentions_systems_specific_requirements(self):
        text = PAPER_READER_SKILL.read_text(encoding="utf-8")

        self.assertIn("Overhead 与兼容性", text)
        self.assertIn("复现与借鉴价值", text)
        self.assertIn("baseline 是否公平", text)
        self.assertIn("实验设置", text)
        self.assertIn("主对比基线", text)

    def test_daily_notes_skill_uses_new_template_quality_gates(self):
        text = DAILY_PAPERS_NOTES_SKILL.read_text(encoding="utf-8")

        self.assertIn("## 批判性思考", ASSET_TEMPLATE.read_text(encoding="utf-8"))
        self.assertIn("## 关联笔记", ASSET_TEMPLATE.read_text(encoding="utf-8"))
        self.assertIn("## 速查卡片", ASSET_TEMPLATE.read_text(encoding="utf-8"))
        self.assertNotIn("行数 >= 100 且包含 `## 关键公式` 和 `## 关键图表`", text)
        self.assertNotIn("包含 `## 关键公式` 和 `## 实验结果`", text)
        self.assertIn("行数 >= 100 且包含 `## 批判性思考`、`## 关联笔记`、`## 速查卡片`", text)
        self.assertIn("**不包含**独立的 `## 关键公式` 或 `## 关键图表` section header", text)


if __name__ == "__main__":
    unittest.main()
