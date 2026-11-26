#!/usr/bin/env python3
"""Unit tests for the sandboxMode patch in web/patch_main.py.

Regression tests for upstream issues #40/#41: the Default and Auto
permission presets set sandboxMode:true, which makes the core re-exec
/proc/self/exe (the glibc loader) with Linux namespace/seccomp flags
that Android rejects with EINVAL ("fork/exec .../libloader.so: invalid
argument"), so every first run_command fails.

Run: python3 web/tests/test_patch_main_sandbox.py
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import patch_main  # noqa: E402

# Faithful excerpt of the W1a preset mapper from the minified bundle
# (only the sandboxMode values matter here; the rest is trimmed).
# The "Desktop Mode" marker makes the Desktop Mode step a no-op, so
# these tests exercise the sandbox patch in isolation.
W1A_UNPATCHED = (
    '/* Desktop Mode */\n'
    'function W1a(a){switch(a){'
    'case "use_global":return{sandboxMode:void 0,autoExecutionPolicy:X};'
    'case "request_review":return{sandboxMode:!1,autoExecutionPolicy:Y};'
    'case "vetted":return{sandboxMode:!1,autoExecutionPolicy:Z};'
    'case "auto":return{sandboxMode:!0,autoExecutionPolicy:A};'
    'case "turbo":return{sandboxMode:!1,autoExecutionPolicy:B};'
    'default:return{sandboxMode:!0,autoExecutionPolicy:C}}}'
)


def _run_patch_main(content):
    with tempfile.NamedTemporaryFile(
        "w", suffix=".js", delete=False, encoding="utf-8"
    ) as f:
        f.write(content)
        path = f.name
    try:
        ok = patch_main.patch_main(path)
        with open(path, encoding="utf-8") as f:
            return ok, f.read()
    finally:
        os.unlink(path)


class SandboxPatchTest(unittest.TestCase):
    def test_flips_auto_and_default_only(self):
        ok, out = _run_patch_main(W1A_UNPATCHED)
        self.assertTrue(ok)
        self.assertIn('case "auto":return{sandboxMode:!1', out)
        self.assertIn("default:return{sandboxMode:!1", out)
        self.assertNotIn("sandboxMode:!0", out)
        # Everything else must be untouched.
        self.assertIn('case "use_global":return{sandboxMode:void 0', out)
        self.assertIn('case "vetted":return{sandboxMode:!1', out)
        self.assertIn('case "turbo":return{sandboxMode:!1', out)

    def test_idempotent(self):
        ok, out = _run_patch_main(W1A_UNPATCHED)
        self.assertTrue(ok)
        ok2, out2 = _run_patch_main(out)
        self.assertTrue(ok2)
        self.assertEqual(out, out2)

    def test_already_patched_is_ok(self):
        already = W1A_UNPATCHED.replace("sandboxMode:!0", "sandboxMode:!1")
        ok, out = _run_patch_main(already)
        self.assertTrue(ok)
        self.assertEqual(already, out)

    def test_missing_pattern_fails_closed(self):
        # No W1a mapper at all: patching must fail, not silently pass,
        # so the build stops instead of shipping a broken bundle.
        ok, out = _run_patch_main('var x = "Desktop Mode";\n')
        self.assertFalse(ok)
        self.assertEqual('var x = "Desktop Mode";\n', out)

    def test_desktop_marker_does_not_skip_sandbox(self):
        # Regression test: an earlier patch_main() returned early when the
        # Desktop Mode toggle was already present, so the sandbox fix was
        # never applied to an already-patched bundle.
        fixture = '/* Desktop Mode */\n' + W1A_UNPATCHED
        ok, out = _run_patch_main(fixture)
        self.assertTrue(ok)
        self.assertNotIn("sandboxMode:!0", out)
        self.assertIn('case "auto":return{sandboxMode:!1', out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
