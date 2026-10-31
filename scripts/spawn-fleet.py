#!/usr/bin/env python3
"""Launch named agent sessions in cmux or herdr, and verify they came up.

Backend: `--backend auto|cmux|herdr`. An explicit choice wins. `auto` picks
herdr when this process runs inside a herdr pane (HERDR_ENV=1), else cmux if
it is on PATH, else herdr. herdr control needs a herdr-managed caller, so the
herdr backend refuses to run without HERDR_ENV=1. herdr has no "window"
concept exposed over its CLI, so --placement window is cmux-only; use split or
workspace on herdr.

Runtime: `--runtime claude|codex` picks the agent CLI, separately from the
backend and the model. claude is the default and works on both backends. codex
starts native Codex sessions through `herdr agent start --kind codex`, so it is
herdr-only; it never falls back to Claude. Claude-only flags
(`--claude-arg`, `--permission-mode`) are refused for codex.

Every input is validated before anything is created: no directory, pane,
workspace or window exists until the whole request is known to be launchable.

Receipts: `--receipt PATH` rewrites a JSON launch receipt after every
allocation, so a launch that fails halfway still names each pane, workspace,
window and directory it created. `--json` prints the final receipt on stdout
and moves the human report to stderr. Format: docs/coordination-contract-v1.md.
Nothing is torn down automatically, on success or failure.

Exit status: 0 every session ready; 1 some session not ready (or blocked)
before --timeout; 2 invalid request, nothing created; 3 a backend operation
failed mid-launch, partial inventory reported.

herdr note: in harnesses that scope SendMessage to Agent-tool-spawned teammates
only (rather than any live sibling `claude` process), a herdr-launched session
will not register a live CLAUDE_CODE_MESSAGING_SOCKET and will not be
SendMessage-reachable even on a build that supports it. This script still
verifies herdr sessions came up (via `herdr agent get`, not the socket
registry) because that check is meaningful there; drive those sessions with
`herdr agent prompt/wait/read <name>` instead of SendMessage. See
references/troubleshooting.md.
"""

import argparse
import contextlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time

from peer_receipts import LaunchReceipt, ReceiptError
from peer_registry import live_records, normalized_name, record_identity, socket_live


UUID = re.compile(r"^[0-9A-Fa-f]{8}(-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}$")
HERDR_DIRECTIONS = {"right", "down"}
# herdr's own rule for agent names (`herdr --skill`).
HERDR_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
CORRELATION_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")
RUNTIMES = ("claude", "codex")
# herdr's documented default for `agent start` readiness.
HERDR_START_TIMEOUT_MS = 30000
DENIAL = re.compile(r"permission|denied|forbidden|unauthori[sz]ed|not allowed", re.I)

EXIT_NOT_READY = 1
EXIT_LAUNCH_FAILED = 3

# Human-readable report. --json moves it to stderr so stdout stays parseable.
OUT = sys.stdout


def say(*args, **kwargs):
    print(*args, file=OUT, **kwargs)


class BackendError(RuntimeError):
    """A cmux/herdr operation, or a directory creation, that did not succeed.

    `outcome` keeps different failures apart, because they need different
    responses:
      transient  known short-lived race (herdr agent_pane_busy); safe to retry
      blocked    the agent stopped at an approval/question UI during startup
      denied     the backend or OS refused; never retry or route around it
      unknown    no usable answer; the operation may or may not have happened
      failed     the backend rejected the operation
    """

    def __init__(self, backend, command, message, code=None, outcome="failed", exit_code=None):
        self.backend = backend
        self.command = list(command) if command is not None else None
        self.message = message
        self.code = code
        self.outcome = outcome
        self.exit_code = exit_code
        self.session = None
        shown = " ".join(self.command or [])
        super().__init__(f"{backend} {shown}\n  → {message}")


def _json(text):
    try:
        return json.loads(text)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# cmux backend
# ---------------------------------------------------------------------------


def cmux(*args, timeout=60):
    """Run cmux and ask for UUIDs beside refs. Refs renumber; UUIDs do not."""
    command = ["cmux", "--id-format", "both", *args]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        raise BackendError(
            "cmux", args, f"no answer within {timeout}s; the outcome is unknown",
            code="timeout", outcome="unknown",
        ) from error
    except PermissionError as error:
        raise BackendError(
            "cmux", args, str(error), code="exec_denied", outcome="denied"
        ) from error
    except OSError as error:
        raise BackendError("cmux", args, str(error), code="exec_failed") from error
    output = (result.stdout + result.stderr).strip()
    if result.returncode != 0 or output.startswith("Error"):
        outcome = "denied" if DENIAL.search(output) else "failed"
        raise BackendError("cmux", args, output, outcome=outcome, exit_code=result.returncode)
    return output


def id_from(output, kind, command=None):
    """Take the durable id for `kind` out of `OK surface:22 (UUID) workspace:10 (UUID)`.

    Falls back to the bare ref when no UUID follows it. Refs renumber, so
    callers record a ref as non-durable and never print a close command for it.
    """
    tokens = output.replace("(", " ").replace(")", " ").split()
    for index, token in enumerate(tokens):
        if not token.startswith(f"{kind}:"):
            continue
        if index + 1 < len(tokens) and UUID.match(tokens[index + 1]):
            return tokens[index + 1]
        return token
    # The command succeeded, so the object probably exists; its id is lost.
    raise BackendError(
        "cmux", command, f"no {kind} id in cmux output: {output!r}",
        code="unparsed_output", outcome="unknown",
    )


def workspace_uuid(ref):
    """`new-workspace` prints a ref only. Refs renumber, so trade it for a UUID.

    Returns None when the tree does not resolve the ref.
    """
    if UUID.match(ref):
        return ref
    # `list-workspaces` covers the caller's window only, so read every window.
    match = re.search(
        rf"workspace {re.escape(ref)}(?![0-9])\s+([0-9A-Fa-f-]{{36}})",
        cmux("tree", "--all"),
    )
    return match.group(1) if match else None


def durable(identifier):
    return bool(identifier and UUID.match(identifier))


def start_session(workspace, surface, directory, argv, name, receipt):
    """Type a launch command into a shell that cmux already opened."""
    receipt.update_session(name, "start_requested", workspace=workspace, surface=surface)
    command = " ".join(shlex.quote(value) for value in argv)
    full = f"cd {shlex.quote(directory)} && {command}"
    cmux("send", "--workspace", workspace, "--surface", surface, full)
    cmux("send-key", "--workspace", workspace, "--surface", surface, "Enter")


def build_splits(specs, argv_for, caller, direction, focus, receipt):
    """Put each session in a new pane beside the caller's pane."""
    workspace = caller["workspace"]
    anchor = caller["surface"]
    if len(specs) > 3 and direction in ("right", "left"):
        print(
            f"note: {len(specs)} side panes get narrow. "
            "Use --direction down, or --placement workspace.",
            file=sys.stderr,
        )
    layout = {
        "placement": "split",
        "backend": "cmux",
        "window": caller.get("window"),
        "workspace": workspace,
        "workspaces": [],
        "surfaces": [],
    }
    for name, directory in specs:
        with tracking(receipt, name):
            split_args = [
                "new-split", direction, "--workspace", workspace, "--surface", anchor,
                "--focus", focus,
            ]
            surface = id_from(cmux(*split_args), "surface", split_args)
            layout["surfaces"].append(surface)
            receipt.add_resource(
                "surface", surface, "cmux new-split", session=name, workspace=workspace,
                durable=durable(surface),
            )
            start_session(workspace, surface, directory, argv_for(name), name, receipt)
        anchor = surface  # chain, so the panes line up in spec order
    return layout


def build_workspaces(specs, argv_for, window, prefix, per_workspace, direction, focus, receipt):
    """Put each group of sessions in its own workspace."""
    layout = {"window": window, "workspaces": [], "surfaces": []}
    groups = [
        specs[index : index + per_workspace]
        for index in range(0, len(specs), per_workspace)
    ]
    for group_index, group in enumerate(groups, 1):
        first_name, first_dir = group[0]
        cmux_args = [
            "new-workspace",
            "--name",
            f"{prefix}-{group_index}",
            "--cwd",
            first_dir,
            "--command",
            " ".join(shlex.quote(value) for value in argv_for(first_name)),
        ]
        if window:
            cmux_args += ["--window", window]
        cmux_args += ["--focus", focus if group_index == 1 else "false"]
        with tracking(receipt, first_name):
            receipt.update_session(first_name, "start_requested")
            ref = id_from(cmux(*cmux_args), "workspace", cmux_args)
            # Record the ref before the UUID lookup, which can fail on its own.
            resource = receipt.add_resource(
                "workspace", ref, "cmux new-workspace", session=first_name, window=window,
                durable=durable(ref),
            )
            resolved = workspace_uuid(ref)
            if resolved is None:
                # Keep going on the ref, which is valid right now, but never
                # hand it out as a close target: it can renumber.
                workspace = ref
            elif resolved != ref:
                workspace = resolved
                resource.update({"id": resolved, "ref": ref, "durable": True})
                receipt.flush()
            else:
                workspace = ref
            layout["workspaces"].append(workspace)
            receipt.update_session(first_name, workspace=workspace)

        for name, directory in group[1:]:
            with tracking(receipt, name):
                split_args = [
                    "new-split", direction, "--workspace", workspace, "--focus", "false"
                ]
                surface = id_from(cmux(*split_args), "surface", split_args)
                layout["surfaces"].append(surface)
                receipt.add_resource(
                    "surface", surface, "cmux new-split", session=name, workspace=workspace,
                    durable=durable(surface),
                )
                start_session(workspace, surface, directory, argv_for(name), name, receipt)
    return layout


def close_line(resource, command):
    """A close command only for a durable id; a ref gets a note instead."""
    if resource.get("durable", True):
        return f"  {command}"
    return (
        f"  # {resource['kind']} {resource['id']} has no durable id (refs renumber). "
        "Resolve it with `cmux tree --all` before closing it."
    )


def cleanup_lines_cmux(receipt, layout):
    lines = []
    if layout["placement"] == "window":
        for window in receipt.owned("window"):
            lines.append(close_line(window, f"cmux close-window --window {window['id']}"))
            lines.append("  # close-window can return OK and leave the window open.")
            lines.append("  # If it stays in cmux list-windows, ask the user for a Cmd+W.")
    elif layout["placement"] == "workspace":
        for workspace in receipt.owned("workspace"):
            lines.append(
                close_line(workspace, f"cmux close-workspace --workspace {workspace['id']}")
            )
    else:
        # Split placement lives in the caller's own workspace. Close the new
        # panes only. Never close this workspace or this window.
        for surface in receipt.owned("surface"):
            lines.append(
                close_line(
                    surface,
                    f"cmux close-surface --workspace {surface['workspace']} "
                    f"--surface {surface['id']}",
                )
            )
    return lines


# ---------------------------------------------------------------------------
# herdr backend
# ---------------------------------------------------------------------------


def classify_herdr(code, message, exit_code, enveloped):
    text = f"{code or ''} {message or ''}"
    if code == "agent_pane_busy":
        return "transient"
    if code == "agent_not_ready":
        return "blocked"
    if DENIAL.search(text):
        return "denied"
    if code and "timeout" in code:
        return "unknown"
    if exit_code == 2:
        return "failed"  # CLI syntax error: the request never reached the server
    if not enveloped:
        return "unknown"
    return "failed"


def herdr(*args, timeout=60):
    """Run herdr and return its parsed JSON `result` payload.

    herdr 0.8 prints success JSON on stdout and server errors as a JSON
    envelope on stderr with exit status 1; syntax errors exit 2. Older builds
    put the error envelope on stdout. Both are read.
    """
    command = ["herdr", *args]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        raise BackendError(
            "herdr", args, f"no answer within {timeout}s; the outcome is unknown",
            code="timeout", outcome="unknown",
        ) from error
    except PermissionError as error:
        raise BackendError(
            "herdr", args, str(error), code="exec_denied", outcome="denied"
        ) from error
    except OSError as error:
        raise BackendError("herdr", args, str(error), code="exec_failed") from error
    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    payload = _json(stdout)
    if result.returncode == 0 and isinstance(payload, dict) and "error" not in payload:
        found = payload.get("result", {})
        if not isinstance(found, dict):
            raise BackendError(
                "herdr", args, f"success payload has no result object: {stdout!r}",
                code="unparsed_output", outcome="unknown", exit_code=0,
            )
        return found

    envelope = None
    for candidate in (payload, _json(stderr)):
        if isinstance(candidate, dict) and "error" in candidate:
            envelope = candidate
            break
    if envelope is not None:
        error = envelope["error"]
        if isinstance(error, dict):
            code = error.get("code")
            message = error.get("message") or json.dumps(error)
        else:
            code, message = None, str(error)
    else:
        code = None
        message = "\n".join(part for part in (stdout, stderr) if part) or (
            f"exit status {result.returncode}"
        )
    outcome = classify_herdr(code, message, result.returncode, envelope is not None)
    raise BackendError("herdr", args, message, code, outcome, result.returncode)


def optional_id(result, *path):
    value = result
    for key in path:
        value = value.get(key) if isinstance(value, dict) else None
    return value if isinstance(value, str) and value else None


def missing_ids(command, result, *paths):
    """The operation succeeded but some ids are absent: an unknown outcome."""
    names = ", ".join(".".join(path) for path in paths)
    return BackendError(
        "herdr", command, f"no {names} in herdr output: {result!r}",
        code="unparsed_output", outcome="unknown",
    )


def herdr_result_id(result, *path, command=None):
    """Read an id out of a herdr success payload; a missing id is an unknown outcome."""
    value = optional_id(result, *path)
    if value is None:
        raise missing_ids(command, result, path)
    return value


def agent_identity(agent):
    """The identity fields herdr exposes for an agent. herdr reports no PID."""
    if not isinstance(agent, dict):
        return {}
    return {
        "agent_kind": agent.get("agent"),
        "pane_id": agent.get("pane_id"),
        "terminal_id": agent.get("terminal_id"),
        "workspace_id": agent.get("workspace_id"),
        "tab_id": agent.get("tab_id"),
    }


def start_session_herdr(name, pane_id, argv, receipt, retry_seconds=5.0):
    """Launch the runtime directly in an existing herdr pane; argv[0] is its kind.

    A pane freshly returned by `pane split`/`workspace create` is not always
    an "available shell" the instant this runs next — herdr is still settling
    the new pty. Retry briefly on that one race (agent_pane_busy). Every other
    failure, including a blocked startup or denial, is final here.
    """
    kind = argv[0]
    receipt.update_session(name, "start_requested", pane_id=pane_id)
    command = [
        "agent", "start", name, "--kind", kind, "--pane", pane_id,
        "--timeout", str(HERDR_START_TIMEOUT_MS),
    ]
    if argv[1:]:
        command += ["--", *argv[1:]]
    deadline = time.time() + retry_seconds
    while True:
        try:
            result = herdr(*command, timeout=HERDR_START_TIMEOUT_MS / 1000 + 30)
            break
        except BackendError as error:
            if error.outcome != "transient" or time.time() >= deadline:
                raise
            time.sleep(0.3)
    agent = result.get("agent") if isinstance(result, dict) else None
    receipt.update_session(name, "started", **agent_identity(agent))


def build_splits_herdr(specs, argv_for, caller, direction, focus, receipt):
    """Put each session in a new pane beside the caller's pane."""
    anchor = caller["surface"]
    if len(specs) > 3 and direction == "right":
        print(
            f"note: {len(specs)} side panes get narrow. "
            "Use --direction down, or --placement workspace.",
            file=sys.stderr,
        )
    layout = {
        "placement": "split",
        "backend": "herdr",
        "window": None,
        "workspace": caller.get("workspace"),
        "workspaces": [],
        "surfaces": [],
    }
    for name, directory in specs:
        with tracking(receipt, name):
            split_args = [
                "pane", "split", "--pane", anchor, "--direction", direction,
                "--cwd", directory,
            ]
            split_args.append("--focus" if focus == "true" else "--no-focus")
            result = herdr(*split_args)
            pane_id = herdr_result_id(result, "pane", "pane_id", command=split_args)
            layout["surfaces"].append(pane_id)
            receipt.add_resource(
                "pane", pane_id, "herdr pane split", session=name,
                workspace=caller.get("workspace"),
            )
            start_session_herdr(name, pane_id, argv_for(name), receipt)
        anchor = pane_id  # chain, so the panes line up in spec order
    return layout


def build_workspaces_herdr(specs, argv_for, prefix, per_workspace, direction, focus, receipt):
    """Put each group of sessions in its own workspace."""
    layout = {"window": None, "workspaces": [], "surfaces": []}
    groups = [
        specs[index : index + per_workspace]
        for index in range(0, len(specs), per_workspace)
    ]
    for group_index, group in enumerate(groups, 1):
        first_name, first_dir = group[0]
        create_args = [
            "workspace", "create", "--cwd", first_dir, "--label", f"{prefix}-{group_index}",
        ]
        create_args.append(
            "--focus" if (focus == "true" and group_index == 1) else "--no-focus"
        )
        with tracking(receipt, first_name):
            result = herdr(*create_args)
            # Record every id herdr did return before complaining about one it
            # did not: each names something that now exists.
            workspace_id = optional_id(result, "workspace", "workspace_id")
            root_pane_id = optional_id(result, "root_pane", "pane_id")
            # Stage both before the one fallible write, so a receipt failure
            # cannot drop the second.
            if workspace_id:
                layout["workspaces"].append(workspace_id)
                receipt.add_resource(
                    "workspace", workspace_id, "herdr workspace create", session=first_name,
                    flush=False,
                )
            if root_pane_id:
                receipt.add_resource(
                    "pane", root_pane_id, "herdr workspace create", session=first_name,
                    workspace=workspace_id, parent=workspace_id, flush=False,
                )
            receipt.flush()
            absent = [
                path
                for path, value in (
                    (("workspace", "workspace_id"), workspace_id),
                    (("root_pane", "pane_id"), root_pane_id),
                )
                if value is None
            ]
            if absent:
                raise missing_ids(create_args, result, *absent)
            start_session_herdr(first_name, root_pane_id, argv_for(first_name), receipt)

        anchor = root_pane_id
        for name, directory in group[1:]:
            with tracking(receipt, name):
                split_args = [
                    "pane", "split", "--pane", anchor, "--direction", direction,
                    "--cwd", directory, "--no-focus",
                ]
                result = herdr(*split_args)
                pane_id = herdr_result_id(result, "pane", "pane_id", command=split_args)
                layout["surfaces"].append(pane_id)
                receipt.add_resource(
                    "pane", pane_id, "herdr pane split", session=name,
                    workspace=workspace_id, parent=workspace_id,
                )
                start_session_herdr(name, pane_id, argv_for(name), receipt)
            anchor = pane_id
    return layout


def herdr_readiness(name, runtime, expected=None):
    """herdr-native readiness: the named agent, of the right kind, ready for input.

    A live CLAUDE_CODE_MESSAGING_SOCKET is not a meaningful readiness signal on
    every herdr host — some harnesses scope SendMessage to Agent-tool-spawned
    teammates and never register one for a herdr-launched sibling regardless of
    build version. Use herdr's own state instead. A name follows the pane's
    current occupant, so the kind is checked too.

    `expected` is the identity recorded at start. herdr keeps a terminal id
    across a pane move but issues a new pane id, so the terminal id is compared
    when known and the pane id otherwise.

    Returns (state, agent, error). state is ready, blocked, starting, missing,
    mismatch, or the BackendError outcome (denied, unknown, failed) when the
    lookup itself failed; error is that BackendError.
    """
    command = ["agent", "get", name]
    try:
        result = herdr(*command)
    except BackendError as error:
        if error.code == "agent_not_found":
            return "missing", None, None
        return error.outcome, None, error
    agent = result.get("agent", result)
    if not isinstance(agent, dict):
        error = missing_ids(command, result, ("agent",))
        return error.outcome, None, error
    if agent.get("agent") not in (None, runtime):
        return "mismatch", agent, None
    expected = expected or {}
    if expected.get("terminal_id") and agent.get("terminal_id"):
        if agent["terminal_id"] != expected["terminal_id"]:
            return "mismatch", agent, None
    elif expected.get("pane_id") and agent.get("pane_id") != expected["pane_id"]:
        return "mismatch", agent, None
    status = agent.get("agent_status")
    if status == "blocked":
        return "blocked", agent, None
    ready_flag = agent.get("interactive_ready")
    if status in ("idle", "done", "working") and (
        ready_flag or (ready_flag is None and status in ("idle", "done"))
    ):
        return "ready", agent, None
    return "starting", agent, None


def reconcile_pane(receipt, name, agent, verified):
    """Bring a session's pane resource up to date with what herdr reports now.

    A pane moved to another workspace gets a new pane id; herdr never reuses
    pane ids, and the old one stops resolving. When the terminal id still
    matches (verified), the close target follows the move. When the name now
    labels someone else, the pane is kept in the inventory but its teardown is
    a note, not a command.
    """
    for resource in receipt.owned("pane"):
        if resource["session"] != name:
            continue
        if not verified:
            resource["verified"] = False
        elif isinstance(agent, dict) and agent.get("pane_id") not in (None, resource["id"]):
            resource["moved_to"] = agent["pane_id"]
            resource["moved_workspace"] = agent.get("workspace_id")
    receipt.flush()


def cleanup_lines_herdr(receipt, layout):
    lines = []
    panes = receipt.owned("pane")
    if layout["placement"] == "workspace":
        doubtful = {pane.get("parent") for pane in panes if pane.get("verified") is False}
        for workspace in receipt.owned("workspace"):
            if workspace["id"] in doubtful:
                lines.append(
                    f"  # workspace {workspace['id']} holds a pane whose agent name now "
                    "labels a different agent. Inspect it before closing it."
                )
            else:
                lines.append(f"  herdr workspace close {workspace['id']}")
        # A pane moved out of its workspace is not closed with it.
        panes = [
            pane for pane in panes
            if pane.get("verified") is False
            or (pane.get("moved_to") and pane.get("moved_workspace") != pane.get("parent"))
        ]
    for pane in panes:
        if pane.get("verified") is False:
            lines.append(
                f"  # pane {pane['id']}: its agent name now labels a different agent. "
                "Inspect it with `herdr pane get` before closing it."
            )
        elif pane.get("moved_to"):
            lines.append(f"  herdr pane close {pane['moved_to']}   # moved from {pane['id']}")
        else:
            lines.append(f"  herdr pane close {pane['id']}")
    return lines


# ---------------------------------------------------------------------------
# shared
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def tracking(receipt, name):
    """Tag a BackendError with the session it hit, and mark that session."""
    try:
        yield
    except BackendError as error:
        if error.session is None:
            error.session = name
            if error.backend != "receipt":
                state = {"blocked": "blocked", "denied": "denied", "unknown": "unknown"}
                receipt.update_session(name, state.get(error.outcome, "failed"))
        raise


def resolve_backend(choice, parser):
    herdr_here = os.environ.get("HERDR_ENV") == "1"
    if choice == "auto":
        if herdr_here and shutil.which("herdr"):
            backend = "herdr"
        elif shutil.which("cmux"):
            backend = "cmux"
        elif shutil.which("herdr"):
            backend = "herdr"
        else:
            parser.error(
                "neither 'cmux' nor 'herdr' is on PATH. This script needs one of "
                "them to open panes/workspaces for new sessions."
            )
    else:
        backend = choice
        if not shutil.which(backend):
            parser.error(f"--backend {backend}: '{backend}' is not on PATH.")
    if backend == "herdr" and not herdr_here:
        parser.error(
            "the herdr backend must run inside a herdr pane (HERDR_ENV=1 is unset). "
            "herdr only allows control from a herdr-managed caller. Run this from a "
            "herdr pane, or choose --backend cmux."
        )
    return backend


def caller_context(backend):
    """Return the workspace and pane/surface this script runs in."""
    if backend == "herdr":
        return {
            "window": None,
            "workspace": os.environ.get("HERDR_WORKSPACE_ID"),
            "surface": os.environ.get("HERDR_PANE_ID"),
        }
    try:
        payload = json.loads(cmux("identify"))
    except (BackendError, ValueError):
        return {}
    caller = payload.get("caller") or {}
    return {
        "window": caller.get("window_id"),
        "workspace": caller.get("workspace_id"),
        "surface": caller.get("surface_id"),
    }


def parse_specs(raw, backend, dirs_mode):
    """Validate every NAME:DIR. Returns (specs, missing dirs) or raises ValueError.

    Pure: creates nothing. Directories are made later, only once the whole
    request has passed validation.
    """
    specs = []
    missing = set()
    for item in raw:
        if ":" not in item:
            raise ValueError(f"'{item}' is not NAME:DIR")
        name, _, directory = item.partition(":")
        name = " ".join(name.split())
        directory = directory.strip()
        if not name:
            raise ValueError(f"'{item}' has an empty name")
        if not directory:
            raise ValueError(f"'{item}' has an empty directory")
        if backend == "herdr" and not HERDR_NAME.match(name):
            raise ValueError(
                f"'{name}' is not a valid herdr agent name "
                "(lowercase letter first, then lowercase letters, digits, - or _; "
                "at most 32 characters)"
            )
        directory = os.path.abspath(os.path.expanduser(directory))
        if os.path.exists(directory):
            if not os.path.isdir(directory):
                raise ValueError(f"'{directory}' exists and is not a directory")
        elif dirs_mode == "existing":
            raise ValueError(
                f"'{directory}' does not exist (--dirs existing). "
                "Create it first, or use --dirs create."
            )
        else:
            ancestor = os.path.dirname(first_missing_ancestor(directory))
            if not os.path.isdir(ancestor):
                raise ValueError(
                    f"'{directory}' cannot be created: '{ancestor}' is not a directory"
                )
            missing.add(directory)
        specs.append((name, directory))
    names = [name for name, _ in specs]
    duplicates = {name for name in names if names.count(name) > 1}
    if duplicates:
        raise ValueError(f"duplicate session names: {', '.join(sorted(duplicates))}")
    return specs, missing


def parse_correlation(pairs):
    correlation = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not CORRELATION_KEY.match(key) or not value:
            raise ValueError(f"--correlate expects KEY=VALUE, got {pair!r}")
        if key in correlation:
            raise ValueError(f"--correlate {key} given twice")
        correlation[key] = value
    return correlation


def first_missing_ancestor(directory):
    root = directory
    while not os.path.exists(os.path.dirname(root)):
        root = os.path.dirname(root)
    return root


def create_directories(specs, missing, receipt):
    for name, directory in specs:
        if directory not in missing or os.path.isdir(directory):
            continue
        created_root = first_missing_ancestor(directory)
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError as error:
            failure = BackendError(
                "filesystem", ["mkdir", directory], str(error),
                code=type(error).__name__,
                outcome="denied" if isinstance(error, PermissionError) else "failed",
            )
            failure.session = name
            receipt.update_session(name, "denied" if failure.outcome == "denied" else "failed")
            raise failure from error
        # Update every in-memory fact first; add_resource's flush can fail.
        receipt.session(name)["directory_created"] = True
        receipt.add_resource(
            "directory", directory, "mkdir", session=name, created_root=created_root
        )


def registry_identity(record):
    return {
        "pid": record.get("pid"),
        "session_id": record.get("sessionId"),
        "proc_start": record.get("procStart"),
        "messaging_socket": record.get("messagingSocketPath"),
    }


def bind_registry(name, directory, before, records=None):
    """Find the one Claude registry record this launch created for `name`.

    Only records absent before the launch, with the same name and the same
    (resolved) cwd, count. Returns (record or None, number of candidates).
    Several candidates bind nothing: a guess could point a later `kill` at
    someone else's session.
    """
    real = os.path.realpath(directory)
    candidates = [
        record
        for record in (live_records() if records is None else records)
        if record_identity(record) not in before
        and normalized_name(record) == name
        and isinstance(record.get("cwd"), str)
        and os.path.realpath(record["cwd"]) == real
    ]
    return (candidates[0] if len(candidates) == 1 else None), len(candidates)


def attach_registry_identities(receipt, specs, before):
    """Record each Claude session's registry identity, when it is unambiguous."""
    if receipt.data["runtime"] != "claude":
        return
    snapshot = live_records()  # one read, so every name is judged on the same state
    present = {entry["name"] for entry in receipt.data["sessions"]}
    for name, directory in specs:
        if name not in present:
            continue
        record, count = bind_registry(name, directory, before, snapshot)
        identity = receipt.session(name)["identity"]
        if record is not None:
            identity.pop("registry_candidates", None)
            receipt.update_session(name, **registry_identity(record))
        else:
            # Drop any earlier binding: it is no longer the only candidate.
            for key in ("pid", "session_id", "proc_start", "messaging_socket"):
                identity.pop(key, None)
            if count > 1:
                receipt.update_session(name, registry_candidates=count)
            else:
                receipt.flush()


def cleanup_block(receipt, layout, backend):
    pids = sorted(
        {
            entry["identity"]["pid"]
            for entry in receipt.data["sessions"]
            if isinstance(entry["identity"].get("pid"), int)
        }
    )
    lines = ["", "Teardown is off by default: hand this block to the user, and run it"]
    lines.append("only when they ask. It names only what this launch created.")
    if pids:
        lines.append("Kill the processes before closing their UI:")
        lines.append("  kill " + " ".join(str(pid) for pid in pids))
    elif backend == "cmux":
        lines.append("  No launched PID registered yet; inspect the panes before closing them.")
    if layout is not None:
        if backend == "herdr":
            lines += cleanup_lines_herdr(receipt, layout)
        else:
            lines += cleanup_lines_cmux(receipt, layout)
    lines.append("  python3 ~/.claude/skills/peer-sessions/scripts/peer-addr.py")
    return lines


def report_failure(receipt, error, layout, backend):
    failure = receipt.data["failure"]
    print(
        f"\nlaunch stopped: {failure['outcome']} during "
        f"{' '.join(failure['command'] or []) or failure['operation']}"
        + (f" for {failure['session']}" if failure["session"] else ""),
        file=sys.stderr,
    )
    print(f"  {error.message}", file=sys.stderr)
    if failure["backend"] == "receipt":
        print(
            "  The receipt file is out of date. The inventory below, from memory, "
            "is complete; no further launches were attempted.",
            file=sys.stderr,
        )
    elif failure["outcome"] == "denied":
        print(
            "  The backend refused. Tell the user; do not route around it.",
            file=sys.stderr,
        )
    elif failure["outcome"] == "unknown":
        print(
            "  The outcome is unknown. Inspect before retrying: the operation may "
            "have created something this receipt could not name.",
            file=sys.stderr,
        )
    elif failure["outcome"] == "blocked":
        print(
            "  The agent stopped at an approval or question prompt. Read the pane "
            "and ask the user before answering it.",
            file=sys.stderr,
        )
    say("\nCreated before the failure (retained, nothing was closed):")
    resources = receipt.data["resources"]
    if not resources:
        say("  nothing")
    for resource in resources:
        owner = f" for {resource['session']}" if resource.get("session") else ""
        say(f"  {resource['kind']} {resource['id']}{owner}")
    for entry in receipt.data["sessions"]:
        say(f"  session {entry['name']}: {entry['state']}")
    if resources:
        for line in cleanup_block(receipt, layout, backend):
            say(line)


def build_parser():
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("specs", nargs="+", metavar="NAME:DIR")
    parser.add_argument(
        "--backend",
        choices=("auto", "cmux", "herdr"),
        default="auto",
        help="auto (default): herdr inside a herdr pane, else cmux, else herdr",
    )
    parser.add_argument(
        "--runtime",
        choices=RUNTIMES,
        default="claude",
        help="agent CLI to start (default: claude; codex needs --backend herdr)",
    )
    parser.add_argument(
        "--placement",
        choices=("split", "workspace", "window"),
        default="workspace",
        help="split: panes beside this one. workspace: new workspaces in this "
        "window. window: a new window (cmux only; default: workspace)",
    )
    parser.add_argument(
        "--window", action="store_true", help="alias for --placement window"
    )
    parser.add_argument(
        "--direction",
        choices=("right", "left", "up", "down"),
        default="right",
        help="direction of each new pane (default: right; herdr supports only "
        "right/down)",
    )
    parser.add_argument(
        "--focus",
        choices=("true", "false"),
        help="move the UI to the fleet (default: false for split, true otherwise)",
    )
    parser.add_argument("--per-workspace", type=int, default=2, choices=(1, 2))
    parser.add_argument("--prefix", default="fleet")
    parser.add_argument("--model", help="model for every session, passed in the runtime's own flag")
    parser.add_argument(
        "--claude-arg", action="append", default=[], help="claude runtime only; repeatable"
    )
    parser.add_argument(
        "--codex-arg", action="append", default=[], help="codex runtime only; repeatable"
    )
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument(
        "--permission-mode", help="claude runtime only (default: auto); see SKILL.md"
    )
    parser.add_argument(
        "--dirs",
        choices=("create", "existing"),
        default="create",
        help="create (default): make missing directories after validation. "
        "existing: refuse a missing directory",
    )
    parser.add_argument(
        "--receipt", metavar="PATH", help="write the JSON launch receipt here, after every step"
    )
    parser.add_argument(
        "--json", action="store_true", help="print the final receipt on stdout; report on stderr"
    )
    parser.add_argument(
        "--correlate",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="caller-issued id echoed verbatim in the receipt (e.g. run_id=r7); repeatable",
    )
    return parser


def validate(args, parser):
    """Check the whole request. Read-only: nothing is created here."""
    backend = resolve_backend(args.backend, parser)
    placement = "window" if args.window else args.placement
    if args.timeout <= 0:
        parser.error("--timeout must be a positive number of seconds")
    if placement == "window" and backend == "herdr":
        parser.error(
            "--placement window has no herdr equivalent (herdr's CLI "
            "exposes workspaces and panes, not OS windows). Use --placement "
            "split or workspace."
        )
    if backend == "herdr" and args.direction not in HERDR_DIRECTIONS:
        parser.error(
            f"herdr only supports --direction right or down (got "
            f"'{args.direction}'). cmux's left/up are not available here."
        )
    if args.runtime == "codex":
        if backend != "herdr":
            parser.error(
                "--runtime codex needs the herdr backend (herdr agent start --kind "
                "codex). Codex launch through cmux is not implemented, and this "
                "script never substitutes Claude."
            )
        if args.claude_arg:
            parser.error("--claude-arg is for the claude runtime; use --codex-arg")
        if args.permission_mode is not None:
            parser.error(
                "--permission-mode is a claude flag; pass Codex approval settings "
                "with --codex-arg"
            )
    elif args.codex_arg:
        parser.error("--codex-arg is for the codex runtime; use --claude-arg")
    if args.receipt:
        receipt_dir = os.path.dirname(os.path.abspath(args.receipt))
        if os.path.isdir(args.receipt):
            parser.error(f"--receipt {args.receipt} is a directory; give a file path")
        if not os.path.isdir(receipt_dir):
            parser.error(
                f"--receipt: '{receipt_dir}' does not exist. Create it first; the "
                "receipt never creates directories."
            )
        if not os.access(receipt_dir, os.W_OK):
            parser.error(f"--receipt: '{receipt_dir}' is not writable")
    try:
        specs, missing = parse_specs(args.specs, backend, args.dirs)
        correlation = parse_correlation(args.correlate)
    except ValueError as error:
        parser.error(str(error))
    if args.receipt:
        receipt_path = os.path.realpath(args.receipt)
        for name, directory in specs:
            real = os.path.realpath(directory)
            if receipt_path == real or real.startswith(receipt_path + os.sep):
                parser.error(
                    f"--receipt {args.receipt} is session {name}'s directory or one of "
                    "its parents; put the receipt somewhere else"
                )
    caller = caller_context(backend)
    if placement == "split":
        if backend == "herdr" and not caller.get("surface"):
            parser.error(
                "--placement split needs to run inside a herdr pane "
                "(HERDR_PANE_ID unset). Run it inside herdr, or use --placement workspace."
            )
        if backend == "cmux" and not (caller.get("workspace") and caller.get("surface")):
            parser.error(
                "--placement split needs a cmux terminal. "
                "Run it inside cmux, or use --placement workspace|window."
            )

    if backend == "herdr":
        # herdr names are unique among live agents; a clash would fail only
        # after a pane exists. Ask first (read-only).
        for name, _ in specs:
            state, agent, _ = herdr_readiness(name, args.runtime)
            if agent is not None:
                parser.error(
                    f"a live herdr agent is already named '{name}' "
                    f"(pane {agent.get('pane_id', '?')}). Pick another name."
                )
            if state == "denied":
                parser.error(f"herdr refused the name check for '{name}'.")
            if state != "missing":
                parser.error(f"could not check whether '{name}' is free in herdr ({state}).")
    return backend, placement, specs, missing, correlation, caller


def runtime_argv(args):
    if args.runtime == "codex":
        extra = list(args.codex_arg)
        if args.model:
            extra += ["--model", args.model]

        def argv_for(name):
            return ["codex", *extra]

        return argv_for

    extra = list(args.claude_arg)
    if args.model:
        extra += ["--model", args.model]
    permission_mode = args.permission_mode or "auto"

    def argv_for(name):
        return [
            "claude",
            "--name",
            name,
            "--permission-mode",
            permission_mode,
            *extra,
        ]

    return argv_for


def error_record(error):
    return {
        "command": error.command,
        "code": error.code,
        "outcome": error.outcome,
        "exit_code": error.exit_code,
        "message": error.message,
    }


def stop(receipt, error, plan, args):
    """Report a launch that stopped early, with everything it created."""
    try:
        receipt.fail(
            " ".join(error.command or []) or "parse backend output", error, error.session
        )
    except ReceiptError as write_error:
        # fail() records the backend failure in memory before writing; that
        # failure is the one to report. The stale file is secondary.
        print(f"  note: {write_error.message}", file=sys.stderr)
    layout = plan["layout"] or {
        "placement": plan["placement"], "backend": plan["backend"], "workspaces": [],
    }
    attach_registry_identities(receipt, plan["specs"], plan["before"])
    report_failure(receipt, error, layout, plan["backend"])
    if args.json:
        print(receipt.to_json())
    elif receipt.persist_failed:
        # The file is stale; the full inventory has to reach someone.
        print(receipt.to_json(), file=sys.stderr)
    return EXIT_LAUNCH_FAILED


def build_layout(args, plan, receipt):
    backend, placement, specs = plan["backend"], plan["placement"], plan["specs"]
    caller, focus, argv_for = plan["caller"], plan["focus"], plan["argv_for"]
    create_directories(specs, plan["missing"], receipt)
    if backend == "herdr":
        if placement == "split":
            layout = build_splits_herdr(specs, argv_for, caller, args.direction, focus, receipt)
            say(f"workspace {layout['workspace']} (this one)")
            say(f"panes {', '.join(layout['surfaces'])}")
        else:
            layout = build_workspaces_herdr(
                specs, argv_for, args.prefix, args.per_workspace, args.direction,
                focus, receipt,
            )
            layout["placement"] = placement
            layout["backend"] = "herdr"
            say(f"workspaces {', '.join(layout['workspaces'])}")
        return layout
    if placement == "split":
        layout = build_splits(specs, argv_for, caller, args.direction, focus, receipt)
        say(f"workspace {layout['workspace']} (this one)")
        say(f"panes {', '.join(layout['surfaces'])}")
        return layout
    # Partial layout for the teardown block if building fails.
    plan["layout"] = {"placement": placement, "backend": "cmux", "workspaces": []}
    if placement == "window":
        with tracking(receipt, specs[0][0]):
            window = cmux("new-window").split()[-1]
        receipt.add_resource("window", window, "cmux new-window", durable=durable(window))
        say(f"window {window} (new)")
    else:
        window = caller.get("window")
        say(f"window {window or '(focused)'} (this one)")
    layout = build_workspaces(
        specs, argv_for, window, args.prefix, args.per_workspace, args.direction, focus,
        receipt,
    )
    layout["placement"] = placement
    layout["backend"] = "cmux"
    say(f"workspaces {', '.join(layout['workspaces'])}")
    return layout


SETTLED = ("ready", "blocked", "denied")


def wait_for_readiness(args, plan, receipt):
    """Poll until every session is ready or settled, or the timeout passes.

    Returns {name: (state, observed, error)}. herdr observes the agent; cmux
    observes the one registry record bound by name and cwd.
    """
    backend, specs, before = plan["backend"], plan["specs"], plan["before"]
    seen = {}

    def poll():
        for name, directory in specs:
            # herdr states settle. A cmux binding is re-derived on every poll:
            # a second matching record can appear at any time.
            if backend == "herdr" and seen.get(name, (None,))[0] in SETTLED:
                continue
            if backend == "herdr":
                expected = receipt.session(name)["identity"]
                seen[name] = herdr_readiness(name, args.runtime, expected)
                continue
            record, count = bind_registry(name, directory, before)
            if record is not None and socket_live(record.get("messagingSocketPath")):
                seen[name] = ("ready", record, None)
            else:
                seen[name] = ("ambiguous" if count > 1 else "starting", None, None)

    started = time.time()
    while time.time() - started < args.timeout:
        poll()
        if all(seen.get(name, (None,))[0] in SETTLED for name, _ in specs):
            break
        time.sleep(2)
    poll()
    plan["elapsed"] = int(time.time() - started)
    return seen


def record_readiness(receipt, plan, seen):
    backend = plan["backend"]
    # One registry snapshot decides cmux readiness and the PID binding together:
    # a second read could disagree with the first.
    attach_registry_identities(receipt, plan["specs"], plan["before"])
    if backend == "cmux":
        for name, _ in plan["specs"]:
            identity = receipt.session(name)["identity"]
            live = "pid" in identity and socket_live(identity.get("messaging_socket"))
            seen[name] = ("ready", None, None) if live else ("starting", None, None)
    for name, _ in plan["specs"]:
        state, observed, error = seen.get(name, ("starting", None, None))
        if state == "ready" and backend == "herdr":
            receipt.update_session(name, "ready", **agent_identity(observed))
            reconcile_pane(receipt, name, observed, verified=True)
        elif state == "ready":
            receipt.update_session(name, "ready")  # identity bound from the snapshot
        elif state == "blocked":
            # herdr_readiness checked identity before reporting blocked.
            receipt.update_session(name, "blocked", **agent_identity(observed))
            reconcile_pane(receipt, name, observed, verified=True)
        elif state == "mismatch":
            # The name now labels a different occupant. Keep both identities.
            receipt.update_session(
                name, "not_ready", observed_occupant=agent_identity(observed)
            )
            reconcile_pane(receipt, name, observed, verified=False)
        elif error is not None:
            # The readiness lookup itself was refused or unreadable.
            receipt.session(name)["readiness_error"] = error_record(error)
            receipt.update_session(name, "denied" if state == "denied" else "unknown")
        else:
            receipt.update_session(name, "not_ready")


def report_readiness(receipt, plan, args):
    backend = plan["backend"]
    for entry in receipt.data["sessions"]:
        name, state, identity = entry["name"], entry["state"], entry["identity"]
        if state == "ready" and backend == "herdr":
            say(f"+ {name:<24} pane {identity.get('pane_id', '?')}")
        elif state == "ready":
            say(f"+ {name:<24} pid {identity['pid']:<7} uds:{identity['messaging_socket']}")
        elif state == "blocked":
            say(
                f"! {name:<24} blocked at an approval or question prompt "
                f"(pane {identity.get('pane_id', '?')})"
            )
        elif state == "denied":
            say(
                f"x {name:<24} herdr refused the readiness check: "
                f"{entry['readiness_error']['message']}. Tell the user; do not route around it."
            )
        elif state == "unknown":
            say(
                f"? {name:<24} readiness unknown: {entry['readiness_error']['message']}. "
                "Reconcile (herdr agent get/read) before another attempt."
            )
        elif "observed_occupant" in identity:
            say(f"- {name:<24} herdr name now labels a different agent; not this launch's")
        elif "registry_candidates" in identity:
            say(
                f"- {name:<24} {identity['registry_candidates']} new registry records match "
                "this name and directory; none is bound"
            )
        else:
            say(f"- {name:<24} did not become ready in {args.timeout}s")


def launch(args, plan, receipt):
    try:
        plan["layout"] = build_layout(args, plan, receipt)
    except BackendError as error:
        return stop(receipt, error, plan, args)
    layout, backend = plan["layout"], plan["backend"]

    seen = wait_for_readiness(args, plan, receipt)

    if backend == "cmux" and plan["focus"] == "true" and layout["workspaces"]:
        # A new window opens on its own default workspace, so `--focus true`
        # on the first workspace does not stick. Select it again here, after
        # every session has booted. An earlier switch races the launch
        # command that cmux types into the new shell, and scrambles it.
        try:
            cmux("select-workspace", "--workspace", layout["workspaces"][0])
        except BackendError as error:
            print(f"note: could not refocus the fleet: {error.message}", file=sys.stderr)

    record_readiness(receipt, plan, seen)
    report_readiness(receipt, plan, args)

    ready = [entry for entry in receipt.data["sessions"] if entry["state"] == "ready"]
    total = len(plan["specs"])
    if len(ready) < total:
        receipt.finish("incomplete")
        print(
            f"\n{len(ready)}/{total} ready after {plan['elapsed']}s. "
            "Check the pane — a stalled permission prompt never registers.",
            file=sys.stderr,
        )
        for line in cleanup_block(receipt, layout, backend):
            say(line)
        if args.json:
            print(receipt.to_json())
        return EXIT_NOT_READY

    receipt.finish("ready")
    say(f"\n{len(ready)} ready in {plan['elapsed']}s.")
    if backend == "cmux":
        say("Send with a uds: address above, or a freshly resolved ListAgents name/ref.")
    for line in cleanup_block(receipt, layout, backend):
        say(line)
    if backend == "herdr":
        say(
            "\nDrive these with `herdr agent prompt <name> <text>` and "
            "`herdr agent wait/read <name>`. If a bare SendMessage bounces with "
            "\"no agent named\", this harness scopes it to Agent-tool teammates only — "
            "herdr's own commands still work."
        )
    if args.json:
        print(receipt.to_json())
    return 0


def main(argv=None):
    global OUT
    parser = build_parser()
    args = parser.parse_args(argv)
    OUT = sys.stderr if args.json else sys.stdout

    backend, placement, specs, missing, correlation, caller = validate(args, parser)
    plan = {
        "backend": backend,
        "placement": placement,
        "specs": specs,
        "missing": missing,
        "caller": caller,
        "focus": args.focus or ("false" if placement == "split" else "true"),
        "argv_for": runtime_argv(args),
        "before": {record_identity(record) for record in live_records()},
        "layout": None,
        "elapsed": 0,
    }

    # Validation passed. From here on, record every side effect as it happens.
    try:
        receipt = LaunchReceipt(backend, args.runtime, placement, correlation, args.receipt)
    except ReceiptError as error:
        print(f"error: {error.message}. Nothing was created.", file=sys.stderr)
        return EXIT_LAUNCH_FAILED
    try:
        for name, directory in specs:
            receipt.add_session(name, directory, False, flush=False)
        receipt.flush()
        return launch(args, plan, receipt)
    except ReceiptError as error:
        return stop(receipt, error, plan, args)


if __name__ == "__main__":
    sys.exit(main())
