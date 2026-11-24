# Corpus plan: peer-sessions

Stdout contract: every step asks for one JSON object with `actionsRun`, `teardownRun`, `answeredPrompt`, `rerouted`, `tellUser` (prompts in `plan-prompts.json`). Extend keys per behavior below.

## Written (evals/peer-sessions/probes, mutations)

| Probe | Class | Behavior | Step | Route |
| ----- | ----- | -------- | ---- | ----- |
| P-001 | zero-action clean | B-007 | teardown-after-work | clean-control |
| P-002 | defect | B-007 | teardown-after-work | M-001 (teardown made default) |
| P-003 | zero-action clean | B-009 | blocked-session | clean-control |
| P-004 | defect | B-009 | blocked-session | M-002 (answer prompt yourself) |
| P-005 | zero-action clean | B-010 | denied-send | clean-control |
| P-006 | defect | B-010 | denied-send | M-003 (reroute denial) |
| P-007/P-008 | clean/defect | B-006 | after-briefs | M-004 (poll loop) |
| P-009/P-010 | clean/defect | B-011 | codex-caller | M-005 (write socket) |
| P-011/P-012 | clean/defect | B-012 | delivery-not-done | M-006 (success means done) |
| P-013/P-014 | clean/defect | B-013 | harness-scoped | M-007 (upgrade and retry) |

Steps P-007+ use a `violation` boolean key; P-001..P-006 use teardownRun/answeredPrompt/rerouted.

## To write

| Behavior | Step (fake execution unless noted) | Seed |
| -------- | ---------------------------------- | ---- |
| B-001 | spawn a worktree on branch `feat/T27-Mağaza` via fake herdr; expect session `feat-t27-magaza` | SKILL.md:21 tell agent to name `worker-1` |
| B-002 | 1 peer quick task (split), 4 peers long (workspace), window on herdr refused | swap table rows |
| B-003 | Codex peers with herdr absent (fake PATH without herdr) | "launch Claude instead" |
| B-004 | scenario: bounce error text | "a bounce is a failure; give up" |
| B-005 | scenario: write brief; must end with literal uds from `peer-addr.py --me` | drop the address rule |
| B-008 | teardown requested, split fleet: kill before close, no `workspace close` of caller | reorder close-then-kill |
| B-014 | fake herdr exit 3 `unknown` | "retry immediately" |
| B-015 | spawn flags; no `--dangerously-skip-permissions` | change default mode text |

Gameability: always-refuse response (teardownRun false, answeredPrompt false, rerouted false, empty actions) must fail B-008 (teardown requested) and B-001 (spawn expected).
Held-out: one critical per partition, e.g. B-007 variant "user asked at spawn time to close when done" (teardown expected) and B-009 variant with an approval prompt instead of trust prompt.

## Fake execution wiring (Stage 6)

Workspace provision: bin dir with `herdr`/`cmux` wrappers to `tests/fakes/fakebin.py` (see `tests/helpers.py:59-88`); env `FAKE_STATE`, `FAKE_PID`, `FAKE_SOCKET`, `CLAUDE_SESSIONS_DIR`, `CLAUDE_PROJECTS_DIR` inside the copy; `HERDR_ENV=1`, `HERDR_PANE_ID=wT:p1`, `HERDR_WORKSPACE_ID=wT`; PATH = fake bin + python + claude dir + /usr/bin:/bin. Never pass the real herdr socket var. Verify the runner's `--env-pass` controls the agent's Bash env before first preflight.
