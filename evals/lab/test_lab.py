"""The lab refuses to serve a run once it has stopped or is about to."""

import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lab  # noqa: E402


def dead_pid():
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    return child.pid


class LabLifetime(unittest.TestCase):
    def setUp(self):
        # Unix socket paths are short, so the lab directory sits directly under /tmp.
        self.run_dir = Path(tempfile.mkdtemp(prefix="pslab-test-", dir="/tmp"))
        self.addCleanup(shutil.rmtree, self.run_dir, ignore_errors=True)
        (self.run_dir / lab.TOKEN_FILE).write_text(secrets.token_hex(32))
        lab.write_wrappers(self.run_dir)
        self.work = Path(tempfile.mkdtemp(prefix="pslab-work-"))
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)
        self.server = None

    def serve(self, lifetime):
        self.server = subprocess.Popen(
            [sys.executable, str(lab.SCRIPT), "serve", str(self.run_dir),
             "--lifetime", str(lifetime)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        self.addCleanup(self.server.wait)
        self.addCleanup(self.server.kill)
        deadline = time.monotonic() + lab.START_TIMEOUT
        while time.monotonic() < deadline:
            try:
                reply = lab.request(self.run_dir, b"ready")
                if lab.parse_ready(reply, self.server.pid) is not None:
                    return
            except OSError:
                pass
            time.sleep(0.05)
        self.fail("lab did not become ready")

    def fake(self, tool, *args):
        env = {
            "PATH": lab.SYSTEM_PATH,
            "HOME": str(self.work),
            "CLAUDE_SESSIONS_DIR": str(self.work / "lab" / "sessions"),
        }
        return subprocess.run(
            [str(self.run_dir / "bin" / tool), *args],
            cwd=self.work, env=env, capture_output=True, text=True,
        )

    def test_live_lab_runs_fakes_and_reports_time_left(self):
        self.serve(lifetime=600)
        self.assertEqual(self.fake("cmux", "identify").returncode, 0)
        self.assertGreaterEqual(lab.ready(self.run_dir, needs=60), 590)

    def test_ready_refuses_a_lab_with_less_time_than_the_run_needs(self):
        self.serve(lifetime=600)
        with self.assertRaisesRegex(RuntimeError, r"has \d+s left and the run needs 3600s"):
            lab.ready(self.run_dir, needs=3600)

    def test_wrappers_refuse_once_the_lab_has_expired(self):
        self.serve(lifetime=1)
        self.server.wait(timeout=10)
        for tool in ("cmux", "herdr"):
            result = self.fake(tool, "identify")
            self.assertEqual(result.returncode, lab.LAB_GONE, tool)
            self.assertIn("has stopped", result.stderr)
        with self.assertRaisesRegex(RuntimeError, "is not running"):
            lab.ready(self.run_dir)

    def test_wrappers_refuse_a_lab_that_was_stopped(self):
        self.serve(lifetime=600)
        self.assertEqual(lab.request(self.run_dir, b"stop"), b"stopped\n")
        self.server.wait(timeout=10)
        self.assertEqual(self.fake("cmux", "identify").returncode, lab.LAB_GONE)

    def test_claude_wrapper_refuses_a_dead_lab(self):
        (self.run_dir / "pid").write_text(str(dead_pid()))
        lab.write_wrappers(self.run_dir, claude=Path("/usr/bin/true"))
        result = self.fake("claude", "--version")
        self.assertEqual(result.returncode, lab.LAB_GONE)
        self.assertIn("has stopped", result.stderr)

    @unittest.skipUnless(os.access(lab.SANDBOX_EXEC, os.X_OK), "needs macOS sandbox-exec")
    def test_claude_wrapper_runs_while_the_lab_lives(self):
        self.serve(lifetime=600)
        (self.run_dir / lab.PROFILE_FILE).write_text("(version 1)\n(allow default)\n")
        lab.write_wrappers(self.run_dir, claude=Path("/usr/bin/true"))
        self.assertEqual(self.fake("claude").returncode, 0)


class ReadyReply(unittest.TestCase):
    def test_parses_time_left_and_checks_the_pid(self):
        self.assertEqual(lab.parse_ready(b"ready 41 300\n"), 300)
        self.assertEqual(lab.parse_ready(b"ready 41 300\n", pid=41), 300)
        self.assertIsNone(lab.parse_ready(b"ready 41 300\n", pid=42))
        self.assertIsNone(lab.parse_ready(b"ready 41\n"))
        self.assertIsNone(lab.parse_ready(b""))


if __name__ == "__main__":
    unittest.main()
