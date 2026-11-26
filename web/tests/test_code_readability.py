#!/usr/bin/env python3
"""Tests for the code-block readability polish in web/jetbox.css.

Keeps the Okaidia (dark) / Prism-default (light) palettes exactly as they
were; only the presentation of Prism code blocks changes:
  - line-height 1.5 -> 1.6 (both themes)
  - tab-size 4 -> 2 (both themes; narrow phone screens)
  - light code blocks gain the border-radius the dark theme already had
  - dark code blocks gain a ::selection rule (previously none: selected
    code fell back to the browser default on the okaidia background)
  - inline code chips get horizontal padding (0.1em -> 0.1em 0.3em)

Run: python3 web/tests/test_code_readability.py
"""

import os
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
JETBOX = os.path.join(ROOT, "web", "jetbox.css")

# Palette values that must NOT change (Okaidia dark / Prism-default light).
PALETTE_GUARDS = [
    "--syntax-keyword: #66d9ef;",  # dark okaidia
    "--syntax-string: #a6e22e;",
    "--syntax-function: #e6db74;",
    "--syntax-keyword: #07a;",  # light prism default
    "--syntax-string: #690;",
    "--syntax-function: #dd4a68;",
]


class ReadabilityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(JETBOX) as f:
            cls.css = f.read()
        # The Prism light theme: first ".theme-light {" up to ".theme-dark {".
        start = cls.css.index(".theme-light {")
        end = cls.css.index(".theme-dark {", start)
        cls.light = cls.css[start:end]
        # The Prism dark theme: first ".theme-dark {" up to the token fix note.
        dstart = cls.css.index(".theme-dark {")
        dend = cls.css.index("/* Keep token spans inline", dstart)
        cls.dark = cls.css[dstart:dend]

    def test_palette_untouched(self):
        for guard in PALETTE_GUARDS:
            self.assertIn(guard, self.css, "palette changed: %s" % guard)

    def test_tab_size_2_everywhere(self):
        self.assertNotIn("tab-size: 4", self.css)
        # Plain "tab-size" only: the -moz-/-o- lines contain it as a substring.
        self.assertEqual(self.css.count("\n    tab-size: 2;"), 2)
        self.assertEqual(self.css.count("-moz-tab-size: 2;"), 2)
        self.assertEqual(self.css.count("-o-tab-size: 2;"), 2)

    def test_line_height_1_6(self):
        self.assertIn("line-height: 1.6;", self.light)
        self.assertIn("line-height: 1.6;", self.dark)
        self.assertNotIn("line-height: 1.5;", self.light)
        self.assertNotIn("line-height: 1.5;", self.dark)

    def test_light_code_block_rounded(self):
        self.assertIn("border-radius: 0.3em;", self.light)

    def test_dark_selection_rule(self):
        self.assertIn("::selection", self.dark)
        self.assertIn("::-moz-selection", self.dark)
        self.assertIn("var(--bg-selection, #264f78)", self.dark)

    def test_inline_code_padding(self):
        self.assertEqual(self.css.count("padding: 0.1em 0.3em;"), 2)

    def test_braces_balanced(self):
        self.assertEqual(
            self.css.count("{"),
            self.css.count("}"),
            "unbalanced braces in jetbox.css",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
