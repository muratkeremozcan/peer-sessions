# Transport contract v1

Status: **pending**. No consumer has recorded agreement with this version yet.
Receipts carry `"contract": {"status": "pending"}` until one does.
Fixtures in `examples/` are labeled `provisional, non-authoritative`.

This is an operational API agreement between peer-sessions (the transport) and any tool that schedules work over it (a coordinator).
It says who issues each field, what the transport promises to record, and what it never decides.

## Layers

peer-sessions owns transport facts: which backend and runtime started a session, the identity the backend exposes, the cwd, which resources one launch created, and how a request identity travels to a peer and back.

A coordinator owns meaning: runs, workstreams, assignment generations, workspace provisioning, completion, integration, and cleanup policy.
The transport echoes the coordinator's IDs verbatim and never interprets them.
A correlated reply proves a peer answered a request; it does not establish completion.

## Fields and issuers

| Field | Issued by | Carried in | Transport behavior |
|---|---|---|---|
| `run_id`, `workstream_id`, `generation` (any key) | coordinator | `spawn-fleet.py --correlate KEY=VALUE` into `receipt.correlation` | echoed verbatim, never validated beyond `KEY=VALUE` shape |
| request `id`, `target`, `generation` | coordinator | `peer-request:` / `peer-reply:` lines (`scripts/peer_correlation.py`) | matched exactly; no IDs invented |
| `launch_id` | transport | receipt | random per launch; names the launch, not the work |
| `backend`, `runtime`, `placement` | transport, from explicit flags or documented `auto` rules | receipt | `auto` resolution recorded as the resolved value |
| `cwd`, `directory_created` | caller supplies the path; transport records creation | `receipt.sessions[]` | `directory_created: true` only when this launch made it |
| herdr `pane_id`, `terminal_id`, `workspace_id`, `tab_id`, `agent_kind` | herdr | `receipt.sessions[].identity` | herdr reports no PID; none is recorded for herdr-only runtimes |
| Claude `pid`, `session_id`, `proc_start`, `messaging_socket` | Claude registry | `receipt.sessions[].identity` | bound only to a registry record that appeared during this launch with the same name and cwd; ambiguous matches record `registry_candidates` and no PID |
| cmux `surface`, `workspace`, `window` | cmux | receipt resources and identity | UUIDs when cmux returns them; a ref is kept beside the UUID it was resolved to |
| display name | caller | `receipt.sessions[].name` | a label; herdr moves a name with the pane occupant, so readiness also checks terminal or pane identity |

## Launch receipt

Written by `spawn-fleet.py --receipt PATH` after every allocation, and printed on stdout with `--json`.
Schema: [`schemas/launch-receipt.v1.schema.json`](../schemas/launch-receipt.v1.schema.json).

- `status`: `launching`, `ready` (all sessions ready), `incomplete` (some not ready or blocked at the timeout), `partial` (a backend operation failed after something was created), `failed` (failed before anything was created).
- `resources[]`: every directory, window, workspace, surface or pane this launch created, recorded the moment it exists, each with `owned: true`, the creating operation and its session.
  A teardown names only these.
- `sessions[].state`: `pending` → `start_requested` → `started` → `ready`, or one of `not_ready`, `blocked`, `denied`, `unknown`, `failed`.
- `failure`: the exact operation, backend, error code, exit status, message and outcome:
  - `transient`: known short race (herdr `agent_pane_busy`); retried for a few seconds, never reported as a final outcome unless retries run out.
  - `blocked`: the agent stopped at an approval or question UI.
  - `denied`: the backend or OS refused. Report it; do not route around it.
  - `unknown`: no usable answer. The operation may have happened. Reconcile before retrying.
  - `failed`: the backend rejected the operation.

Nothing is torn down automatically on success or failure.
Partial resources stay for inspection, and the printed teardown block names exactly the owned ones.

## Delivery, response and completion

These are separate evidence states and the transport never merges them:

1. **Delivered**: `SendMessage` returned `success: true`, or `herdr agent prompt` returned. Proves arrival only.
2. **Responded**: a reply carrying the matching `peer-reply:` line was found (`peer-inbox.py --request-id`, exit 0, `evidence: reply-correlated`).
3. **Completed**: decided by the coordinator against its own acceptance evidence.

A reply for another request id, target or generation is counted by reason and cannot satisfy the current request.
A lost delivery acknowledgment is reconciled (read the transcript or pane) before any resend.

## Versioning

`schema_version` is an integer.
New optional fields keep version 1.
A new required field or changed state meaning bumps the version; readers refuse versions they do not know.
