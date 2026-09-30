import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "_shared"))

from md_escape_check import check, fix  # noqa: E402


class MdEscapeCheckTest(unittest.TestCase):
    def test_escapes_chained_array_index(self):
        self.assertEqual(fix("算一个 C[i][j] 要扫"), r"算一个 C\[i\]\[j\] 要扫")
        self.assertEqual(fix("| A[i][k] |"), r"| A\[i\]\[k\] |")

    def test_escapes_literal_dollars(self):
        self.assertEqual(fix("每页 $200，共 $800"), r"每页 \$200，共 \$800")

    def test_is_idempotent(self):
        once = fix("addr[42:39] and $HOME")
        self.assertEqual(fix(once), once)
        self.assertEqual(check(once), [])

    def test_leaves_code_math_and_links_alone(self):
        source = (
            "---\ntitle: x[0]\n---\n"
            "`C[i][j]` and ``a`b[0]`` and $x_i[k]$ and\n"
            "$$\nA[i] = \\$5\n$$\n"
            "```c\nsum[n] += w[n][i];\n```\n"
            "[[Loop Tiling]] ![[00_assets/a[1].png|fig]] [DOI](https://x.org/a[1])\n"
            "<!-- note[0] -->\n"
        )
        self.assertEqual(fix(source), source)
        self.assertEqual(check(source), [])

    def test_ignores_plain_brackets_and_real_links(self):
        source = "区间 [0, 1] 和 [text](url) 以及 [ref]"
        self.assertEqual(fix(source), source)

    def test_horizontal_rules_are_not_frontmatter(self):
        # regression: `---` separators in the body must not hide text between them
        source = "# T\n\n---\n\nB 在 C1 为 M[0]\n\n---\n"
        self.assertEqual([line for line, _ in check(source)], [5])

    def test_check_reports_line_numbers(self):
        hits = check("ok\nE[est] ≈ T\n")
        self.assertEqual([line for line, _ in hits], [2])


if __name__ == "__main__":
    unittest.main()
