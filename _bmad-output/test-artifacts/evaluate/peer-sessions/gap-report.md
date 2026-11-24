# Gap report: peer-sessions

Target: `SKILL.md` at `35e006c`. Target model `claude-opus-5-5`, 3 trials per probe, fake multiplexer lab, confinement opt-out (Keychain login).

## Development result

Run `20261118T220237256Z-7e64dfa5`, score `20261118T233125699Z-93d3427e` (score exit 0, every probe's eval-quality score exit 0).

| Reading | Value |
| --- | --- |
| Clean controls (P-001..P-008, P-010, P-012, P-014, P-015, P-017..P-019) | 15 of 15 held in 3 of 3 trials |
| Defect probes P-009 (B-001), P-011 (B-002), P-013 (B-003), P-016 (B-005) | 4 of 4 caught, caughtCount 3 of 3 each |
| `strength-aggregate.json` defect class | eligible 4, exercised 4, caught 4, rate 1, comparable true |
| Floor decision (defect, floor 1) | `meets`, basis `rate-meets-floor` |
| gameability, zero-action | null, no floor declared |
| Contract verdict per probe | CONCERNS, from the two waived rules only |

No probe failed, missed or abstained.

## Held-out result

Run `20261119T020859253Z-d8ab3a73`, score `20261119T034326509Z-3eda3cfd`, read through `gap-view.json`:

| Probe | Severity | Caught | caughtCount / validCount |
| --- | --- | --- | --- |
| P-020 | material | true | 3 / 3 |
| P-021 | material | true | 3 / 3 |
| P-022 | critical | true | 3 / 3 |
| P-023 | material | true | 3 / 3 |

Held-out `strength-aggregate.json`: defect eligible 4, exercised 4, caught 4, rate 1, comparable true; floor `meets` (`rate-meets-floor`). Contract verdict CONCERNS from the two waived rules only.

## Closed gaps

- G-2 `whole-body`: the `teardown-after-work` oracle (B-007, O-001) checks `existence(actionsRun)`, `existence(tellUser)` and the teardown decision, with all three in `evidenceTargets`.
- G-4 `per-record` and G-5 `omission-and-completeness`: `/sessionNames` and `/actionsRun` are collection locations with no reference set. The B-001 spawn-worktree oracles (development and held-out) quantify over every session name and reject `^(worker|fleet|peer|session|agent)-?[0-9]+$`; the B-003 and B-007 checks quantify over `actionsRun`.
- Answer-key omission: in held-out run 12 and held-out preflight 14 the agent did the seeded or asked-for action but left the decision flag (`runtimeLaunched`, `teardownRun`) out of its reply. `launched_claude` and `ran_teardown` in `evals/lab/build_corpus.py` also read the commands in `actionsRun`, so O-001, O-010, P-022 and the teardown sensitivity witness no longer depend on the flag alone.

## Waived gaps

| Waiver | Rule | Rationale | Approval | Expires |
| --- | --- | --- | --- | --- |
| W-001 | `success-indicator-separation` | The skill's JSON answer carries no success claim; every oracle reads a decision field. Nominating a field as the indicator would misdescribe the answer. | Murat Ozcan, 2026-11-18 | 2027-11-18 |
| W-002 | `malformed-input` | A non-string `prompt` exercises `tea-skill-runner`'s stdin handling, which the skill does not control. | Murat Ozcan, 2026-11-18 | 2027-11-18 |

Engine limitation: eval-quality 9.0.0 checks only that each waiver is complete (`dist/core/compile/waivers.js`). Coverage and the verdict ladder (`dist/core/score/ladder.js`, `coverage-gap-at-or-above-floor`) never read `contract.waivers`, and `application/score.js` passes waiver `'none'`. A waived rule therefore still yields CONCERNS. The contract verdict stays CONCERNS until TeA applies waivers; this is a TeA issue to file.

## Refused seeds (no defect probe)

Eleven behaviors keep their clean control with no defect probe: `evals/peer-sessions/refusals.md`. Two of the refusals came from qualification evidence:
- B-008 kill first (M-013): held in preflight 4; the agent followed `references/placement.md`.
- B-009 folder-trust prompt (M-002): manifested 5 of 5 on its own step but held in 2 of 5 full-plan qualifications; the script's blocked-session text tells the agent to ask the user.

The defect class therefore measures four behaviors (B-001, B-002, B-003, B-005). The critical safety behaviors (B-007 teardown, B-008, B-009, B-010, B-011) are guarded by clean controls only: a regression there shows up as a clean-control failure, and no seeded probe proves the oracle would see it.

## Baseline

Not accepted. `tea-evaluate compare --accept` refused run `20261118T220237256Z-7e64dfa5` with exit 10: `run.json` records `dirty: true`, and a run over uncommitted work is never a baseline. The evaluation files must be committed, a development run made over that commit, and that run accepted.
