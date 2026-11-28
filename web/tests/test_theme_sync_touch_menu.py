#!/usr/bin/env python3
"""Tests for the theme_sync + touch_model_menu slices (upstream PR #34).

Theme sync (web/src/patches/theme_sync/*): resolution order is now body
classList > Android.getTheme() > initial host theme > media query, with a
<meta name="color-scheme"> kept in sync, and the native Android theme is
only persisted from a body-class transition after boot (never during the
initial pre-React load). install() runs immediately instead of waiting
for DOMContentLoaded.

Touch model menu (web/src/patches/touch_model_menu/*): scan debounce
180ms -> 80ms, the panel observer is armed on demand (pointerdown /
click on the trigger or panel) and disconnected when the panel closes.

Two upstream defects are repaired in the fork (see the comments in
scan.js / install.js): scan() calls enhanceGroup(), which exists
nowhere upstream (register.js only defines registerRow), and install()
dropped the detectTouch() call, leaving state.hasTouch false forever
— without the repairs the fragment would throw on scan and install()
would be a permanent no-op.

Checks:
  1. The node runtime test (test_theme_sync_touch_menu.mjs) proves the
     mechanisms with stubbed DOMs: theme resolution order, the
     color-scheme meta, the native persistence guard, immediate install,
     body observation after DOMContentLoaded; touch no-op on non-touch
     devices, on-demand arming, 3 scheduled scans, 80ms debounce
     coalescing, observer disconnect when the panel closes.
  2. The source fragments carry the ported markers (and the two fork
     repairs).
  3. The committed generated/patches/theme_sync.js and
     touch_model_menu.js carry the same markers (the bundles must be
     regenerated with web/build.sh).

Run: python3 web/tests/test_theme_sync_touch_menu.py
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


class ThemeSyncTouchMenuTest(unittest.TestCase):
    def test_node_harness(self):
        proc = subprocess.run(
            ["node", os.path.join(WEB, "tests", "test_theme_sync_touch_menu.mjs")],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, "node test failed:\n%s\n%s" % (proc.stdout, proc.stderr))
        self.assertIn("test_theme_sync_touch_menu.mjs: OK", proc.stdout)

    def test_theme_sync_source_markers(self):
        config = _read("src/patches/theme_sync/config.js")
        self.assertIn("var initialHostTheme = 'system';", config)
        self.assertIn("lastFromBody: null,", config)
        self.assertNotIn("var hostTheme =", config)
        resolve = _read("src/patches/theme_sync/resolve.js")
        self.assertIn("body classList > Android > host > media", resolve)
        self.assertIn("function updateColorSchemeMeta(theme) {", resolve)
        self.assertIn("if (initialHostTheme === 'light') return 'light';", resolve)
        notify = _read("src/patches/theme_sync/notify.js")
        self.assertIn("var bodyChanged = (bodyTheme !== null && bodyTheme !== state.lastFromBody);", notify)
        self.assertIn("if (bodyChanged && state.notifications > 1", notify)
        self.assertIn("updateColorSchemeMeta(theme);", notify)
        install = _read("src/patches/theme_sync/install.js")
        self.assertIn("function observeBody() {", install)
        public_api = _read("src/patches/theme_sync/public-api.js")
        self.assertIn("hostTheme: initialHostTheme,", public_api)
        self.assertTrue(public_api.rstrip().endswith("install();"))

    def test_touch_menu_source_markers(self):
        scan = _read("src/patches/touch_model_menu/scan.js")
        self.assertIn("var SCAN_DEBOUNCE_MS = 80;", scan)
        self.assertIn("function isPanelOpen() {", scan)
        self.assertIn("function disconnectObserver() {", scan)
        self.assertIn("function armPanelObserver() {", scan)
        self.assertIn("function enhanceGroup(group) {", scan)  # fork repair
        self.assertIn("registerRow(row);", scan)
        install = _read("src/patches/touch_model_menu/install.js")
        self.assertIn("state.hasTouch = detectTouch();", install)  # fork repair
        self.assertIn("document.addEventListener('pointerdown', onInteract,", install)

    def test_generated_bundles_carry_markers(self):
        theme = _read("generated/patches/theme_sync.js")
        self.assertIn("updateColorSchemeMeta", theme)
        self.assertIn("var initialHostTheme = 'system';", theme)
        self.assertNotIn("var hostTheme =", theme)
        touch = _read("generated/patches/touch_model_menu.js")
        self.assertIn("SCAN_DEBOUNCE_MS = 80", touch)
        self.assertIn("function enhanceGroup(group) {", touch)
        self.assertIn("state.hasTouch = detectTouch();", touch)
        self.assertIn("function armPanelObserver() {", touch)


if __name__ == "__main__":
    unittest.main(verbosity=2)
