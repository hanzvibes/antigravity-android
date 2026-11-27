#!/usr/bin/env python3
"""Tests for the CSRF cookie cache (upstream PR #34).

syncCsrf() runs on every RPC (endpoints.js sets the
x-codeium-csrf-token header from it), so writing both cookies
unconditionally on each call is redundant once the token is stable.
web/src/core/csrf.js now caches lastSyncedCookieToken and skips the
document.cookie writes when the token has not changed, and readCsrf()
prefers the cached CONFIG.csrfToken over re-querying the meta tag.

Checks:
  1. The node runtime test (test_csrf_cache.mjs) proves the mechanism
     with a stubbed document whose cookie setter records writes:
     first sync writes both cookies, same-token sync writes nothing,
     changed-token sync writes again, CONFIG beats the meta tag,
     window.__AG_CSRF__ still wins.
  2. web/src/core/csrf.js carries the cache guard.
  3. The committed generated/bridge.core.js carries the cache guard
     (the bundle must be regenerated with web/build.sh).

Run: python3 web/tests/test_csrf_cache.py
(also driven by web/tests/selftest.sh)
"""

import os
import subprocess
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
WEB = os.path.join(ROOT, "web")


class CsrfCacheTest(unittest.TestCase):
    def test_node_harness(self):
        proc = subprocess.run(
            ["node", os.path.join(WEB, "tests", "test_csrf_cache.mjs")],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, "node test failed:\n%s\n%s" % (proc.stdout, proc.stderr))
        self.assertIn("test_csrf_cache.mjs: OK", proc.stdout)

    def test_source_carries_cache_guard(self):
        with open(os.path.join(WEB, "src", "core", "csrf.js"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn("var lastSyncedCookieToken = null;", src)
        self.assertIn("if (token !== lastSyncedCookieToken) {", src)
        self.assertIn("if (CONFIG.csrfToken) return String(CONFIG.csrfToken);", src)

    def test_generated_bundle_carries_cache_guard(self):
        with open(os.path.join(WEB, "generated", "bridge.core.js"), encoding="utf-8", errors="ignore") as f:
            bundle = f.read()
        self.assertIn("lastSyncedCookieToken", bundle)


if __name__ == "__main__":
    unittest.main(verbosity=2)
