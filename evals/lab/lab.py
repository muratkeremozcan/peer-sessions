#!/usr/bin/env python3
"""Fake herdr/cmux lab for the peer-sessions evaluation.

Use `lab.py start` to print a run-specific PATH. Stop that run with the
directory above its bin, for example `lab.py stop "${LAB_PATH%%/bin:*}"`.
Fake state stays in the trial cwd and follows CLAUDE_SESSIONS_DIR.

The run's `claude` starts under Seatbelt with reads and writes of the
held-out state directory denied (see `prepare_held_out.py`), so the agent and
every process it starts cannot open held-out material even with TeA's
confinement off. `lab.py withhold-check FILE` proves that from the export.
"""
import argparse
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import secrets
import selectors
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tarfile
import tempfile
import threading
import time

SCRIPT = Path(__file__).resolve()
REPO = SCRIPT.parents[2]
FAKEBIN = REPO / "tests" / "fakes" / "fakebin.py"
SYSTEM_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
RUN_PREFIX = "pslab-"
CONTROL_FILE = "control.sock"
SOCK_FILE = "s.sock"
TOKEN_FILE = "token"
START_TIMEOUT = 5
CONTROL_TIMEOUT = 0.25
RUN_TIMEOUT = 6 * 3600
SANDBOX_EXEC = "/usr/bin/sandbox-exec"
PROFILE_FILE = "withhold.sb"
STATE = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state") / "peer-sessions-eval"
TARGET_PATHS = ("LICENSE", "README.md", "SKILL.md", "docs", "examples", "references", "schemas", "scripts", "tests")

WRAPPER = '''#!/usr/bin/python3
import os, runpy
sessions = os.path.abspath(os.environ.get("CLAUDE_SESSIONS_DIR", ".peer-lab/sessions"))
lab = os.path.dirname(sessions)
state = os.path.join(lab, "state")
for d in (sessions, state, os.path.join(lab, "projects")):
    os.makedirs(d, exist_ok=True)
os.environ["CLAUDE_SESSIONS_DIR"] = sessions
os.environ.setdefault("FAKE_STATE", state)
with open({pidfile!r}) as handle:
    os.environ["FAKE_PID"] = handle.read().strip()
os.environ["FAKE_SOCKET"] = {sock!r}
os.environ["FAKE_TOOL"] = {tool!r}
runpy.run_path({fakebin!r}, run_name="__main__")
'''


CLAUDE_WRAPPER = """#!/bin/sh
exec {sandbox} -f {profile} {claude} "$@"
"""


def withhold_profile():
    """Seatbelt profile that allows everything except the held-out state directory."""
    paths = {str(STATE), os.path.realpath(STATE)}
    rules = " ".join(f'(subpath "{path}")' for path in sorted(paths))
    return f"(version 1)\n(allow default)\n(deny file-read* file-write* {rules})\n"


def run_path(run):
    return f"{run / 'bin'}:{SYSTEM_PATH}"


def unix_socket(path):
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        listener.bind(str(path))
        listener.listen(64)
    except OSError:
        listener.close()
        raise
    return listener


def serve(run):
    # Only the starter owns a child handle. Detached runs use their control socket.
    for signum in (signal.SIGINT, signal.SIGHUP, signal.SIGTERM):
        signal.signal(signum, signal.SIG_IGN)
    token = (run / TOKEN_FILE).read_bytes()
    deadline = time.monotonic() + RUN_TIMEOUT
    with unix_socket(run / SOCK_FILE) as fake, unix_socket(run / CONTROL_FILE) as control, selectors.DefaultSelector() as selector:
        selector.register(fake, selectors.EVENT_READ)
        selector.register(control, selectors.EVENT_READ)
        (run / "pid").write_text(str(os.getpid()))
        while (remaining := deadline - time.monotonic()) > 0:
            for key, _ in selector.select(remaining):
                conn, _ = key.fileobj.accept()
                with conn:
                    if key.fileobj is fake:
                        continue
                    conn.settimeout(CONTROL_TIMEOUT)
                    try:
                        with conn.makefile("rb") as stream:
                            request = stream.readline(128)
                        command, _, secret = request.rstrip(b"\n").partition(b" ")
                        if not hmac.compare_digest(secret, token):
                            continue
                        if command == b"stop":
                            # Close the fake endpoint before acknowledging shutdown.
                            selector.unregister(fake)
                            fake.close()
                            conn.sendall(b"stopped\n")
                            return
                        if command == b"ready":
                            conn.sendall(f"ready {os.getpid()}\n".encode())
                    except OSError:
                        continue


def request(run, command):
    token = (run / TOKEN_FILE).read_bytes()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(CONTROL_TIMEOUT)
        client.connect(str(run / CONTROL_FILE))
        client.sendall(command + b" " + token + b"\n")
        with client.makefile("rb") as stream:
            return stream.readline(128)


def start():
    run = Path(tempfile.mkdtemp(prefix=RUN_PREFIX, dir="/tmp"))
    server = None
    ready = False
    try:
        bindir = run / "bin"
        bindir.mkdir()
        (run / TOKEN_FILE).write_text(secrets.token_hex(32))
        for tool in ("herdr", "cmux"):
            wrapper = bindir / tool
            wrapper.write_text(WRAPPER.format(
                pidfile=str(run / "pid"), sock=str(run / SOCK_FILE), tool=tool, fakebin=str(FAKEBIN),
            ))
            wrapper.chmod(0o755)
        for tool in ("claude", "node", "npm", "npx"):
            real = shutil.which(tool)
            if real is None:
                raise RuntimeError(f"{tool} not found on PATH")
            if tool == "claude":
                if not os.access(SANDBOX_EXEC, os.X_OK):
                    raise RuntimeError(f"{SANDBOX_EXEC} is required to withhold {STATE}")
                # Homebrew can delete the versioned executable during a run.
                shutil.copy2(os.path.realpath(real), bindir / ".claude-bin")
                (run / PROFILE_FILE).write_text(withhold_profile())
                (bindir / tool).write_text(CLAUDE_WRAPPER.format(
                    sandbox=SANDBOX_EXEC, profile=run / PROFILE_FILE, claude=bindir / ".claude-bin",
                ))
                (bindir / tool).chmod(0o755)
            else:
                (bindir / tool).symlink_to(real)
        server = subprocess.Popen(
            [sys.executable, str(SCRIPT), "serve", str(run)], start_new_session=True,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + START_TIMEOUT
        while server.poll() is None and time.monotonic() < deadline:
            try:
                ready = request(run, b"ready") == f"ready {server.pid}\n".encode()
            except OSError:
                pass
            if ready:
                threading.Thread(target=server.wait, daemon=True).start()
                return run
            time.sleep(0.05)
        raise RuntimeError("server did not become ready")
    finally:
        if not ready:
            if server is not None:
                server.kill()
                server.wait()
            shutil.rmtree(run)


def stop(run):
    root = Path("/tmp").resolve()
    if run.parent.resolve() != root or not run.name.startswith(RUN_PREFIX):
        raise ValueError("expected a per-run lab directory")
    info = run.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError("expected an owned private lab directory")
    if request(run, b"stop") != b"stopped\n":
        raise RuntimeError("lab did not confirm shutdown")
    shutil.rmtree(run)


def withhold_check(target, cwd):
    """Read TARGET from CWD inside the run's sandbox: exit 0 only when the read is refused."""
    run = start()
    try:
        probe = "import sys\ntry:\n    open(sys.argv[1], 'rb').read(1)\nexcept PermissionError as e:\n    print('refused:', e); sys.exit(0)\nprint('readable'); sys.exit(1)\n"
        result = subprocess.run(
            [SANDBOX_EXEC, "-f", str(run / PROFILE_FILE), "/usr/bin/python3", "-c", probe, str(target)],
            cwd=cwd, env={"PATH": run_path(run), "HOME": os.environ["HOME"]}, capture_output=True, text=True,
        )
        unconfined = subprocess.run(["/usr/bin/python3", "-c", probe, str(target)], cwd=cwd, capture_output=True, text=True)
    finally:
        stop(run)
    print(f"lab sandbox: {result.stdout.strip() or result.stderr.strip()}")
    print(f"outside the lab: {unconfined.stdout.strip() or unconfined.stderr.strip()}")
    return result.returncode


def tree_digest(root):
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            entry = [relative, "link", os.readlink(path)]
        elif path.is_file():
            mode = "executable" if path.stat().st_mode & 0o111 else "regular"
            entry = [relative, mode, hashlib.sha256(path.read_bytes()).hexdigest()]
        else:
            continue
        digest.update((json.dumps(entry) + "\n").encode())
    return digest.hexdigest()


def sync_root(revision, root):
    """Export only the committed skill and record the exact archive used."""
    head = subprocess.check_output(
        ["git", "-C", REPO, "rev-parse", "--verify", "--end-of-options", revision + "^{commit}"],
        text=True,
    ).strip()
    archive = subprocess.check_output([
        "git", "-C", REPO, "archive", "--format=tar", "--prefix=peer-sessions/", head, "--", *TARGET_PATHS,
    ])
    stamp = {"commit": head, "archiveSha256": hashlib.sha256(archive).hexdigest()}
    target = root / "peer-sessions"
    # Preserve an existing Git checkout until the operator moves it out of the launch root.
    if (target / ".git").exists():
        raise ValueError(f"move the old Git checkout at {target} aside before exporting here")
    root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".peer-export-", dir=root.parent) as work:
        staging = Path(work) / "new"
        staging.mkdir()
        with tarfile.open(fileobj=io.BytesIO(archive)) as source:
            source.extractall(staging, filter="data")
        stamp["treeSha256"] = tree_digest(staging / "peer-sessions")
        (staging / "target-revision.json").write_text(json.dumps(stamp, indent=2) + "\n")
        backup = Path(work) / "previous"
        if root.exists():
            if not (root / "target-revision.json").is_file():
                raise ValueError(f"expected an empty or previously exported launch root at {root}")
            root.rename(backup)
        try:
            staging.rename(root)
        except OSError:
            if backup.exists():
                backup.rename(root)
            raise
    print(f"root at {head}, tree sha256:{stamp['treeSha256']}")



def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("start")
    sync = commands.add_parser("sync-root")
    sync.add_argument("revision", nargs="?", default="HEAD")
    sync.add_argument("--root", type=Path, default=REPO / "evals" / "root")
    check = commands.add_parser("withhold-check")
    check.add_argument("target", type=Path)
    check.add_argument("--cwd", type=Path, default=REPO / "evals" / "root" / "peer-sessions")
    for command in ("stop", "serve"):
        commands.add_parser(command).add_argument("run", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "start":
            print(run_path(start()))
        elif args.command == "stop":
            stop(args.run)
        elif args.command == "serve":
            serve(args.run)
        elif args.command == "withhold-check":
            sys.exit(withhold_check(args.target, args.cwd))
        else:
            sync_root(args.revision, args.root)
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"lab: {error}\n")


if __name__ == "__main__":
    main()
