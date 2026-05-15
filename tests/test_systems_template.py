import unittest
from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parents[1]
ASSET_TEMPLATE = REPO_ROOT / "skills" / "paper-reader" / "assets" / "paper-note-template.md"
LEGACY_OBSIDIAN_TEMPLATE = REPO_ROOT / "obsidian-templates" / "论文笔记模板.md"
PAPER_READER_SKILL = REPO_ROOT / "skills" / "paper-reader" / "SKILL.md"
DAILY_PAPERS_NOTES_SKILL = REPO_ROOT / "skills" / "daily-papers-notes" / "SKILL.md"
README = REPO_ROOT / "README.md"
PAPER_DAEMON = REPO_ROOT / "skills" / "paper-reader" / "paper_daemon.py"
QUALITY_STANDARDS = REPO_ROOT / "skills" / "paper-reader" / "references" / "quality-standards.md"
CONCEPT_CATEGORIES = REPO_ROOT / "skills" / "paper-reader" / "references" / "concept-categories.md"


def assert_table_header(testcase, text, columns):
    escaped_columns = [re.escape(column) for column in columns]
    pattern = r"(?m)^\|\s*" + r"\s*\|\s*".join(escaped_columns) + r"\s*\|$"
    testcase.assertRegex(text, pattern)


class SystemsTemplateTests(unittest.TestCase):
    def test_asset_template_uses_systems_sections(self):
        text = ASSET_TEMPLATE.read_text(encoding="utf-8")

        required_sections = [
            "## 这篇论文为什么重要",
            "## 问题定义与瓶颈",
            "## 作者核心 Insights",
            "## 动机实验 / Characterization",
            "## 系统设计总览",
            "### 系统架构与执行流",
            "### 优化目标与度量口径",
            "### 系统组成与职责",
            "## 关键机制拆解",
            "## 实验设置",
            "## 核心结果",
            "## Overhead 与兼容性",
            "## 批判性思考",
            "## 经验与可迁移启示",
            "## 复现",
            "## 关联笔记",
            "## 速查卡片",
        ]
        for section in required_sections:
            self.assertIn(section, text)

        forbidden_sections = [
            "## 关键公式",
            "## 关键图表",
            "## 局限与隐含假设",
            "## 复现与借鉴价值",
            "## 复现线索",
            "### 部署位置",
            "### 数据流 / 控制流",
            "### 关键指标 / 总览公式",
            "### 关键组件",
            "### 硬件改动清单",
            "#### 对应公式 / 图示",
            "#### 参数选择 / 设计空间扫描",
            "### 与实验设置强相关的图 / 公式",
            "### 可复现性评估",
        ]
        for section in forbidden_sections:
            self.assertNotRegex(text, rf"(?m)^{re.escape(section)}(?:\s|$)")

        self.assertIn("### 实现改动清单", text)
        self.assertIn("#### 参数与权衡", text)
        self.assertIn("### 模拟器与微架构参数", text)
        self.assertIn("#### Silicon-feasibility", text)
        self.assertIn("```mermaid", text)
        self.assertIn("flowchart LR", text)
        assert_table_header(self, text, ["组件", "职责", "输入输出", "关键状态或参数", "关联概念"])

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

    def test_paper_note_template_is_the_single_template_source(self):
        readme = README.read_text(encoding="utf-8")

        self.assertFalse(LEGACY_OBSIDIAN_TEMPLATE.exists())
        self.assertIn("skills/paper-reader/assets/paper-note-template.md", readme)
        self.assertNotIn("obsidian-templates/论文笔记模板.md", readme)

    def test_related_work_table_requires_internal_and_external_link_slots(self):
        asset_text = ASSET_TEMPLATE.read_text(encoding="utf-8")

        assert_table_header(self, asset_text, ["论文", "外部链接", "关系", "差异"])
        self.assertIn("`论文` 列优先写", asset_text)
        self.assertIn("`外部链接` 列写", asset_text)

    def test_paper_reader_skill_mentions_systems_specific_requirements(self):
        text = PAPER_READER_SKILL.read_text(encoding="utf-8")

        self.assertIn("Overhead 与兼容性", text)
        self.assertIn("经验与可迁移启示", text)
        self.assertIn("复现", text)
        self.assertNotIn("复现与借鉴价值", text)
        self.assertIn("baseline 是否公平", text)
        self.assertIn("实验设置", text)
        self.assertIn("主对比基线", text)

    def test_concept_reference_defines_seed_vocabulary_and_three_way_paper_method_policy(self):
        text = CONCEPT_CATEGORIES.read_text(encoding="utf-8")

        self.assertIn("## Systems Concept Seed Vocabulary", text)
        for concept_type in [
            "data-structure",
            "algorithm",
            "mechanism",
            "architecture",
            "hardware",
            "software-abstraction",
            "metric",
            "theory-model",
        ]:
            self.assertRegex(text, rf"(?m)^\|\s*{re.escape(concept_type)}\s*\|")

        for seed in ["RDMA", "NVLink", "PCIe", "NUMA", "HBM", "CXL", "AllReduce", "NCCL", "CUDA"]:
            self.assertIn(seed, text)

        self.assertIn("论文首创 + 仅本论文实验", text)
        self.assertIn("论文具名实现 + 前人工作 / 被多篇当 baseline", text)
        self.assertIn("完全是前人工作 + 该论文只是引用", text)

    def test_concept_generation_prompts_prefer_recall_and_exclude_datasets(self):
        paper_reader = PAPER_READER_SKILL.read_text(encoding="utf-8")
        daily_notes = DAILY_PAPERS_NOTES_SKILL.read_text(encoding="utf-8")
        daemon = PAPER_DAEMON.read_text(encoding="utf-8")
        combined = "\n".join([paper_reader, daily_notes, daemon])

        self.assertIn("宁可漏判几个通用词，也不要误杀真正的 systems concept", combined)
        self.assertIn("不确定就创建", combined)
        self.assertIn("数据集 / 仿真器不作为 concept", combined)
        self.assertIn("seed list", combined)
        self.assertIn("首次出现必须写成 `[[概念名]]`", combined)
        self.assertIn("Admission Control", combined)
        self.assertIn("Kernel Fusion", combined)

    def test_concept_reference_uses_enhanced_template_with_required_sections(self):
        text = CONCEPT_CATEGORIES.read_text(encoding="utf-8")

        # 4 个新必选段必须在 reference 里出现
        for section in ["## 动机与痛点", "## 直观例子", "## 边界与对比", "## 学习索引"]:
            self.assertIn(section, text)

        # 长度目标
        self.assertIn("60-100 行", text)

        # 学习索引允许整段写 TODO 的硬规则
        self.assertIn("TODO: 待人工补充学习材料", text)

    def test_concept_reference_lists_per_type_differentiation_sections(self):
        text = CONCEPT_CATEGORIES.read_text(encoding="utf-8")

        # 8 类各自的差异化段都要在 reference 里列出
        differentiation_sections = [
            "## 内存视图 / 字段布局",           # data-structure
            "## 步骤",                          # algorithm
            "## 复杂度",                        # algorithm
            "## 状态与触发条件",                # mechanism
            "## 关键参数",                      # mechanism
            "## 组件与接口",                    # architecture
            "## 接口与典型参数",                # hardware
            "## API 与生命周期",                # software-abstraction
            "## 测量方法",                      # metric
            "## 假设与失效边界",                # theory-model
        ]
        for section in differentiation_sections:
            self.assertIn(section, text)

        # architecture 类必须用 Mermaid,不允许 ASCII 替代
        self.assertIn("不允许 ASCII", text)
        self.assertIn("Mermaid", text)

    def test_enhanced_template_propagated_to_paper_daemon_and_daily_notes(self):
        paper_reader = PAPER_READER_SKILL.read_text(encoding="utf-8")
        daily_notes = DAILY_PAPERS_NOTES_SKILL.read_text(encoding="utf-8")
        daemon = PAPER_DAEMON.read_text(encoding="utf-8")

        # 三处都要提到增强模板和 4 个必选段;daemon 自带模板示例
        for blob, name in [
            (paper_reader, "paper-reader SKILL.md"),
            (daily_notes, "daily-papers-notes SKILL.md"),
            (daemon, "paper_daemon.py"),
        ]:
            for keyword in ["动机与痛点", "直观例子", "边界与对比", "学习索引"]:
                self.assertIn(keyword, blob, f"{name} 缺少关键词 {keyword}")

        # 三处都要明确长度目标
        self.assertIn("60-100 行", paper_reader)
        self.assertIn("60-100 行", daily_notes)
        self.assertIn("60-100 行", daemon)

    def test_paper_reader_zotero_workflow_is_readonly_and_collection_path_based(self):
        text = PAPER_READER_SKILL.read_text(encoding="utf-8")
        asset_text = ASSET_TEMPLATE.read_text(encoding="utf-8")

        self.assertIn("zotero_item_id: {zotero_item_id}", asset_text)
        self.assertIn("zotero_collection: {zotero_path}", asset_text)
        self.assertIn("Zotero 默认只读", text)
        self.assertIn("{NOTES_PATH}/{selected_collection_path}/{MethodName}.md", text)
        self.assertIn("批量从 collection 进入时", text)
        self.assertIn("确认后才调用", text)

    def test_daily_notes_skill_uses_new_template_quality_gates(self):
        text = DAILY_PAPERS_NOTES_SKILL.read_text(encoding="utf-8")

        self.assertIn("## 批判性思考", ASSET_TEMPLATE.read_text(encoding="utf-8"))
        self.assertIn("## 关联笔记", ASSET_TEMPLATE.read_text(encoding="utf-8"))
        self.assertIn("## 速查卡片", ASSET_TEMPLATE.read_text(encoding="utf-8"))
        self.assertIn("## 复现", ASSET_TEMPLATE.read_text(encoding="utf-8"))
        self.assertNotIn("行数 >= 100 且包含 `## 关键公式` 和 `## 关键图表`", text)
        self.assertNotIn("包含 `## 关键公式` 和 `## 实验结果`", text)
        self.assertIn("行数 >= 100 且包含 `## 批判性思考`、`## 复现`、`## 关联笔记`、`## 速查卡片`", text)
        self.assertIn("**不包含**独立的 `## 关键公式` 或 `## 关键图表` section header", text)

    def test_figure_and_formula_guidance_uses_natural_explanations(self):
        template_text = ASSET_TEMPLATE.read_text(encoding="utf-8")
        daemon_text = PAPER_DAEMON.read_text(encoding="utf-8")
        standards_text = QUALITY_STANDARDS.read_text(encoding="utf-8")

        rigid_phrases = [
            "这张图说明什么瓶颈或规律",
            "这张图说明什么",
            "关键数字",
            "最关键数字",
            "公式想说明什么",
            "图里最关键的视觉证据",
            "**说明**:",
            "**表格说明**:",
            "**含义**:",
            "**符号说明**:",
            "扫描了哪些参数",
            "最终选择",
            "选择依据",
            "去掉哪个模块最伤性能",
            "参数变化的趋势",
            "额外开销来自哪里",
            "部署位置",
            "数据流 / 控制流",
            "关键指标 / 总览公式",
            "关键组件",
            "硬件改动清单",
            "对应公式 / 图示",
            "参数选择 / 设计空间扫描",
            "与实验设置强相关的图 / 公式",
            "可复现性评估",
            "复现与借鉴价值",
            "复现线索",
        ]
        combined_text = "\n".join([template_text, daemon_text, standards_text])
        for phrase in rigid_phrases:
            self.assertNotIn(phrase, combined_text)

        natural_guidance = [
            "自然段",
            "论证链",
            "关键趋势",
            "支撑的设计或结论",
        ]
        for phrase in natural_guidance:
            self.assertIn(phrase, combined_text)


if __name__ == "__main__":
    unittest.main()
