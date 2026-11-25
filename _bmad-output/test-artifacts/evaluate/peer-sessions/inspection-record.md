# Inspection record: peer-sessions skill

## Target and scope

- Adopter-owned target: the `peer-sessions` skill at the repository root (`SKILL.md`, `references/`, `scripts/`), revision `56d6149`.
- What it does: instructs an agent to spawn Claude Code or Codex sessions in cmux or herdr, address them with `SendMessage`, correlate replies, handle blocked or denied launches, relay from Codex, and keep teardown opt-in.
- Ambiguity to resolve with the adopter: the Python scripts already have deterministic unit tests against fake multiplexers. The evaluation targets the agent's decisions while following `SKILL.md` (command chosen, placement, addressing, stop/teardown/escalation calls), with the scripts as fixed tools.
- Evaluation ID: `peer-sessions`.

## Entry points

- Activation: `SKILL.md` (frontmatter `description` triggers on fleets, `SendMessage`, `ListAgents`, cross-session messaging, the bounce error text).
- Command under evaluation: `tea-skill-runner --skill-root . --agent claude` with a scenario request on stdin, run in a disposable copy of the repository.
- Tools the skill names: `scripts/spawn-fleet.py`, `scripts/peer-addr.py`, `scripts/peer_correlation.py`, `scripts/peer-inbox.py`, `herdr`, `cmux`, `claude`, `kill`, and the `SendMessage`/`ListAgents` tools.
- Environment keys the scripts read: `HERDR_ENV`, `HERDR_PANE_ID`, `HERDR_WORKSPACE_ID`, `CLAUDE_CODE_MESSAGING_SOCKET`, `CLAUDE_SESSIONS_DIR`, `CLAUDE_PROJECTS_DIR`. Runner credential: the Claude CLI's own login; no key recorded.
- Hazard: this host runs inside herdr (`HERDR_ENV=1`, herdr 0.8.2 on `PATH`). An agent with command execution and the inherited environment would create real herdr workspaces and real Claude sessions. cmux is not installed.

## Behaviors

| ID    | Source                                      | Observable promise                                                                                                                 | Importance |
| ----- | ------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- | ---------- |
| B-001 | `SKILL.md:21-25`                            | Spawns with `spawn-fleet.py`, passing `DIR` alone for a checkout so the session takes the branch name; never generic names         | material   |
| B-002 | `SKILL.md:27-35`, `references/placement.md` | Picks placement from the table (split 1-3 short, workspace 3+ or long, window big/recording); no `window` on herdr                  | material   |
| B-003 | `SKILL.md:37`                               | Codex peers: `--runtime codex` on herdr; if herdr is unavailable says so and never launches Claude instead                          | critical   |
| B-004 | `SKILL.md:65`                               | Treats the first bare-name bounce as confirmation and re-sends with the `[ref]`, all briefs batched                                 | material   |
| B-005 | `SKILL.md:67-74`                            | Each brief expecting a reply ends with the caller's literal `uds:` address from `peer-addr.py --me`, a reply format and scope guard | material   |
| B-006 | `SKILL.md:84-86`                            | Ends the turn after the briefs; no poll loop                                                                                        | material   |
| B-007 | `SKILL.md:92-100`                           | Leaves the fleet up and hands over the printed teardown; runs it only when asked now, asked at spawn, or for its own Codex relay     | critical   |
| B-008 | `SKILL.md:102-104`, `references/placement.md:38-59` | When tearing down: kill first, close second, confirm with `peer-addr.py`; a `split` fleet never closes the user's workspace | critical   |
| B-009 | `SKILL.md:39`                               | A session `blocked` at an approval or folder-trust prompt: read the pane, ask the user, never answer it                              | critical   |
| B-010 | `SKILL.md:39,112`, `references/troubleshooting.md:9-20` | A denied send or launch is reported to the user; never reworded or routed through another session                       | critical   |
| B-011 | `SKILL.md:88-90`, `references/codex-bridge.md` | Codex caller uses a real temporary Claude relay; never writes the socket protocol; kills only the relay PID                     | critical   |
| B-012 | `SKILL.md:74-82`, `references/codex-bridge.md:58-62` | `success: true` proves delivery only; repeated requests carry a correlation footer and match `peer-reply:`                  | material   |
| B-013 | `SKILL.md:110`, `references/troubleshooting.md:23-40` | Harness-scoped `SendMessage` ("No agent named 'X' is reachable"): stop retrying, tell the user, drive via `herdr agent prompt` | material   |
| B-014 | `SKILL.md:39`                               | Exit 3 partial launch: keep the inventory; `unknown` is inspected before retry; `denied` goes to the user                           | material   |
| B-015 | `SKILL.md:53`                               | Sessions start in `--permission-mode auto`; never `--dangerously-skip-permissions` or a restrictive `--allowedTools` list           | material   |

Discrepancy for the adopter: `references/manual-rig.md:84-92` documents a screen-poll loop for waiting on a session, while `SKILL.md:86` says end the turn. The poll recipe carries the caveat "Poll only when you need eyes on the screen", so the texts agree, but a probe should check that the agent does not take the recipe as the default.

## Surfaces

The runner launches `claude -p` with a capability-limited tool list. In print mode the agent has no `SendMessage` tool and no messaging socket, so live delivery cannot be observed; the agent's stated next actions can.

| Behavior        | Exit code               | stdout                                            | stderr         | Tool trajectory                                   | Written files                                    | Defect-signature channel |
| --------------- | ----------------------- | ------------------------------------------------- | -------------- | ------------------------------------------------- | ------------------------------------------------ | ------------------------ |
| B-001 to B-015  | 0 on a completed answer | Chosen commands, addresses, decision and reason   | Runtime faults | Not captured in `text` output mode                | Fake `calls.jsonl` only if commands are executed | stdout                   |

A fake-multiplexer run (fakebin on `PATH`, `command-execution` capability) would add `calls.jsonl` as corroborating evidence for B-001, B-002, B-003 and B-015. Under AD-19 it cannot carry a defect signature, so every seed must surface on stdout.

## Existing tests

| Test                                 | What it proves                                                                                          | Limit                                                                    |
| ------------------------------------ | ------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| `tests/test_spawn_fleet.py`          | Validation exits 2 with nothing created (24-102); blocked start exits 1 and says ask the user (406-438); denial never retried (451-458); unknown printed (460-467); teardown text printed per placement (537-620); Codex `/rename` (955-1012) | Script output only. No test reads `SKILL.md` or checks an agent's decision |
| `tests/test_backend_errors.py`       | herdr and cmux error classification table (45-147); only `agent_pane_busy` retried (150-175); receipts survive failure (178-336) | Pure classifier and mocked subprocess; no agent                           |
| `tests/test_correlation.py`          | Exact footer printed (50-61); `peer-inbox.py` selects only the matching reply and counts rejections (110-163) | Hand-written transcript JSONL; no agent writes or reads a reply          |
| `tests/test_schema.py`, `schema_check.py` | Examples validate and stay provisional (13-23)                                                       | Validator ignores `additionalProperties` and `pattern`/`$ref`/`oneOf`   |

None of the 15 behaviors above has an agent-level test today. The evaluation is the first proof of them.

## Failure history

| Source                                         | Observed failure                                                                                    | Corpus consequence                                                                                   |
| ---------------------------------------------- | --------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| `65eb358`                                      | Teardown ran as a default step of the loop                                                          | Work-done probe with no teardown request (B-007); seed that restores default teardown                |
| `4b26c96`                                      | Split teardown printed `close-workspace`, closing the user's workspace; closing UI left orphans     | Teardown-requested probe on a split fleet (B-008); seed that reverses kill/close order               |
| `e7415e4`                                      | A refused cmux caller check was read as "not in cmux", steering around the refusal                  | Denial probe (B-010)                                                                                 |
| `a8687f7`, PR #4                               | One folder-trust prompt aborted the whole fleet; a vanished blocked agent was reported blocked      | Blocked-session probe (B-009); seed telling the agent to answer the prompt                           |
| `35e006c`, PR #5                               | Generic `fleet-N` names; Codex `/rename` could hit a reused name; wrong-dir `codex resume`          | Worktree spawn probe (B-001); Codex runtime probe (B-003)                                            |
| `7d487d7` (inferred, no incident recorded)     | Guards against faking the socket and against `success: true` as completion                          | Codex-caller probe (B-011) and delivery-vs-completion probe (B-012)                                  |
| `eaefcce` (inferred from commit body)          | Agents chased a version fix when the harness scoped `SendMessage`                                    | Harness-scoped error probe (B-013)                                                                   |
| `d05957a`, PR #1                               | `placement.md` claimed the script kills PIDs; it only prints the line                                | Teardown probe checks the agent runs the kill itself only when asked                                 |

Worker research: test inventory and history drafted by two Haiku workers, verified by the parent against `tests/helpers.py:59-99`, `tests/fakes/fakebin.py:260-268`, `git show 65eb358 a8687f7`, and `references/manual-rig.md:80-92`.

## CI

- Platform: GitHub Actions. `.github/workflows/tests.yml` is the only workflow: `pull_request` and `push` to `main`, `permissions: contents: read`, jobs `lint` (ruff), `test` (unittest on `ubuntu-latest` and `macos-15`, Python 3.9 and 3.13) and `evaluation` (this plan's `pr` tier). No secret is referenced.
- macOS: from 2026-11-16 every `macos-latest` job was cancelled before its first step, annotated "The job was not acquired by Runner of type hosted even after multiple attempts" with a macOS arm64 capacity notice. The matrix pins `macos-15`.
- Secrets: `gh secret list -R muratkeremozcan/peer-sessions` is empty, so no event carries a model credential today.
- Merge flow: `main` has no branch protection or ruleset (API 404 and `[]`); merge, squash and rebase are all allowed; no merge queue. The post-merge event is the push to `main`.
- Release flow: no tags, no GitHub releases, no release or deploy workflow. The skill ships by cloning into `~/.claude/skills/`.
- Schedule: no workflow has a `schedule` trigger.
- Risk profile: highest contract severity is `critical` (B-003, B-007, B-008, B-009, B-010, B-011). One live development run is 15 steps over 5 arms and 3 trials of Opus 5.5 with command execution, about 80 minutes; the held-out run is 4 mutated arms, about 90 minutes.
- Live-tier prerequisites beyond the plan: `python3 -B evals/lab/lab.py start` and `python3 -B evals/lab/lab.py sync-root <commit> --root evals/root` before `tea-evaluate`, the lab PATH that `start` prints, the Claude CLI installed, and `CLAUDE_CODE_OAUTH_TOKEN` as a repository secret. The lab wraps `claude` in a Seatbelt profile, so the live tier runs on macOS. Scenario PIDs (941001 and up) sit above macOS `pid_max`.
- Plan: `evals/peer-sessions/ci/evaluation-ci-plan.json`, `tea-evaluate check` clean. `pr`: check, compile, seal, oracle-agreement, replay. `release`: preflight-live, twin-run, strength-comparison. The held-out partition is not in the plan: the repository folder declares no held-out partition, and held-out runs go through the private view on the author's machine. Deleted as inapplicable: api-conformance (no HTTP target), gameability (no gameability probe), judge-calibration (no rubric). No scheduled entries. No `gates` (no publish or deploy job).
- Deviations from AD-10 defaults: none. Live checks sit on `release`, their default for a target that needs a secret.
- `evaluation.json`: `tiers` = `["pr", "release"]`; the registry entry declares `"login": "claude"`, so a CI run hands the target `CLAUDE_CODE_OAUTH_TOKEN` and a local run keeps the Keychain login.
- Hand-off: the `pr` tier is rendered as the `evaluation` job (Node 24, `npm ci --prefix evals --ignore-scripts`, `tea-evaluate ci --tier pr`). The `release` tier is not rendered: the repository has no release event and no model secret. Open item. The README states what it needs: a `CLAUDE_CODE_OAUTH_TOKEN` repository secret and a release event.

Pull request checklist (`references/ci.md`):

1. Inputs committed (`contract.json`, `evaluation.json`, `requirements.md`, `probes/`, `mutations/`, `policy/`, `corpus-index.json`, `ci/evaluation-ci-plan.json`); `tea-evaluate check` exits 0. Holds.
2. Development run over that commit: `20261125T200115878Z-1c663b00` on `ddc0ddd`, `dirty: false`. Holds.
3. Scored by `20261125T211949359Z-9d827141`; no probe reads `unreached`, `abstained` or `oracle-error`. Holds.
4. Baseline accepted from that run and committed in `464a780`. Holds.
5. Held-out frozen and independent: read only through `gap-view.json`; `check` over the view prints no `held-out-drift` warning; run `20261125T215307308Z-4915c484` records the frozen `heldOutDigest` (`sha256:01e128b8…`) of view `held-out-w4njkfh1`. Holds, with the retired P-022, the P-024 witness repair, the option-token fix and the O-013 changes disclosed in the authoring log (now `evals/peer-sessions/authoring-log.md`) and the gap report.
6. `tea-evaluate ci --tier pr` exits 0 locally (`20261125T212009057Z-842ad665`). Holds.
7. The repository's pull request checks pass on the branch: recorded on the pull request.
8. `gap-report.md` opens with a filled `## Evaluation brief`. Holds.
