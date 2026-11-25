# Gap report: peer-sessions

## Summary

We tested the peer-sessions skill at commit `35e006c`.
Claude Opus 5.5 ran it in a lab with fake `cmux` and `herdr`.
There are 15 scenarios, one per behavior in `requirements.md`, and each one ran 3 times.
Each model call gets 540 seconds.

Both partitions pass.
The skill did the right thing in every scenario and every trial.
Every planted defect was caught in 3 of 3 trials, on both partitions.

## What the skill got wrong

One thing: SKILL.md section 2 never says where the reply-format request goes relative to the closing address (F-1).
In about 1 of 60 runs, the agent put it after the address, so the brief did not end with the caller's address, which B-005 requires.
This PR adds the missing sentence.

## Net improvements

- The F-1 sentence in SKILL.md.
- Past bugs are now scenarios that fail if they come back:
  - teardown running when nobody asked (B-007);
  - a split teardown closing the user's workspace, or closing panes before killing the sessions (B-008);
  - one folder-trust prompt aborting the whole fleet (B-009, PR #4);
  - a refused cmux caller check being treated as "not in cmux" (B-010, PR #3);
  - generic `fleet-N` session names (B-001, PR #5).
- For B-001, a planted copy of the old bug was caught 3 of 3 times.
  The others are guarded by passing scenarios only, as the next section says.

## What the evaluation can't prove

- 11 behaviors (B-004, B-006 to B-015) have no planted defect, because editing one file of the skill never made the model misbehave.
  They pass, but nothing shows their checks would catch a regression.
  Five of them are critical: B-007 to B-011.
- Several of those checks trust a flag the agent reports about itself (`answeredPrompt`, `rerouted`, `violation`).
  A reply that leaves the flag out passes.
- The same people wrote the held-out and the development cases.
  The held-out boundary hides the files from the agent only.
- One held-out instrument was repaired after the freeze: the P-023 witness fired on a correct reply.
  The held-out cases and checks stayed the same.
  The freeze moved to `sha256:671c9a9f…`, and the authoring log records it under "Instrument repair after the freeze".
- The agent ran outside TeA's sandbox so it could use the Keychain login.
  A Seatbelt profile still blocked it from the held-out folder.
- A live run needs a logged-in Claude CLI and about 80 minutes per partition, so CI runs only the offline `pr` tier.

Next step: add the `CLAUDE_CODE_OAUTH_TOKEN` repo secret so CI can run the live tier.

## Results

Development run `20261124T235450135Z-0ae6815c` on commit `9e121b3`, score `20261125T011351760Z-cebb6d6e`:

- 15 of 15 clean controls held in 3 of 3 trials.
- 4 of 4 planted defects caught: P-009 (B-001), P-011 (B-002), P-013 (B-003), P-016 (B-005).
- Accepted as the baseline: 199 files in `evals/peer-sessions/baseline/`, commit `4ec0cc4`.
  The local `pr` tier (`20261125T035133274Z-458049d5`) replays it with exit 0.

Held-out run `20261125T022308310Z-c1e0626a`, score `20261125T035055963Z-44839a38`, freeze `sha256:671c9a9f50392481e79313c9334dd5ba665cd5a0651c545f510f12739b1c6de5`:

- 4 of 4 planted defects caught, each in 3 of 3 trials: P-020, P-021, P-022 (critical), P-023.
- Read through its `gap-view.json`, which stays outside the repository.

Both partitions meet the defect floor of 1.

## Waivers

| Waiver | Rule | Why | Approved | Expires |
| --- | --- | --- | --- | --- |
| W-001 | `success-indicator-separation` | The skill's JSON answer has no success claim; every check reads a decision field. | Murat Ozcan, 2026-11-18 | 2027-11-18 |
| W-002 | `malformed-input` | A non-string `prompt` tests `tea-skill-runner`'s stdin handling, which the skill doesn't control. | Murat Ozcan, 2026-11-18 | 2027-11-18 |

Both still hold under eval-quality 10.1.1.
Since 10.1.1 applies waivers, both gaps count as waived and the verdict is PASS.

## Fixed during this run

- **G-6.** The read-only check rejected a correct teardown.
  It counted `2>/dev/null` as a write and allowed only six chained commands.
  It now allows discards to `/dev/null`, `>&1`, `>&2` and up to eight commands; any other write still fails.
  `teardown-split` then passed 45 of 45.
- **G-7.** P-016's signature and P-023's witness counted any reply with no brief as the defect.
  Both now need a brief whose final reply instruction is missing the address.
  O-012 and O-104 stayed the same.
  The reruns passed: development preflight `20261124T212156840Z-dd8634d7`, held-out preflight `20261125T015004756Z-fccd57e6`.
- **G-8.** The split teardown scenario never said which multiplexer was in use, so the agent closed a herdr fleet with `cmux close-surface`.
  The scenario now says herdr (commit `9e121b3`), and O-013 stayed the same.
  P-017 then held in 3 of 3 trials.
- Three runs stopped on lab problems and were rerun: `20261124T215739326Z-c190c1a6`, `20261124T222400201Z-d3bd0460`, and preflight `20261124T205104973Z-353d0839`.

Fixed earlier, on 2026-11-18 and 2026-11-19:

- **G-2.** The teardown check (O-001) requires `actionsRun`, `tellUser` and the teardown decision.
- **G-4, G-5.** The session-name and `actionsRun` checks look at every entry, and B-001 rejects generic names like `worker-1`.
- The launch and teardown checks read the commands the agent ran, so they work even when the agent leaves its decision flag out.

## Skill finding F-1

SKILL.md section 2 says a brief ends with the caller's address, and two lines later says to ask for a fixed reply format.
It never says which comes first.
In development run `20261124T232529002Z-e8ee2007`, the agent put the reply-format line after the address, and P-016's clean control failed.
It is rare: the clean prescreen passed 20 of 20, and the next run held 3 of 3.
The fix is one sentence in SKILL.md.

## Planted defects that didn't take

The full list is in `evals/peer-sessions/refusals.md`.
Two came from qualification runs:

- B-008, kill first (M-013): the agent followed `references/placement.md` anyway.
- B-009, folder-trust prompt (M-002): it showed up 5 of 5 times on its own step, but only 2 of 5 times in full runs, because the script's blocked-session text tells the agent to ask the user.
