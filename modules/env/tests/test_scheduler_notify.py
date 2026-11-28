#!/usr/bin/env python3
"""
test_scheduler_notify.py - Unit tests for the clickable-notification + DNS
resilience slice ported from upstream PR #34 (scheduler.py, agy-notify,
resolv.conf, AgyClickableNotify DEX helper).

Runs hermetically: HOME is pointed at a temp dir before the daemon package
is imported, so RESOLV_CONF_PATH / BRAIN_GLOB resolve inside the temp dir,
and scheduler.notify is monkeypatched with a recorder (no real
agy-notify subprocess is ever spawned).

Run:  python3 modules/env/tests/test_scheduler_notify.py
(or via modules/env/tests/run_all.sh)
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(TESTS_DIR)))
DAEMON_LIB = os.path.join(REPO_ROOT, "env", "overlay", "lib")
OVERLAY = os.path.join(REPO_ROOT, "env", "overlay")

_tmp_home = tempfile.mkdtemp(prefix="agy_sched_test_")
os.environ["HOME"] = _tmp_home
sys.path.insert(0, DAEMON_LIB)

import daemon.scheduler as sched  # noqa: E402


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _transcript_path(convo="convo1"):
    return os.path.join(
        _tmp_home, ".gemini", "antigravity-app", "brain", convo,
        ".system_generated", "logs", "transcript.jsonl",
    )


class TestGuardResolvConf(unittest.TestCase):
    def setUp(self):
        self.state = {}
        self.logs = []
        self._orig_log = sched.log
        sched.log = lambda msg: self.logs.append(msg)

    def tearDown(self):
        sched.log = self._orig_log

    def test_healthy_file_untouched(self):
        healthy = "options timeout:2 attempts:3 rotate\nnameserver 1.1.1.1\nnameserver 8.8.8.8\n"
        _write(sched.RESOLV_CONF_PATH, healthy)
        sched._guard_resolv_conf(self.state)
        with open(sched.RESOLV_CONF_PATH, encoding="utf-8") as f:
            self.assertEqual(f.read(), healthy)
        self.assertIn("resolv_mtime", self.state)

    def test_degraded_file_restored(self):
        _write(sched.RESOLV_CONF_PATH,
               "options timeout:1 attempts:1\nnameserver 9.9.9.9\n")
        sched._guard_resolv_conf(self.state)
        with open(sched.RESOLV_CONF_PATH, encoding="utf-8") as f:
            lines = f.read().splitlines()
        self.assertEqual(lines[0], "options timeout:2 attempts:3 rotate")
        self.assertEqual(lines[1], "nameserver 1.1.1.1")
        self.assertEqual(lines[2], "nameserver 8.8.8.8")
        self.assertIn("nameserver 9.9.9.9", lines)  # other nameservers preserved
        self.assertTrue(any("Restored resilient DNS" in m for m in self.logs))

    def test_missing_1111_triggers_restore(self):
        _write(sched.RESOLV_CONF_PATH, "nameserver 9.9.9.9\n")
        sched._guard_resolv_conf(self.state)
        with open(sched.RESOLV_CONF_PATH, encoding="utf-8") as f:
            self.assertIn("1.1.1.1", f.read())

    def test_same_mtime_is_noop(self):
        _write(sched.RESOLV_CONF_PATH,
               "options timeout:1 attempts:1\nnameserver 9.9.9.9\n")
        sched._guard_resolv_conf(self.state)
        with open(sched.RESOLV_CONF_PATH, encoding="utf-8") as f:
            after_first = f.read()
        sched._guard_resolv_conf(self.state)  # mtime unchanged -> early return
        with open(sched.RESOLV_CONF_PATH, encoding="utf-8") as f:
            self.assertEqual(f.read(), after_first)

    def test_missing_file_does_not_raise(self):
        missing_state = {}
        # RESOLV_CONF_PATH does not exist yet in a fresh sub-home; point the
        # module constant at a nonexistent path for this case.
        orig = sched.RESOLV_CONF_PATH
        try:
            sched.RESOLV_CONF_PATH = os.path.join(_tmp_home, "etc", "no-such.conf")
            sched._guard_resolv_conf(missing_state)  # must not raise
        finally:
            sched.RESOLV_CONF_PATH = orig


class TestReadLastJsonlRecord(unittest.TestCase):
    def test_reads_last_valid_line(self):
        path = os.path.join(_tmp_home, "t.jsonl")
        _write(path, '{"a": 1}\n{"b": 2}\n')
        self.assertEqual(sched._read_last_jsonl_record(path), {"b": 2})

    def test_skips_trailing_garbage(self):
        path = os.path.join(_tmp_home, "t2.jsonl")
        _write(path, '{"a": 1}\npartial line without brace\n')
        self.assertEqual(sched._read_last_jsonl_record(path), {"a": 1})

    def test_empty_and_missing(self):
        path = os.path.join(_tmp_home, "t3.jsonl")
        _write(path, "")
        self.assertIsNone(sched._read_last_jsonl_record(path))
        self.assertIsNone(sched._read_last_jsonl_record(os.path.join(_tmp_home, "nope.jsonl")))


class TestConversationTurns(unittest.TestCase):
    def setUp(self):
        self.state = {}
        self.posts = []
        self._orig_notify = sched.notify
        self._orig_log = sched.log
        sched.notify = lambda title, message, tag=None: self.posts.append((title, message, tag))
        sched.log = lambda msg: None
        self.path = _transcript_path()
        self._mtime = 1700000000

    def tearDown(self):
        sched.notify = self._orig_notify
        sched.log = self._orig_log

    def _append_record(self, rec):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
        self._mtime += 1
        os.utime(self.path, (self._mtime, self._mtime))

    def test_turn_complete_notifies_once(self):
        self._append_record({"step_index": 0, "type": "USER_INPUT",
                             "status": "", "tool_calls": [], "content": "kerjakan ini"})
        sched._check_conversation_turns(self.state)
        self.assertEqual(self.posts, [])  # first call only initializes

        self._append_record({"step_index": 1, "type": "PLANNER_RESPONSE",
                             "status": "DONE", "tool_calls": [],
                             "content": "Selesai, ini hasilnya"})
        sched._check_conversation_turns(self.state)
        self.assertEqual(len(self.posts), 1)
        title, message, tag = self.posts[0]
        self.assertEqual(title, "Antigravity: Task Complete")
        self.assertIn("Selesai", message)
        self.assertEqual(tag, "agy_turn_done")

        # Same step again (mtime bumped, no new step) -> no duplicate.
        self._mtime += 1
        os.utime(self.path, (self._mtime, self._mtime))
        sched._check_conversation_turns(self.state)
        self.assertEqual(len(self.posts), 1)

    def test_ask_question_notifies_input_needed(self):
        self._append_record({"step_index": 0, "type": "USER_INPUT",
                             "status": "", "tool_calls": [], "content": "lanjut"})
        sched._check_conversation_turns(self.state)
        self._append_record({"step_index": 1, "type": "PLANNER_RESPONSE",
                             "status": "DONE",
                             "tool_calls": [{"name": "ask_question"}],
                             "content": ""})
        sched._check_conversation_turns(self.state)
        self.assertEqual(len(self.posts), 1)
        self.assertEqual(self.posts[0][0], "Antigravity: Input Needed")
        self.assertEqual(self.posts[0][2], "agy_turn_done")


class TestShippedFiles(unittest.TestCase):
    def test_resolv_conf_has_options_line(self):
        with open(os.path.join(OVERLAY, "etc", "resolv.conf"), encoding="utf-8") as f:
            content = f.read()
        self.assertIn("options timeout:2 attempts:3 rotate", content)
        self.assertIn("nameserver 1.1.1.1", content)
        self.assertIn("nameserver 8.8.8.8", content)

    def test_agy_notify_script(self):
        script = os.path.join(OVERLAY, "bin", "agy-notify")
        with open(script, encoding="utf-8") as f:
            src = f.read()
        self.assertIn("AgyClickableNotify", src)
        self.assertIn("app_process", src)
        self.assertIn("cmd notification post", src)  # fallback path kept
        self.assertIn('TAG="agy_turn_done"', src)
        self.assertTrue(os.path.isfile(
            os.path.join(OVERLAY, "share", "agy-notify-dex", "agy_notify.jar")))

    def test_agy_notify_bash_syntax(self):
        script = os.path.join(OVERLAY, "bin", "agy-notify")
        res = subprocess.run(["bash", "-n", script], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)

    def test_dex_jar_contains_helper_class(self):
        jar = os.path.join(OVERLAY, "share", "agy-notify-dex", "agy_notify.jar")
        self.assertTrue(zipfile.is_zipfile(jar))
        with zipfile.ZipFile(jar) as z:
            self.assertIn("classes.dex", z.namelist())
            dex = z.read("classes.dex")
        self.assertIn(b"AgyClickableNotify", dex)

    @unittest.skipIf(shutil.which("javac") is None, "javac not on PATH")
    def test_java_source_compiles(self):
        src = os.path.join(OVERLAY, "share", "agy-notify-dex",
                           "AgyClickableNotify.java")
        android_jar = os.path.join(REPO_ROOT, "tools", "android.jar")
        outdir = tempfile.mkdtemp(prefix="agy_javac_")
        try:
            res = subprocess.run(
                ["javac", "-cp", android_jar, "-d", outdir, src],
                capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertTrue(os.path.isfile(
                os.path.join(outdir, "AgyClickableNotify.class")))
        finally:
            shutil.rmtree(outdir, ignore_errors=True)


def tearDownModule():
    shutil.rmtree(_tmp_home, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
