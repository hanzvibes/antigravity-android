#!/usr/bin/env python3
"""Tests for the web_optimizations bundle.js port (upstream PR #34).

bundle.js consolidates the old taps/viewport/gpu fragments into one
file and adds: the Base UI fast-path flag
(BASE_UI_ANIMATIONS_DISABLED, read once by main.js to skip the
MutationObserver / getAnimations layout flush), passive scroll
listeners + blocking the desktop overlay-scrollbar listeners, a
soft-keyboard focus guard, a lazy 48kHz AudioContext gate, and
targeted CSS (instant taps/menus, native scrollbar, no backdrop
blur, no Prism text-shadow). It deliberately avoids translateZ(0)
on the chat viewport (position:fixed trap) and removes the old
gpu-acceleration style tag, so the old gpu.js must NOT run alongside
it. tablet-scale.js (ours) self-installs after bundle.js, since the
public-api.js that used to call it is no longer in the bundle.

The old fragment files stay on disk (dead code, same as upstream)
but are no longer in the manifest. --agy-vvh (viewport.js) had no
consumers anywhere, so dropping it loses nothing.

Checks:
  1. Manifest order: exactly bundle.js then tablet-scale.js, no
     taps/viewport/gpu/public-api.
  2. bundle.js source carries the perf markers and no translateZ(0).
  3. tablet-scale.js self-installs.
  4. The node runtime test (test_web_optimizations_bundle.mjs)
     proves the mechanism in a vm harness.
  5. The committed generated/patches/web_optimizations.js carries
     the bundle markers and none of the old gpu CSS or --agy-vvh
     (the bundle must be regenerated with web/build.sh).

Run: python3 web/tests/test_web_optimizations_bundle.py
(also driven by web/tests/selftest.sh)
"""

import os
import subprocess
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
WEB = os.path.join(ROOT, "web")

FRAGMENTS = [
    "src/patches/web_optimizations/bundle.js",
    "src/patches/web_optimizations/tablet-scale.js",
]

BUNDLE_MARKERS = [
    "BASE_UI_ANIMATIONS_DISABLED = true",
    "__agLazyGated",
    "installFocusGuard",
    "installLazyAudioGate",
    ".md-table-scroll",
    "setAttribute('data-agy', 'web-optimizations')",
    "version: '3.2.0'",
]


class ManifestTest(unittest.TestCase):
    def test_web_optimizations_fragment_order(self):
        with open(os.path.join(WEB, "src.manifest")) as f:
            manifest = f.read()
        start = manifest.index("bundle iife patches/web_optimizations.js")
        end = manifest.index("bundle iife", start + 1)
        section = manifest[start:end]
        lines = [ln.strip() for ln in section.splitlines() if ln.strip().startswith("src/")]
        self.assertEqual(lines, FRAGMENTS)


class SourceTest(unittest.TestCase):
    def test_bundle_source_markers(self):
        with open(os.path.join(WEB, "src", "patches", "web_optimizations", "bundle.js")) as f:
            src = f.read()
        for marker in BUNDLE_MARKERS:
            self.assertIn(marker, src, "missing marker: %s" % marker)
        self.assertNotIn("transform: translateZ(0);", src,
                         "bundle.js must not apply translateZ(0) as a CSS rule "
                         "(the only mentions are comments explaining why not)")
        self.assertIn('style[data-agy="gpu-acceleration"]', src,
                      "bundle.js must remove the old gpu-acceleration style tag")

    def test_tablet_scale_self_installs(self):
        with open(os.path.join(WEB, "src", "patches", "web_optimizations", "tablet-scale.js")) as f:
            src = f.read()
        self.assertIn("installTabletScale(window, window.document)", src)


class NodeRuntimeTest(unittest.TestCase):
    def test_node_runtime(self):
        proc = subprocess.run(
            ["node", os.path.join(WEB, "tests", "test_web_optimizations_bundle.mjs")],
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            proc.returncode,
            0,
            "node test failed:\n%s\n%s" % (proc.stdout, proc.stderr),
        )


class GeneratedBundleTest(unittest.TestCase):
    def test_rebuilt_bundle_markers(self):
        with open(os.path.join(WEB, "generated", "patches", "web_optimizations.js"),
                  encoding="utf-8", errors="ignore") as f:
            bundle = f.read()
        for marker in ["BASE_UI_ANIMATIONS_DISABLED", "__agLazyGated",
                       "installTabletScale", "initial-scale"]:
            self.assertIn(marker, bundle, "missing marker: %s" % marker)
        self.assertNotIn('main, [data-testid="chat-container"]', bundle,
                         "old gpu.js CSS must be gone from the rebuilt bundle")
        self.assertNotIn("--agy-vvh", bundle, "viewport.js --agy-vvh must be gone")
        self.assertNotIn(".style.zoom", bundle, "rebuilt bundle must not contain root zoom")


if __name__ == "__main__":
    unittest.main(verbosity=2)
