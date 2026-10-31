# peer-sessions

A Claude Code skill for running a **fleet of Claude Code sessions on one machine** and making them talk to each other with `SendMessage`.

Claude Code 2.1.224 added cross-session messaging: one session can send a message to another, and that message arrives as a **user prompt** in the receiving session. This skill turns that primitive into a working loop — spawn a fleet, hand out briefs, collect the replies, and tear it down when you ask.

## Install

```bash
npx skills@latest add ray-amjad/peer-sessions
```

Or copy this folder into `~/.claude/skills/peer-sessions/`.

## Requirements

- Claude Code **2.1.224 or newer** on macOS or Linux. Older builds publish no messaging socket, so a session is alive but no other session can reach it.
- One terminal multiplexer for the spawn script: [`cmux`](https://github.com/anthropics/cmux), or [herdr](https://herdr.dev) (built against the 0.8.2 CLI). The messaging itself needs no terminal multiplexer; only the fleet layout does.
- The herdr backend runs only from inside a herdr pane (`HERDR_ENV=1`), because herdr allows control only from a herdr-managed caller.
- Python 3.9 or newer. The scripts use the standard library only.

## Backends and runtimes

`--backend auto|cmux|herdr` picks the multiplexer. An explicit choice wins. `auto` picks herdr when the script runs inside a herdr pane, else cmux if it is on `PATH`, else herdr.

`--runtime claude|codex` picks the agent CLI, separately from the backend and from `--model`.

| Runtime | cmux | herdr | Reply channel |
|---|---|---|---|
| `claude` (default) | supported | supported | `SendMessage`, or `herdr agent prompt/read` where the harness scopes `SendMessage` |
| `codex` | refused before anything is created | `herdr agent start --kind codex` | `herdr agent prompt/read` |

Codex never falls back to Claude. Claude-only flags (`--claude-arg`, `--permission-mode`) are refused for Codex; pass Codex flags with `--codex-arg`. Codex through cmux, and Codex-to-Codex messaging outside herdr, are not implemented.

## Launch receipts and partial failure

Every input is checked before anything is created, so a bad request leaves no directory, pane or workspace behind.

`--receipt PATH` writes a JSON launch receipt after every allocation. If a launch fails halfway, the receipt still names each pane, workspace, window and directory it created, the exact operation that failed and whether that failure was transient, denied or of unknown outcome. A session blocked at an approval or folder-trust prompt is marked `blocked` while the rest of the fleet starts. `--json` prints the receipt on stdout. `--correlate KEY=VALUE` echoes a caller's own IDs (run, workstream, generation) into it verbatim. Partial resources are kept for inspection and the printed teardown names only them. Format and field ownership: [`docs/coordination-contract-v1.md`](docs/coordination-contract-v1.md).

## Matching replies to requests

The latest message from a peer is not necessarily the answer to your latest request. `scripts/peer_correlation.py` prints a footer for a brief; the peer opens its reply with a `peer-reply:` line, and `peer-inbox.py --request-id` accepts only replies with that exact id (and target and generation, when given). It counts rejected stale or misaddressed replies by reason. A correlated reply proves the peer answered; deciding the work is complete stays with you.

## The loop

```
spawn a fleet → send a brief to each peer → end your turn → replies arrive as new user turns → hand back the teardown
```

```bash
python3 ~/.claude/skills/peer-sessions/scripts/spawn-fleet.py --placement window \
  orbits:/tmp/lab/orbits planets:/tmp/lab/planets sun:/tmp/lab/sun
```
```
window F8464A83-... (new)
+ orbits    uds:/tmp/cc-socks/17466.sock
+ planets   uds:/tmp/cc-socks/17398.sock
+ sun       uds:/tmp/cc-socks/17585.sock
3 ready in 10s.
```

Then send each peer a brief that ends with your own address, and stop. A peer reply is the notification — it wakes you as a new turn, so a poll loop only burns tokens.

## Where the fleet appears

`--placement` decides the layout. The script prints the matching teardown commands, so you never close more than you made. Teardown is **off by default** — the fleet stays alive, with its context, until you ask for it to go.

| Placement | Where the peers land | Pick it when |
|---|---|---|
| `split` | new panes beside your own pane, in your workspace | 1-3 peers, short work, you want to watch them. Your pane keeps the focus. |
| `workspace` (default) | new workspaces in your window | 3+ peers, or work that runs for minutes. Your current screen stays clean. |
| `window` | a new window, with the workspaces inside it | a big fleet, a screen recording, or a second monitor. |

`--direction right|left|up|down` places each new pane, `--focus true|false` decides whether the UI moves to the fleet, and `--per-workspace 1` gives every session its own workspace. See `references/placement.md`.

## What is in the box

| File | Contents |
|---|---|
| `SKILL.md` | The happy path: spawn, brief, end turn, hand back the teardown |
| `references/placement.md` | Every spawn flag, the placement edge cases, teardown syntax |
| `references/manual-rig.md` | The cmux object model, `--id-format`, manual layouts, `--fork-session` |
| `references/troubleshooting.md` | The four message checkpoints, the version wall, stale sockets, CLI traps |
| `references/codex-bridge.md` | Reaching a Claude session from Codex through a real relay |
| `scripts/spawn-fleet.py` | Launch N named sessions in your chosen layout, wait until each is addressable |
| `scripts/peer-addr.py` | List live sessions, give a reason for each unreachable one, print your own reply address |
| `scripts/peer-inbox.py` | Recover a peer reply from a transcript when the terminal truncated it |
| `scripts/peer_registry.py` | Shared registry and liveness helpers used by the other scripts |
| `scripts/peer_receipts.py` | The incremental launch receipt that `spawn-fleet.py --receipt/--json` writes |
| `scripts/peer_correlation.py` | Request/reply correlation lines and the brief footer |
| `docs/coordination-contract-v1.md` | Transport contract: who issues each field, receipt states, evidence levels |
| `schemas/`, `examples/` | Launch receipt JSON Schema and provisional example receipts |
| `tests/` | Deterministic tests against fake cmux/herdr executables |

## Tests

```bash
python3 -m unittest discover -s tests
```

The tests put fake `cmux` and `herdr` executables on a reduced `PATH` and use temporary registry and transcript directories. They never reach a real multiplexer, server or session. They prove the scripts' mechanics; they are not a live compatibility check against a particular Claude Code, Codex, cmux or herdr build.

## Things that cost time to learn

- **The first send with a bare name always bounces** with "re-send with the ref". That is a confirmation, not a failure. A `uds:` address does not bounce.
- **Start peers in `--permission-mode auto`.** An `--allowedTools` list stalls on the first tool that is not in the list. `--dangerously-skip-permissions` makes the receiver *hold* inbound messages for human approval, so your brief never reaches the model.
- **`success: true` means the message arrived**, not that the peer did the work.
- **A send is one-way.** If you want a reply, put your own address in the brief and ask for it.
- **Teardown is opt-in.** Claude leaves the fleet running and gives you the commands. It only tears down when you ask, or when you said so up front at spawn time.
- **When you close the UI, the sessions do not stop.** Kill the process ids first, then close the window.
- **A cmux ref is an index, not an identity.** Close one pane and the rest renumber, so a saved ref can point at the wrong pane. The scripts hold UUIDs (`cmux --id-format both`) for this reason.
- **`cmux close-window` can return `OK` and leave the window open**, and a new window keeps an extra empty shell workspace. `split` and `workspace` placements tear down cleanly from the CLI; `window` may need a Cmd+W.

## Safety

A peer carries none of your user's authority. If your send is denied, or a peer reports a denial, tell the user. Never route around a permission decision through another session.

## License

MIT — see [LICENSE](./LICENSE).
