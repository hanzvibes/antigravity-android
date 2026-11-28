#!/usr/bin/env python3
"""Tests for the startup_ready slice (upstream PR #34).

Startup ready (web/src/patches/startup_ready/*) tells the native side the
web UI has really rendered, so Android.onUiReady fires at the right moment
instead of on a fixed timeout. It signals on a '[ConversationLoad]'
console.info, on real chat content / the input area / any root content
(watched by arm.js via MutationObserver + a 40ms poller), or on a 5.5s
fallback timeout.

The head changes ported here: console-hook.js only signals while
!state.signalled and unhooks itself (console.info = origInfo) once the UI
is ready; detect-ui.js uses the current Antigravity selectors
([data-testid="conversation-view"], [data-testid="autoscroll-viewport"],
[role="article"], [data-lexical-editor="true"]) instead of the old
[data-role]/[data-turn-id] ones. The other startup_ready fragments
(signal.js, error-capture.js, arm.js, public-api.js) are identical
between the fork and the PR head, and the regenerated bundle is
byte-identical to the head's.

No upstream defect was found in this slice (unlike PR #12): the head's
source and its committed generated bundle agree exactly, and the
console-hook guard + self-unhook logic is sound.

Checks:
  1. The node runtime test (test_startup_ready.mjs) proves the mechanisms
     with stubbed DOMs and a virtual clock: single [ConversationLoad]
     signal + self-unhook, no signal on non-matching logs, detect-ui
     selectors (new ones match, old ones do not), the 40ms poller, the
     MutationObserver path, the exact 5.5s fallback, error capture before
     (and not after) the ready signal, and the DOMContentLoaded path.
  2. The source fragments carry the ported markers (and none of the old
     selectors).
  3. The committed generated/patches/startup_ready.js carries the same
     markers (the bundle must be regenerated with web/build.sh).

Run: python3 web/tests/test_startup_ready.py
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


class StartupReadyTest(unittest.TestCase):
    def test_node_harness(self):
        proc = subprocess.run(
            ["node", os.path.join(WEB, "tests", "test_startup_ready.mjs")],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, "node test failed:\n%s\n%s" % (proc.stdout, proc.stderr))
        self.assertIn("test_startup_ready.mjs: OK", proc.stdout)

    def test_console_hook_source_markers(self):
        hook = _read("src/patches/startup_ready/console-hook.js")
        self.assertIn("if (!state.signalled && typeof msg === 'string'", hook)
        self.assertIn("signal('conversation-load-completed');", hook)
        self.assertEqual(hook.count("console.info = origInfo;"), 2,
                         "hook must unhook itself on signal and when already signalled")

    def test_detect_ui_source_markers(self):
        detect = _read("src/patches/startup_ready/detect-ui.js")
        self.assertIn('[data-testid="conversation-view"]', detect)
        self.assertIn('[data-testid="autoscroll-viewport"]', detect)
        self.assertIn('[role="article"]', detect)
        self.assertIn('[data-lexical-editor="true"]', detect)
        self.assertIn("signal('messages-rendered');", detect)
        self.assertIn("signal('chat-input-ready');", detect)
        self.assertNotIn('[data-role="user"]', detect)
        self.assertNotIn('[data-turn-id]', detect)
        self.assertNotIn('[data-message-id]', detect)

    def test_generated_bundle_carry_markers(self):
        bundle = _read("generated/patches/startup_ready.js")
        self.assertIn("if (!state.signalled && typeof msg === 'string'", bundle)
        self.assertEqual(bundle.count("console.info = origInfo;"), 2)
        self.assertIn('[data-testid="conversation-view"]', bundle)
        self.assertIn('[data-lexical-editor="true"]', bundle)
        self.assertNotIn('[data-role="user"]', bundle)
        self.assertNotIn('[data-turn-id]', bundle)


if __name__ == "__main__":
    unittest.main(verbosity=2)
