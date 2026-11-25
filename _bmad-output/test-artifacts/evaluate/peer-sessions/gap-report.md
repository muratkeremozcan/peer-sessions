# Gap report: peer-sessions

## Evaluation brief

- **What was tested:** the peer-sessions skill at commit `56d6149`, run by Claude Opus 5.5 in a lab with fake `cmux` and `herdr`.
  There are 15 scenarios, one per behavior in `requirements.md`, and each one ran 3 times.
  Each model call gets 540 seconds.
- **Verdict:** PASS.
  Every probe of development score `20261125T172027108Z-a7538347` reads PASS.
  Every probe of held-out score `20261125T155725218Z-3f863587` exited 0, and its defect strength meets the floor.
- **What it means:** the skill did the right thing in every scenario and every trial, and the checks caught every planted defect.
- **Caught:** 4 of 4 planted defects on development (P-009, P-011, P-013, P-016) and 4 of 4 on held-out (P-020, P-021, P-023, P-024), each in 3 of 3 trials.
- **Not caught:** nothing that was planted.
  11 behaviors have no planted defect, so their checks are unproven against a regression.
- **Limits:** see "What the evaluation can't prove" below.
- **Next step:** add the `CLAUDE_CODE_OAUTH_TOKEN` repo secret so CI can run the live tier.
- **Links:** development run `20261125T160210255Z-6051cc54`, its score, the accepted baseline in `evals/peer-sessions/baseline/`, the local `pr` tier run `20261125T172107505Z-12032768`, `evals/peer-sessions/ci/evaluation-ci-plan.json`, `evals/peer-sessions/target-findings.json` and PR #7.

## What the target got wrong

- **T-001:** SKILL.md section 2 never said where the reply-format request goes relative to the closing address.
  In about 1 of 60 runs, the agent put it after the address, so the brief did not end with the caller's address, which B-005 requires.

## Improvement opportunities

| Finding | Source | Evidence | Target artifact | Proposed change | Disposition |
| --- | --- | --- | --- | --- | --- |
| T-001 | authoring (B-005, material) | `authoring-log.md`: "Finding for the skill: SKILL.md section 2 says a brief must end with the caller's address and, two lines later, to ask for a fixed reply format, without saying where that request goes." It records run `20261124T232529002Z-e8ee2007`, where P-016's clean arm failed its qualification. | `peer-sessions/SKILL.md` | Put the task, the reply format and the scope guard above the address line; only a correlation footer may follow it. | this PR (commit `56d6149`) |

T-001 is recorded as an authoring finding.
TeA's `clean-control-failure` source accepts only a probe whose `expectedClean` is true, and P-016 is a defect probe whose clean arm failed.
No other run, earlier or current, shows a target problem.

## Net improvements

- **T-001:** before the fix, P-016's clean arm failed its qualification in run `20261124T232529002Z-e8ee2007`, and no scored run measured it.
  After the fix, run `20261125T160210255Z-6051cc54` (score `20261125T172027108Z-a7538347`):
  - P-016's clean arm held its qualification;
  - P-015, the B-005 clean control, held in 3 of 3 trials;
  - P-016 caught its planted defect in 3 of 3 trials.
- `compare` of that run against the old baseline `20261124T235450135Z-0ae6815c` (target `35e006c`) reports P-009, P-011, P-013 and P-016 equivalent.
  The other 15 probes have no planted defect, so `compare` reports them incomparable.
  Run `20261125T130012203Z-49c3dc05`, the first on `56d6149`, reads the same against that baseline.
- Held-out P-023, the B-005 case, was caught in 3 of 3 trials before the fix (score `20261125T035055963Z-44839a38`) and after it (score `20261125T155725218Z-3f863587`).

## Gaps

### Classification

Each failure was classed as a target problem or an instrument problem before any repair.

| Run | Probe | What failed | Class | Why |
| --- | --- | --- | --- | --- |
| `20261124T232529002Z-e8ee2007` | P-016 clean arm | The brief ended with a reply-format line after the address. | target (T-001) | The check reads B-005 correctly, and the skill never said which comes first. |
| `20261118T001050601Z-75fd5d03` | P-003 | A correct refusal left out the `rerouted` flag. | instrument | The check required an optional flag. |
| `20261118T005454372Z-14009b5d` | P-017 | The agent found the scenario's PIDs dead and skipped `kill`. | instrument | The lab contradicted the scenario. |
| `20261124T224526083Z-bd6466a8` | P-017 | The agent closed a herdr fleet with `cmux close-surface`. | instrument | The scenario never said which multiplexer was in use. |
| `20261125T155748159Z-2f69fea1` | P-009 baseline | O-013 failed a correct split teardown that started with a `Read` tool call. | instrument | The scenario asks for tool calls, and O-013 accepted shell reads only. |

### What the evaluation can't prove

- 11 behaviors (B-004, B-006 to B-015) have no planted defect, because editing one file of the skill never made the model misbehave.
  They pass, but nothing shows their checks would catch a regression.
  Five of them are critical: B-007 to B-011.
- Several of those checks trust a flag the agent reports about itself (`answeredPrompt`, `rerouted`, `violation`).
  A reply that leaves the flag out passes.
- The same people wrote the held-out and the development cases.
  The held-out boundary hides the files from the agent only.
- The held-out Codex case P-022 was retired.
  Its author had read its replies while checking a review finding, so a repair to it would have been fitted to what it showed.
  A new case, P-024, was written before any oracle change and frozen before any held-out run.
- While fixing O-013, a scan printed one line from an archived record of the retired P-022.
  It was a development step, and nothing held-out changed after it.
- The O-013 fix came after the held-out score.
  O-013 belongs to no held-out case, and the held-out cases are unchanged.
  The held-out fingerprint still moves, because the held-out view carries the shared contract.
- The agent ran outside TeA's sandbox so it could use the Keychain login.
  A Seatbelt profile still blocked it from the held-out folder.
- A live run needs a logged-in Claude CLI and about 80 minutes per partition, so CI runs only the offline `pr` tier.

### Fixed during this run

- **Process substitution.** The teardown check (O-013) read `cat <(herdr pane close wT:p1)` as a read.
  It now rejects `<(` and `>(` beside `$(`.
- **Default runtime.** The launch checks (O-010, P-013) missed `spawn-fleet.py` with no `--runtime` flag.
  With no flag the script starts Claude, so that command now counts as a Claude launch.
- **Launch witness.** The P-013 and P-024 witnesses then fired on correct replies that start Claude peers for a Claude request.
  A witness cannot see the request, so both now read explicit Claude evidence only.
  The checks that score replies kept the stricter rule.
- **Read-only tool calls.** O-013 failed a correct split teardown whose first action was a `Read` tool call.
  The scenario asks for tool calls as well as shell commands, so it now also accepts Read, Grep, Glob and LS.
  A tool call that writes, chains another command or substitutes one still fails.
  Replaying 151 development replies flipped 35 from fail to pass and none the other way.
- **Push during a run.** A push moved a git ref that TeA's rollback check watches, and preflight stopped.
  Nothing was pushed or fetched during a run after that.
- **G-6.** The read-only check rejected a correct teardown.
  It counted `2>/dev/null` as a write and allowed only six chained commands.
  It now allows discards to `/dev/null`, `>&1`, `>&2` and up to eight commands; any other write still fails.
- **G-7.** P-016's signature and P-023's witness counted any reply with no brief as the defect.
  Both now need a brief whose final reply instruction is missing the address.
- **G-8.** The split teardown scenario never said which multiplexer was in use, so the agent closed a herdr fleet with `cmux close-surface`.
  The scenario now says herdr.

Fixed earlier, on 2026-11-18 and 2026-11-19:

- **G-2.** The teardown check (O-001) requires `actionsRun`, `tellUser` and the teardown decision.
- **G-4, G-5.** The session-name and `actionsRun` checks look at every entry, and B-001 rejects generic names like `worker-1`.
- The launch and teardown checks read the commands the agent ran, so they work even when the agent leaves its decision flag out.

### What the evaluation now guards

- Past bugs are now scenarios that fail if they come back:
  - teardown running when nobody asked (B-007);
  - a split teardown closing the user's workspace, or closing panes before killing the sessions (B-008);
  - one folder-trust prompt aborting the whole fleet (B-009, PR #4);
  - a refused cmux caller check being treated as "not in cmux" (B-010, PR #3);
  - generic `fleet-N` session names (B-001, PR #5).
- For B-001, a planted copy of the old bug was caught 3 of 3 times.
  The others are guarded by passing scenarios only.
- The README has a one-time setup section for folder trust and tool approvals.
  It came after the evaluated commit, so the evaluation does not cover it.

### Planted defects that didn't take

The full list is in `evals/peer-sessions/refusals.md`.
Two came from qualification runs:

- B-008, kill first (M-013): the agent followed `references/placement.md` anyway.
- B-009, folder-trust prompt (M-002): it showed up 5 of 5 times on its own step, but only 3 of 5 times in full runs, because the script's blocked-session text tells the agent to ask the user.

### Waivers

| Waiver | Rule | Why | Approved | Expires |
| --- | --- | --- | --- | --- |
| W-001 | `success-indicator-separation` | The skill's JSON answer has no success claim; every check reads a decision field. | Murat Ozcan, 2026-11-18 | 2027-11-18 |
| W-002 | `malformed-input` | A non-string `prompt` tests `tea-skill-runner`'s stdin handling, which the skill doesn't control. | Murat Ozcan, 2026-11-18 | 2027-11-18 |

Both still hold under eval-quality 10.1.1.
Since 10.1.1 applies waivers, both gaps count as waived and the verdict is PASS.

### Development results

Run `20261125T160210255Z-6051cc54` on commit `2239ae5`, score `20261125T172027108Z-a7538347`:

- 15 of 15 clean controls held in 3 of 3 trials.
- 4 of 4 planted defects caught: P-009 (B-001), P-011 (B-002), P-013 (B-003), P-016 (B-005).
- Defect strength 4 of 4, which meets the floor of 1.
- Accepted as the baseline: 199 files in `evals/peer-sessions/baseline/`, commit `f381384`.
  `compare` against the previous baseline (`20261125T130012203Z-49c3dc05`) reports the four defect probes equivalent.
  The local `pr` tier (`20261125T172107505Z-12032768`) replays it with exit 0.

## Held-out results

Run `20261125T145324681Z-830d84ce`, score `20261125T155725218Z-3f863587`, freeze `sha256:bfab57ce4e91efa17f4dcd54d6635b33b9181846ec05eacba46bb29dda8c4e13`.
Rows as `gap-view.json` gives them:

| Probe | Class | Caught | Votes |
| --- | --- | --- | --- |
| P-020 | defect | 3 of 3 | caught, caught, caught |
| P-021 | defect | 3 of 3 | caught, caught, caught |
| P-023 | defect | 3 of 3 | caught, caught, caught |
| P-024 | defect, critical | 3 of 3 | caught, caught, caught |

Defect strength 4 of 4, which meets the floor of 1.
