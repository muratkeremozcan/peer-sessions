"""Backend wrappers classify failures without touching a real multiplexer."""

import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock

from helpers import load_script

spawn = load_script("spawn_fleet", "spawn-fleet.py")
receipts = load_script("peer_receipts", "peer_receipts.py")


def completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


class HerdrEnvelope(unittest.TestCase):
    def run_herdr(self, response):
        with mock.patch.object(spawn.subprocess, "run", return_value=response):
            return spawn.herdr("agent", "get", "x")

    def error_for(self, response):
        with self.assertRaises(spawn.BackendError) as caught:
            self.run_herdr(response)
        return caught.exception

    def test_success_returns_the_result(self):
        stdout = json.dumps({"result": {"agent": {"name": "x"}}})
        self.assertEqual(self.run_herdr(completed(stdout=stdout)), {"agent": {"name": "x"}})

    def test_stderr_envelope_from_herdr_0_8(self):
        stderr = json.dumps({"error": {"code": "agent_not_found", "message": "nope"}})
        error = self.error_for(completed(1, stderr=stderr))
        self.assertEqual((error.code, error.outcome, error.exit_code),
                         ("agent_not_found", "failed", 1))
        self.assertEqual(error.message, "nope")

    def test_classification(self):
        cases = {
            ("agent_pane_busy", "", 1, True): "transient",
            ("agent_not_ready", "", 1, True): "blocked",
            ("server_error", "PermissionDenied", 1, True): "denied",
            ("agent_start_timeout", "", 1, True): "unknown",
            (None, "usage: herdr agent get <target>", 2, False): "failed",
            (None, "garbage", 1, False): "unknown",
            (None, "", 0, False): "unknown",
            ("agent_start_failed", "", 1, True): "failed",
        }
        for args, outcome in cases.items():
            with self.subTest(args=args):
                self.assertEqual(spawn.classify_herdr(*args), outcome)

    def test_exit_zero_without_json_is_unknown(self):
        self.assertEqual(self.error_for(completed(0, stdout="ok?")).outcome, "unknown")

    def test_timeout_is_unknown(self):
        expired = subprocess.TimeoutExpired(["herdr"], 1)
        with mock.patch.object(spawn.subprocess, "run", side_effect=expired):
            with self.assertRaises(spawn.BackendError) as caught:
                spawn.herdr("agent", "start", "x")
        self.assertEqual((caught.exception.code, caught.exception.outcome),
                         ("timeout", "unknown"))

    def test_exec_permission_error_is_denied(self):
        with mock.patch.object(spawn.subprocess, "run", side_effect=PermissionError("no")):
            with self.assertRaises(spawn.BackendError) as caught:
                spawn.herdr("agent", "list")
        self.assertEqual(caught.exception.outcome, "denied")

    def test_missing_id_in_success_payload_is_unknown(self):
        with self.assertRaises(spawn.BackendError) as caught:
            spawn.herdr_result_id({"pane": {}}, "pane", "pane_id")
        self.assertEqual(caught.exception.outcome, "unknown")


class CmuxWrapper(unittest.TestCase):
    def test_error_prefix_and_denial(self):
        response = completed(0, stdout="Error: permission denied for socket")
        with mock.patch.object(spawn.subprocess, "run", return_value=response):
            with self.assertRaises(spawn.BackendError) as caught:
                spawn.cmux("new-split", "right")
        self.assertEqual(caught.exception.outcome, "denied")

    def test_unparsed_id_is_unknown(self):
        with self.assertRaises(spawn.BackendError) as caught:
            spawn.id_from("OK", "surface")
        self.assertEqual(caught.exception.outcome, "unknown")


class StartRetry(unittest.TestCase):
    def setUp(self):
        directory = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(directory))
        self.receipt = receipts.LaunchReceipt("herdr", "codex", "split",
                                              path=os.path.join(directory, "r.json"))
        self.receipt.add_session("rev", "/tmp", False)

    def test_only_pane_busy_is_retried(self):
        busy = spawn.BackendError("herdr", ["agent"], "busy", "agent_pane_busy", "transient")
        unknown = spawn.BackendError("herdr", ["agent"], "?", None, "unknown")
        with mock.patch.object(spawn, "herdr", side_effect=[busy, unknown]) as fake, \
                mock.patch.object(spawn.time, "sleep"):
            with self.assertRaises(spawn.BackendError) as caught:
                spawn.start_session_herdr("rev", "w:p2", ["codex"], self.receipt)
        self.assertEqual(fake.call_count, 2)
        self.assertEqual(caught.exception.outcome, "unknown")

    def test_retry_stops_at_the_deadline(self):
        busy = spawn.BackendError("herdr", ["agent"], "busy", "agent_pane_busy", "transient")
        with mock.patch.object(spawn, "herdr", side_effect=busy) as fake, \
                mock.patch.object(spawn.time, "sleep"), \
                mock.patch.object(spawn.time, "time", side_effect=[0, 1, 2, 10]):
            with self.assertRaises(spawn.BackendError):
                spawn.start_session_herdr("rev", "w:p2", ["codex"], self.receipt)
        self.assertEqual(fake.call_count, 3)


class ReceiptFile(unittest.TestCase):
    def test_written_after_each_step_and_states_are_checked(self):
        directory = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(directory))
        path = os.path.join(directory, "nested", "receipt.json")
        receipt = receipts.LaunchReceipt("cmux", "claude", "workspace", {"run_id": "r1"}, path)
        receipt.add_session("a", "/tmp/a", True)
        receipt.add_resource("workspace", "W1", "cmux new-workspace", session="a")
        with open(path) as handle:
            on_disk = json.load(handle)
        self.assertEqual(on_disk["resources"][0]["id"], "W1")
        self.assertEqual(on_disk["correlation"], {"run_id": "r1"})
        self.assertEqual(on_disk["schema_version"], 1)
        with self.assertRaises(ValueError):
            receipt.update_session("a", "finished")
        self.assertEqual(os.listdir(os.path.dirname(path)), ["receipt.json"])


if __name__ == "__main__":
    unittest.main()
