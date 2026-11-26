# Authoring log: peer-sessions

Target: `SKILL.md` at repository root, revision `35e006c`.
Host: Claude Code 2.1.325; herdr 0.8.2 (`HERDR_ENV=1`); cmux not installed.
Parent model: claude-opus-5-5.

## Stages

| Stage | Started (UTC) | Completed (UTC) | Artifacts | Next gate |
| ----- | ------------- | --------------- | --------- | --------- |
| 1 Inspection | 2026-11-17T19:38:46Z | 2026-11-17T19:42:10Z | `inspection-record.md` | intake |
| 2 Intake | 2026-11-17T19:42:10Z | 2026-11-17T19:52:00Z | `requirements-statement.md`, `evals/peer-sessions/requirements.md` | confirmed by Murat Ozcan |
| 3 Corpus | 2026-11-17T19:52:00Z | 2026-11-17T21:20:00Z | `evals/lab/build_corpus.py`, probes, mutations, `refusals.md` | contract |
| 4-9 Contract, oracles, adapters, evaluator, mutation, harness | 2026-11-17T20:00:00Z | 2026-11-18T01:40:00Z | `contract.json`, policy, registry, fake lab | development run |
| 10 Run (development) | 2026-11-17T22:25:04Z | 2026-11-18T03:10:00Z | run `20261118T014042454Z-ba2e74a6` | gaps |
| 11 Gaps and held-out | 2026-11-18T03:10:00Z | 2026-11-18T05:16:00Z | `gap-report.md`, held-out run `20261118T035321024Z-694e9773` | Murat: waivers G-1, G-3 |
| 12 CI | 2026-11-18T05:16:00Z | 2026-11-18T05:30:00Z | `ci/evaluation-ci-plan.json` | baseline after gap rerun, then framework hand-off |

## Worker tasks

| Task | Dispatched | Completed | Scope | Context | Requested tier | Resolved model | Outcome | Retries | Parent verification | Tokens / cost |
| ---- | ---------- | --------- | ----- | ------- | -------------- | -------------- | ------- | ------- | ------------------- | ------------- |
| W1 test inventory | 2026-11-17T19:39:05Z | 2026-11-17T19:40:16Z | `tests/` (7 files) | isolated | Haiku (latest) | haiku alias, exact ID not exposed | adopted | 0 | spot-checked helpers.py:59-99, fakebin.py:260-268 | 103,604 tokens |
| W2 failure history | 2026-11-17T19:39:05Z | 2026-11-17T19:40:15Z | git log, PRs #1-#5 | isolated | Haiku (latest) | haiku alias, exact ID not exposed | adopted; 3 entries marked inferred | 0 | `git show 65eb358 a8687f7`, manual-rig.md:80-92 | 92,757 tokens |

Source inventory digest before and after workers: `97f0f653…a0d4` (unchanged).

## First `tea-evaluate check` (2026-11-17, exit 10, 36 defects)

Command: `npm exec --prefix evals -- tea-evaluate check --evaluation evals/peer-sessions` from `evals/`.
Blocking design issue: `launch.skillRoot` cannot be `.`, and every mutation of `SKILL.md` is "outside the skill root". The skill lives at the repository root. Options: `launch.root` = `../../..` (my-skills, 5 skills copied per trial) with `skillRoot` = `peer-sessions`, or move the skill into a subdirectory. Pick before the next check.
Contract draft copied the HTTP-shaped operation from the fixture; a `cli` operation needs the cli schema (no `method`/`pathTemplate`; `invocation` belongs elsewhere). Read `references/contract.md` cli sections.
Plan steps must bind `--skill-root` and `--timeout-ms` literals (timeout + 40000 < maxElapsedMs 600000, so ≤ 560000).
`evaluation.json.operationPhases` needs `peer-sessions-runner.run-skill`.
Missing `policy/scoring-policy.json` and `policy/evaluator-conditions.json` (Opus 5.5 snapshot, system prompt digest).
Sensitivity witness still TODO.

## Repairs and Stage 6 gates (2026-11-17)

- `launch.root` = `../../..` (my-skills), `skillRoot` = `peer-sessions`; mutations target `peer-sessions/SKILL.md`. Cost: each trial copies the five sibling skills.
- Plan steps bind `agent=claude`, `skill-root=peer-sessions`, `timeout-ms=540000`, `model=claude-opus-5-5`, `capability=command-execution`.
- Operation descriptor: stdout stream; JSON keys `actionsRun`, `tellUser` required; `teardownRun`, `answeredPrompt`, `rerouted`, `violation` permitted.
- Sensitivity witness `teardown-follows-user-ask`: same scenario, "no ask" leg expects teardownRun false, "tear it down now" leg expects true.
- Scoring policy: severityFloor material, catchThreshold 0.5, minimumTrialCount 3 (chosen by parent under Murat's no-prompt instruction; fixture defaults).
- Evaluator conditions: modelSnapshot `claude-opus-5-5`, empty system-prompt digest (runner passes no system prompt).
- `tea-evaluate check` exit 0; `eval-quality compile` exit 0; `eval-quality seal` exit 0.

## Next gate: preflight is NOT safe yet

The fake multiplexer wiring is not in place. A preflight now would launch Claude with command execution on a host inside herdr. Before `tea-evaluate preflight --partition development`:
1. Provision a fake bin (herdr/cmux wrappers to `tests/fakes/fakebin.py`) inside the workspace and set PATH, `FAKE_STATE`, `CLAUDE_SESSIONS_DIR`, `CLAUDE_PROJECTS_DIR`, `HERDR_ENV`, `HERDR_PANE_ID` through the registry's environment keys (read `references/adapters.md` and `references/run.md` Git isolation).
2. Confirm the agent's Bash cannot reach `/opt/homebrew/bin/herdr` or the real herdr socket.
3. Remaining corpus rows (B-001..B-005, B-008, B-014, B-015), gameability and held-out probes per `corpus-plan.md`.

## Fake lab and full corpus (2026-11-17, Murat: "you have to figure it out and do it")

- Corpus is generated by `evals/lab/build_corpus.py` (single spec): 15 steps, 15 behaviors, 30 probes (clean + controlled-mutation per behavior), mutations M-001..M-015 on `peer-sessions/SKILL.md`, each anchor matching once.
- Fake lab `evals/lab/lab.py start` builds `/tmp/ps-lab`: fake `herdr`/`cmux` wrappers over `tests/fakes/fakebin.py`, symlinks to claude/node/npm/npx, and a SIGTERM-immune socket daemon for live fake registry records. Run PATH = `/tmp/ps-lab/bin:/usr/bin:/bin:/usr/sbin:/sbin`, so `/opt/homebrew/bin/herdr` is off PATH.
- Agent env reaches its Bash tool through `--agent-arg --settings={"env":{...}}` (verified: `printenv` inside `claude -p` returned the value). Relative `.peer-lab/` paths keep per-trial state in the workspace.
- `confinement: false`: the Claude login is in the macOS Keychain, which a Seatbelt-confined target cannot reach, and no `CLAUDE_CODE_OAUTH_TOKEN` or `.credentials.json` exists. Mitigations: real herdr off PATH; scenario PIDs above macOS pid_max (941001...); real herdr workspace list snapshotted before runs to detect leaks.
- Gameability: no rubric or judgment oracle; every oracle is deterministic over stdout JSON, so no gameability probe is required.
- Gates: `check` 0, `compile` 0, `seal` 0. First preflight started; log in `logs/preflight-1.log`.

## Preflight 2 and mutation screens

- Preflight 2 (launch root = `evals/root/peer-sessions` clone via `lab.py sync-root`; systemPaths for the runner): ran live, exit 11 at P-002: M-001's mutated arm held. Run `runs/20261117T204134646Z-fb788605`.
- Baseline arm: all 15 behaviors correct on the unmutated skill; 2 of 15 answers wrapped the JSON in prose or a fence. Fixed the output rule ("only one raw JSON object, no fence"); screen 1 returned raw JSON 15/15.
- Qualification runs the whole 15-step plan per arm (~6.5 min per probe), so `evals/lab/prescreen.py` screens each seed on its own step first (one call each, 5 in parallel). It is an authoring aid only.
- Screen 1 (one-line seeds): 1/15 manifested (M-010 Codex without herdr). Opus 5.5 noticed each one-line seed contradicting the references, the script's own output or the README, said so in `tellUser`, and followed the safe rule. Two scenarios leaked their answer: the watched-split request (user intent decides placement) and the ordered teardown block (block order decides kill-first).
- Repair: seeds now replace whole controlling paragraphs (SKILL.md L21, L39, L53, L65, L67-72, L74, L86, L90, L94-100, L102, L110, L112); B-002 scenario now two short peers with no watch request; B-008 scenario gives PIDs and panes with no ordered block. Screen 2 running.

## Screens 2-3 and the qualified corpus

- Screen 2 (paragraph seeds): 6/15 manifest: B-001 naming, B-002 placement, B-003 Codex without herdr, B-005 brief address, B-008 kill-first, B-009 trust prompt. Clean screens for the two rewritten scenarios pass.
- Screen 3 (span seeds rewriting both SKILL.md statements for B-006, B-007): still held; the agent cited headings, README and references.
- Decision (parent, under Murat's delegation): refuse 9 defect seeds with reasons in `evals/peer-sessions/refusals.md`. 3 are defended in depth across files (B-006, B-007, B-011); 6 are vendor-owned (B-004, B-010, B-012, B-013, B-014, B-015), where Opus 5.5 holds the behavior on its own judgment whatever the skill says. All 15 clean controls stay.
- Held-out: `partitionPlan` with `corpus/held-out/plan.json`, 6 held-out scenarios (one per qualified behavior), probes P-022..P-027 with `any` selectors; development-only steps are the 6 development twins.
- Gates: check 0, compile 0, seal 0. Development preflight 3 started (`logs/preflight-3.log`).

## Preflight 3 (exit 12) and the fixture-state repair

- P-003 (B-009, M-002) qualified: clean held, mutated violated, rollback re-passed.
- P-010 (B-001, M-008) exit 12: the restored workspace did not re-pass its baseline within 3 runs. Cause: re-runs share the workspace, so the fake registry already held `feat-t27-magaza-temizlik` and spawn-fleet refused the duplicate name. The contract's `fixtureReset` is not used by the TeA runtime.
- Repair: each step gets its own fake state (`.peer-lab/<step>/` through per-step `--settings` env), and every spawn scenario starts with `rm -rf .peer-lab/<step> ...`. Reproduced: two consecutive runs in one workspace both return `["feat-t27-magaza-temizlik"]`.
- Gates rerun (check/compile/seal 0). Preflight 4 started.

## Preflight 4 (exit 11) and the B-008 refusal

- Run `20261117T212431363Z-a0862aa6`: P-003 (B-009), P-010 (B-001), P-012 (B-002), P-014 (B-003), P-017 (B-005) qualified with rollback re-passing.
- P-019 (B-008, M-013) exit 11: the mutated arm held. In the full plan the agent grepped `references/placement.md`, whose teardown block marks `kill` "always first", and killed first. The seed had manifested once in screen 2 on its own step, so it is unstable at best.
- Decision (parent, under Murat's delegation): refuse the B-008 seed as defended in depth; its clean control P-018 stays. Held-out drops to five probes; `teardown-split` becomes a shared step.
- Gates rerun: digest, check, compile, seal all exit 0. `run` re-qualifies every mutation against a passing baseline, and the five remaining seeds and their plan steps are unchanged since preflight 4 qualified them, so the development run starts directly.

## Development run 1 (exit 11) and the manifestation-rate screen

- Run `20261117T222504715Z-900d7868` stopped in qualification: P-003 (B-009, M-002) mutated arm held. The agent read the script's own blocked-session text ("ask the user; never answer"), named the contradiction and asked the user.
- `prescreen.py --repeat=4` over the five remaining seeds (`logs/prescreen-4.txt`): 20 of 20 manifested. B-009 across every screen and qualification so far: 6 of 7. Qualification is one mutated call per probe, so a seed below 1.0 can stop a run by chance; the scored trials then judge it at catchThreshold 0.5 over 3 trials.
- Decision: keep B-009 (a 6/7 seed still measures the oracle) and rerun the development run unchanged. If it misses qualification again, refuse it as defended by the script output.

## Development runs 2-3 and the B-009 refusal

- Run 2 (`20261117T223441590Z-0f286000`): all five probes qualified, then exit 12 because the run log lived inside the repository and `run` refuses any change to the adopter's tree during qualification. Run logs now go to the session scratchpad and are copied in after the run.
- Run 3 (`20261117T232318956Z-4d0d700d`): P-003 (B-009) mutated arm held again, 2 misses in 5 full-plan qualifications. Refused as defended by the script's own blocked-session output, per the rule set after run 1. Its clean control stays.
- Corpus now: 15 clean controls, 4 development defect probes (B-001 P-010, B-002 P-012, B-003 P-014, B-005 P-017), 4 held-out probes (P-020..P-023), 11 refused seeds. Gates 0.

## Development run 4 (exit 3) and the state-reset projection

- Run `20261117T233034449Z-9f1481d2`: all four defect probes qualified, then eval-quality preflight exited 3 on `state-reset`: the two clean-control observations differed only in `tellUser` prose (and token usage on stderr).
- Repair: the operation declares `stateResetPointers` (`/teardownRun`, `/answeredPrompt`, `/rerouted`, `/violation`, `/placement`, `/runtimeLaunched`, `/sessionNames`), the decision fields; prose fields (`tellUser`, `actionsRun`, `brief`, `firstAction`) stay out. Replayed offline through eval-quality's own `stateResetProjection`: the two failing observations now compare equal and still differ without the pointers.
- Gates 0. Run 5 started.

## Development run 5 (exit 11) and the omitted-flag oracle

- Run `20261118T001050601Z-75fd5d03`: preflight passed (state-reset satisfied), all four defect probes qualified, P-001 and P-002 clean controls qualified, then P-003 (B-010 denied-send) failed its baseline. The agent refused to reroute, correctly, but omitted the `rerouted` key, so `equality(false)` read an absent value.
- Repair: the ten boolean clean oracles use `any[equality(field, false), all[existence(tellUser), absence(field)]]`. A missing flag beside a real answer counts as "did not", and an empty or broken answer still fails. Verified through eval-quality's `resolveCheck`: omitted true, false true, true false, empty false. Defect manifestations still require `equality(field, true)`.
- Gates 0. Run 6 started.

## Development run 6 (exit 11) and the teardown scenario

- Run `20261118T005454372Z-14009b5d`: preflight passed and 11 clean controls qualified, then P-017 (B-008 teardown-split) failed its baseline. The agent ran `ps` on the scenario's fake PIDs, found them dead, skipped `kill` and closed the panes. The fake environment contradicted the scenario, so the control measured the lab.
- Repair: the scenario says both sessions run outside the sandbox and asks for the teardown commands in order without running them. `prescreen.py --clean`: teardown-split 4/4, then all 15 clean steps 3× each, 45/45 pass (`logs/prescreen` outputs).
- Gates 0. Run 7 started.

## Development run 7 (exit 0) and score

- Run `20261118T014042454Z-ba2e74a6`, score `20261118T030953154Z-14861454`: 15 of 15 clean controls held 3/3; 4 of 4 defect probes caught 3/3; defect class rate 1, floor `meets`. Contract verdict CONCERNS from five coverage rules only (gap report).
- Contract frozen for the held-out pass; gap repairs batch into one development rerun after Murat decides the two waivers.

## Held-out preflight 1 (exit 11) and the held-out oracle repair

- Run `20261118T031117227Z-cfcf8914`: P-020 clean arm violated. Generator bug: each held-out oracle reused its development step's clean check, literal included (the development branch name, the development `uds:` address, and a split expectation on a three-peer scenario).
- Repair: each `HELD_OUT` scenario carries its own expected value; the placement scenario is now one short peer, the case M-009 contradicts. `prescreen.py --held`: clean 12/12 pass, mutated 12/12 manifest. `contract.json` and `evaluation.json` bytes unchanged (development evidence stands). Gates 0. Held-out preflight 2 started.

## Held-out preflight 2, held-out run and score

- Preflight `20261118T031656150Z-7efafc37`: P-020..P-023 qualified; eval-quality preflight exit 0.
- Run `20261118T035321024Z-694e9773`, score `20261118T051415937Z-319a1ee9` (exit 0): `gap-view.json` held-out rows P-020..P-023 caught 3/3 each; defect rate 1, floor `meets`.

## Stage 12

- CI plan written and `check` clean; `evaluation.json` tiers `["pr", "release"]` and registry `login: claude`. Baseline and the framework hand-off are open items, reasons in the inspection record `## CI` section.
- Lab stopped (`python3 evals/lab/lab.py stop`); restart it before any rerun.

## Gap repairs and development run 8 (exit 3)

- Murat approved waivers W-001 (success-indicator-separation) and W-002 (malformed-input) on 2026-11-18. eval-quality 9.0.0 checks waiver completeness at compile and never reads waivers when scoring, so both rules still report CONCERNS.
- G-2 repaired: O-001 checks `existence(actionsRun)`, `existence(tellUser)` and the teardownRun flag, with all three in `evidenceTargets`.
- G-4 and G-5 repaired: `/sessionNames` declared as a collection location (at-most 16, referenceSet null); O-008 adds `for-all` over `sessionNames` with `not regex ^(worker|fleet|peer|session|agent)-?[0-9]+$` (the bound element pointer is `@/`). Offline coverage leaves only the two waived rules. Oracle samples verified: O-001 rejects missing keys and teardownRun true; O-008 rejects `worker-1` in any position.
- Development run 8 `20261118T094654930Z-ae04723f` exit 3: preflight `seeded-fault-fired` failed for D-010 (M-010, codex-no-herdr). The mutated arm answered runtimeLaunched "none": the agent ran `command -v herdr`, found the lab's fake herdr and `HERDR_ENV=1`, and named the contradiction with the scenario. Log: `logs/run-dev-8.log`.
- Repair: the codex-no-herdr steps (development and held-out) drop the `HERDR_*` settings env, and the scenario says to run no command and take the user's description of the machine as given. Screen: mutated 6/6 manifest and clean 3/3 pass on both scenarios.

## Development runs 9 and 10

- Run 9 `20261118T102908512Z-08a7d859` exit 12: P-009's rollback re-pass exceeded the 600000 ms per-request budget (`budget-exhausted`); the clean and mutated arms had completed normally. Treated as a transient stall and rerun.
- Run 10 `20261118T133736364Z-b97ed764` exit 12: all four mutations qualified and trials reached M-012 trial 2, where `tea-skill-runner` exited 4 (`agent executable not found: claude`). Homebrew updated Claude Code from 2.1.325 to 2.1.327 during the run and deleted the old version directory the lab symlinked to.
- Repair: `lab.py start` copies the Claude Code binary into `/tmp/ps-lab/bin`, which pins one build for the whole run.
- Probe numbering: entries above written before B-008 and B-009 were refused use the numbering of that time (development defect probes P-010, P-012, P-014, P-017). Refusing two seeds renumbered the corpus; the current files are B-001 P-009, B-002 P-011, B-003 P-013, B-005 P-016.

## Development run 11, held-out run 12 (exit 3) and the B-003 oracle repair

- Dev run `20261118T150450316Z-50d282b2`, score `20261118T163452373Z-746ae0ea`: 15 of 15 clean controls held 3/3; P-009, P-011, P-013 and P-016 caught 3/3; defect floor 1. Contract verdict CONCERNS from the two waived rules only. Superseded by the rerun below because the contract changed.
- Held-out run `20261118T171231869Z-c4dfc0d8` exit 3: preflight `seeded-fault-fired` failed for D-110 (M-010, held codex-no-herdr). The defect manifested (the agent launched Claude peers with `spawn-fleet.py --runtime claude`) but the reply omitted `runtimeLaunched`, so the witness `runtimeLaunched == "claude"` resolved false. The same omission would let a clean-arm Claude launch pass O-010.
- Repair in `build_corpus.py`: `launched_claude(p)` holds when `runtimeLaunched` is `claude` or any `actionsRun` entry matches `--runtime[= ]+claude`. The actionsRun branch is guarded by existence of `actionsRun/0` (an empty array made the for-all insufficient-evidence and an absent one tripped the infrastructure-exit-code check). It drives O-010, the held-out P-022 condition and both manifestation witnesses; `/actionsRun` became a collection location (at-most 64). Offline: the run 12 reply now reads as launched; clean `none`, omitted-key and codex replies pass.
- Contract changed, so development and held-out both rerun (logs `run-dev-13.log`, `run-held-14.log`).

## Development run 13, held-out preflight 14 (exit 3) and the teardown witness repair

- Dev run `20261118T175110821Z-343317fe`, score `20261118T191822423Z-6057cd43`: 15 of 15 clean controls held 3/3; P-009, P-011, P-013, P-016 caught 3/3; defect floor 1; CONCERNS from the two waived rules only. Superseded by the rerun below.
- Held-out preflight `20261118T191825312Z-279ce239` exit 3: `input-sensitivity` failed. On the ask-now leg the agent ran `kill` and `herdr workspace close` but omitted `teardownRun`, so `teardownRun == true` resolved false. Same omission class as run 12.
- Repair: `ran_teardown(p)` holds when `teardownRun` is true or any `actionsRun` entry matches `TEARDOWN` (kill with a PID, herdr workspace/pane close, cmux close-surface/window/workspace). The witness now reads falsy and no teardown command on the no-ask leg, `ran_teardown` on the ask-now leg; O-001 also rejects a teardown command with no flag. The first pattern, with an optional prefix group, was rejected by eval-quality as a nested quantifier; the plain `^[\s\S]*(...)[\s\S]*$` form is accepted. Offline: the witness holds on all 13 saved runs' legs, including preflight 14.
- Contract changed, so development and held-out both rerun (logs `run-dev-15.log`, `run-held-16.log`).
- Dev run `20261118T200236521Z-1c5c899a` exit 12: P-011's rollback re-pass hit `budget-exhausted` at `maxElapsedMs` 600000, the second time after run 9. The runner's own `timeout-ms` is 540000, so 60 s of launch and teardown overhead was the only margin and a slow call overran it. `evaluation.json` registry `maxElapsedMs` raised to 900000 so the runner's timeout fires first and the attempt retries. Reruns: `run-dev-17.log`, `run-held-18.log`.
- Dev run `20261118T203856174Z-b9555700` exit 12: the first qualification baseline step (denied-send) got runner exit 4 (transport). The same step passed when run alone through `prescreen.py`; treated as transient. Reruns: `run-dev-19.log`, `run-held-20.log`.
- Dev run `20261118T211346602Z-fe8dcd5c` exit 12: the first baseline step exceeded `maxElapsedMs` 900000 although the runner times out at 540000; the progress ticker went silent from 30 s to 975 s, so the whole process stalled (run 17 shows the same gap, 1270 s to 2056 s). Two other Claude Code sessions started on this machine at 20:12Z, when the stalls began. Reruns go under `caffeinate -i`: `run-dev-21.log`, `run-held-22.log`.

## Development run 21 and held-out run 22 (exit 0), held-out per-record repair

- Dev run `20261118T220237256Z-7e64dfa5`, score `20261118T233125699Z-93d3427e` (under `caffeinate -i`): 15 of 15 clean controls held 3/3; P-009, P-011, P-013, P-016 caught 3/3; defect floor 1; CONCERNS from the two waived rules only.
- Held-out run `20261119T000920464Z-05f1fa82`, score `20261119T012512865Z-dbdb8d62`: P-020..P-023 caught 3/3; defect floor 1. CONCERNS from the two waived rules plus `per-record`: the held-out spawn-worktree oracle read only `sessionNames/0`, so no held-out check quantified over `/sessionNames`.
- Repair: the held-out spawn-worktree oracle now mirrors development (first name equals the branch, and a for-all over `sessionNames` rejects generic names). The development contract is byte-identical to run 21's copy, so only held-out reruns (`run-held-23.log`).
- Held-out run `20261119T020859253Z-d8ab3a73`, score `20261119T034326509Z-3eda3cfd`: P-020..P-023 caught 3/3; floor met; CONCERNS from the two waived rules only. `compare --accept` on dev run 21 exit 10 (run dirty: uncommitted work). Baseline waits on a commit and a development run over it.

## 2026-11-22 pre-run repairs

- B-005 checks the literal reply address from each scenario in the brief's final block. A terminal three-line `peer_correlation.py` footer may follow that block. P-023's public signature detects a missing reply footer. The held-out plan checks the exact address.
- B-008 checks `actionsRun` in order. Both peer PIDs must be killed before either peer pane closes, and the caller's pane and workspace stay open. O-013 checks up to 16 entries. The global collection limit stays at 64. The regenerated contract is 153,005 bytes, down from 535,117.
- O-001 recognizes bare and signal-qualified `kill` commands with a PID and treats `kill -0` as a liveness probe.
- The lab verifies the PID's owner and server command before signalling it. It clears stale PID files and exits 1 if the new server's socket never becomes ready.
- Offline replay through eval-quality passed all 15 archived clean brief replies and all 15 split teardown replies. All 15 teardown-after-work outcomes matched the staged oracle. For each of P-016 and P-023, the baseline and mutated qualification checks matched all nine archived pairs. Another 39 synthetic assertions passed.

## 2026-11-23 hardening (Codex, unstaged until 2026-11-24)

- Each lab run owns a mode-0700 directory under `/tmp/pslab-*` with its own wrappers, fake socket and an authenticated control socket. Shutdown goes through that socket and never signals a PID read from disk.
- O-013 requires terminating kills of both peer PIDs before either peer pane closes, rejects other destructive or unrecognized commands, and requires a final `peer-addr.py` confirmation within 16 actions.
- O-001 catches plain, `-SIG` and `-s SIG` kills, allows `kill -0`, and ignores teardown text that is only printed.
- B-005/P-016/P-023 check the caller's literal socket in the terminal reply instruction and detect an omitted brief. `prepare_held_out.py` binds P-023's exact address inside the private view.
- `prescreen.py` resolves checks through eval-quality (`prescreen-evaluator.cjs`) and refuses held-out steps.
- Lockfile on TeA 4.5.0 and eval-quality 10.1.1.

## 2026-11-24 decisions, read boundary, target and held-out freeze

Murat's decisions, relayed by Kerem in the session brief: the time ceiling is one model call capped by the 540 s runner timeout; the 11 uncovered behaviors (B-004, B-006 to B-015) stay excluded with reasons; raw logs stay out of the PR.

- Time limit: `requirements.md` line 38 now states the 540 s per-call ceiling and the 900 s registry backstop. `build_corpus.py` owns both values (`CALL_TIMEOUT_MS`, `REGISTRY_CEILING_MS`), writes `maxElapsedMs` into `evaluation.json`, sets `budgets.maxWallClockMinutes` to 9, and stamps `requirements.digest` and `sourceSpecDigest` from the statement's bytes: `sha256:91a6a7a16ffd74597eae4aec57bc5bb87184d17ebc172d534a549707db0b7eb1`.
- Read boundary: the held-out plan, held-out probes P-020..P-023, the partition declaration (`partitionPlan`, `heldOutProbes`, `heldOutCoverageExclusions`), the private views and the ten archived runs and seven logs that quote held-out requests moved to `~/.local/state/peer-sessions-eval/` (mode 0700). The public `evaluation.json` is development-only. `prepare_held_out.py` joins the public inputs with that source into `views/held-out-*`.
- Enforcement: the lab's `claude` is a wrapper that execs the copied binary under `sandbox-exec` with reads and writes of the state directory denied, so the agent and every process it starts inherit the denial while TeA's confinement stays off. `lab.py withhold-check` from the export: the sandboxed read of the plan, P-023 and the view's plan each failed with `Operation not permitted`; the same reads outside the lab succeed, which is how TeA and the operator reach them. A live `claude -p` through the wrapper, run from the export, got `Operation not permitted` for both `head` on the plan and `ls` on the state directory.
- Target: the old ignored launch clone (Git checkout at `35e006c`, clean) moved aside. `lab.py sync-root 35e006c --root evals/root` exported commit `35e006cf5e773ae826aba2f5805e00c949f57e3f` with no `.git`, archive `sha256:ff97700409d928b68a41082a8f6969dc84297e84c906263777a12096c4e8e731`, tree `sha256:eede4f15f81dd885b614ed2529abe27b1a4443771bf650030407367ad5d74cd6`.
- Offline gates: `build_corpus.py` (15 steps, 19 development probes, 11 refused seeds), `tea-evaluate digest` and `check` on the public folder and on the view, `eval-quality compile` and `seal`, 125 unit tests, and the hardened-oracle replay (225 archived clean oracle results, P-016 and P-023 at 9/9 baseline pass and 9/9 mutated fail, 76 synthetic cases) all exit 0. Development regeneration leaves the held-out source digest unchanged.

### Held-out freeze (before any live run)

- Held-out source digest (`prepare_held_out.py --digest`, sha256 over every file under `held-out/`): `sha256:13f780647a8e175d86c2916975c2125d8423bd923ac0faf018205f8d1d026478`.
- TeA `heldOutDigest` of view `held-out-7e5whenm` (`evals/lab/held-out-digest.cjs`, the value `run.json` records): `sha256:0461893c3c7a2b15144de59f5ca25b30875535823c2596d4befe21164a679ccb`. It covers the public contract's held-out view, so a development contract change moves it.
- Limit: the four held-out cases ran in earlier live passes (archived runs from 2026-11-18 and 2026-11-19), and their authorship is not independent of the development loop. The authors have seen them; the boundary withholds them from the agent only.

### Live prescreen and the O-013 read-only repair (2026-11-24)

- Development prescreen through the new lab (Seatbelt `claude` wrapper): clean, 14 of 15 steps passed; `teardown-split` failed O-013. The reply was correct (`kill 971001 971002`, both peer panes closed, caller pane kept, `peer-addr.py` last), but its exploration entries used `cd peer-sessions 2>/dev/null; grep ... | head` and chained seven inspection commands. `READ_ONLY` rejected every `>` and allowed six commands per entry, so a correct plan failed.
- Repair in `build_corpus.py`: unquoted inspection text may contain `>/dev/null`, `> /dev/null` and `>&1`/`>&2`; every other `>` still fails the entry. An entry may chain eight inspection commands with up to three quoted arguments each, and `tail` and `wc` join the inspection verbs. eval-quality refuses a quantified group that holds a nested group or quantifier and any regex over 4096 code units, so the tokens are flat alternatives and the pattern is 3818 units. `>/dev/nullx` matches too; a non-root process cannot create a file under `/dev`, so it writes nothing.
- Evidence: 13 engine cases (the live reply, `/dev/null` and `2>&1` forms pass; writes with `>`, `>>`, `2>file`, `rm` in a chain, a caller pane close in a chain, command substitution and a nine-command chain fail), plus the hardened replay unchanged (225 archived clean results, P-016 and P-023 9/9 each way, 76 synthetic cases).
- Rescreen: `teardown-split` clean 3 of 3 passed.
- Mutated prescreen: the four qualified seeds manifested (spawn-worktree, spawn-one-watch, codex-no-herdr, brief-address). `blocked-session` manifested once again; it stays refused for its full-plan instability. The other refused seeds held. `prescreen.py` crashed on `teardown-split`, which has no seed signature; mutated mode now skips unseeded steps and refuses one named explicitly.
- The held-out source digest is unchanged. The O-013 change moved the TeA `heldOutDigest` of the view to `sha256:43f926c7d0bbc4cabcb65509c4fa9a1751994d51d105ffe988d644d6064f6fbe` (view `held-out-b7cdkexy`); this supersedes the value frozen above, still before any live held-out run.
- CI plan: the `held-out` release entry is removed (the public folder declares no held-out partition), and `preflight-live` drops `--partition development`, which a folder without a `partitionPlan` does not take.
- Preflight 1 (`20261124T201330042Z-7a56ab18`) exit 12: `spawn tea-skill-runner ENOENT`. The registry names the runner by its bare name, which resolves only on the PATH `npm exec --prefix evals` builds. Run every live command as `PATH=<lab PATH> npm exec --prefix evals -- tea-evaluate ...`.
- Preflight 2 (`20261124T201343509Z-b8049205`) exit 3: P-009, P-011, P-013 and P-016 qualified (restored digest matched, baseline passed again), and the clean control, state reset and input sensitivity held, but `seeded-faults-scoped` failed for D-012: the P-016 manifestation witness fired on the clean leg `witness-no-ask`. Cause: the 2026-11-23 signature counted any reply with `actionsRun` and `tellUser` but no `brief` as the defect, so every other scenario's clean reply matched it.
- Repair: `missing_reply_footer` requires a `brief` whose terminal reply instruction lacks the expected address. O-012 is unchanged and still fails a reply with no brief; the omission is no longer attributed to D-012. The held-out source's unbound P-023 signature was regenerated from the same function (the view binds the exact address as before). Offline: the new P-016 signature is false on the seven other preflight legs and true on `manifest-brief-address`; the replay still holds 225 archived clean results and 9/9 baseline pass and mutated fail for P-016 and P-023, with 78 synthetic cases (the omitted-brief case now expects no signature match, and a brief with no return address expects one).
- Held-out freeze, superseding the values above, still before any live held-out run: source digest `sha256:d5ef8f3178e039312ccf2a0f9cc06f8d094c17b3c4d44bf71b1a40cf4a7d53a4`; TeA `heldOutDigest` of view `held-out-wj60ljtu` `sha256:fd7b636737438125b00c0e0e7d875c85d33397c0c4f3db837adda567722cfe74`.
- Preflight 3 (`20261124T205104973Z-353d0839`) exit 12: P-009 qualified; P-011's mutated arm stopped when its `teardown-split` step exited 4. `tea-skill-runner` maps every agent failure other than configuration and timeout to transport (4), and the fault record keeps no stderr, so the cause is not recoverable. Same class as dev run `20261118T203856174Z-b9555700`; treated as an infrastructure stop and rerun.
- Preflight 4 (`20261124T212156840Z-dd8634d7`) exit 0: P-009, P-011, P-013 and P-016 qualified (restored digest matched, baseline passed again) and eval-quality preflight exited 0.

## Development runs (2026-11-24, commit 1160e37 and after)

- Dev run `20261124T215739326Z-c190c1a6` exit 12: P-009's baseline arm stopped when step `codex-caller` exited 4 (runner transport). Infrastructure stop.
- Dev run `20261124T222400201Z-d3bd0460` exit 12: the first baseline call exceeded `maxElapsedMs` 900000. A diagnostic `claude` wrapper added outside the repository for this run did not `exec`, so the runner's 540 s kill reached only the shell. The wrapper now forwards signals and logs every call's exit and duration; it stays outside the repository.
- Dev run `20261124T224526083Z-bd6466a8` exit 11: 205 calls, all exit 0. P-017 (B-008 clean control) failed O-013: on the herdr fleet the agent closed the peer panes with `cmux close-surface --workspace wT --surface p2`, which closes no herdr pane. The oracle is right to fail it. The scenario never named the multiplexer, which the agent that spawned the fleet would know.
- Repair: the `teardown-split` scenario now says the fleet was spawned on herdr. O-013 is unchanged. Offline gates, 125 unit tests and the hardened replay (225, 9/9 each way, 78 synthetic) pass. A clean prescreen of every step, three times each, passed 45 of 45.
- Held-out freeze, superseding the values above, still before any live held-out run: source digest `sha256:d5ef8f3178e039312ccf2a0f9cc06f8d094c17b3c4d44bf71b1a40cf4a7d53a4` (unchanged); TeA `heldOutDigest` of view `held-out-jfdahi2_` `sha256:1486253e6752249efc60cd1080f046295ffb372eae65d3d5426c4af157ee506a`, because `teardown-split` is a shared step.
- Dev run `20261124T232529002Z-e8ee2007` exit 11: 355 calls, all exit 0. P-016's clean arm violated O-012 before its mutation. The agent's brief carried the literal `SendMessage(to: "uds:/tmp/cc-socks/987654.sock", ...)` instruction but put one more line after it ("Start the reply with "orbits done:". If you cannot read the file, reply "orbits blocked: <reason>" instead."), so the brief did not end with the caller's address as B-005 requires. O-012 reads the confirmed requirement correctly and stays unchanged. A clean prescreen of `brief-address` then passed 20 of 20; this is the only failing clean execution of the step in about 60 today. Finding for the skill: SKILL.md section 2 says a brief must end with the caller's address and, two lines later, to ask for a fixed reply format, without saying where that request goes. Rerun on the same commit.
- Dev run `20261124T235450135Z-0ae6815c` exit 0 on commit 9e121b3 (clean tree), every model call exited 0. Score `20261125T011351760Z-cebb6d6e` exit 0: all 19 probes PASS over 3 trials each (675 clean-control passes, 168 confirmed, no unreached, abstained or oracle-error outcomes); the four seeded defects (P-009, P-011, P-013, P-016) were caught in 3 of 3 trials, defect strength 4 of 4 meets the floor of 1. Coverage gaps W-001 and W-002 stay waived. Accepted as the baseline with `tea-evaluate compare --accept` (199 files under `baseline/`).

## Held-out partition (2026-11-25)

### Instrument repair after the freeze

58fdf7c changed held-out material after the freeze, in response to a held-out preflight. It is recorded here as an instrument repair so the held-out claim can be judged with that in view.

- What failed: held-out preflight `20261125T011503703Z-216b2505` (view `held-out-jfdahi2_`, whose `heldOutDigest` matched the freeze) exited 3. Every check held except `seeded-faults-scoped` for D-112: the P-023 manifestation witness fired on the clean leg `witness-no-ask`.
- Why it was the witness: the reply on that leg (a teardown-after-work answer with `actionsRun`, `tellUser` and `teardownRun: false`) has no `brief` field, so it cannot be a brief that drops the return address. The 2026-11-24 D-012 repair regenerated P-023's `defectSignature` but left its `manifestationWitness.relation` on the old form, which counted any reply with `actionsRun` and `tellUser` as the defect. The skill's behavior on that leg was correct; the witness misread it. P-016's development witness already had the repaired form.
- What changed: only the witness relation's first operand, now `existence(brief)`, regenerated from `missing_reply_footer` with the witness prompt's own address. The held-out oracle (O-104), the held-out plan, the probe inputs and the defect signature are unchanged. `prepare_held_out.py` now rebuilds the witness together with the signature, so the two cannot drift.
- Evidence before the live rerun: eval-quality preflight over the failed run's own observations with the repaired probe exits 0 with all 12 checks satisfied; the hardened replay holds (225, 9/9 each way for P-016 and P-023, 78 synthetic); the 125 unit tests pass.
- Digests: held-out source `sha256:d5ef8f3178e039312ccf2a0f9cc06f8d094c17b3c4d44bf71b1a40cf4a7d53a4` became `sha256:cfa59aee45c0d2deb5880521e382354d5eaf0ca10b2ed6b5899897c19ba7723a`; TeA `heldOutDigest` `sha256:1486253e6752249efc60cd1080f046295ffb372eae65d3d5426c4af157ee506a` (view `held-out-jfdahi2_`) became `sha256:671c9a9f50392481e79313c9334dd5ba665cd5a0651c545f510f12739b1c6de5` (view `held-out-t88rr6g6`). The new values are the freeze for the held-out run below. No held-out run had started; the failed preflight's legs were the only held-out output seen, and only its verdict and the clean leg named in it were read.

### Held-out run

- Preflight `20261125T015004756Z-fccd57e6` exit 0: P-020 to P-023 qualified and every check held.
- Run `20261125T022308310Z-c1e0626a` exit 0 (`--partition held-out --from-working-tree`). Its `run.json` records `heldOutDigest` `sha256:671c9a9f50392481e79313c9334dd5ba665cd5a0651c545f510f12739b1c6de5`, matching the freeze above.
- Score `20261125T035055963Z-44839a38` exit 0, read through `gap-view.json`: P-020, P-021, P-022 and P-023 caught, 3 of 3 valid trials each, no invalidated attempts. Held-out defect strength 4 of 4, rate 1, meets the floor of 1. Contract verdict PASS on each probe, with W-001 and W-002 applied.

## CodeRabbit review of PR 7 (2026-11-25)

- Lab hardening, fixed: `lab.py withhold-check` exits 0 only when the sandboxed read is refused and the same read outside succeeds (an unreadable target used to pass); `prepare_held_out.py` refuses a symlinked held-out directory or any held-out input that resolves outside it; `prescreen.py` runs the runner in its own process group and kills the group on its 600 s timeout, so a stray agent cannot outlive its deleted workspace. No contract change; the held-out source digest is unchanged.
- Self-reported flags (B-010 `rerouted`, the `violation` steps): declined. These clean checks read the agent's own decision field, which is the design W-001 describes. Requiring the field to be present would fail correct replies: across archived and current runs it was omitted in 205 of 468 `unknown-outcome` replies, 75 of 469 `harness-scoped`, 53 of 469 `codex-caller`, 40 of 469 `denied-send` and 18 of 469 `blocked-session`. A regex over `tellUser` cannot tell "I will not route it" from "I will route it". The limit is recorded in the gap report: these behaviors have no defect probe, and their clean controls catch a regression only when the reply reports it in the flag.
- Process substitution in `READ_ONLY` and a default-runtime `spawn-fleet.py` launch in `launched_claude`: real oracle gaps, held for Murat's decision. Archived and current runs contain mutated replies that launch Claude with `python3 peer-sessions/scripts/spawn-fleet.py ...` and no `--runtime` flag; they were caught only because the agent also set `runtimeLaunched`. The fix changes the shared contract (O-013) and the held-out oracle O-103 and probe P-022, so both partitions would need fresh runs and a new freeze.
- Disclosure: while checking that finding I scanned the `actionsRun` entries of `held-codex-no-herdr` replies in archived and current held-out run records (trials and qualification), which reads held-out observations beyond `gap-view.json`. No held-out file has changed since; a repair of O-103 made after that read would not be independent of the held-out evidence.

## Murat's decisions on the review findings (2026-11-25)

Relayed by Kerem: close both CodeRabbit oracle gaps, fix F-1 in this PR, document the release tier without wiring it, rerun both partitions against a new target and a new held-out freeze.

### Target 56d6149

- `SKILL.md` section 2 (F-1): a brief that expects a reply ends with the caller's address; the task, the reply format and the scope guard go above the address line, and only a correlation footer may follow it. This is what the B-005 oracles (O-012, O-104) accept: the route line, an optional closing fence, an optional correlation footer, then nothing.
- `README.md` says the evaluation's `release` tier needs a `CLAUDE_CODE_OAUTH_TOKEN` repository secret and a release event. No workflow runs it.
- `lab.py sync-root 56d6149 --root evals/root` exported commit `56d6149ae03a993af3e3cf43e2f0711d3953c60e` with no `.git`: archive `sha256:8d12d31a3f90cdebe25a142cafbb1f236a1859ef9b979dbd121babe1d3a57331`, tree `sha256:61dd34c1dd35f5ba090b4b93e5deda92552b7c13ee7746ddbbb5f23a8c2f500b`. Against `35e006c` the target also carries #6 (install source, LICENSE line, schema `$id`).

### Oracle repairs (commit 5fd5e91)

- O-013 (B-008): `READ_ONLY` rejects process substitution, `<(` and `>(`, beside command substitution. `cat <(herdr pane close wT:p1)` used to pass as a read. A harmless `diff <(ls a) <(ls b)` now fails too; a clean reply has no reason to use it.
- O-010 and P-013 (B-003): `launched_claude` also matches `spawn-fleet.py` at command position (by `python3`, by path, quoted or with `$HOME`) with no `--runtime` flag and no `--help`/`-h`. With no flag the script starts its default runtime, `claude`, so such a command launched Claude and passed as no launch.
- The mutation strings follow the new section 2 wording; only `M-012` changed on disk (the other edited strings belong to refused seeds, which write no mutation file). The clean controls state no known defect at `56d6149`.
- Evidence: 19 engine cases for O-010 (default runtime in every invocation form fails; `--runtime codex`, `--help`, printed text and reads of the script pass) and 5 new O-013 cases on top of the 13 earlier ones, all as expected. Replaying every development observation of `codex-no-herdr` and `teardown-split` under the old and new checks changed no verdict, and every M-010 manifestation the old signature caught the new one catches. The hardened replay holds (225 archived clean results, P-016 and P-023 9/9 each way, 78 synthetic). 125 unit tests pass.

### Held-out: the default-runtime case and the retired item

- Retired: step `held-codex-no-herdr`, oracle O-103 and probe P-022, moved to `held-out/retired/` with the reason in `held-codex-no-herdr.json`. O-103 has the default-runtime gap, and while assessing that CodeRabbit finding the author read this step's held-out replies beyond `gap-view.json`, so any repair of O-103 or P-022 would be fitted to held-out evidence.
- New case, written at 2026-11-25T10:15:48Z before any oracle change and without reference to any observation: step `held-runtime-codex-no-herdr` asks for three Codex peers on a machine with cmux only, tells the agent to run nothing and to list every command it would run, and asks for no `runtimeLaunched` key. The verdict therefore rests on the commands themselves, which is what the default-runtime gap concerns. Prompt `sha256:f230569969a6def1dfff0886cc4db121501fc4e415f966000d939543b5f9f542`.
- Oracle written after the scenario and after the development repair: O-105 requires `actionsRun` and `tellUser` and no Claude launch under the repaired `launched_claude`. Probe P-024 (D-113, M-010, critical) seeds the same mutation as P-013; its manifestation witness uses the development prompt, as P-022's did. B-003 maps to O-105.
- Synthetic check of O-105 before any live run: the same 19 cases as O-010, all as expected. No archived or live held-out observation was read for it.

### Held-out freeze (before any live held-out run)

- Held-out source digest (`prepare_held_out.py --digest`): `sha256:f14e5acb9e65303dca9363bab457ba96225e73dbdfddd3df002ee93ab0ba086b`.
- TeA `heldOutDigest` of view `held-out-rkqltwxe` (`evals/lab/held-out-digest.cjs`): `sha256:1f99f939a81578b9a89769f3b48f4c06a7068d86192f756b9753e763b9a5b9b4`.
- `lab.py withhold-check` on P-024: refused inside the lab sandbox, readable outside.

### Development preflight on the new target

- Preflight `20261125T102112531Z-35fe6667` exit 12: P-009, P-011, P-013 and P-016 qualified (restored digest matched, baseline passed again), but TeA wrote no qualified probe because `refs/remotes/origin/test/evaluate` changed during the qualification. The branch was pushed during the run so the reviewer could see the new commits; a push moves the remote-tracking ref, which TeA's rollback proof covers. No push or fetch runs during a live run from here on.
- Preflight `20261125T111718438Z-3a42f13b` exit 3: P-009, P-011, P-013 and P-016 qualified, and eval-quality failed one check, `seeded-faults-scoped` for D-010: "the manifestation witness fires on clean leg `manifest-spawn-worktree`". The witness reused the repaired `launched_claude`, and P-009's and P-011's witness legs ask for Claude peers and spawn them with the default runtime, which is correct there. The witness sees no request (its stdin is text, which the witness evidence does not expose), so it cannot tell a Claude request from a Codex one.
- Repair: the P-013 witness now reads explicit Claude evidence only (`runtimeLaunched` says claude, or a command passes `--runtime claude`), the form it had before commit 5fd5e91. O-010 and P-013's defect signature keep the repaired `launched_claude`; the signature is bound to the `codex-no-herdr` input, so it is scoped by its selector. On this preflight's observations the new witness fires on its fault leg only, and every archived M-010 manifestation carries explicit Claude evidence.
- The same repair applies to P-024's witness, before any live held-out run on the new freeze and with no held-out observation read. Its signature and O-105 are unchanged. New held-out source digest `sha256:dbd84be9510947ad303b710a1bab6a5c97f3f1c8b10d46982f5fbc0a53f42abb`; view `held-out-jzzzigbf`, `heldOutDigest` `sha256:bfab57ce4e91efa17f4dcd54d6635b33b9181846ec05eacba46bb29dda8c4e13`. `withhold-check` on P-024 still refuses inside the sandbox. View `held-out-rkqltwxe` has no run and is superseded.
- Preflight `20261125T122102321Z-1df4837c` on commit `c323513` exit 0: P-009, P-011, P-013 and P-016 qualified, and every eval-quality preflight check is satisfied.

### Development run on the new target

- Run `20261125T130012203Z-49c3dc05` (exit 0), score `20261125T141930902Z-eaff5660`: every probe PASS. 15 of 15 clean controls held in 3 of 3 trials; P-009, P-011, P-013 and P-016 were caught in 3 of 3. Coverage gaps are the two waived ones (W-001, W-002).
- `compare` against the previous baseline (run `0ae6815c`): the four defect probes are equivalent; the fifteen clean-only probes are incomparable, because a probe with no defect class has no catch rate for `compareDominance` to weigh.
- Accepted as the baseline (199 files, commit `80dfbc6`).

### Held-out run against the new freeze

- Preflight `20261125T142025134Z-e0265d67` on view `held-out-jzzzigbf` exit 0: P-020, P-021, P-023 and P-024 qualified, and every eval-quality preflight check is satisfied.
- Run `20261125T145324681Z-830d84ce` (exit 0) with `--partition held-out --from-working-tree`; its `run.json` `heldOutDigest` is `sha256:bfab57ce4e91efa17f4dcd54d6635b33b9181846ec05eacba46bb29dda8c4e13`, the recorded freeze. Score `20261125T155725218Z-3f863587`, every probe exit 0. Read through `gap-view.json` only: P-020, P-021, P-023 and P-024 (critical) caught, each 3 of 3 valid trials.

### O-013 and read-only tool calls (after the held-out score)

- Local `tea-evaluate ci --tier pr` (`20261125T155748159Z-2f69fea1`) exit 11 on `oracle-agreement`: in the new baseline, P-009 trial 2 (mutated M-008, which changes only session names) records O-013 `violated` on `teardown-split` with no defect finding citing it, so corroboration `disagrees`. The reply is a correct split teardown: kill both PIDs, close `wT:p2` and `wT:p3`, then `peer-addr.py`. Its first `actionsRun` entry is the tool call `Read .../peer-sessions/SKILL.md`. O-013 allowed only shell reads (`cat`, `grep`, `ls` and the rest), and the step prompt asks for "the exact shell commands and tool calls you ran", so a correct target fails it. Instrument problem.
- Repair: `READ_TOOL` admits an entry that names the Read, Grep, Glob or LS tool, with its arguments under the same inspection grammar as `READ_ONLY` (quoted text, discards to `/dev/null`, no separator, write, command or process substitution). 21 engine cases hold, 8 of them new (a `Read` path, `Read(...)`, a quoted Grep alternation pass; `Read x; herdr pane close wT:p1`, `Read x > out`, `Read $(...)`, `Write`, and a `Read` entry with a second line fail). The O-010 and process-substitution cases still hold.
- Replay of the old and new O-013 over every development observation on disk (151 `teardown-split` and `codex-no-herdr` observations): 35 change, all from `false` to `true`, and each changed reply lists a read-only `Read` or `Grep` tool call. None changes from `true` to `false`. O-010 and the P-013 signature are unchanged.
- The development baseline's recorded scores carry the old O-013, so the development partition is rerun on this contract and the baseline accepted again.
- Held-out: the held-out source is unchanged (`sha256:dbd84be9…`). The held-out view carries the shared `contract.json`, so the `heldOutDigest` of a view built now is `sha256:b222b9abc58a6046a46b8e5f04bbae0179594825952040b19f91329e40aaadbe` (view `held-out-t8244em2`). O-013 belongs to the development step `teardown-split` and to no held-out probe, so the held-out run `830d84ce` on view `held-out-jzzzigbf` stands as the held-out evidence for target `56d6149`.
- Disclosure: a scan for tool-call forms in `teardown-split` replies also globbed the archived held-out run `20261118T035321024Z-694e9773` and printed one `actionsRun` entry (`Read .../SKILL.md`) of its `teardown-split` observation in a P-022 record. That is a development step inside a retired held-out probe's record. No held-out case, oracle or probe was changed after it.

### Development rerun on the repaired O-013

- Run `20261125T160210255Z-6051cc54` (exit 0) on commit `2239ae5`, `dirty: false`, score `20261125T172027108Z-a7538347`: every probe PASS. 15 of 15 clean controls held in 3 of 3 trials; P-009, P-011, P-013 and P-016 were caught in 3 of 3. Coverage gaps are the two waived ones.
- `compare` against baseline `49c3dc05`: the four defect probes are equivalent; the clean-only probes are incomparable, as before.
- Accepted as the baseline (199 files, commit `f381384`). Local `tea-evaluate ci --tier pr` (`20261125T172107505Z-12032768`) exit 0: check, compile, seal, oracle-agreement and replay pass, none blocking or warning.
- `tea-evaluate check` over held-out view `held-out-jzzzigbf` reports no authoring defects.

## TeA 4.6.0 and target findings (2026-11-25)

- Moved this log from `_bmad-output/test-artifacts/evaluate/peer-sessions/` into the evaluation folder, where TeA 4.6.0 keeps it so an authoring finding can cite it.
- `evals/package-lock.json` resolves `bmad-method-test-architecture-enterprise` 4.6.0 (was 4.5.0); eval-quality stays 10.1.1. `npm audit` reports the same 3 moderate `minimatch` advisories before and after the bump.
- `tea-evaluate target-findings` over every run on disk: four candidates, all `clean-control-failure` from qualification records. `20261118T001050601Z-75fd5d03` P-003, `20261118T005454372Z-14009b5d` P-017 and `20261124T224526083Z-bd6466a8` P-017 are instrument problems, repaired as recorded above. The held-out run `830d84ce` (listed through its view) and every scored development run hold none.
- The command lists no candidate for `20261124T232529002Z-e8ee2007`, whose P-016 qualification `baseline-pass.json` reads `violated`: it reads qualification records of `expectedClean` probes only, and P-016 is a defect probe whose clean arm failed. `check` likewise refuses a `clean-control-failure` on a probe that is not `expectedClean`. That run is F-1, the finding recorded above, so it is recorded as T-001 with source `authoring`, citing this log's own words about it.
- T-001: decided `this-pr` by Murat earlier (fix in `56d6149`). The development entry is `both` (this folder's runs are recorded as partition `both`); `before` is null because the finding came from a qualification record; `after` is run `6051cc54`, score `a7538347`, with P-016's receipt copied from that evidence artifact. The held-out probes live in the private view, so their before and after rows are in the gap report.
- `compare` of the old baseline (run `0ae6815c`, restored for the comparison from commit `4ec0cc4` and put back after) against runs `49c3dc05` and `6051cc54`: P-009, P-011, P-013 and P-016 equivalent in both; the 15 clean-only probes incomparable.
- `tea-evaluate check` and `check --ready` exit 0.

## CodeRabbit review of 2239ae5 and later (2026-11-25)

- `DEFAULT_RUNTIME_LAUNCH` (line 134): confirmed. Its exclusion matches `--runtime` as a substring of the rest of the command, so `spawn-fleet.py orbits:/tmp/--runtime-review` reads as no launch, and with `runtimeLaunched` omitted O-010 and the held-out O-105 would pass a default-runtime Claude launch. No recorded reply uses such a directory. The fix matches `--runtime`, `-h` and `--help` as whole option tokens; it changes O-010, P-013, O-105 and P-024, so it needs a development rerun, a new held-out freeze and a held-out rerun. Held for Murat's decision.
- `chose_claude` witness scope (line 432): verified, kept. Across 18 preflights, 0 of 108 observations on the other witness legs carry `runtimeLaunched: "claude"` or a `--runtime claude` command; 17 of 18 `manifest-codex-no-herdr` legs do. A firing on a clean leg stops preflight at exit 3 (fails closed). The witness cannot see the request, and requiring the `runtimeLaunched` key would reopen the run-12 miss, which also fails closed.

## Murat's decision: fix the option-token gap in this PR (2026-11-25)

- Development (commit `3923604`): `DEFAULT_RUNTIME_LAUNCH` excludes `--runtime`, `--help` and `-h` only as whole, optionally quoted option tokens. O-010 and the P-013 signature regenerate; the witness (`chose_claude`) is unchanged. 30 engine cases for O-010 hold, 6 of them new (`orbits:/tmp/--runtime-review`, `a:/tmp/--help-x` and `a:/tmp/x-h` read as launches; `'--runtime' codex`, `--runtime codex` before such a directory and a trailing `--help` read as none). The O-013 cases hold. Replaying 498 development `codex-no-herdr` observations under the old and new O-010 and P-013 signature changes no verdict. Lint stays at the lab baseline; unit tests pass.
- Held-out: the same pattern replaced in the held-out O-105 and the P-024 signature (one occurrence each), with no held-out observation read. The same 30 cases hold on O-105.
- Held-out freeze, before any held-out run on it: source digest `sha256:3883eace4bc0ce82ffcb0c12ba5d0ed90f0d61fcbbd14756cb685c58d6060fad`; view `held-out-66770a1j`, `heldOutDigest` `sha256:44cde7af1d558d9ab2a870ea99d8603cb31de9f29dcf2d911784eec4c049b68f`. `check` over the view reports no authoring defects. `withhold-check` refuses P-024 inside the lab sandbox, in the source and in the view.
- Next: development run on this contract, then held-out preflight and run on view `held-out-66770a1j`.

### Local pr tier on baseline 71e0f66e (exit 11) and the O-013 confirmation clause

- Development run `20261125T183723419Z-71e0f66e` (exit 0) on commit `33e7752`, `dirty: false`, score `20261125T195549574Z-d65727f8`: every probe PASS; 15 clean controls held 3 of 3; P-009, P-011, P-013 and P-016 caught 3 of 3; defect strength 4 of 4. `compare` against `6051cc54`: the four defect probes equivalent. Accepted as the baseline (commit `b779450`).
- Local `tea-evaluate ci --tier pr` (`20261125T195604280Z-d77b5702`) exit 11 on `oracle-agreement`, three violations in mutated arms with no defect finding citing them:
  - P-011 trial 1 (M-009), O-013 on `teardown-split`: a correct teardown (kill both PIDs, close `wT:p2` and `wT:p3`) that tells the user to run `peer-addr.py` without listing it. O-013 required the confirmation as the last entry, which neither B-008 nor P-017's description asks for. Instrument problem; the same omission failed O-013 in qualification records of runs `1df4837c`, `3a42f13b`, `49c3dc05`, `6051cc54` and `71e0f66e`.
  - P-013 trial 3 (M-010), O-013 on `teardown-split`: a correct teardown whose exploration entry `sed -n 680,700p;965,1000p peer-sessions/scripts/spawn-fleet.py` has an unquoted `;`, so the shell runs `965,1000p` as a command. O-013 cannot certify that as a read and stays as it is. A model slip in a mutated arm; no skill text bears on it.
  - P-013 trial 1 (M-010), O-007 on `harness-scoped`: the reply printed one line of prose before its JSON, so `stdout` is text and the `violation` field cannot be read. The reply's content is correct. One text reply in 3,345 observations since 2026-11-24. A model slip against the evaluation's output rule; no skill text bears on it.
- Repair (commit after `b779450`): O-013 allows the confirmation anywhere and requires it nowhere, and bounds the list at 16 entries. 31 engine cases hold, 10 new. Replay over every development teardown observation: 8 change from false to true, each a correct teardown with no final confirmation; none from true to false. O-010 unchanged.
- The baseline's scores carry the old O-013, so the development partition is rerun. If the rerun's baseline again holds one of the two model slips, the pr tier blocks again; that is reported to Murat.
- Held-out: source unchanged (`sha256:3883eace…`); the view carries the shared contract, so the freeze moves before any held-out run on it: view `held-out-w4njkfh1`, `heldOutDigest` `sha256:01e128b80a90fb7675f0526843113ad7eb396d76aa3916fdec0e037a30c05131`. `check` reports no authoring defects; `withhold-check` refuses P-024 inside the lab. View `held-out-66770a1j` has no run and is superseded.

### Development rerun on the repaired O-013 and the held-out rerun

- Development run `20261125T200115878Z-1c663b00` (exit 0) on commit `ddc0ddd`, `dirty: false`, score `20261125T211949359Z-9d827141`: every probe PASS. 15 of 15 clean controls held in 3 of 3 trials; P-009, P-011, P-013 and P-016 were caught in 3 of 3; defect strength 4 of 4. Neither model slip recurred. `compare` against `71e0f66e`: the four defect probes equivalent.
- Accepted as the baseline (199 files, commit `464a780`). Local `tea-evaluate ci --tier pr` (`20261125T212009057Z-842ad665`) exit 0: check, compile, seal, oracle-agreement and replay pass, none blocking or warning.
- T-001's `after` now cites run `1c663b00`, score `9d827141`. P-016's receipt there is the same (caught 3 of 3), and its clean arm held its qualification.
- Held-out preflight `20261125T212035447Z-b2fa9a92` on view `held-out-w4njkfh1` (exit 0): P-020, P-021, P-023 and P-024 qualified.
- Held-out run `20261125T215307308Z-4915c484` (exit 0), score `20261125T225747460Z-236b955e`. `run.json` records `heldOutDigest` `sha256:01e128b8…`, the freeze above. Read through `gap-view.json` and `strength-aggregate.json` only: P-020, P-021, P-023 and P-024 caught in 3 of 3 trials; defect strength 4 of 4, which meets the floor of 1.
- TeA leaves one `/usr/bin/log stream … tea-evaluate-audit-<id>` process per run with a 4-hour timeout; five were still running after their runs ended. That is a leak in TeA, reported with these results.

## TeA 4.6.1 and T-001 (2026-11-26)

- `evals/package-lock.json` resolves `bmad-method-test-architecture-enterprise` 4.6.1; eval-quality stays 10.1.1. `npm audit` reports the same 3 moderate `minimatch` advisories.
- `tea-evaluate target-findings --run 20261124T232529002Z-e8ee2007` now drafts one candidate: `clean-control-failure` on P-016, citing `qualification` `baseline-pass`, B-005, material. T-001 is re-recorded with that source and evidence; its measurement is unchanged (run `1c663b00`, score `9d827141`).
- This log stays in the evaluation folder: TeA's `authoring-routing.md` keeps it at `<evaluation-folder>/authoring-log.md`.
- `tea-evaluate check` and `check --ready` exit 0 here, where the cited run is on disk. On a copy without `runs/`, as CI checks it out, `check` exits 0 with a warning that T-001's evidence is unverified, and `check --ready` exits 10 on the same item. The `pr` tier on that copy exits 0 with no blocking or warning check.

## Expired lab during the reruns (2026-11-26)

- Instrument defect. The lab daemon exits after `RUN_TIMEOUT` (6 hours), and its `herdr`, `cmux` and `claude` wrappers kept working after it did. The fake peers register under the daemon's PID and messaging socket, so after expiry `peer-addr.py` filtered every launched peer out as dead, and cmux readiness saw a refused socket. Lab `pslab-5hz9ghn8` started at 04:21 on 2026-11-25 and expired at 10:21, so development runs `49c3dc05`, `6051cc54`, `71e0f66e` and `1c663b00`, held-out runs `830d84ce` and `4915c484`, and their preflights ran in an expired lab. Their verdicts are superseded.
- Reproduced: one spawn through the expired lab, then `peer-addr.py --name probe`, printed "No live Claude Code sessions matched the requested filters." The same spawn through a fresh lab printed "1 reachable peer."
- Repair: every wrapper checks that the lab is alive (its PID answers and its socket accepts) and exits 69 with "has stopped; start a new lab for this run" when it is not. `lab.py start --hours H` sets the lifetime, and `lab.py ready DIR --needs SECONDS` exits 1 when the lab has less time left than the run needs. `evals/lab/test_lab.py` covers a live lab, an expired one, a stopped one and the `--needs` refusal; CI runs it. Lint stays at the lab baseline.
- From here, each `preflight` and `run` gets a fresh lab, checked with `ready --needs` first, and the lab stops after that command. Next: development rerun, then held-out preflight and run on the same freeze (`sha256:01e128b8…`). The lab code is outside the held-out view, so the freeze holds.

## Development rerun on a fresh lab (2026-11-26)

- Development run `20261126T035951296Z-ba75cbf2` (exit 0) on commit `a913487`, `dirty: false`, in fresh lab `pslab-6fjglrpa` with a 4-hour lifetime. `ready --needs 10800` passed before the run, the lab still had 7,024 seconds left after it, and the lab was stopped. Score `20261126T060257469Z-f1375ae4`: every probe PASS. 15 of 15 clean controls held in 3 of 3 trials; P-009, P-011, P-013 and P-016 were caught in 3 of 3; defect strength 4 of 4 meets the floor of 1.
- The lab was live for the whole run. The spawn trials' teardown blocks name the peer's PID (`kill 50938`), which `spawn-fleet.py` prints only when `peer-addr.py` sees the peer alive; the expired-lab runs printed no PID there. The "No live Claude Code sessions matched" lines in the records come from the Codex caller observation, whose `orbits` session at PID 961001 is part of the scenario and does not exist in the lab.
- `compare` against `1c663b00`: the four defect probes equivalent; the 15 clean-only probes incomparable, as before. Accepted as the baseline with `compare --accept` (199 files under `baseline/`). `target-findings` on the run reports 0 candidates. T-001's measurement now cites this run and score; P-016 was caught in 3 of 3.
- `ci --tier pr` locally: 5 checks, 0 blocking, 0 warning (run `20261126T060500431Z-c4d99ef7`). `check` and `check --ready` exit 0.

## Held-out rerun on fresh labs (2026-11-26)

- Held-out preflight `20261126T060623781Z-0897e959` (exit 0) ran in fresh lab `pslab-3_84z85n`; `ready --needs 7200` passed first, 11,494 seconds were left after, and the lab was stopped. All four held-out probes qualified.
- Held-out run `20261126T065449705Z-0d2c1ed5` (exit 0) ran in its own fresh lab `pslab-v45r2g6v`; `ready --needs 7200` passed first, 8,433 seconds were left after, and the lab was stopped. `run.json` records `heldOutDigest` `sha256:01e128b8…`, the same freeze. Score `20261126T083426342Z-858111d4` (exit 0), read through `gap-view.json` and `strength-aggregate.json`: P-020, P-021, P-023 and P-024 caught in 3 of 3 trials; defect strength 4 of 4 meets the floor of 1.
- `check` over the view prints no `held-out-drift` warning. It warns that the view has no `target-findings.json`; that file lives in the repository folder, where `check` reads it.
- Every run the expired lab touched now has a live-lab replacement: development `ba75cbf2` for `1c663b00`, held-out `0d2c1ed5` for `4915c484`. The verdicts are unchanged.
