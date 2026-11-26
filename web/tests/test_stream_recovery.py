#!/usr/bin/env python3
"""Tests for the stream-freeze-on-resume fix (upstream issue #20).

Ports the stream-recovery slice of upstream PR #34 into this fork:
  - web/src/core/online-and-notifications.js (new)
  - web/src/core/resume-stream-recovery.js (new)
  - web/src/core/fetch-rewrite.js (streaming wrap + abort-aware retry)
  - web/src.manifest (fragment order in the bridge.core.js bundle)

Checks:
  1. Manifest order: online-and-notifications before resume-stream-recovery
     before fetch-rewrite (resume-stream-recovery defines origSetTimeout,
     wrapStreamingFetch and isStreamingRpc that fetch-rewrite.js uses, and
     registers its 'agy:host-resume' listener via the origAddEventListener
     captured by online-and-notifications.js).
  2. The rebuilt generated/bridge.core.js contains the recovery markers.
  3. The node runtime test (test_stream_recovery.mjs) proves the mechanism:
     a stuck stream's pending read resolves done:true on host-resume.

Run: python3 web/tests/test_stream_recovery.py
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
SRC = os.path.join(WEB, "src", "core")

BRIDGE_FRAGMENTS = [
    "src/core/namespace.js",
    "src/core/online-and-notifications.js",
    "src/core/polyfills-process.js",
    "src/core/config.js",
    "src/core/csrf.js",
    "src/core/endpoints.js",
    "src/core/resume-stream-recovery.js",
    "src/core/fetch-rewrite.js",
    "src/core/public-api.js",
]

GENERATED_MARKERS = [
    "activeStreamClosers",  # resume-stream-recovery.js
    "agy:host-resume",
    "wrapStreamingFetch",
    "isStreamingRpc",
    "isLoopbackRpcUrl",
    "isAborted",  # fetch-rewrite.js: aborted fetches are not retried
    "/jetski.",  # new RPC marker
    "FakeNotification",  # online-and-notifications.js
]


class ManifestOrderTest(unittest.TestCase):
    def test_bridge_core_fragment_order(self):
        with open(os.path.join(WEB, "src.manifest")) as f:
            manifest = f.read()
        # Only the bridge.core.js bundle section.
        start = manifest.index("bundle iife bridge.core.js")
        end = manifest.index("bundle iife", start + 1)
        section = manifest[start:end]
        lines = [ln.strip() for ln in section.splitlines() if ln.strip().startswith("src/")]
        self.assertEqual(lines, BRIDGE_FRAGMENTS)

    def test_fragments_exist(self):
        for frag in BRIDGE_FRAGMENTS:
            self.assertTrue(
                os.path.isfile(os.path.join(WEB, frag)),
                "missing fragment: %s" % frag,
            )


class GeneratedBundleTest(unittest.TestCase):
    def test_rebuilt_bundle_contains_recovery(self):
        tmp = tempfile.mkdtemp(prefix="agy-stream-test.")
        try:
            shutil.copytree(WEB, os.path.join(tmp, "web"))
            subprocess.run(
                ["bash", os.path.join(tmp, "web", "build.sh")],
                check=True,
                capture_output=True,
                text=True,
            )
            with open(os.path.join(tmp, "web", "generated", "bridge.core.js")) as f:
                bundle = f.read()
            for marker in GENERATED_MARKERS:
                self.assertIn(marker, bundle, "missing marker in bridge.core.js: %s" % marker)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class NodeRuntimeTest(unittest.TestCase):
    def test_node_runtime(self):
        proc = subprocess.run(
            ["node", os.path.join(WEB, "tests", "test_stream_recovery.mjs")],
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
