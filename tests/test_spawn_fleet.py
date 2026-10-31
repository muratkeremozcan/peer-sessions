"""spawn-fleet.py against fake cmux/herdr: validation, selection, receipts."""

import json
import os
import subprocess
import unittest

from helpers import FleetCase
from schema_check import errors, load_schema

SCHEMA = load_schema()


def receipt_from(result):
    """Parse a --json receipt and hold it to the published schema."""
    receipt = json.loads(result.stdout)
    problems = errors(receipt, SCHEMA)
    assert not problems, problems
    return receipt


class InvalidInputCreatesNothing(FleetCase):
    def assert_rejected(self, result, fragment):
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn(fragment, result.stderr)
        self.assertEqual(self.mutating_calls(), [])
        self.assertEqual(os.listdir(self.work), [])
        self.assertFalse(os.path.exists(os.path.join(self.root, "receipt.json")))

    def spawn_herdr(self, *args):
        self.install("herdr")
        return self.spawn(*args, "--receipt", os.path.join(self.root, "receipt.json"))

    def test_duplicate_names_create_no_directories(self):
        result = self.spawn_herdr(f"alpha:{self.dir('a')}", f"alpha:{self.dir('b')}")
        self.assert_rejected(result, "duplicate session names: alpha")

    def test_names_that_normalize_to_the_same_label_are_duplicates(self):
        self.install("cmux")
        result = self.spawn(f"a  b:{self.dir('a')}", f"a b:{self.dir('b')}", herdr_env=False)
        self.assert_rejected(result, "duplicate session names: a b")

    def test_invalid_herdr_name(self):
        result = self.spawn_herdr(f"Alpha One:{self.dir('a')}")
        self.assert_rejected(result, "not a valid herdr agent name")

    def test_missing_directory_with_dirs_existing(self):
        result = self.spawn_herdr("--dirs", "existing", f"alpha:{self.dir('nope')}")
        self.assert_rejected(result, "does not exist (--dirs existing)")

    def test_file_in_place_of_directory(self):
        self.install("herdr")
        blocker = os.path.join(self.root, "a-file")
        open(blocker, "w").close()
        result = self.spawn(f"alpha:{blocker}", f"beta:{self.dir('b')}")
        self.assertEqual(result.returncode, 2)
        self.assertIn("is not a directory", result.stderr)
        self.assertEqual(self.mutating_calls(), [])
        self.assertFalse(os.path.exists(self.dir("b")))

    def test_codex_on_cmux_is_refused_and_never_becomes_claude(self):
        self.install("cmux")
        result = self.spawn("--runtime", "codex", f"alpha:{self.dir('a')}", herdr_env=False)
        self.assert_rejected(result, "--runtime codex needs the herdr backend")

    def test_claude_flags_refused_for_codex(self):
        result = self.spawn_herdr(
            "--runtime", "codex", "--claude-arg=--verbose", f"alpha:{self.dir('a')}"
        )
        self.assert_rejected(result, "--claude-arg is for the claude runtime")

    def test_permission_mode_refused_for_codex(self):
        result = self.spawn_herdr(
            "--runtime", "codex", "--permission-mode", "auto", f"alpha:{self.dir('a')}"
        )
        self.assert_rejected(result, "--permission-mode is a claude flag")

    def test_codex_flags_refused_for_claude(self):
        result = self.spawn_herdr("--codex-arg=--foo", f"alpha:{self.dir('a')}")
        self.assert_rejected(result, "--codex-arg is for the codex runtime")

    def test_window_placement_on_herdr(self):
        result = self.spawn_herdr("--placement", "window", f"alpha:{self.dir('a')}")
        self.assert_rejected(result, "--placement window has no herdr equivalent")

    def test_unsupported_direction_on_herdr(self):
        result = self.spawn_herdr("--direction", "left", f"alpha:{self.dir('a')}")
        self.assert_rejected(result, "herdr only supports --direction right or down")

    def test_split_outside_a_herdr_pane(self):
        self.install("herdr")
        result = self.spawn(
            "--placement", "split", f"alpha:{self.dir('a')}",
            extra={"HERDR_PANE_ID": ""},
        )
        self.assert_rejected(result, "--placement split needs to run inside a herdr pane")

    def test_split_outside_cmux(self):
        self.install("cmux")
        result = self.spawn("--placement", "split", f"alpha:{self.dir('a')}", herdr_env=False)
        self.assert_rejected(result, "--placement split needs a cmux terminal")

    def test_herdr_backend_outside_herdr(self):
        self.install("herdr")
        result = self.spawn("--backend", "herdr", f"alpha:{self.dir('a')}", herdr_env=False)
        self.assert_rejected(result, "must run inside a herdr pane")

    def test_explicit_backend_missing_from_path(self):
        self.install("herdr")
        result = self.spawn("--backend", "cmux", f"alpha:{self.dir('a')}")
        self.assert_rejected(result, "--backend cmux: 'cmux' is not on PATH")

    def test_name_already_live_in_herdr(self):
        self.set_scenario(agents={"alpha": {"agent": "claude", "pane_id": "wX:p3"}})
        result = self.spawn_herdr(f"alpha:{self.dir('a')}")
        self.assert_rejected(result, "a live herdr agent is already named 'alpha'")

    def test_bad_correlation_field(self):
        result = self.spawn_herdr("--correlate", "run id=7", f"alpha:{self.dir('a')}")
        self.assert_rejected(result, "--correlate expects KEY=VALUE")

    def test_empty_directory(self):
        result = self.spawn_herdr("alpha:")
        self.assert_rejected(result, "has an empty directory")


class BackendSelection(FleetCase):
    def setUp(self):
        super().setUp()
        self.install("herdr", "cmux")
        self.set_scenario(caller={"workspace_id": "W", "surface_id": "S", "window_id": "X"})

    def tools_used(self):
        return {call[0] for call in self.mutating_calls()}

    def test_explicit_cmux_wins_inside_herdr(self):
        result = self.spawn("--backend", "cmux", "--timeout", "5", f"alpha:{self.dir('a')}")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.tools_used(), {"cmux"})

    def test_auto_prefers_the_herdr_pane_it_runs_in(self):
        result = self.spawn("--timeout", "5", f"alpha:{self.dir('a')}")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.tools_used(), {"herdr"})

    def test_auto_outside_herdr_keeps_cmux_first(self):
        result = self.spawn("--timeout", "5", f"alpha:{self.dir('a')}", herdr_env=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.tools_used(), {"cmux"})


class RuntimeArguments(FleetCase):
    def setUp(self):
        super().setUp()
        self.install("herdr")

    def start_args(self, name):
        (call,) = self.calls_matching("herdr", "agent", "start", name)
        return call[1:]

    def test_codex_receives_no_claude_flags(self):
        result = self.spawn(
            "--runtime", "codex", "--model", "gpt-5.5", "--codex-arg=--search",
            "--timeout", "5", f"rev:{self.dir('a')}",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        args = self.start_args("rev")
        self.assertEqual(args[args.index("--kind") + 1], "codex")
        self.assertEqual(args[args.index("--") + 1 :], ["--search", "--model", "gpt-5.5"])
        for claude_only in ("--name", "--permission-mode", "claude"):
            self.assertNotIn(claude_only, args[args.index("--") :])

    def test_codex_without_native_args_passes_no_separator(self):
        result = self.spawn("--runtime", "codex", "--timeout", "5", f"rev:{self.dir('a')}")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("--", self.start_args("rev"))

    def test_claude_on_herdr_keeps_its_flags(self):
        result = self.spawn("--model", "opus", "--timeout", "5", f"impl:{self.dir('a')}")
        self.assertEqual(result.returncode, 0, result.stderr)
        args = self.start_args("impl")
        self.assertEqual(args[args.index("--kind") + 1], "claude")
        self.assertEqual(
            args[args.index("--") + 1 :],
            ["--name", "impl", "--permission-mode", "auto", "--model", "opus"],
        )


class PathsWithSpaces(FleetCase):
    def test_herdr_cwd_survives_verbatim(self):
        self.install("herdr")
        directory = self.dir("with space", "and 'quote'")
        result = self.spawn("--placement", "split", "--timeout", "5", f"alpha:{directory}")
        self.assertEqual(result.returncode, 0, result.stderr)
        (split,) = self.calls_matching("herdr", "pane", "split")
        self.assertEqual(split[split.index("--cwd") + 1], directory)
        self.assertTrue(os.path.isdir(directory))

    def test_cmux_launch_command_quotes_the_directory(self):
        self.install("cmux")
        self.set_scenario(caller={"workspace_id": "W", "surface_id": "S"})
        directory = self.dir("with space")
        result = self.spawn(
            "--placement", "split", "--timeout", "5", f"alpha:{directory}", herdr_env=False
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        (send,) = self.calls_matching("cmux", "--id-format", "both", "send")
        self.assertTrue(send[-1].startswith(f"cd '{directory}' && claude --name alpha"))


class PartialLaunchInventory(FleetCase):
    def test_second_herdr_start_fails_after_two_panes_exist(self):
        self.install("herdr")
        self.set_scenario(
            rules=[
                {
                    "tool": "herdr",
                    "match": ["agent", "start", "second"],
                    "stderr": json.dumps(
                        {"error": {"code": "agent_start_failed", "message": "exec failed"}}
                    ),
                }
            ]
        )
        receipt_path = os.path.join(self.root, "receipt.json")
        result = self.spawn(
            "--placement", "split", "--receipt", receipt_path, "--json",
            "--correlate", "run_id=r7", "--correlate", "generation=3",
            f"first:{self.dir('a')}", f"second:{self.dir('b')}",
        )
        self.assertEqual(result.returncode, 3, result.stderr)
        receipt = receipt_from(result)
        with open(receipt_path) as handle:
            self.assertEqual(json.load(handle), receipt)

        self.assertEqual(receipt["status"], "partial")
        self.assertEqual(receipt["correlation"], {"run_id": "r7", "generation": "3"})
        panes = [(r["id"], r["session"]) for r in receipt["resources"] if r["kind"] == "pane"]
        self.assertEqual(panes, [("wT:p2", "first"), ("wT:p3", "second")])
        states = {s["name"]: s["state"] for s in receipt["sessions"]}
        self.assertEqual(states, {"first": "started", "second": "failed"})
        self.assertTrue(all(s["directory_created"] for s in receipt["sessions"]))
        failure = receipt["failure"]
        self.assertEqual(failure["session"], "second")
        self.assertEqual(failure["code"], "agent_start_failed")
        self.assertEqual(failure["outcome"], "failed")
        self.assertEqual(failure["command"][:3], ["agent", "start", "second"])
        self.assertEqual(receipt["contract"]["status"], "pending")

        # Retained, not rolled back; the teardown names exactly the two panes.
        self.assertEqual(self.calls_matching("herdr", "pane", "close"), [])
        self.assertIn("herdr pane close wT:p2", result.stderr)
        self.assertIn("herdr pane close wT:p3", result.stderr)
        self.assertNotIn("wT:p1", result.stderr.split("Created before the failure")[1])

    def test_second_herdr_workspace_fails(self):
        self.install("herdr")
        self.set_scenario(
            rules=[
                {
                    "tool": "herdr",
                    "match": ["workspace", "create", "--label", "fleet-2"],
                    "stderr": json.dumps({"error": {"code": "workspace_create_failed",
                                                    "message": "no"}}),
                }
            ]
        )
        result = self.spawn(
            "--per-workspace", "1", "--json",
            f"first:{self.dir('a')}", f"second:{self.dir('b')}",
        )
        self.assertEqual(result.returncode, 3, result.stderr)
        receipt = receipt_from(result)
        kinds = [(r["kind"], r["id"]) for r in receipt["resources"]]
        self.assertEqual(
            kinds,
            [("directory", self.dir("a")), ("directory", self.dir("b")),
             ("workspace", "wF1"), ("pane", "wF1:p1")],
        )
        self.assertIn("herdr workspace close wF1", result.stderr)
        self.assertEqual(self.calls_matching("herdr", "workspace", "close"), [])

    def test_second_cmux_split_fails_inside_a_workspace(self):
        self.install("cmux")
        self.set_scenario(
            rules=[{"tool": "cmux", "match": ["new-split"], "stdout": "Error: pane limit"}]
        )
        result = self.spawn("--json", f"first:{self.dir('a')}", f"second:{self.dir('b')}",
                            herdr_env=False)
        self.assertEqual(result.returncode, 3, result.stderr)
        receipt = receipt_from(result)
        workspaces = [r for r in receipt["resources"] if r["kind"] == "workspace"]
        self.assertEqual(len(workspaces), 1)
        self.assertEqual(workspaces[0]["ref"], "workspace:1")
        self.assertEqual(workspaces[0]["id"], "00000000-0000-0000-0000-0000000003e9")
        states = {s["name"]: s["state"] for s in receipt["sessions"]}
        self.assertEqual(states, {"first": "start_requested", "second": "failed"})
        # The first session registered; its PID is bound by identity, not name.
        first = receipt["sessions"][0]["identity"]
        self.assertEqual(first["pid"], os.getpid())
        self.assertIn(f"cmux close-workspace --workspace {workspaces[0]['id']}", result.stderr)


class DirectoryFailure(FleetCase):
    def test_unwritable_parent_is_a_denied_partial_launch(self):
        self.install("herdr")
        locked = os.path.join(self.root, "locked")
        os.makedirs(locked)
        os.chmod(locked, 0o500)
        self.addCleanup(os.chmod, locked, 0o700)
        if os.access(locked, os.W_OK):
            self.skipTest("running with privileges that ignore directory modes")
        result = self.spawn("--json", f"first:{self.dir('a')}",
                            f"second:{os.path.join(locked, 'b')}")
        self.assertEqual(result.returncode, 3, result.stderr)
        receipt = receipt_from(result)
        self.assertEqual(receipt["failure"]["backend"], "filesystem")
        self.assertEqual(receipt["failure"]["outcome"], "denied")
        self.assertEqual([r["id"] for r in receipt["resources"]], [self.dir("a")])
        self.assertEqual(self.mutating_calls(), [])


class StartupFailureKinds(FleetCase):
    def setUp(self):
        super().setUp()
        self.install("herdr")

    def run_with(self, rule, *extra):
        self.set_scenario(rules=[dict(tool="herdr", match=["agent", "start"], **rule)])
        return self.spawn("--placement", "split", "--json", "--timeout", "5", *extra,
                          f"alpha:{self.dir('a')}")

    def starts(self):
        return self.calls_matching("herdr", "agent", "start")

    def envelope(self, code, message="x"):
        return json.dumps({"error": {"code": code, "message": message}})

    def test_pane_busy_is_retried_then_succeeds(self):
        result = self.run_with({"stderr": self.envelope("agent_pane_busy"), "times": 2})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.starts()), 3)
        self.assertEqual(receipt_from(result)["sessions"][0]["state"], "ready")

    def test_blocked_startup_is_not_retried(self):
        result = self.run_with({
            "stderr": self.envelope("agent_not_ready", "approval UI"), "leave_agent": "blocked",
        })
        self.assertEqual(result.returncode, 1)
        self.assertEqual(len(self.starts()), 1)
        receipt = receipt_from(result)
        self.assertEqual(receipt["status"], "incomplete")
        self.assertIsNone(receipt["failure"])
        session = receipt["sessions"][0]
        self.assertEqual(session["state"], "blocked")
        self.assertEqual(session["readiness_error"]["code"], "agent_not_ready")
        self.assertIn("ask the user", result.stderr)

    def test_blocked_startup_does_not_stop_the_other_sessions(self):
        # Claude's folder-trust question blocks a fresh directory at start.
        self.set_scenario(rules=[{
            "tool": "herdr", "match": ["agent", "start", "alpha"],
            "stderr": self.envelope("agent_not_ready", "Do you trust this folder?"), "exit": 1,
            "leave_agent": "blocked",
        }])
        result = self.spawn(
            "--placement", "workspace", "--per-workspace", "1", "--json", "--timeout", "30",
            f"alpha:{self.dir('a')}", f"beta:{self.dir('b')}", f"gamma:{self.dir('c')}",
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(len(self.starts()), 3)
        receipt = receipt_from(result)
        states = {entry["name"]: entry["state"] for entry in receipt["sessions"]}
        self.assertEqual(states, {"alpha": "blocked", "beta": "ready", "gamma": "ready"})
        self.assertEqual(receipt["status"], "incomplete")
        self.assertEqual(len([r for r in receipt["resources"] if r["kind"] == "pane"]), 3)
        self.assertIn("! alpha", result.stderr)
        for workspace in [r["id"] for r in receipt["resources"] if r["kind"] == "workspace"]:
            self.assertIn(f"herdr workspace close {workspace}", result.stderr)

    def test_agent_gone_after_a_blocked_start_is_not_reported_blocked(self):
        # The user stopped it, so herdr dropped the name: no prompt waits anymore.
        result = self.run_with({"stderr": self.envelope("agent_not_ready", "approval UI")})
        self.assertEqual(result.returncode, 1)
        session = receipt_from(result)["sessions"][0]
        self.assertEqual(session["state"], "not_ready")
        self.assertEqual(session["readiness_error"]["code"], "agent_not_ready")
        self.assertNotIn("! alpha", result.stderr)

    def test_permission_denial_is_not_retried_or_routed_around(self):
        result = self.run_with({"stderr": self.envelope("permission_denied", "PermissionDenied")})
        self.assertEqual(result.returncode, 3)
        self.assertEqual(len(self.starts()), 1)
        receipt = receipt_from(result)
        self.assertEqual(receipt["failure"]["outcome"], "denied")
        self.assertEqual(receipt["sessions"][0]["state"], "denied")
        self.assertIn("do not route around it", result.stderr)

    def test_unparseable_answer_is_an_unknown_outcome(self):
        result = self.run_with({"stderr": "segmentation fault", "exit": 139})
        self.assertEqual(result.returncode, 3)
        self.assertEqual(len(self.starts()), 1)
        receipt = receipt_from(result)
        self.assertEqual(receipt["failure"]["outcome"], "unknown")
        self.assertEqual(receipt["sessions"][0]["state"], "unknown")
        self.assertIn("Inspect before retrying", result.stderr)

    def test_legacy_stdout_error_envelope_is_still_read(self):
        result = self.run_with({"stdout": self.envelope("agent_pane_busy"), "exit": 0,
                                "times": 1})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.starts()), 2)


class Readiness(FleetCase):
    def setUp(self):
        super().setUp()
        self.install("herdr")

    def test_blocked_after_start_is_reported_as_blocked(self):
        self.set_scenario(status={"alpha": "blocked"})
        result = self.spawn("--json", "--timeout", "30", f"alpha:{self.dir('a')}")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(receipt_from(result)["sessions"][0]["state"], "blocked")
        self.assertIn("! alpha", result.stderr)

    def test_name_reassigned_to_another_agent_is_not_ready(self):
        self.set_scenario(occupant={"alpha": {"terminal_id": "term_someone_else"}})
        result = self.spawn("--json", "--timeout", "1", f"alpha:{self.dir('a')}")
        self.assertEqual(result.returncode, 1)
        session = receipt_from(result)["sessions"][0]
        self.assertEqual(session["state"], "not_ready")
        self.assertEqual(session["identity"]["terminal_id"], "term_alpha")
        self.assertEqual(
            session["identity"]["observed_occupant"]["terminal_id"], "term_someone_else"
        )

    def test_wrong_kind_in_the_pane_is_not_ready(self):
        self.set_scenario(occupant={"rev": {"agent": "claude"}})
        result = self.spawn("--runtime", "codex", "--json", "--timeout", "1",
                            f"rev:{self.dir('a')}")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(receipt_from(result)["sessions"][0]["state"], "not_ready")

    def test_codex_without_interactive_ready_field_counts_when_idle(self):
        self.set_scenario(occupant={"rev": {"interactive_ready": None}})
        # occupant cannot delete keys; None mirrors herdr omitting the field.
        result = self.spawn("--runtime", "codex", "--json", "--timeout", "5",
                            f"rev:{self.dir('a')}")
        self.assertEqual(result.returncode, 0, result.stderr)


class OwnedCleanup(FleetCase):
    def test_herdr_teardown_names_only_this_launch(self):
        self.install("herdr")
        foreign = subprocess.Popen(["sleep", "30"])
        self.addCleanup(foreign.wait)
        self.addCleanup(foreign.kill)
        # A pre-existing session with the same name and directory.
        self.write_registry("alpha", foreign.pid, self.dir("a"))
        os.makedirs(self.dir("a"))
        result = self.spawn("--placement", "split", "--json", "--timeout", "5",
                            f"alpha:{self.dir('a')}")
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = receipt_from(result)
        identity = receipt["sessions"][0]["identity"]
        self.assertEqual(identity["pid"], os.getpid())
        self.assertNotEqual(identity["session_id"], "pre-existing")
        self.assertIn(f"kill {os.getpid()}", result.stderr)
        self.assertNotIn(str(foreign.pid), result.stderr)
        self.assertIn("herdr pane close wT:p2", result.stderr)
        self.assertNotIn("pane close wT:p1", result.stderr)
        self.assertEqual(
            [r["kind"] for r in receipt["resources"]], ["pane"],
            "an existing directory is not a created resource",
        )
        self.assertFalse(receipt["sessions"][0]["directory_created"])

    def test_cmux_split_teardown_never_closes_the_callers_surface(self):
        self.install("cmux")
        self.set_scenario(caller={"workspace_id": "W", "surface_id": "CALLER"})
        result = self.spawn("--placement", "split", "--timeout", "5",
                            f"alpha:{self.dir('a')}", f"beta:{self.dir('b')}",
                            herdr_env=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        closes = [line for line in result.stdout.splitlines() if "close-" in line]
        self.assertEqual(len(closes), 2)
        self.assertFalse(any("CALLER" in line for line in closes))
        self.assertFalse(any("close-workspace" in line for line in closes))


class ClaudeCompatibility(FleetCase):
    """The original cmux/Claude happy path keeps its commands and output."""

    def setUp(self):
        super().setUp()
        self.install("cmux")
        self.set_scenario(caller={"workspace_id": "W", "surface_id": "S", "window_id": "WIN"})

    def test_workspace_placement(self):
        result = self.spawn("--model", "opus", "--timeout", "5",
                            f"orbits:{self.dir('o')}", f"planets:{self.dir('p')}",
                            f"sun:{self.dir('s')}", herdr_env=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        creates = self.calls_matching("cmux", "--id-format", "both", "new-workspace")
        self.assertEqual(len(creates), 2)
        first = creates[0]
        self.assertEqual(
            first[first.index("--command") + 1],
            "claude --name orbits --permission-mode auto --model opus",
        )
        self.assertEqual(first[first.index("--window") + 1], "WIN")
        for name in ("orbits", "planets", "sun"):
            self.assertRegex(result.stdout, rf"\+ {name}\s+pid {os.getpid()}\s+uds:")
        self.assertIn("3 ready in", result.stdout)
        self.assertIn("Send with a uds: address above", result.stdout)
        self.assertEqual(len(self.calls_matching("cmux", "--id-format", "both",
                                                 "select-workspace")), 1)

    def test_window_placement_records_the_window(self):
        result = self.spawn("--window", "--json", "--timeout", "5",
                            f"orbits:{self.dir('o')}", herdr_env=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = receipt_from(result)
        self.assertEqual(receipt["resources"][1]["kind"], "window")
        self.assertIn("cmux close-window --window 00000000-0000-0000-0000-00000000270f",
                      result.stderr)

    def test_not_ready_keeps_exit_one_and_teardown(self):
        self.set_scenario(register=False)
        result = self.spawn("--timeout", "1", f"orbits:{self.dir('o')}", herdr_env=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("- orbits", result.stdout)
        self.assertIn("did not become ready in 1s", result.stdout)
        self.assertIn("0/1 ready", result.stderr)
        self.assertIn("cmux close-workspace", result.stdout)


class ReceiptPath(FleetCase):
    def test_missing_receipt_parent_creates_nothing(self):
        self.install("herdr")
        for receipt in (os.path.join(self.root, "nope", "r.json"),
                        os.path.join(self.dir("a"), "r.json")):
            with self.subTest(receipt=receipt):
                result = self.spawn("--receipt", receipt, f"alpha:{self.dir('a')}")
                self.assertEqual(result.returncode, 2)
                self.assertIn("the receipt never creates directories", result.stderr)
                self.assertEqual(os.listdir(self.work), [])
                self.assertEqual(self.mutating_calls(), [])

    def test_receipt_write_failure_keeps_the_inventory(self):
        self.install("herdr")
        receipts = os.path.join(self.root, "receipts")
        os.makedirs(receipts)
        self.addCleanup(os.chmod, receipts, 0o700)
        self.set_scenario(chmod={"match": ["pane", "split"], "path": receipts, "mode": 0o500})
        path = os.path.join(receipts, "r.json")
        result = self.spawn("--placement", "split", "--json", "--receipt", path,
                            f"alpha:{self.dir('a')}", f"beta:{self.dir('b')}")
        if os.access(receipts, os.W_OK):
            self.skipTest("running with privileges that ignore directory modes")
        self.assertEqual(result.returncode, 3, result.stderr)
        receipt = receipt_from(result)
        self.assertIn("cannot write receipt", receipt["persistence_error"])
        self.assertEqual(receipt["failure"]["backend"], "receipt")
        self.assertIn(("pane", "wT:p2"), [(r["kind"], r["id"]) for r in receipt["resources"]])
        self.assertEqual(self.calls_matching("herdr", "agent", "start"), [])
        self.assertIn("The receipt file is out of date", result.stderr)
        with open(path) as handle:
            stale = json.load(handle)
        self.assertNotIn("pane", [r["kind"] for r in stale["resources"]])


class AncestorValidation(FleetCase):
    def test_file_in_the_parent_chain_is_rejected_first(self):
        self.install("herdr")
        blocker = os.path.join(self.root, "a-file")
        open(blocker, "w").close()
        result = self.spawn(f"alpha:{self.dir('a')}", f"beta:{blocker}/child")
        self.assertEqual(result.returncode, 2)
        self.assertIn("is not a directory", result.stderr)
        self.assertEqual(os.listdir(self.work), [])
        self.assertEqual(self.mutating_calls(), [])


class RegistryBinding(FleetCase):
    def setUp(self):
        super().setUp()
        self.install("cmux")
        self.set_scenario(caller={"workspace_id": "W", "surface_id": "S"})

    def test_foreign_record_appearing_during_launch_is_never_bound(self):
        foreign = subprocess.Popen(["sleep", "30"])
        self.addCleanup(foreign.wait)
        self.addCleanup(foreign.kill)
        self.set_scenario(foreign={"name": "alpha", "cwd": "/other/project", "pid": foreign.pid})
        result = self.spawn("--json", "--timeout", "5", f"alpha:{self.dir('a')}",
                            herdr_env=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        identity = receipt_from(result)["sessions"][0]["identity"]
        self.assertEqual(identity["pid"], os.getpid())
        self.assertIn(f"kill {os.getpid()}", result.stderr)
        self.assertNotIn(str(foreign.pid), result.stderr)

    def test_two_matching_new_records_bind_nothing(self):
        self.set_scenario(register_twice=True)
        result = self.spawn("--json", "--timeout", "1", f"alpha:{self.dir('a')}",
                            herdr_env=False)
        self.assertEqual(result.returncode, 1)
        session = receipt_from(result)["sessions"][0]
        self.assertEqual(session["state"], "not_ready")
        self.assertEqual(session["identity"]["registry_candidates"], 2)
        self.assertNotIn("pid", session["identity"])
        self.assertNotIn("kill ", result.stderr)
        self.assertIn("2 new registry records match", result.stderr)


class UnresolvedCmuxRefs(FleetCase):
    def setUp(self):
        super().setUp()
        self.install("cmux")
        self.set_scenario(caller={"workspace_id": "W", "surface_id": "S"})

    def test_ref_the_tree_cannot_resolve_gets_a_note(self):
        self.set_scenario(rules=[{"tool": "cmux", "match": ["tree", "--all"], "stdout": "",
                                  "exit": 0, "times": 99}])
        result = self.spawn("--json", "--timeout", "5", f"alpha:{self.dir('a')}",
                            herdr_env=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        (workspace,) = [r for r in receipt_from(result)["resources"] if r["kind"] == "workspace"]
        self.assertEqual((workspace["id"], workspace["durable"]), ("workspace:1", False))
        self.assertNotIn("close-workspace --workspace workspace:1", result.stderr)
        self.assertIn("workspace workspace:1 has no durable id", result.stderr)

    def test_failed_tree_lookup_keeps_the_ref_as_non_durable(self):
        self.set_scenario(rules=[{"tool": "cmux", "match": ["tree", "--all"],
                                  "stdout": "Error: tree unavailable"}])
        result = self.spawn("--json", f"alpha:{self.dir('a')}", herdr_env=False)
        self.assertEqual(result.returncode, 3)
        receipt = receipt_from(result)
        (workspace,) = [r for r in receipt["resources"] if r["kind"] == "workspace"]
        self.assertFalse(workspace["durable"])
        self.assertEqual(receipt["failure"]["command"], ["tree", "--all"])
        self.assertNotIn("close-workspace", result.stdout)


class HerdrIdentityDrift(FleetCase):
    def setUp(self):
        super().setUp()
        self.install("herdr")

    def test_moved_pane_moves_the_close_target(self):
        self.set_scenario(occupant={"alpha": {"pane_id": "wOTHER:p9", "workspace_id": "wOTHER"}})
        result = self.spawn("--placement", "split", "--json", "--timeout", "5",
                            f"alpha:{self.dir('a')}")
        self.assertEqual(result.returncode, 0, result.stderr)
        (pane,) = [r for r in receipt_from(result)["resources"] if r["kind"] == "pane"]
        self.assertEqual((pane["id"], pane["moved_to"]), ("wT:p2", "wOTHER:p9"))
        self.assertIn("herdr pane close wOTHER:p9", result.stderr)
        self.assertNotIn("herdr pane close wT:p2", result.stderr)

    def test_pane_moved_out_of_its_workspace_is_closed_separately(self):
        self.set_scenario(occupant={"alpha": {"pane_id": "wOTHER:p9", "workspace_id": "wOTHER"}})
        result = self.spawn("--json", "--timeout", "5", f"alpha:{self.dir('a')}")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("herdr workspace close wF1", result.stderr)
        self.assertIn("herdr pane close wOTHER:p9", result.stderr)

    def test_reassigned_name_turns_the_close_into_a_note(self):
        self.set_scenario(occupant={"alpha": {"terminal_id": "term_someone_else"}})
        result = self.spawn("--placement", "split", "--timeout", "1", f"alpha:{self.dir('a')}")
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("herdr pane close wT:p2", result.stdout)
        self.assertIn("pane wT:p2: its agent name now labels a different agent", result.stdout)

    def test_denied_readiness_check_settles_as_denied(self):
        self.set_scenario(rules=[{
            "tool": "herdr", "match": ["agent", "get", "alpha"], "skip": 1, "times": 99,
            "stderr": json.dumps({"error": {"code": "forbidden", "message": "PermissionDenied"}}),
        }])
        result = self.spawn("--json", "--timeout", "60", f"alpha:{self.dir('a')}", timeout=30)
        self.assertEqual(result.returncode, 1)
        session = receipt_from(result)["sessions"][0]
        self.assertEqual(session["state"], "denied")
        self.assertEqual(session["readiness_error"]["outcome"], "denied")
        self.assertEqual(session["readiness_error"]["command"], ["agent", "get", "alpha"])
        self.assertLessEqual(len(self.calls_matching("herdr", "agent", "get", "alpha")), 3)
        self.assertIn("do not route around it", result.stderr)

    def test_unreadable_readiness_answer_settles_as_unknown(self):
        self.set_scenario(rules=[{
            "tool": "herdr", "match": ["agent", "get", "alpha"], "skip": 1, "times": 99,
            "stdout": '{"result": null}', "exit": 0,
        }])
        result = self.spawn("--json", "--timeout", "1", f"alpha:{self.dir('a')}")
        self.assertEqual(result.returncode, 1)
        session = receipt_from(result)["sessions"][0]
        self.assertEqual(session["state"], "unknown")
        self.assertEqual(session["readiness_error"]["code"], "unparsed_output")
        self.assertIn("Reconcile", result.stderr)

    def test_partial_workspace_payload_keeps_the_ids_it_has(self):
        payload = {"result": {"root_pane": {"pane_id": "wKNOWN:p1"},
                              "tab": {"tab_id": "wKNOWN:t1"}}}
        self.set_scenario(rules=[{"tool": "herdr", "match": ["workspace", "create"],
                                  "stdout": json.dumps(payload), "exit": 0}])
        result = self.spawn("--json", f"alpha:{self.dir('a')}")
        self.assertEqual(result.returncode, 3)
        receipt = receipt_from(result)
        self.assertEqual(receipt["status"], "partial")
        self.assertIn(("pane", "wKNOWN:p1"), [(r["kind"], r["id"]) for r in receipt["resources"]])
        self.assertEqual(receipt["failure"]["command"][:2], ["workspace", "create"])
        self.assertEqual(receipt["failure"]["outcome"], "unknown")
        self.assertIn("workspace.workspace_id", receipt["failure"]["message"])


class ReReviewRegressions(FleetCase):
    def test_ambiguity_after_first_ready_poll_unbinds_the_pid(self):
        self.install("cmux")
        self.set_scenario(
            caller={"workspace_id": "W", "surface_id": "S"},
            duplicate_on={"match": ["select-workspace"], "name": "alpha",
                          "cwd": self.dir("a")},
        )
        result = self.spawn("--json", "--timeout", "5", f"alpha:{self.dir('a')}",
                            herdr_env=False)
        self.assertEqual(result.returncode, 1, result.stderr)
        session = receipt_from(result)["sessions"][0]
        self.assertEqual(session["state"], "not_ready")
        self.assertEqual(session["identity"]["registry_candidates"], 2)
        self.assertNotIn("pid", session["identity"])
        self.assertNotIn("kill ", result.stderr)

    def test_blocked_moved_pane_moves_the_close_target(self):
        self.install("herdr")
        self.set_scenario(
            status={"alpha": "blocked"},
            occupant={"alpha": {"pane_id": "wOTHER:p9", "workspace_id": "wOTHER"}},
        )
        result = self.spawn("--placement", "split", "--timeout", "10",
                            f"alpha:{self.dir('a')}")
        self.assertEqual(result.returncode, 1)
        self.assertIn("herdr pane close wOTHER:p9", result.stdout)
        self.assertNotIn("herdr pane close wT:p2", result.stdout)

    def test_receipt_failure_during_workspace_create_keeps_both_ids(self):
        self.install("herdr")
        receipts = os.path.join(self.root, "receipts")
        os.makedirs(receipts)
        self.addCleanup(os.chmod, receipts, 0o700)
        self.set_scenario(chmod={"match": ["workspace", "create"], "path": receipts,
                                 "mode": 0o500})
        result = self.spawn("--json", "--receipt", os.path.join(receipts, "r.json"),
                            f"alpha:{self.dir('a')}")
        if os.access(receipts, os.W_OK):
            self.skipTest("running with privileges that ignore directory modes")
        self.assertEqual(result.returncode, 3, result.stderr)
        kinds = [(r["kind"], r["id"]) for r in receipt_from(result)["resources"]]
        self.assertIn(("workspace", "wF1"), kinds)
        self.assertIn(("pane", "wF1:p1"), kinds)

    def test_receipt_path_cannot_be_a_session_directory_or_its_parent(self):
        self.install("herdr")
        for receipt, spec in ((self.dir("a"), f"alpha:{self.dir('a')}"),
                              (self.dir("x"), f"alpha:{self.dir('x', 'y')}")):
            with self.subTest(receipt=receipt):
                result = self.spawn("--receipt", receipt, spec)
                self.assertEqual(result.returncode, 2)
                self.assertIn("put the receipt somewhere else", result.stderr)
                self.assertEqual(os.listdir(self.work), [])


if __name__ == "__main__":
    unittest.main()
