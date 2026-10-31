"""Backend wrappers classify failures without touching a real multiplexer."""

import contextlib
import io
import json
import os
import socket
import subprocess
import tempfile
import unittest
from unittest import mock

from helpers import load_script

spawn = load_script("spawn_fleet", "spawn-fleet.py")
# The module spawn-fleet imported, so ReceiptError is the class it catches.
import peer_receipts as receipts  # noqa: E402


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
            ("server_error", "Operation not permitted", 1, True): "denied",
            ("server_error", "sandbox blocked the call", 1, True): "denied",
            ("agent_start_timeout", "", 1, True): "unknown",
            (None, "usage: herdr agent get <target>", 2, False): "failed",
            (None, "garbage", 1, False): "unknown",
            (None, "", 0, False): "unknown",
            ("agent_start_failed", "", 1, True): "failed",
        }
        for args, outcome in cases.items():
            with self.subTest(args=args):
                self.assertEqual(spawn.classify_herdr(*args), outcome)

    def test_non_object_result_is_unknown(self):
        for stdout in ('{"result": null}', '{"result": []}', '{"result": "ok"}'):
            with self.subTest(stdout=stdout):
                error = self.error_for(completed(0, stdout=stdout))
                self.assertEqual((error.outcome, error.code), ("unknown", "unparsed_output"))
                self.assertEqual(error.command, ["agent", "get", "x"])

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

    def test_os_refusal_wording_is_denied(self):
        for text in (
            "Error: Operation not permitted",
            "Error: blocked by sandbox",
            "Error: EACCES connecting to socket",
            "Error: EPERM on the cmux socket",
        ):
            with self.subTest(text=text):
                response = completed(1, stdout=text)
                with mock.patch.object(spawn.subprocess, "run", return_value=response):
                    with self.assertRaises(spawn.BackendError) as caught:
                        spawn.cmux("new-workspace")
                self.assertEqual(caught.exception.outcome, "denied")

    def test_ordinary_failure_stays_failed(self):
        response = completed(1, stdout="Error: workspace limit reached")
        with mock.patch.object(spawn.subprocess, "run", return_value=response):
            with self.assertRaises(spawn.BackendError) as caught:
                spawn.cmux("new-workspace")
        self.assertEqual(caught.exception.outcome, "failed")

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
        path = os.path.join(directory, "receipt.json")
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

    def test_missing_parent_is_a_receipt_error_and_creates_nothing(self):
        directory = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(directory))
        path = os.path.join(directory, "nested", "receipt.json")
        with self.assertRaises(receipts.ReceiptError):
            receipts.LaunchReceipt("herdr", "claude", "split", path=path)
        self.assertEqual(os.listdir(directory), [])


class ReceiptWriteFailures(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.directory))
        self.path = os.path.join(self.directory, "r.json")

    def test_unlink_failure_cannot_mask_the_receipt_error(self):
        receipt = receipts.LaunchReceipt("herdr", "claude", "split", path=self.path)
        receipt.add_session("a", "/tmp/a", False)
        with mock.patch.object(receipts.os, "replace", side_effect=PermissionError("ro")), \
                mock.patch.object(receipts.os, "unlink", side_effect=PermissionError("ro")):
            with self.assertRaises(receipts.ReceiptError):
                receipt.add_resource("pane", "w:p2", "herdr pane split", session="a")
        self.assertIn("cannot write receipt", receipt.data["persistence_error"])
        self.assertEqual(receipt.data["resources"][0]["id"], "w:p2")
        # Later updates stay in memory without raising again.
        receipt.update_session("a", "started")

    def test_mkdir_facts_survive_a_receipt_failure(self):
        receipt = receipts.LaunchReceipt("herdr", "claude", "split", path=self.path)
        target = os.path.join(self.directory, "work", "a")
        receipt.add_session("a", target, False)
        os.makedirs(os.path.dirname(target))
        # The receipt's directory turns read-only; work/ stays writable.
        os.chmod(self.directory, 0o500)
        self.addCleanup(os.chmod, self.directory, 0o700)
        if os.access(self.directory, os.W_OK):
            self.skipTest("running with privileges that ignore directory modes")
        with self.assertRaises(receipts.ReceiptError):
            spawn.create_directories([("a", target)], {target}, receipt)
        self.assertTrue(os.path.isdir(target))
        self.assertEqual(receipt.data["resources"][0]["id"], target)
        self.assertTrue(receipt.session("a")["directory_created"])


class FinalBindingSnapshot(unittest.TestCase):
    """cmux readiness and the PID come from one registry read, never two."""

    def setUp(self):
        self.directory = tempfile.mkdtemp(dir="/tmp")
        self.addCleanup(lambda: __import__("shutil").rmtree(self.directory))
        self.sock = os.path.join(self.directory, "s.sock")
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(self.sock)
        self.server.listen(4)
        self.addCleanup(self.server.close)

    def record(self, session_id, pid):
        return {"pid": pid, "sessionId": session_id, "procStart": session_id, "name": "alpha",
                "cwd": self.directory, "messagingSocketPath": self.sock}

    def test_registry_changing_between_reads_cannot_restore_a_pid(self):
        one = [self.record("s1", 111111)]
        two = one + [self.record("s2", 222222)]
        receipt = receipts.LaunchReceipt("cmux", "claude", "workspace")
        receipt.add_session("alpha", self.directory, False)
        plan = {"backend": "cmux", "specs": [("alpha", self.directory)], "before": set()}
        seen = {"alpha": ("ready", one[0], None)}  # the polling loop saw one record
        with mock.patch.object(spawn, "live_records", side_effect=[two, one, one]) as reads:
            spawn.record_readiness(receipt, plan, seen)
        self.assertEqual(reads.call_count, 1)
        session = receipt.session("alpha")
        self.assertEqual(session["state"], "not_ready")
        self.assertEqual(session["identity"]["registry_candidates"], 2)
        self.assertNotIn("pid", session["identity"])

    def test_unique_record_in_the_snapshot_is_ready(self):
        receipt = receipts.LaunchReceipt("cmux", "claude", "workspace")
        receipt.add_session("alpha", self.directory, False)
        plan = {"backend": "cmux", "specs": [("alpha", self.directory)], "before": set()}
        with mock.patch.object(spawn, "live_records", return_value=[self.record("s1", 111111)]):
            spawn.record_readiness(receipt, plan, {})
        session = receipt.session("alpha")
        self.assertEqual((session["state"], session["identity"]["pid"]), ("ready", 111111))


class SessionStaging(unittest.TestCase):
    def test_receipt_failure_while_adding_sessions_still_reports(self):
        directory = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(directory))
        path = os.path.join(directory, "r.json")
        specs = [("alpha", "/nowhere/a"), ("beta", "/nowhere/b")]
        real_replace = os.replace
        calls = []

        def replace(source, target):
            calls.append(target)
            if len(calls) > 1:  # the constructor's write succeeds, the next fails
                raise PermissionError("read-only")
            return real_replace(source, target)

        validated = ("herdr", "split", specs, set(), {}, {"surface": "w:p1"})
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(spawn, "validate", return_value=validated), \
                mock.patch.object(spawn, "live_records", return_value=[]), \
                mock.patch.object(spawn, "build_layout") as build, \
                mock.patch.object(receipts.os, "replace", side_effect=replace), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = spawn.main(["--json", "--receipt", path, "alpha:/nowhere/a",
                               "beta:/nowhere/b"])
        self.assertEqual(code, 3, err.getvalue())
        build.assert_not_called()
        receipt = json.loads(out.getvalue())
        self.assertEqual([s["name"] for s in receipt["sessions"]], ["alpha", "beta"])
        self.assertIn("cannot write receipt", receipt["persistence_error"])
        self.assertEqual(receipt["status"], "failed")


class StopKeepsTheBackendFailure(unittest.TestCase):
    def test_receipt_write_failure_inside_stop_keeps_the_backend_error(self):
        directory = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(directory))
        receipt = receipts.LaunchReceipt("herdr", "claude", "split",
                                         path=os.path.join(directory, "r.json"))
        receipt.add_session("alpha", "/tmp/a", False)
        receipt.add_resource("pane", "w:p2", "herdr pane split", session="alpha")
        error = spawn.BackendError("herdr", ["agent", "start", "alpha"], "approval UI",
                                   "agent_not_ready", "blocked", 1)
        error.session = "alpha"
        plan = {"layout": None, "placement": "split", "backend": "herdr",
                "specs": [("alpha", "/tmp/a")], "before": set()}
        args = mock.Mock(json=True)
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(receipts.os, "replace", side_effect=PermissionError("ro")), \
                mock.patch.object(spawn, "live_records", return_value=[]), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = spawn.stop(receipt, error, plan, args)
        self.assertEqual(code, 3)
        printed = json.loads(out.getvalue())
        self.assertEqual(printed["failure"]["code"], "agent_not_ready")
        self.assertEqual(printed["failure"]["outcome"], "blocked")
        self.assertIn("cannot write receipt", printed["persistence_error"])
        self.assertIn("note: cannot write receipt", err.getvalue())


if __name__ == "__main__":
    unittest.main()
