"""Tests for regenerate_concepts.py.

Covers:
- Concept loading from frontmatter (name / aliases / concept_type)
- Reverse paper reference matching with alias / case / [[Concept#section]] forms
- Prompt construction includes diff-section names by concept_type
- subprocess.run is called as list, not shell=True
- --install refuses dirty git tree without --force
- --install respects manifest
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "skills" / "_shared" / "regenerate_concepts.py"


def load_module():
    sys.path.insert(0, str(REPO_ROOT / "skills" / "_shared"))
    spec = importlib.util.spec_from_file_location("regenerate_concepts", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["regenerate_concepts"] = module  # required for dataclass to resolve types on 3.9
    spec.loader.exec_module(module)
    return module


class RegenerateConceptsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def _make_concept(self, root: Path, type_: str, name: str, body: str = "old body", aliases=None):
        aliases = aliases or []
        alias_str = "[" + ", ".join(aliases) + "]" if aliases else "[]"
        path = root / type_ / f"{name}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"---\ntype: concept\naliases: {alias_str}\nconcept_type: {type_}\n---\n\n"
            f"# {name}\n\n{body}\n",
            encoding="utf-8",
        )
        return path

    def test_load_concepts_extracts_name_type_aliases_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            concepts_root = Path(tmp) / "_concepts"
            self._make_concept(concepts_root, "data-structure", "KV Cache", body="some kv cache stuff", aliases=["键值缓存"])
            (concepts_root / "data-structure" / "_index_data-structure.md").write_text("---\ntags: [MOC]\n---\n# index", encoding="utf-8")

            concepts = self.module.load_concepts(concepts_root)

        self.assertEqual(len(concepts), 1)
        c = concepts[0]
        self.assertEqual(c.name, "KV Cache")
        self.assertEqual(c.concept_type, "data-structure")
        self.assertIn("键值缓存", c.aliases)
        self.assertIn("some kv cache stuff", c.body)
        # lookup keys should include both name and alias normalized
        self.assertIn(self.module.normalize_name("KV Cache"), c.lookup_keys)
        self.assertIn(self.module.normalize_name("键值缓存"), c.lookup_keys)

    def test_find_paper_references_matches_alias_and_section_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            concepts_root = tmp / "_concepts"
            self._make_concept(concepts_root, "data-structure", "KV Cache", aliases=["键值缓存"])
            concepts = self.module.load_concepts(concepts_root)

            notes_root = tmp / "PaperNotes"
            # paper 1: links via [[KV Cache]]
            (notes_root / "P1.md").parent.mkdir(parents=True, exist_ok=True)
            (notes_root / "P1.md").write_text(
                "Some text mentioning [[KV Cache]] in passing.\n\nNew paragraph.\n",
                encoding="utf-8",
            )
            # paper 2: links via alias [[键值缓存]]
            (notes_root / "P2.md").write_text("用 [[键值缓存]] 提速。", encoding="utf-8")
            # paper 3: section form [[KV Cache#内存视图]]
            (notes_root / "P3.md").write_text("See [[KV Cache#内存视图]] for layout.", encoding="utf-8")
            # paper 4: completely unrelated
            (notes_root / "P4.md").write_text("Just talks about [[PagedAttention]].", encoding="utf-8")
            # concept self-folder dir excluded by iter_note_files (concepts_root is also under notes_root in some test layouts, but here separate)

            refs = self.module.find_paper_references(concepts[0], notes_root, concepts_root, max_refs=10)

        ref_stems = {p.stem for p, _ in refs}
        self.assertIn("P1", ref_stems)
        self.assertIn("P2", ref_stems)
        self.assertIn("P3", ref_stems)
        self.assertNotIn("P4", ref_stems)

    def test_build_prompt_includes_diff_section_for_concept_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            concepts_root = tmp / "_concepts"
            self._make_concept(concepts_root, "architecture", "LLM Serving")
            self._make_concept(concepts_root, "algorithm", "Huffman Coding")
            concepts = self.module.load_concepts(concepts_root)
        c_arch = next(c for c in concepts if c.name == "LLM Serving")
        c_algo = next(c for c in concepts if c.name == "Huffman Coding")

        arch_prompt = self.module.build_prompt(c_arch, refs=[])
        algo_prompt = self.module.build_prompt(c_algo, refs=[])

        # architecture must mention the diff section and Mermaid requirement
        self.assertIn("## 组件与接口", arch_prompt)
        # algorithm needs both 步骤 + 复杂度
        self.assertIn("## 步骤", algo_prompt)
        self.assertIn("## 复杂度", algo_prompt)
        # hard rules echoed
        self.assertIn("不可凭空编造", arch_prompt)
        self.assertIn("学习索引", arch_prompt)

    def test_run_llm_uses_list_args_not_shell(self):
        # Verify the subprocess.run call uses list form (not shell=True). We patch
        # subprocess.run inside the module and inspect the recorded call args.
        with patch.object(self.module, "subprocess") as mock_sp:
            mock_sp.run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="ok\n", stderr="")
            # Provide TimeoutExpired and CalledProcessError attrs that the caller may inspect
            mock_sp.TimeoutExpired = subprocess.TimeoutExpired
            mock_sp.CalledProcessError = subprocess.CalledProcessError
            result = self.module.run_llm(["claude", "-p"], "hello")

        self.assertEqual(result, "ok")
        called_args, called_kwargs = mock_sp.run.call_args
        self.assertEqual(called_args[0], ["claude", "-p"])
        # never pass shell=True
        self.assertNotIn("shell", called_kwargs)

    def test_install_refuses_dirty_git_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            concepts_root = tmp / "_concepts"
            notes_root = tmp / "PaperNotes"
            self._make_concept(concepts_root, "data-structure", "KV Cache")
            concepts = self.module.load_concepts(concepts_root)

            regen_root = self.module.regen_dir_for(concepts_root)
            regen_root.mkdir(parents=True, exist_ok=True)
            (regen_root / "data-structure").mkdir(parents=True, exist_ok=True)
            (regen_root / "data-structure" / "KV Cache.md").write_text("new content", encoding="utf-8")
            (regen_root / ".install_manifest.json").write_text(
                json.dumps({"items": [{"rel": "data-structure/KV Cache.md", "original_sha": "a", "regen_sha": "b"}]}),
                encoding="utf-8",
            )

            # mock ensure_vault_git_clean to return dirty
            with patch.object(self.module, "ensure_vault_git_clean", return_value=(False, "M something")):
                rc_dirty = self.module.cmd_install(concepts, notes_root, concepts_root, force=False)
                self.assertEqual(rc_dirty, 1)
                # should NOT have overwritten the existing concept
                self.assertEqual((concepts_root / "data-structure" / "KV Cache.md").read_text(encoding="utf-8")[:5], "---\nt")

                # force=True bypasses
                rc_force = self.module.cmd_install(concepts, notes_root, concepts_root, force=True)
                self.assertEqual(rc_force, 0)
                self.assertEqual((concepts_root / "data-structure" / "KV Cache.md").read_text(encoding="utf-8"), "new content")


if __name__ == "__main__":
    unittest.main()
