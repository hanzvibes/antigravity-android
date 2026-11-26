#!/usr/bin/env python3
"""Tests for the tablet UI scale fix (web_optimizations/tablet-scale.js).

On tablets the phone-density web UI renders tiny (text, buttons,
everything). A new fragment scales the whole layout with CSS `zoom` on
the root element when the layout viewport is >= 600 CSS px, and skips
Desktop Mode (which already scales via overview mode).

Checks:
  1. Manifest order in the web_optimizations bundle.
  2. The rebuilt generated bundle contains the fragment.
  3. The node runtime test (test_tablet_scale.mjs) proves the zoom
     steps, the Desktop Mode exclusion, and resize handling.

Run: python3 web/tests/test_tablet_scale.py
(also driven by web/tests/selftest.sh)
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
WEB = os.path.join(ROOT, "web")

WEB_OPT_FRAGMENTS = [
    "src/patches/web_optimizations/taps.js",
    "src/patches/web_optimizations/viewport.js",
    "src/patches/web_optimizations/tablet-scale.js",
    "src/patches/web_optimizations/gpu.js",
    "src/patches/web_optimizations/public-api.js",
]


class ManifestOrderTest(unittest.TestCase):
    def test_web_optimizations_fragment_order(self):
        with open(os.path.join(WEB, "src.manifest")) as f:
            manifest = f.read()
        start = manifest.index("bundle iife patches/web_optimizations.js")
        end = manifest.index("bundle iife", start + 1)
        section = manifest[start:end]
        lines = [ln.strip() for ln in section.splitlines() if ln.strip().startswith("src/")]
        self.assertEqual(lines, WEB_OPT_FRAGMENTS)


class GeneratedBundleTest(unittest.TestCase):
    def test_rebuilt_bundle_contains_tablet_scale(self):
        tmp = tempfile.mkdtemp(prefix="agy-tablet-test.")
        try:
            shutil.copytree(WEB, os.path.join(tmp, "web"))
            subprocess.run(
                ["bash", os.path.join(tmp, "web", "build.sh")],
                check=True,
                capture_output=True,
                text=True,
            )
            with open(os.path.join(tmp, "web", "generated", "patches", "web_optimizations.js")) as f:
                bundle = f.read()
            for marker in ["installTabletScale", "Antigravity/"]:
                self.assertIn(marker, bundle, "missing marker: %s" % marker)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class NodeRuntimeTest(unittest.TestCase):
    def test_node_runtime(self):
        proc = subprocess.run(
            ["node", os.path.join(WEB, "tests", "test_tablet_scale.mjs")],
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            proc.returncode,
            0,
            "node test failed:\n%s\n%s" % (proc.stdout, proc.stderr),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
