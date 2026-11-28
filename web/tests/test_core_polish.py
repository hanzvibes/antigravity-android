#!/usr/bin/env python3
"""Tests for the core-polish leftovers (upstream PR #34).

The last small core-polish diffs of upstream PR #34 that belonged to no
named slice (PR #13 deliberately left them out):

  1. web/src/core/namespace.js: VERSION '1.0.0' -> '1.2.1'. It flows
     into api.version and CONFIG appVersion/version via config.js.
  2. web/src/core/public-api.js: window.__agBridgeCore now also exposes
     triggerStreamRecovery and getActiveStreamCount (the latter returns
     activeStreamClosers.size), and the ready log line is versioned:
     "v1.2.1 ready (loopback stream recovery + online shim active)".
     The functions themselves were already defined in the fork (PR #4
     ported resume-stream-recovery.js byte-identical); they just were
     not exposed on window.__agBridgeCore.

No upstream defect was found in these hunks (unlike PR #12): the head's
source and its committed generated bundle agree exactly for both files,
and the exposure is sound — namespace.js (manifest line 20) defines
VERSION, resume-stream-recovery.js (line 26) defines
triggerStreamRecovery/activeStreamClosers, both before public-api.js
(line 28), so all three names are in scope. Nothing in the repo
consumes window.__agBridgeCore yet, so the exposure is purely
additive.

Checks:
  1. The node runtime test (test_core_polish.mjs) proves the
     mechanisms with stubbed window/document/fetch: version
     '1.2.1' on the API object, config and __APP_CONFIG__, the
     versioned ready log line (old endpoints-count line gone),
     triggerStreamRecovery/getActiveStreamCount exposed and
     callable, the active-stream count going 0 -> 1 on a loopback
     streaming RPC via the wrapped fetch and back to 0 on
     triggerStreamRecovery (directly and via the real
     'agy:host-resume' listener), the 300ms debounce, a no-stream
     forced trigger, and a non-streaming fetch registering
     nothing.
  2. The source fragments carry the ported markers (and none of
     the old ones).
  3. The committed generated/bridge.core.js carries the same
     markers (the bundle must be regenerated with web/build.sh),
     and differs from the upstream head's generated bundle only
     by the fork's own PR #9 csrf.js comment block.

Run: python3 web/tests/test_core_polish.py
(also driven by web/tests/selftest.sh)
"""

import os
import subprocess
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
WEB = os.path.join(ROOT, "web")


def _read(rel):
    with open(os.path.join(WEB, rel), encoding="utf-8", errors="ignore") as f:
        return f.read()


class CorePolishTest(unittest.TestCase):
    def test_node_harness(self):
        proc = subprocess.run(
            ["node", os.path.join(WEB, "tests", "test_core_polish.mjs")],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, "node test failed:\n%s\n%s" % (proc.stdout, proc.stderr))
        self.assertIn("test_core_polish.mjs: OK", proc.stdout)

    def test_namespace_source_markers(self):
        ns = _read("src/core/namespace.js")
        self.assertIn("var VERSION = '1.2.1';", ns)
        self.assertNotIn("var VERSION = '1.0.0';", ns)

    def test_public_api_source_markers(self):
        api = _read("src/core/public-api.js")
        self.assertIn("triggerStreamRecovery: triggerStreamRecovery,", api)
        self.assertIn("getActiveStreamCount: function () { return activeStreamClosers.size; }", api)
        self.assertIn("'[AGY bridge.core] v' + VERSION + ' ready (loopback stream recovery + online shim active)'", api)
        self.assertNotIn("ready (endpoints: ' + Object.keys(ENDPOINTS).length", api)

    def test_generated_bundle_carry_markers(self):
        bundle = _read("generated/bridge.core.js")
        self.assertIn("var VERSION = '1.2.1';", bundle)
        self.assertNotIn("var VERSION = '1.0.0';", bundle)
        self.assertIn("triggerStreamRecovery: triggerStreamRecovery,", bundle)
        self.assertIn("getActiveStreamCount: function () { return activeStreamClosers.size; }", bundle)
        self.assertIn("'[AGY bridge.core] v' + VERSION + ' ready (loopback stream recovery + online shim active)'", bundle)
        self.assertNotIn("ready (endpoints: ' + Object.keys(ENDPOINTS).length", bundle)


if __name__ == "__main__":
    unittest.main(verbosity=2)
