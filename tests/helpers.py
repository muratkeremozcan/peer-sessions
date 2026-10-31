"""Shared fixtures: a temp PATH holding fake herdr/cmux, and temp Claude dirs.

PATH is reduced to the fake bin directory plus /usr/bin:/bin, so a real herdr
or cmux installed elsewhere (e.g. /opt/homebrew/bin) can never be reached.
"""

import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
SPAWN = os.path.join(SCRIPTS, "spawn-fleet.py")
INBOX = os.path.join(SCRIPTS, "peer-inbox.py")
FAKEBIN = os.path.join(ROOT, "tests", "fakes", "fakebin.py")
READ_ONLY = (["agent", "get"], ["identify"], ["tree", "--all"])


def load_script(name, filename):
    """Import a hyphenated script as a module, for unit-level checks."""
    if SCRIPTS not in sys.path:
        sys.path.insert(0, SCRIPTS)
    spec = importlib.util.spec_from_file_location(name, os.path.join(SCRIPTS, filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FleetCase(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="peer-sessions-test-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.bin = os.path.join(self.root, "bin")
        self.state = os.path.join(self.root, "state")
        self.sessions = os.path.join(self.root, "sessions")
        self.projects = os.path.join(self.root, "projects")
        self.work = os.path.join(self.root, "work")
        for directory in (self.bin, self.state, self.sessions, self.projects, self.work):
            os.makedirs(directory)
        # AF_UNIX paths are short on macOS; keep the socket under /tmp.
        self.sock_dir = tempfile.mkdtemp(prefix="ps-", dir="/tmp")
        self.addCleanup(shutil.rmtree, self.sock_dir, ignore_errors=True)
        self.socket_path = os.path.join(self.sock_dir, "s.sock")
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(self.socket_path)
        self.server.listen(64)
        self.addCleanup(self.server.close)
        self.scenario = {}

    # -- fakes -------------------------------------------------------------

    def install(self, *tools):
        for tool in tools:
            target = os.path.join(self.bin, tool)
            with open(target, "w") as handle:
                handle.write(
                    f"#!{sys.executable}\n"
                    "import os, runpy\n"
                    f"os.environ['FAKE_TOOL'] = {tool!r}\n"
                    f"runpy.run_path({FAKEBIN!r}, run_name='__main__')\n"
                )
            os.chmod(target, 0o755)

    def set_scenario(self, **scenario):
        self.scenario.update(scenario)
        with open(os.path.join(self.state, "scenario.json"), "w") as handle:
            json.dump(self.scenario, handle)

    def env(self, herdr_env=True, extra=None):
        env = {
            "PATH": f"{self.bin}{os.pathsep}/usr/bin{os.pathsep}/bin",
            "HOME": self.root,
            "FAKE_STATE": self.state,
            "FAKE_PID": str(os.getpid()),
            "FAKE_SOCKET": self.socket_path,
            "CLAUDE_SESSIONS_DIR": self.sessions,
            "CLAUDE_PROJECTS_DIR": self.projects,
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        if herdr_env:
            env.update({"HERDR_ENV": "1", "HERDR_PANE_ID": "wT:p1", "HERDR_WORKSPACE_ID": "wT"})
        env.update(extra or {})
        return env

    def spawn(self, *args, herdr_env=True, extra=None, timeout=60):
        return subprocess.run(
            [sys.executable, SPAWN, *args],
            env=self.env(herdr_env, extra),
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    def calls(self):
        try:
            with open(os.path.join(self.state, "calls.jsonl")) as handle:
                return [json.loads(line) for line in handle]
        except OSError:
            return []

    def mutating_calls(self):
        found = []
        for call in self.calls():
            argv = call[1:]
            if argv[:2] == ["--id-format", "both"]:
                argv = argv[2:]
            if any(argv[: len(prefix)] == prefix for prefix in READ_ONLY):
                continue
            found.append(call)
        return found

    def calls_matching(self, tool, *prefix):
        return [
            call
            for call in self.calls()
            if call[0] == tool and call[1 : 1 + len(prefix)] == list(prefix)
        ]

    def write_registry(self, name, pid, cwd, session_id="pre-existing"):
        with open(os.path.join(self.sessions, f"{session_id}.json"), "w") as handle:
            json.dump(
                {
                    "pid": pid,
                    "sessionId": session_id,
                    "procStart": "pre",
                    "name": name,
                    "cwd": cwd,
                    "messagingSocketPath": self.socket_path,
                },
                handle,
            )

    def dir(self, *parts):
        return os.path.join(self.work, *parts)
