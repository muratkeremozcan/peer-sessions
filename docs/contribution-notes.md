# Contribution notes

Base: upstream `ray-amjad/peer-sessions` `main` at `6086667d30107467e618188e6f4659a20c0f42c8` (merge of PR #2, the herdr backend).
Fork: `muratkeremozcan/peer-sessions`.
License: MIT, Ray Amjad's copyright notice unchanged.

## Scope

Transport-level fixes only:

1. Validate the whole request before any side effect: names (including herdr's name rule and live-name clashes), duplicates after whitespace normalization, directories, backend/runtime/placement/direction combinations, split caller context.
   `--dirs existing` refuses missing directories; the default still creates them, after validation.
2. Explicit `--backend auto|cmux|herdr`.
   `auto` prefers herdr when running inside a herdr pane, then keeps the original cmux-first PATH order.
   The herdr backend refuses to run without `HERDR_ENV=1`, matching herdr's own control rule.
3. Explicit `--runtime claude|codex`, separate from backend and model.
   Codex is herdr-only, receives no Claude flags, and is never replaced by Claude.
4. herdr 0.8 error envelopes on stderr, with outcomes that keep transient, blocked, denied, unknown and failed apart.
   Only `agent_pane_busy` is retried.
5. Incremental launch receipts (`--receipt`, `--json`) that survive a mid-launch failure, record only resources this launch created, and bind Claude PIDs by registry identity instead of by name.
   Exit 3 on a mid-launch failure; nothing is torn down automatically.
6. Request correlation (`peer_correlation.py`, `peer-inbox.py --request-id/--target/--generation/--since/--stdin`) so an old reply cannot answer a new request.
7. Deterministic tests against fake cmux/herdr executables, a receipt JSON Schema, provisional examples, and a CI workflow.

Out of scope: TreeHouse or other workspace provisioning, coordinator run/workstream semantics, scheduling, merge or release policy, any daemon or socket protocol, Codex through cmux, and live compatibility qualification.

## Relationship to upstream PR #3

`placement-defaults-and-backend-identity` (`3bb03bb`, open) also adds `HERDR_ENV`-aware detection and changes the default placement to follow fleet size.
This branch reimplements only the detection rule, under an explicit `--backend` flag, and leaves the placement default unchanged.
The two touch the same lines; whichever lands second needs a small rebase.
PR #3 also commits two `__pycache__` files; this branch adds a `.gitignore` for them.

## Behavior changes a current user would notice

- The herdr backend now exits 2 outside a herdr pane instead of attempting control.
- Invalid requests exit 2 (argparse) instead of 1, and create no directories.
- A mid-launch backend failure exits 3 with a retained inventory, instead of a Python traceback.
- On herdr, readiness also checks the agent kind and terminal (or pane) identity, so a reused name is not reported as this launch's session.

## Known limits

- herdr exposes no PID for agents. herdr-launched Claude sessions get a PID only when exactly one new registry record matches their name and cwd.
- Denial detection for herdr and cmux matches permission/denied wording in the error; no structured denial code was observed in herdr 0.8.2.
- The tests prove mechanics against fakes built from herdr 0.8.2's documented CLI and observed responses. No live fleet was launched to produce them.

## Proposed upstream PR description

> **Validate before launching, select backend and runtime explicitly, and keep a receipt of partial launches**
>
> `spawn-fleet.py` used to create directories before rejecting duplicate names, picked cmux whenever it was on PATH even inside a herdr pane, and lost track of panes it had already created when a later launch failed.
> This change checks the whole request first, adds `--backend` and `--runtime` (native Codex on herdr), classifies herdr's stderr error envelopes so only the known pane-busy race is retried, and writes an incremental JSON receipt naming exactly what each launch created.
> It also adds a small request-correlation helper so `peer-inbox.py` can tell a reply to this request from an older one.
> Existing Claude invocations keep their commands and output.
> Tests run against fake cmux/herdr executables and need no multiplexer.
