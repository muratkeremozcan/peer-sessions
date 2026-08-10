#!/usr/bin/env python3
"""Launch named Claude Code sessions in cmux or herdr, and verify their live sockets.

Backend is auto-detected: cmux if it's on PATH (unchanged, original behavior),
else herdr if that's on PATH instead. herdr has no "window" concept exposed over
its CLI, so --placement window is cmux-only; use split or workspace on herdr.

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
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time

from peer_registry import live_records, normalized_name, record_identity, socket_live


UUID = re.compile(r"^[0-9A-Fa-f]{8}(-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}$")
HERDR_DIRECTIONS = {"right", "down"}


def detect_backend():
    """Pick cmux if present (unchanged default), else herdr, else fail clearly."""
    if shutil.which("cmux"):
        return "cmux"
    if shutil.which("herdr"):
        return "herdr"
    sys.exit(
        "error: neither 'cmux' nor 'herdr' is on PATH. This script needs one of "
        "them to open panes/workspaces for new sessions."
    )


def herdr_direction(direction):
    """herdr only supports right/down; cmux's left/up have no herdr equivalent."""
    if direction not in HERDR_DIRECTIONS:
        sys.exit(
            f"error: herdr only supports --direction right or down (got "
            f"'{direction}'). cmux's left/up are not available here."
        )
    return direction


# ---------------------------------------------------------------------------
# cmux backend (unchanged behavior)
# ---------------------------------------------------------------------------


def cmux(*args):
    """Run cmux and ask for UUIDs beside refs. Refs renumber; UUIDs do not."""
    result = subprocess.run(
        ["cmux", "--id-format", "both", *args], capture_output=True, text=True
    )
    output = (result.stdout + result.stderr).strip()
    if result.returncode != 0 or output.startswith("Error"):
        raise RuntimeError(f"cmux {' '.join(args)}\n  → {output}")
    return output


def id_from(output, kind):
    """Take the durable id for `kind` out of `OK surface:22 (UUID) workspace:10 (UUID)`."""
    tokens = output.replace("(", " ").replace(")", " ").split()
    for index, token in enumerate(tokens):
        if not token.startswith(f"{kind}:"):
            continue
        if index + 1 < len(tokens) and UUID.match(tokens[index + 1]):
            return tokens[index + 1]
        return token
    raise RuntimeError(f"no {kind} id in cmux output: {output!r}")


def workspace_uuid(ref):
    """`new-workspace` prints a ref only. Refs renumber, so trade it for a UUID."""
    if UUID.match(ref):
        return ref
    # `list-workspaces` covers the caller's window only, so read every window.
    match = re.search(
        rf"workspace {re.escape(ref)}(?![0-9])\s+([0-9A-Fa-f-]{{36}})",
        cmux("tree", "--all"),
    )
    return match.group(1) if match else ref


def start_session(workspace, surface, directory, argv):
    """Type a launch command into a shell that cmux already opened."""
    command = " ".join(shlex.quote(value) for value in argv)
    full = f"cd {shlex.quote(directory)} && {command}"
    cmux("send", "--workspace", workspace, "--surface", surface, full)
    cmux("send-key", "--workspace", workspace, "--surface", surface, "Enter")


def build_splits(specs, argv_for, caller, direction, focus):
    """Put each session in a new pane beside the caller's pane."""
    workspace = caller.get("workspace")
    anchor = caller.get("surface")
    if not workspace or not anchor:
        sys.exit(
            "error: --placement split needs a cmux terminal. "
            "Run it inside cmux, or use --placement workspace|window."
        )
    if len(specs) > 3 and direction in ("right", "left"):
        print(
            f"note: {len(specs)} side panes get narrow. "
            "Use --direction down, or --placement workspace.",
            file=sys.stderr,
        )
    surfaces = []
    for name, directory in specs:
        output = cmux(
            "new-split",
            direction,
            "--workspace",
            workspace,
            "--surface",
            anchor,
            "--focus",
            focus,
        )
        surface = id_from(output, "surface")
        surfaces.append(surface)
        start_session(workspace, surface, directory, argv_for(name))
        anchor = surface  # chain, so the panes line up in spec order
    return {
        "placement": "split",
        "backend": "cmux",
        "window": caller.get("window"),
        "workspace": workspace,
        "workspaces": [],
        "surfaces": surfaces,
    }


def build_workspaces(specs, argv_for, window, prefix, per_workspace, direction, focus):
    """Put each group of sessions in its own workspace."""
    workspaces = []
    surfaces = []
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
        workspace = workspace_uuid(id_from(cmux(*cmux_args), "workspace"))
        workspaces.append(workspace)

        for name, directory in group[1:]:
            output = cmux(
                "new-split", direction, "--workspace", workspace, "--focus", "false"
            )
            surface = id_from(output, "surface")
            surfaces.append(surface)
            start_session(workspace, surface, directory, argv_for(name))
    return {"window": window, "workspaces": workspaces, "surfaces": surfaces}


def print_cleanup_cmux(records, layout):
    pids = sorted(
        {record.get("pid") for record in records if isinstance(record.get("pid"), int)}
    )
    print("\nTeardown is off by default: hand this block to the user, and run it")
    print("only when they ask. Kill the processes before closing their UI:")
    if pids:
        print("  kill " + " ".join(str(pid) for pid in pids))
    else:
        print("  No launched PID registered yet; inspect the panes before closing them.")
    if layout["placement"] == "window":
        print(f"  cmux close-window --window {layout['window']}")
        print("  # close-window can return OK and leave the window open.")
        print("  # If it stays in cmux list-windows, ask the user for a Cmd+W.")
    elif layout["placement"] == "workspace":
        for workspace in layout["workspaces"]:
            print(f"  cmux close-workspace --workspace {workspace}")
    else:
        # Split placement lives in the caller's own workspace. Close the new
        # panes only. Never close this workspace or this window.
        for surface in layout["surfaces"]:
            print(
                f"  cmux close-surface --workspace {layout['workspace']} "
                f"--surface {surface}"
            )
    print("  python3 ~/.claude/skills/peer-sessions/scripts/peer-addr.py")


# ---------------------------------------------------------------------------
# herdr backend
# ---------------------------------------------------------------------------


def herdr(*args):
    """Run herdr and return its parsed JSON `result` payload."""
    result = subprocess.run(["herdr", *args], capture_output=True, text=True)
    text = (result.stdout or "").strip()
    try:
        payload = json.loads(text)
    except ValueError:
        combined = (result.stdout + result.stderr).strip()
        raise RuntimeError(f"herdr {' '.join(args)}\n  → {combined}")
    if "error" in payload:
        raise RuntimeError(f"herdr {' '.join(args)}\n  → {payload['error']}")
    if result.returncode != 0:
        raise RuntimeError(f"herdr {' '.join(args)}\n  → {text}")
    return payload.get("result", {})


def start_session_herdr(name, pane_id, argv, retry_seconds=5.0):
    """Launch claude directly in an existing herdr pane; argv[0] is 'claude'.

    A pane freshly returned by `pane split`/`workspace create` is not always
    an "available shell" the instant this runs next — herdr is still settling
    the new pty. Retry briefly on that specific race instead of failing outright.
    """
    deadline = time.time() + retry_seconds
    while True:
        try:
            herdr(
                "agent", "start", name, "--kind", "claude", "--pane", pane_id,
                "--", *argv[1:],
            )
            return
        except RuntimeError as error:
            if "agent_pane_busy" not in str(error) or time.time() >= deadline:
                raise
            time.sleep(0.3)


def build_splits_herdr(specs, argv_for, caller, direction, focus):
    """Put each session in a new pane beside the caller's pane."""
    anchor = caller.get("surface")
    if not anchor:
        sys.exit(
            "error: --placement split needs to run inside a herdr pane "
            "(HERDR_PANE_ID unset). Run it inside herdr, or use --placement workspace."
        )
    herdr_dir = herdr_direction(direction)
    if len(specs) > 3 and herdr_dir == "right":
        print(
            f"note: {len(specs)} side panes get narrow. "
            "Use --direction down, or --placement workspace.",
            file=sys.stderr,
        )
    panes = []
    for name, directory in specs:
        split_args = [
            "pane", "split", "--pane", anchor, "--direction", herdr_dir, "--cwd", directory,
        ]
        split_args.append("--focus" if focus == "true" else "--no-focus")
        result = herdr(*split_args)
        pane_id = result["pane"]["pane_id"]
        panes.append(pane_id)
        start_session_herdr(name, pane_id, argv_for(name))
        anchor = pane_id  # chain, so the panes line up in spec order
    return {
        "placement": "split",
        "backend": "herdr",
        "window": None,
        "workspace": caller.get("workspace"),
        "workspaces": [],
        "surfaces": panes,
    }


def build_workspaces_herdr(specs, argv_for, prefix, per_workspace, direction, focus):
    """Put each group of sessions in its own workspace."""
    herdr_dir = herdr_direction(direction)
    workspaces = []
    surfaces = []
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
        result = herdr(*create_args)
        workspace_id = result["workspace"]["workspace_id"]
        root_pane_id = result["root_pane"]["pane_id"]
        workspaces.append(workspace_id)
        start_session_herdr(first_name, root_pane_id, argv_for(first_name))

        anchor = root_pane_id
        for name, directory in group[1:]:
            result = herdr(
                "pane", "split", "--pane", anchor, "--direction", herdr_dir,
                "--cwd", directory, "--no-focus",
            )
            pane_id = result["pane"]["pane_id"]
            surfaces.append(pane_id)
            start_session_herdr(name, pane_id, argv_for(name))
            anchor = pane_id
    return {"window": None, "workspaces": workspaces, "surfaces": surfaces}


def herdr_agent_ready(name):
    """herdr-native readiness: alive and interactive_ready, not a messaging socket.

    A live CLAUDE_CODE_MESSAGING_SOCKET is not a meaningful readiness signal on
    every herdr host — some harnesses scope SendMessage to Agent-tool-spawned
    teammates and never register one for a herdr-launched sibling regardless of
    build version. Use herdr's own state instead.
    """
    try:
        result = herdr("agent", "get", name)
    except RuntimeError:
        return None
    agent = result.get("agent", result)
    if agent.get("interactive_ready") and agent.get("agent_status") in ("idle", "working"):
        return agent
    return None


def print_cleanup_herdr(specs, layout):
    pids = []
    for name, _ in specs:
        agent = herdr_agent_ready(name)
        if agent:
            record = next(
                (
                    r
                    for r in live_records()
                    if normalized_name(r) == name
                ),
                None,
            )
            if record and isinstance(record.get("pid"), int):
                pids.append(record["pid"])
    print("\nTeardown is off by default: hand this block to the user, and run it")
    print("only when they ask.")
    if pids:
        print("  kill " + " ".join(str(pid) for pid in sorted(set(pids))))
    if layout["placement"] == "workspace":
        for workspace in layout["workspaces"]:
            print(f"  herdr workspace close {workspace}")
    else:
        for surface in layout["surfaces"]:
            print(f"  herdr pane close {surface}")
    print("  python3 ~/.claude/skills/peer-sessions/scripts/peer-addr.py")
    print(
        "\nDrive these with `herdr agent prompt <name> <text>` and "
        "`herdr agent wait/read <name>`. If a bare SendMessage bounces with "
        "\"no agent named\", this harness scopes it to Agent-tool teammates only — "
        "herdr's own commands still work."
    )


# ---------------------------------------------------------------------------
# shared
# ---------------------------------------------------------------------------


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
    except (RuntimeError, ValueError):
        return {}
    caller = payload.get("caller") or {}
    return {
        "window": caller.get("window_id"),
        "workspace": caller.get("workspace_id"),
        "surface": caller.get("surface_id"),
    }


def parse_specs(raw):
    specs = []
    for item in raw:
        if ":" not in item:
            sys.exit(f"error: '{item}' is not NAME:DIR")
        name, _, directory = item.partition(":")
        name = name.strip()
        directory = os.path.abspath(os.path.expanduser(directory.strip()))
        if not name:
            sys.exit(f"error: '{item}' has an empty name")
        os.makedirs(directory, exist_ok=True)
        specs.append((name, directory))
    names = [name for name, _ in specs]
    duplicates = {name for name in names if names.count(name) > 1}
    if duplicates:
        sys.exit(f"error: duplicate session names: {', '.join(sorted(duplicates))}")
    return specs


def new_matching_records(before, wanted):
    return [
        record
        for record in live_records()
        if record_identity(record) not in before and normalized_name(record) in wanted
    ]


def ready_by_name(records):
    ready = {}
    for record in records:
        socket_path = record.get("messagingSocketPath")
        if not socket_live(socket_path):
            continue
        name = normalized_name(record)
        previous = ready.get(name)
        if previous is None or (record.get("startedAt") or 0) > (
            previous.get("startedAt") or 0
        ):
            ready[name] = record
    return ready


def main():
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("specs", nargs="+", metavar="NAME:DIR")
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
    parser.add_argument("--model")
    parser.add_argument("--claude-arg", action="append", default=[])
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--permission-mode", default="auto")
    args = parser.parse_args()

    backend = detect_backend()
    placement = "window" if args.window else args.placement
    if placement == "window" and backend == "herdr":
        sys.exit(
            "error: --placement window has no herdr equivalent (herdr's CLI "
            "exposes workspaces and panes, not OS windows). Use --placement "
            "split or workspace."
        )
    focus = args.focus or ("false" if placement == "split" else "true")

    specs = parse_specs(args.specs)
    before = {record_identity(record) for record in live_records()}
    wanted = {name for name, _ in specs}

    extra = list(args.claude_arg)
    if args.model:
        extra += ["--model", args.model]

    def argv_for(name):
        return [
            "claude",
            "--name",
            name,
            "--permission-mode",
            args.permission_mode,
            *extra,
        ]

    caller = caller_context(backend)

    if backend == "herdr":
        if placement == "split":
            layout = build_splits_herdr(specs, argv_for, caller, args.direction, focus)
            print(f"workspace {layout['workspace']} (this one)")
            print(f"panes {', '.join(layout['surfaces'])}")
        else:
            layout = build_workspaces_herdr(
                specs, argv_for, args.prefix, args.per_workspace, args.direction, focus
            )
            layout["placement"] = placement
            layout["backend"] = "herdr"
            print(f"workspaces {', '.join(layout['workspaces'])}")
    else:
        if placement == "split":
            layout = build_splits(specs, argv_for, caller, args.direction, focus)
            print(f"workspace {layout['workspace']} (this one)")
            print(f"panes {', '.join(layout['surfaces'])}")
        else:
            if placement == "window":
                window = cmux("new-window").split()[-1]
                print(f"window {window} (new)")
            else:
                window = caller.get("window")
                print(f"window {window or '(focused)'} (this one)")
            layout = build_workspaces(
                specs,
                argv_for,
                window,
                args.prefix,
                args.per_workspace,
                args.direction,
                focus,
            )
            layout["placement"] = placement
            layout["backend"] = "cmux"
            print(f"workspaces {', '.join(layout['workspaces'])}")

    started = time.time()
    records = []
    ready = {}
    while time.time() - started < args.timeout:
        if backend == "herdr":
            ready = {
                name: agent
                for name in wanted
                if (agent := herdr_agent_ready(name)) is not None
            }
        else:
            records = new_matching_records(before, wanted)
            ready = ready_by_name(records)
        if len(ready) == len(wanted):
            break
        time.sleep(2)

    elapsed = int(time.time() - started)
    if backend == "herdr":
        ready = {
            name: agent
            for name in wanted
            if (agent := herdr_agent_ready(name)) is not None
        }
    else:
        records = new_matching_records(before, wanted)
        ready = ready_by_name(records)
        if focus == "true" and layout["workspaces"]:
            # A new window opens on its own default workspace, so `--focus true`
            # on the first workspace does not stick. Select it again here, after
            # every session has booted. An earlier switch races the launch
            # command that cmux types into the new shell, and scrambles it.
            cmux("select-workspace", "--workspace", layout["workspaces"][0])

    for name, _ in specs:
        if name in ready:
            if backend == "herdr":
                agent = ready[name]
                print(f"+ {name:<24} pane {agent.get('pane_id', '?')}")
            else:
                record = ready[name]
                print(
                    f"+ {name:<24} pid {record['pid']:<7} "
                    f"uds:{record['messagingSocketPath']}"
                )
        else:
            print(f"- {name:<24} did not become ready in {args.timeout}s")

    missing = [name for name, _ in specs if name not in ready]
    if missing:
        print(
            f"\n{len(ready)}/{len(wanted)} ready after {elapsed}s. "
            "Check the pane — a stalled permission prompt never registers.",
            file=sys.stderr,
        )
        if backend == "herdr":
            print_cleanup_herdr(specs, layout)
        else:
            print_cleanup_cmux(records, layout)
        return 1

    print(f"\n{len(ready)} ready in {elapsed}s.")
    if backend == "herdr":
        print_cleanup_herdr(specs, layout)
    else:
        print("Send with a uds: address above, or a freshly resolved ListAgents name/ref.")
        print_cleanup_cmux(records, layout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
