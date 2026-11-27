#!/usr/bin/env python3
"""Tests for the swipe/drag PERF patch (web/patch_main.py, PERF_HUNKS).

Upstream PR #34 rewrote the swipe/drag gesture hook to stop re-rendering
React on every pointer move: the dragged element's transform is written
straight to the DOM (translate3d + transition:none while dragging,
cleared on release) and the swiping flag is mirrored with a data-swiping
attribute. The 22 hunks are applied by patch_main.py at build time to a
staged copy of the upstream bundle (the checked-in web/main.js is never
modified).

Checks:
  1. The patcher applies cleanly to a copy of web/main.js (exit 0).
  2. Every old string is gone and every new string is present exactly
     once in the patched copy (22/22).
  3. The patched bundle carries the direct-DOM markers (translate3d,
     data-swiping, removeProperty("transition")) and passes node --check.
  4. The patcher is idempotent: a second run is a clean no-op.
  5. The patcher fails closed: corrupting one old string makes it exit
     non-zero instead of shipping a half-patched bundle.

Run: python3 web/tests/test_perf_patch.py
(also driven by web/tests/selftest.sh)
"""

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
WEB = os.path.join(ROOT, "web")


def load_patcher():
    spec = importlib.util.spec_from_file_location(
        "patch_main", os.path.join(WEB, "patch_main.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class PerfPatchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="agy-perf-test.")
        self.patcher = load_patcher()
        self.hunks = self.patcher.PERF_HUNKS
        self.assertEqual(len(self.hunks), 22, "PERF_HUNKS must have 22 entries")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _copy_main(self, name="main.js"):
        dst = os.path.join(self.tmp, name)
        shutil.copyfile(os.path.join(WEB, "main.js"), dst)
        return dst

    def _run_patcher(self, path):
        return subprocess.run(
            [sys.executable, os.path.join(WEB, "patch_main.py"), path],
            capture_output=True,
            text=True,
        )

    def test_all_hunks_apply_exactly_once(self):
        dst = self._copy_main()
        proc = self._run_patcher(dst)
        self.assertEqual(proc.returncode, 0, "patcher failed:\n%s\n%s" % (proc.stdout, proc.stderr))
        with open(dst, encoding="utf-8", errors="ignore") as f:
            patched = f.read()
        for name, old, new in self.hunks:
            self.assertEqual(patched.count(old), 0, "%s: old string still present" % name)
            self.assertEqual(patched.count(new), 1, "%s: new string not present exactly once" % name)

    def test_direct_dom_markers_and_syntax(self):
        dst = self._copy_main()
        proc = self._run_patcher(dst)
        self.assertEqual(proc.returncode, 0, "patcher failed:\n%s\n%s" % (proc.stdout, proc.stderr))
        with open(dst, encoding="utf-8", errors="ignore") as f:
            patched = f.read()
        for marker in ("translate3d(", "data-swiping", 'removeProperty("transition")'):
            self.assertIn(marker, patched, "missing direct-DOM marker: %s" % marker)
        node = subprocess.run(
            ["node", "--check", dst], capture_output=True, text=True
        )
        self.assertEqual(node.returncode, 0, "node --check failed:\n%s" % node.stderr)

    def test_idempotent(self):
        dst = self._copy_main()
        first = self._run_patcher(dst)
        self.assertEqual(first.returncode, 0)
        with open(dst, encoding="utf-8", errors="ignore") as f:
            once = f.read()
        second = self._run_patcher(dst)
        self.assertEqual(second.returncode, 0, "second run failed:\n%s\n%s" % (second.stdout, second.stderr))
        with open(dst, encoding="utf-8", errors="ignore") as f:
            twice = f.read()
        self.assertEqual(once, twice, "second run changed the bundle")
        self.assertIn("0 applied, 22 already present", second.stdout)

    def test_fails_closed_on_missing_hunk(self):
        dst = self._copy_main()
        with open(dst, encoding="utf-8", errors="ignore") as f:
            content = f.read()
        name, old, _new = self.hunks[0]
        self.assertEqual(content.count(old), 1)
        content = content.replace(old, "XXCORRUPTXX" + old[12:], 1)
        with open(dst, "w", encoding="utf-8") as f:
            f.write(content)
        proc = self._run_patcher(dst)
        self.assertNotEqual(proc.returncode, 0, "patcher must fail when %s is missing" % name)
        self.assertIn(name, proc.stderr)

    def test_skips_when_hook_absent(self):
        # A minimal bundle without the gesture hook (e.g. the sandbox
        # test fixture) must not fail the whole patch run.
        content = "var x = 1; // no swipe hook here\n"
        out = self.patcher._apply_perf_patch(content)
        self.assertEqual(out, content)


if __name__ == "__main__":
    unittest.main(verbosity=2)
