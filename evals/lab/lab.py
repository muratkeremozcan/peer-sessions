#!/usr/bin/env python3
"""Fake herdr/cmux lab for the peer-sessions evaluation.

Use `lab.py start` to print a run-specific PATH. Stop that run with the
directory above its bin, for example `lab.py stop "${LAB_PATH%%/bin:*}"`.
Fake state stays in the trial cwd and follows CLAUDE_SESSIONS_DIR.

A lab lives for `--hours` (6 by default) and then exits. Its fake peers use
the lab's own PID and socket, so they cannot outlive it, and every wrapper
refuses to run once it is gone. Start a fresh lab for each run and check it
first with `lab.py ready DIR --needs SECONDS`, which fails when the lab has
less time left than the run needs.

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
import shlex
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
# EX_UNAVAILABLE: a wrapper of a lab that has stopped.
LAB_GONE = 69
SANDBOX_EXEC = "/usr/bin/sandbox-exec"
PROFILE_FILE = "withhold.sb"
STATE = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state") / "peer-sessions-eval"
TARGET_PATHS = ("LICENSE", "README.md", "SKILL.md", "docs", "examples", "references", "schemas", "scripts", "tests")

WRAPPER = '''#!/usr/bin/python3
import os, runpy, socket, sys
# The fake peers register under the lab's PID and socket. Once the lab has
# stopped they read as dead, so refuse to run instead of misreporting them.
try:
    with open({pidfile!r}) as handle:
        lab_pid = int(handle.read().strip())
    os.kill(lab_pid, 0)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.25)
        probe.connect({sock!r})
except (OSError, ValueError):
    sys.stderr.write({stopped!r} + "\\n")
    sys.exit({gone})
sessions = os.path.abspath(os.environ.get("CLAUDE_SESSIONS_DIR", ".peer-lab/sessions"))
lab = os.path.dirname(sessions)
state = os.path.join(lab, "state")
for d in (sessions, state, os.path.join(lab, "projects")):
    os.makedirs(d, exist_ok=True)
os.environ["CLAUDE_SESSIONS_DIR"] = sessions
os.environ.setdefault("FAKE_STATE", state)
os.environ["FAKE_PID"] = str(lab_pid)
os.environ["FAKE_SOCKET"] = {sock!r}
os.environ["FAKE_TOOL"] = {tool!r}
runpy.run_path({fakebin!r}, run_name="__main__")
'''


CLAUDE_WRAPPER = """#!/bin/sh
if ! kill -0 "$(cat {pidfile} 2>/dev/null)" 2>/dev/null; then
    echo {stopped} >&2
    exit {gone}
fi
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


def serve(run, lifetime=RUN_TIMEOUT):
    # Only the starter owns a child handle. Detached runs use their control socket.
    for signum in (signal.SIGINT, signal.SIGHUP, signal.SIGTERM):
        signal.signal(signum, signal.SIG_IGN)
    token = (run / TOKEN_FILE).read_bytes()
    deadline = time.monotonic() + lifetime
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
                            left = max(0, int(deadline - time.monotonic()))
                            conn.sendall(f"ready {os.getpid()} {left}\n".encode())
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


def write_wrappers(run, claude=None):
    """The fake herdr and cmux wrappers, and the sandboxed claude when CLAUDE is a copied binary."""
    bindir = run / "bin"
    bindir.mkdir(exist_ok=True)
    stopped = f"peer-sessions lab {run} has stopped; start a new lab for this run"
    names = {"pidfile": str(run / "pid"), "sock": str(run / SOCK_FILE), "gone": LAB_GONE}
    for tool in ("herdr", "cmux"):
        wrapper = bindir / tool
        wrapper.write_text(WRAPPER.format(tool=tool, fakebin=str(FAKEBIN), stopped=stopped, **names))
        wrapper.chmod(0o755)
    if claude is not None:
        wrapper = bindir / "claude"
        wrapper.write_text(CLAUDE_WRAPPER.format(
            sandbox=SANDBOX_EXEC, profile=run / PROFILE_FILE, claude=claude,
            pidfile=shlex.quote(names["pidfile"]), stopped=shlex.quote(stopped), gone=LAB_GONE,
        ))
        wrapper.chmod(0o755)


def parse_ready(reply, pid=None):
    """Seconds the lab has left from its `ready` reply, or None when the reply is not one."""
    parts = reply.decode(errors="replace").split()
    if len(parts) != 3 or parts[0] != "ready" or not parts[2].isdigit():
        return None
    if pid is not None and parts[1] != str(pid):
        return None
    return int(parts[2])


def ready(run, needs=0):
    """Seconds left in the lab at RUN; fail when it is gone or has less than NEEDS left."""
    try:
        left = parse_ready(request(run, b"ready"))
    except OSError as error:
        raise RuntimeError(f"lab {run} is not running ({error}); start a new one") from error
    if left is None:
        raise RuntimeError(f"lab {run} gave no ready reply; start a new one")
    if left < needs:
        raise RuntimeError(
            f"lab {run} has {left}s left and the run needs {needs}s; start a new one"
        )
    return left


def start(lifetime=RUN_TIMEOUT):
    run = Path(tempfile.mkdtemp(prefix=RUN_PREFIX, dir="/tmp"))
    server = None
    ready = False
    try:
        bindir = run / "bin"
        bindir.mkdir()
        (run / TOKEN_FILE).write_text(secrets.token_hex(32))
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
            else:
                (bindir / tool).symlink_to(real)
        write_wrappers(run, claude=bindir / ".claude-bin")
        server = subprocess.Popen(
            [sys.executable, str(SCRIPT), "serve", str(run), "--lifetime", str(lifetime)],
            start_new_session=True,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + START_TIMEOUT
        while server.poll() is None and time.monotonic() < deadline:
            try:
                ready = parse_ready(request(run, b"ready"), server.pid) is not None
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
    """Read TARGET from CWD inside and outside the run's sandbox.

    Exit 0 only when the sandbox refuses the read and the same read outside it
    succeeds; an unreadable target proves nothing about the sandbox.
    """
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
    # The probe exits 0 on a refused read and 1 on a successful one.
    return 0 if result.returncode == 0 and unconfined.returncode == 1 else 1


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
    begin = commands.add_parser("start")
    begin.add_argument("--hours", type=float, default=RUN_TIMEOUT / 3600)
    check_ready = commands.add_parser("ready")
    check_ready.add_argument("run", type=Path)
    check_ready.add_argument("--needs", type=int, default=0, help="seconds the next run needs")
    sync = commands.add_parser("sync-root")
    sync.add_argument("revision", nargs="?", default="HEAD")
    sync.add_argument("--root", type=Path, default=REPO / "evals" / "root")
    check = commands.add_parser("withhold-check")
    check.add_argument("target", type=Path)
    check.add_argument("--cwd", type=Path, default=REPO / "evals" / "root" / "peer-sessions")
    commands.add_parser("stop").add_argument("run", type=Path)
    server = commands.add_parser("serve")
    server.add_argument("run", type=Path)
    server.add_argument("--lifetime", type=float, default=RUN_TIMEOUT)
    args = parser.parse_args()
    try:
        if args.command == "start":
            print(run_path(start(args.hours * 3600)))
        elif args.command == "ready":
            print(f"lab {args.run}: {ready(args.run, args.needs)}s left")
        elif args.command == "stop":
            stop(args.run)
        elif args.command == "serve":
            serve(args.run, args.lifetime)
        elif args.command == "withhold-check":
            sys.exit(withhold_check(args.target, args.cwd))
        else:
            sync_root(args.revision, args.root)
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"lab: {error}\n")


if __name__ == "__main__":
    main()
