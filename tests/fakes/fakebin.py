"""Fake `herdr` and `cmux` executables for deterministic tests.

Installed into a temp PATH directory under both names. Every call is appended
to calls.jsonl in $FAKE_STATE, so tests assert on the exact commands, their
order and their side effects. Nothing here talks to a real multiplexer.

Scenario ($FAKE_STATE/scenario.json):
  rules:  [{"tool": "herdr", "match": ["agent", "start", "beta"], "times": 1,
            "exit": 1, "stderr": "...", "stdout": "..."}]
          First rule whose tokens all appear, in order, in argv wins.
  agents: {"name": {...}} live herdr agents before the launch
  status: {"name": "blocked"} agent_status reported by `agent get`
  occupant: {"name": {...}} fields to override in `agent get` (identity drift)
  caller: cmux identify payload
  register: true -> a claude launch writes a registry record (pid $FAKE_PID)
"""

import json
import os
import shlex
import sys
import uuid


STATE = os.environ["FAKE_STATE"]
# runpy.run_path rewrites argv[0], so the wrapper names the tool explicitly.
TOOL = os.environ.get("FAKE_TOOL") or os.path.basename(sys.argv[0])
ARGS = sys.argv[1:]


def path(name):
    return os.path.join(STATE, name)


def load(name, default):
    try:
        with open(path(name)) as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default


def save(name, value):
    with open(path(name), "w") as handle:
        json.dump(value, handle)


def contains_in_order(argv, tokens):
    position = 0
    for token in tokens:
        try:
            position = argv.index(token, position) + 1
        except ValueError:
            return False
    return True


def apply_rules(scenario):
    rules = scenario.get("rules", [])
    used = load("rules-used.json", {})
    for index, rule in enumerate(rules):
        if rule.get("tool", TOOL) != TOOL or not contains_in_order(ARGS, rule["match"]):
            continue
        times = rule.get("times", 1)
        if used.get(str(index), 0) >= times:
            continue
        used[str(index)] = used.get(str(index), 0) + 1
        save("rules-used.json", used)
        sys.stdout.write(rule.get("stdout", ""))
        sys.stderr.write(rule.get("stderr", ""))
        sys.exit(rule.get("exit", 1))


def counter(name):
    counts = load("counters.json", {})
    counts[name] = counts.get(name, 0) + 1
    save("counters.json", counts)
    return counts[name]


def register_claude(argv, cwd):
    """Simulate a Claude session publishing its registry record."""
    scenario = load("scenario.json", {})
    if not scenario.get("register", True) or not argv or argv[0] != "claude":
        return
    name = argv[argv.index("--name") + 1] if "--name" in argv else None
    session_id = str(uuid.uuid4())
    record = {
        "pid": int(os.environ["FAKE_PID"]),
        "sessionId": session_id,
        "procStart": f"fake-{session_id[:8]}",
        "name": name,
        "cwd": cwd,
        "startedAt": counter("started"),
        "messagingSocketPath": os.environ.get("FAKE_SOCKET"),
        "version": "2.1.300",
    }
    sessions = os.environ["CLAUDE_SESSIONS_DIR"]
    with open(os.path.join(sessions, f"{session_id}.json"), "w") as handle:
        json.dump(record, handle)


def ok(result):
    print(json.dumps({"id": "fake", "result": result}))
    sys.exit(0)


def error(code, message):
    sys.stderr.write(json.dumps({"error": {"code": code, "message": message}, "id": "fake"}))
    sys.exit(1)


def herdr():
    scenario = load("scenario.json", {})
    agents = load("agents.json", scenario.get("agents", {}))
    panes = load("panes.json", {})
    if ARGS[:2] == ["agent", "get"]:
        name = ARGS[2]
        agent = agents.get(name)
        if agent is None:
            error("agent_not_found", f"agent target {name} not found")
        agent = dict(agent)
        if name in scenario.get("status", {}):
            agent["agent_status"] = scenario["status"][name]
        agent.update(scenario.get("occupant", {}).get(name, {}))
        ok({"agent": agent, "type": "agent_info"})
    if ARGS[:2] == ["pane", "split"]:
        anchor = ARGS[ARGS.index("--pane") + 1]
        workspace = anchor.split(":")[0]
        pane_id = f"{workspace}:p{counter('pane-' + workspace) + 1}"
        panes[pane_id] = {"cwd": ARGS[ARGS.index("--cwd") + 1], "workspace": workspace}
        save("panes.json", panes)
        ok({"pane": {"pane_id": pane_id, "workspace_id": workspace}})
    if ARGS[:2] == ["workspace", "create"]:
        workspace = f"wF{counter('workspace')}"
        root = f"{workspace}:p1"
        panes[root] = {"cwd": ARGS[ARGS.index("--cwd") + 1], "workspace": workspace}
        save("panes.json", panes)
        ok(
            {
                "workspace": {"workspace_id": workspace},
                "tab": {"tab_id": f"{workspace}:t1"},
                "root_pane": {"pane_id": root},
            }
        )
    if ARGS[:2] == ["agent", "start"]:
        name = ARGS[2]
        kind = ARGS[ARGS.index("--kind") + 1]
        pane_id = ARGS[ARGS.index("--pane") + 1]
        native = ARGS[ARGS.index("--") + 1 :] if "--" in ARGS else []
        agent = {
            "agent": kind,
            "agent_status": "idle",
            "interactive_ready": True,
            "name": name,
            "pane_id": pane_id,
            "terminal_id": f"term_{name}",
            "workspace_id": pane_id.split(":")[0],
            "cwd": panes.get(pane_id, {}).get("cwd"),
        }
        agents[name] = agent
        save("agents.json", agents)
        register_claude([kind, *native], agent["cwd"])
        ok({"agent": agent, "type": "agent_started"})
    if ARGS[:1] in (["workspace"], ["pane"]) and ARGS[1:2] == ["close"]:
        ok({})
    error("fake_unsupported", f"fake herdr does not model: {ARGS}")


def cmux():
    scenario = load("scenario.json", {})
    args = ARGS[2:] if ARGS[:2] == ["--id-format", "both"] else ARGS
    if args[:1] == ["identify"]:
        print(json.dumps({"caller": scenario.get("caller", {})}))
        sys.exit(0)
    if args[:1] == ["new-split"]:
        number = counter("surface")
        print(f"OK surface:{number} ({uuid.UUID(int=number)}) workspace:1")
        sys.exit(0)
    if args[:1] == ["new-workspace"]:
        number = counter("workspace")
        cwd = args[args.index("--cwd") + 1]
        register_claude(shlex.split(args[args.index("--command") + 1]), cwd)
        print(f"OK workspace:{number}")
        sys.exit(0)
    if args[:2] == ["tree", "--all"]:
        count = load("counters.json", {}).get("workspace", 0)
        for number in range(1, count + 1):
            print(f"workspace workspace:{number} {uuid.UUID(int=1000 + number)}")
        sys.exit(0)
    if args[:1] == ["new-window"]:
        print(f"OK {uuid.UUID(int=9999)}")
        sys.exit(0)
    if args[:1] == ["send"]:
        save("last-send.json", args[-1])
        sys.exit(0)
    if args[:1] == ["send-key"]:
        command = load("last-send.json", "")
        if command.startswith("cd "):
            directory_part, _, launch = command.partition(" && ")
            register_claude(shlex.split(launch), shlex.split(directory_part)[1])
        print("OK")
        sys.exit(0)
    if args[:1] in (["select-workspace"], ["close-surface"], ["close-workspace"]):
        print("OK")
        sys.exit(0)
    print(f"Error: fake cmux does not model: {args}")
    sys.exit(1)


def main():
    with open(path("calls.jsonl"), "a") as handle:
        handle.write(json.dumps([TOOL, *ARGS]) + "\n")
    apply_rules(load("scenario.json", {}))
    if TOOL == "herdr":
        herdr()
    cmux()


if __name__ == "__main__":
    main()
