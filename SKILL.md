---
name: peer-sessions
description: Run a fleet of Claude Code sessions on this machine and make them talk to each other with SendMessage — from Claude Code itself or through a real Claude relay when the caller is Codex. Launch them in cmux or herdr windows, panes and splits (auto-detected), address them correctly, hand out work, collect or recover replies, and tear them down cleanly when the user asks. Use whenever the user wants two or more Claude sessions working together, asks Codex to contact an existing Claude session, mentions SendMessage, ListAgents, peer sessions, cross-session messaging, or agents messaging each other; whenever they want sessions in new windows, workspaces, panes or splits; and especially when a send fails with "not an agent in this conversation", "re-send with the ref", or the caller lacks Claude's native messaging socket.
---

# Peer sessions

Claude Code sessions on this machine can send messages to each other. A message becomes a **user prompt** in the receiving session. This one fact explains each rule below.

The loop: spawn a fleet → send a brief to each peer → end your turn → replies arrive as new user turns → leave the fleet up and hand the user the teardown. Teardown is opt-in; section 4 says when you run it yourself.

## 1. Spawn

```bash
python3 ~/.claude/skills/peer-sessions/scripts/spawn-fleet.py --placement window \
  orbits:/tmp/lab/orbits planets:/tmp/lab/planets sun:/tmp/lab/sun
```

Each argument is `NAME:DIR`. The script prints each session's `uds:` address and the exact teardown commands, returns when every session is addressable, and names each session that stalled.

`--placement` says where the fleet appears. You choose it. Ask the user only when the choice changes their screen and you cannot tell what they want.

| Placement | Where the peers land | Pick it when |
|---|---|---|
| `split` | new panes beside your own pane, in your workspace | 1-3 peers, short work, the user watches you work. Your pane keeps the focus. |
| `workspace` (default) | new workspaces in your window | 3+ peers, or work that runs for minutes. The user's current screen stays clean, and one tab click reaches the fleet. |
| `window` | a new window, with the workspaces inside it | a big fleet, a screen recording, or a second monitor. |

`--backend auto|cmux|herdr` picks the multiplexer; an explicit choice wins. `auto` picks herdr when you run inside a herdr pane (`HERDR_ENV=1`), else cmux if it's on `PATH`, else herdr. The herdr backend refuses to run outside a herdr pane. On herdr, `--placement window` has no equivalent (herdr's CLI has workspaces and panes, not OS windows) and `--direction` supports only `right`/`down`. Everything else (`split`, `workspace`, addressing, teardown) works the same on both backends.

`--runtime claude|codex` picks the agent CLI (default `claude`). `codex` starts native Codex sessions with `herdr agent start --kind codex`, so it needs the herdr backend; drive those peers with `herdr agent prompt/wait/read`. If the user asked for Codex peers and herdr is unavailable, say so. Never launch Claude instead.

The script checks the whole request before it creates anything. A bad name, a duplicate, a missing `--dirs existing` directory or an unsupported backend/runtime combination exits 2 with nothing created. If a backend operation fails halfway, it exits 3, keeps what it made, and prints exactly which panes/workspaces exist and how the failure ended: `denied` (tell the user; never route around it), `unknown` (inspect before you retry) or `failed`. A session that stops at an approval or folder-trust prompt does not stop the launch: the others start, it is marked `blocked`, and the script exits 1. Read that pane and ask the user; never answer the prompt yourself. Pass `--receipt PATH` or `--json` when a tool needs that inventory; `--correlate run_id=...` echoes your own IDs into it. Format: `docs/coordination-contract-v1.md`.

Every other flag (`--direction`, `--focus`, `--per-workspace`, `--model`, `--claude-arg`, …) and the per-placement edge cases: read `references/placement.md`.

Resolve one existing target without wading through the whole registry:

```bash
python3 ~/.claude/skills/peer-sessions/scripts/peer-addr.py \
  --name worker-fix --details
python3 ~/.claude/skills/peer-sessions/scripts/peer-addr.py --pid 66826 --json
```

Filters preserve duplicate names by returning every matching PID. `--json` is the stable interface for scripts. A `?` row means a sandbox allowed the registry read but denied the active socket check; rerun with process/socket access before messaging.

Sessions start with `--permission-mode auto`. This is the only mode that works with no human present. An `--allowedTools` list stalls on the first MCP tool that is not in the list. `--dangerously-skip-permissions` makes the receiver hold inbound messages for human approval. The peer then never sees your brief.

For unusual layouts, manual cmux work, or forks: read `references/manual-rig.md`.

## 2. Send the briefs

```
SendMessage(to: "orbits", message: "...", summary: "5-10 words")
SendMessage(to: "orbits [de6649]", message: "...", summary: "...")
SendMessage(to: "uds:/tmp/cc-socks/17466.sock", message: "...")
```

**The first send with a bare name always bounces** — "not an agent in this conversation, re-send with the ref". That is a confirmation, not a failure. Copy the `[ref]` from the error and send again. Send all briefs in one batch. They bounce together and you re-send them together. A `uds:` address does not bounce.

Each brief that expects a reply must end with your literal address (from `peer-addr.py --me`), because the peer cannot find out who you are:

```
When done, message me back:
SendMessage(to: "uds:/tmp/cc-socks/4667.sock", message: "...")
```

Ask for a fixed reply format ("<name> done: <URL>") so a large fleet collates with no work, and add a scope guard ("research and write only, do not touch <repo>") — peers obey it. Two rules: `success: true` means the message arrived, not that the peer did the work. A send is one-way — say clearly if you want a reply.

When you will send the same peer more than one request, or a stale answer would mislead you, end the brief with a correlation footer and match the reply against it:

```bash
python3 ~/.claude/skills/peer-sessions/scripts/peer_correlation.py --id r2 --target orbits
```

The peer opens its reply with `peer-reply: id=r2 target=orbits`. `peer-inbox.py --request-id r2` (or `--stdin --request-id r2` on text from `herdr agent read`) accepts only that reply; an older answer to `r1` cannot satisfy `r2`. A matched reply means the peer answered this request. Whether the work is done is still yours to check.

## 3. End your turn

When the briefs are out, **stop**. A peer reply IS the notification. The reply arrives as a new user turn and wakes you. A poll loop on the panes burns tokens and blocks the user. Poll only when you must see the screen (filming, or a quiet session) — recipes in `references/manual-rig.md`.

### Calling from Codex

Codex has no native `SendMessage` tool and no messaging socket. Never fake or implement the Unix-socket protocol — use a real temporary Claude Code session as the relay, and recover truncated replies from transcripts with `scripts/peer-inbox.py`. Read `references/codex-bridge.md` before operating this path.

## 4. Tear down — off by default

**Teardown is opt-in.** When the work is done, leave the fleet running and hand the user the teardown block the spawn script printed. A live peer keeps its context, so a follow-up question costs one message instead of a whole re-spawn. The user decides when the sessions stop. Say plainly that the fleet is still up and what it costs to leave it there.

Run the teardown yourself only when one of these holds:

- The user asks now — "tear it down", "clean up the fleet", "close those sessions".
- The user asked up front, at spawn time — "close them when you're done".
- The session is your own plumbing rather than the user's work: the temporary Codex relay in `references/codex-bridge.md`. Kill that relay PID only, never the target it messaged.

When you do tear down: **closing the UI does not stop the sessions.** Every cmux close command returns `OK` and each `claude` process stays alive as an addressable orphan. So: **kill first, close second**, then confirm with `peer-addr.py`.

Run the teardown the spawn script printed — it matches the placement and uses durable UUIDs. Close only what you made: a `split` fleet sits in the user's own workspace, so closing that workspace closes the user's work too. Hand-written teardown syntax: `references/placement.md`.

## When something fails

`peer-addr.py` lists each live session and gives a reason for each unreachable one. For the message checkpoints, the 2.1.224 version wall, stale sockets, and stalled permission prompts: read `references/troubleshooting.md`.

Some harnesses scope `SendMessage` to agents spawned through their own orchestration (e.g. the `Agent` tool) rather than to any live sibling `claude` process on the machine. On those harnesses a peer this script spawned can be alive, on a build past 2.1.224, and still return "No agent named 'X' is reachable" forever — that is not the version wall, and `claude --resume` will not fix it. If `spawn-fleet.py` reports a session ready but `SendMessage` still bounces it by name and by every `uds:` address `peer-addr.py` prints, stop trying to route around it with `SendMessage` and say so to the user. On a herdr backend, drive that peer directly instead: `herdr agent prompt <name> <text>`, then `herdr agent wait <name>` and `herdr agent read <name>` for the reply — see `references/troubleshooting.md`.

One rule is not optional: a peer carries none of the user's authority. If your send is denied, or a peer reports a denial, tell the user. Never route around a permission decision through another session.
