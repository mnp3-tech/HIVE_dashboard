# Unified Dashboard — bounded MVP

Local-only, read-only-by-default operating picture for HIVE Core. It does not modify
PROD, WONG, ROCKET, or any existing HIVE implementation. The existing HIVE UI was used
as a visual reference; this is a separate surface.

## Scope of this MVP

1. **Project catalog** — projects known to HIVE Core, with explicit `valid` /
   `unavailable` / `unknown` / `auth_required` evidence instead of a fabricated empty
   or zeroed list.
2. **Task queue** — queued / active / completed / blocked task records, bucketed only
   from statuses the adapter actually receives. Unrecognized upstream statuses land in
   an explicit `unknown` bucket rather than being guessed into one of the four.
3. **Adapter health** — per-adapter `configured` / `authenticated` / `reachable` /
   `last_observed_at` / `last_seen` / `validity` / `reason`, kept distinct from each
   other (e.g. a stale adapter is never shown as `unavailable`, and an unconfigured one
   is never shown as `reachable`). `adapters.hive` additionally carries `health` and
   `ready` sub-records — the raw server-side provenance from HIVE Core's `/health` and
   `/ready` endpoints (see item 7).
4. **Evidence everywhere** — every metric, project-catalog fetch, and task-queue fetch
   carries `source`, `observed_at`, `validity`, and `reason`. Missing or weak evidence
   is surfaced as `unavailable`/`unknown`/`auth_required`, never silently treated as
   "no change".
5. **Proposal-only actions** — the only write path is `POST /api/control/dispatch`
   with `mode: "proposal"`. It requires explicit confirmation, requires a live
   reachability check against HIVE Core immediately before submitting (fails closed if
   that evidence is absent), and only ever creates an immutable proposal task
   (`apply_artifacts: false`). There is no apply, deploy, promote, rollback, or active
   replacement route anywhere in this adapter.
6. **Topology visualization is deferred** — removed from the active MVP surface. The
   snapshot returns an explicit `topology: {status: "deferred", reason: ...}` record and
   the UI renders a labeled deferred panel instead of a graph. No graph rendering or
   event-derived topology is computed anywhere in this codebase.
7. **HIVE health/ready monitor with provenance** — `server.py` calls HIVE Core's public
   `/health` and `/ready` endpoints directly (`health_probe()` / `ready_probe()`) and
   reports their raw status, database/queue sub-status, `observed_at`, `validity`, and
   `reason` under `core.ready` and `adapters.hive.health` / `adapters.hive.ready`. A
   `/health` call that returns an unrecognized status (or a 200 with no `status` field)
   is `unknown`, never fabricated as healthy.
8. **`auth_required` is distinct from `unavailable`/`unknown`.** A protected endpoint
   (`/projects`, `/tasks`, `/workers`, `/events`, `/system`) that rejects the request
   with HTTP 401/403 is reported with `validity: "auth_required"` — proof the endpoint
   is reachable and simply needs a valid token — never conflated with a connection
   failure (`unavailable`) or a 404 (`unknown`).
9. **Safe worker availability without an authenticated registry.** HIVE Core's public,
   unauthenticated `/ready` response already embeds a lower-detail worker-availability
   list. When the authenticated `/workers` registry is `unavailable` or
   `auth_required`, `worker_registry()` falls back to that public list instead of
   collapsing to an empty array — always evidenced as a fallback (`evidence.source`
   names `/ready`, `evidence.reason` explains why), never presented as the
   authenticated registry.
10. **CREATOR OPS status adapter (read-only, privacy-safe).** `creator_ops_status()`
    opens the local CREATOR OPS SQLite file in `mode=ro` (the connection cannot write)
    and runs only fixed `SELECT COUNT(*)` queries against a small hardcoded table
    allowlist. It returns aggregate row counts only — no captions, handles, notes,
    URLs, or credentials are ever read or exposed — surfaced in the snapshot as
    `adapters.creator_ops`. A missing or unreadable database file is reported
    `unavailable` with a real reason, never as zeroed counts.
11. **AO (Agent Orchestrator) CLI bridge — session listing, history, and controlled,
    idempotent send only.** AO's documented interface is a local CLI (`ao`) over its
    daemon; no public HTTP API is published for session, worker, or chat data, and
    this adapter never guesses at or probes the daemon's internal transport, and
    never reads AO's own internal SQLite store. Instead it bridges exactly four
    documented, verified `ao` subcommand shapes via `subprocess.run(..., shell=False)`
    with a hardcoded argv allowlist:
    - `GET /api/ao/sessions` → `ao session ls --all --json`
    - `GET /api/ao/sessions/<id>/history?limit=&offset=` → `ao session history <id> --limit --offset`
    - `POST /api/ao/sessions/<id>/send` (requires `{"message": ..., "confirm": true}`, optional `client_message_id`) → `ao send --session <id> --steer --message <text> --client-message-id <id>`
    - `POST /api/ao/sessions/<id>/send/recover` (requires `{"client_message_id": ..., "confirm": true}`) → `ao send --session <id> --steer --recover-only --client-message-id <id>`

    Send always uses the documented atomic `--steer` transport ("one atomic daemon
    operation" per `using-ao`'s `send` reference) together with a `--client-message-id`
    — the only AO send mode with a documented idempotent round-trip. A caller-supplied
    `client_message_id` is validated and reused verbatim, never silently replaced; one
    is generated when omitted. If the CLI call fails or times out, the error message
    explicitly preserves that id and points at `/send/recover` instead of resending —
    recovery calls `--recover-only`, which asks the daemon for the recorded delivery
    outcome without re-sending the original message, so it can never double-deliver.

    The bridge is disabled unless `AO_CLI_PATH` is set to an absolute path to an
    existing `ao` binary; when disabled, or when a CLI call fails or times out, these
    routes report `validity: "unavailable"` (or, for `send`/`send/recover`, a
    fail-closed error carrying the delivery handle) with a real reason instead of
    fabricating success. Session ids and client message ids are validated against
    fixed allowlist patterns, send messages are length-bounded, `history`
    `limit`/`offset` are bounded server-side (limit ≤ 50, matching the CLI's own cap),
    every call has an 8-second timeout, and CLI stdout/stderr is bounded to 200,000
    characters. `redact_secrets()` applies a best-effort regex redaction (bearer
    tokens, `key=value` secrets, provider API-key prefixes, AWS access key IDs,
    JWT-shaped strings) to all CLI output before it is returned — a defensive filter,
    not a guarantee, since session history is free-form chat text that could contain
    an inline secret in an unanticipated shape.

    **`send` and `send/recover` additionally require caller authentication,
    independent of `AO_CLI_PATH`.** Set `AO_SEND_CALLER_TOKEN` to a server-held
    secret; every request to either route must carry a matching
    `Authorization: Bearer <token>` header, checked with `hmac.compare_digest`
    (constant-time) via `require_ao_send_caller_auth()` **before** the request body
    is read, before JSON is parsed, and before `ao_send()`/`ao_recover_send()` is
    ever called. A missing, malformed, or wrong token is rejected with `401`. If
    `AO_SEND_CALLER_TOKEN` is unset, both routes reject every request with `503`
    rather than treating an unconfigured gate as "no auth required" — there would be
    no server-held value to authenticate a caller against. The expected value is
    always the server-configured `AO_SEND_CALLER_TOKEN`; a client-supplied header
    value is only ever the candidate being checked, never accepted as the
    reference. (session listing and history do not carry this requirement — they
    are read-only and gated only by `AO_CLI_PATH`.)

    `/api/control/capabilities` reports `ao.session_list_confirmed` /
    `session_history_confirmed` as `true` whenever `AO_CLI_PATH` is configured.
    `send_confirmed` / `send_recover_confirmed` additionally require
    `AO_SEND_CALLER_TOKEN` to be configured — `ao.caller_auth_configured` reports
    that fact directly — since those routes cannot actually be reached by any
    caller otherwise. `worker_api_confirmed` and `chat_realtime_api_confirmed`
    remain `false` always — no such contract is documented for AO.
12. **Worker routing policy read-model (`GET /api/control/worker-policy`).**
    `WORKER_POLICY` is a static, in-memory table declaring `capability`,
    `execution_mode` (`local`/`remote`), `cost_mode` (`free`/`subscription`/
    `metered`/`unknown`), `network_requirement`, and `fallback_policy` for every
    worker id this adapter accepts as `preferred_worker`. It is purely
    declarative — reading it never probes a port, calls a service, or starts one
    (no LM Studio autostart); any local-service metadata it carries stays a
    static classification, never a live, dialable address. `evaluate_worker_policy()`
    is the fail-closed admission check `dispatch()` now runs instead of the old
    flat allowlist: only `cost_mode` `free`/`subscription` is ever accepted —
    `metered` and `unknown` (including any worker id not in the table, e.g.
    `antigravity`/`codex` today) are always blocked, never allowed through by
    default — and local-first routing means a remote (`execution_mode: "remote"`)
    worker is blocked whenever the caller sets `local_only`, regardless of its
    cost_mode. A blocked worker makes `dispatch()` fail closed with `400` and the
    specific `blocked_reason`; no proposal is ever submitted to HIVE Core for it.

## Run

From this directory:

```powershell
.\start.ps1
```

Open `http://127.0.0.1:4173/` for live-adapter mode. The local adapter serves the UI and
requests HIVE Core on loopback only. It exposes `GET /api/dashboard/snapshot`,
`GET /api/control/capabilities`, `GET /api/control/worker-policy`, the controlled
`POST /api/control/dispatch` route, and
the AO CLI bridge routes (`GET /api/ao/sessions`, `GET /api/ao/sessions/<id>/history`,
`POST /api/ao/sessions/<id>/send`, `POST /api/ao/sessions/<id>/send/recover`)
described in item 11 above.

To enable the AO CLI bridge, set `AO_CLI_PATH` to an absolute path to the `ao` binary
before starting the adapter. To additionally enable `send`/`send/recover`, also set
`AO_SEND_CALLER_TOKEN` to a secret value, and present it as a bearer token on every
request to those two routes:

```powershell
$env:AO_CLI_PATH = 'C:\Users\Martin\AppData\Local\Programs\agent-orchestrator\resources\daemon\ao.exe'
$env:AO_SEND_CALLER_TOKEN = (New-Guid).Guid
.\start.ps1
```

```powershell
# Example authenticated call to the send route
Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:4173/api/ao/sessions/mer-3/send' `
    -Headers @{ Authorization = "Bearer $env:AO_SEND_CALLER_TOKEN" } `
    -ContentType 'application/json' `
    -Body '{"message": "Focus only on the backend.", "confirm": true}'
```

Leaving `AO_CLI_PATH` unset is the safe default: `session listing`/`history` report
`validity: "unavailable"` rather than attempting to locate or guess at the `ao`
binary's location. Leaving `AO_SEND_CALLER_TOKEN` unset is likewise the safe default
for `send`/`send/recover`: both reject every request with `503` even if `AO_CLI_PATH`
is configured, since there is no way to authenticate a caller without it.

Set the Core URL and token only in the process environment; never put the token in the
browser, source tree, or command output:

```powershell
$env:HIVE_CORE_URL = 'http://127.0.0.1:8765'
$env:HIVE_API_TOKEN = (Get-Content 'C:\HIVE\runtime\api-token' -Raw).Trim()
.\start.ps1
```

`HIVE_CORE_URL` must resolve to a loopback address (`127.0.0.1`, `::1`, or
`localhost`); the adapter refuses to start otherwise, and `core_json()` refuses every
individual request to a non-loopback target as a second, independent check. `--bind`
is checked the same way.

Only set `HIVE_API_TOKEN` if you also have a real HIVE Core token. Additionally, only
set `$env:HIVE_HEALTH_REQUIRES_AUTH = 'true'` if you have independently verified that
*this* HIVE Core deployment's `/health` route requires and validates that bearer
token — this is what allows `adapters.hive.authenticated` to become `true` on a
successful call. Leaving it unset is the safe default: a successful `/health` call
then only ever proves reachability, never authentication.

For visual QA only, use `http://127.0.0.1:4173/?demo=1`. The banner marks fixture mode;
the default route never fabricates projects, tasks, or adapter health.

## Adapter contract

The snapshot endpoint returns the shape in [snapshot.example.json](snapshot.example.json):
`core`, `metrics`, `adapters` (per-adapter health), `projects` (`items` + `evidence`),
`tasks` (`items` + `evidence`), `workers`, `events`, and `topology` (always `deferred`
in this MVP). The browser never receives HIVE Core credentials. `server.py` is
responsible for authenticating to HIVE Core, normalizing upstream shapes into this
contract, and setting `validity` to `valid`, `stale`, `unavailable`, or `unknown`.

The UI treats `null`/`unavailable`/`unknown` as distinct from zero or an empty-but-valid
result. A 404 from HIVE Core on an allowlisted path is treated as `unknown` (endpoint not
present on this Core version); a connection failure or timeout is treated as
`unavailable`.

## Security hardening applied after independent review

An independent review of an earlier commit on this branch found four issues, all
remediated here:

- **Loopback enforced, not assumed.** `--bind` and `HIVE_CORE_URL` are both validated
  against loopback forms (`127.0.0.1`, `::1`, `localhost`) at process startup, and the
  server refuses to start otherwise. `core_json()` re-checks this on every call *before*
  constructing the request or attaching the bearer token, so a misconfigured
  `HIVE_CORE_URL` can never cause the token to be sent to a non-loopback host.
- **`task_type` is allowlisted server-side.** The UI only offers a fixed list, but that
  was client-side only; `dispatch()` now independently rejects any `task_type` outside
  `{EVOLUTION_TASK, GENERAL, ANALYSIS, PROJECT_TASK, RESEARCH}`.
- **Optional adapter fetches keep their evidence on failure.** `/system`, `/workers`,
  and `/events` failures used to collapse into an empty/default value with no
  provenance. They now go through `fetch_with_evidence()`, and `workers`/`events` in the
  snapshot carry the same `{items, evidence}` shape as `projects`/`tasks`; a failed
  `/system` fetch also propagates its real reason into the CPU/memory/disk metrics
  instead of a generic "not supplied".
- **No more fabricated timestamps or validity.** A missing event timestamp is reported
  as `timestamp: null, timestamp_validity: "unknown"` instead of being stamped with the
  current time. A `/health` call that returns 200 with a missing or unrecognized
  `status` field is reported as adapter `validity: "unknown"` (not `"valid"`) even
  though it was reachable. `authenticated` now means a token was actually sent and not
  rejected; a `token_configured` field reports the separate, weaker fact that a token
  string is present in the environment — a 401/403 rejection (or any other failure) now
  always reports `authenticated: false`, even when a token is configured.

A follow-up review found that this last fix still fabricated `authenticated: true`
whenever a token was configured and `/health` happened to return 200 — but a
successful response does not, by itself, prove `/health` even checks the token (it
may be a public endpoint). This is fixed: `authenticated` is now `false` by default
whenever that proof is missing, and `adapters.hive.authentication_validity` reports
`"unknown"` (distinct from both `token_configured` and from an explicit `401`/`403`
rejection, which is `"unavailable"`). `authenticated` only becomes `true` if the
operator sets `HIVE_HEALTH_REQUIRES_AUTH=true` — an explicit, documented statement
that *this* HIVE Core deployment's `/health` route is known to validate the bearer
token — and the call still succeeds. Left unset (the default), a successful call
only ever proves reachability, never authentication.

## Current evidence and limits

- A live local HIVE Core instance (`http://127.0.0.1:8765`, no bearer token
  configured) was reachable during this session and used to verify the behavior
  documented above end to end: `/health` returns `status: "alive"` (recognized as
  healthy), `/ready` returns `status: "ready", database: "ok", queue: "running"` plus
  a public worker-availability list, and the protected `/projects`, `/tasks`,
  `/workers`, `/events` endpoints all correctly return `auth_required` rather than
  being fabricated as an empty-but-valid catalog. [snapshot.example.json](snapshot.example.json)
  is a real captured snapshot from that session (worker list trimmed for length), not
  a hand-written fixture.
- Beszel is intentionally **not implemented** in this MVP. The adapter reports it as
  `configured: false` (or `true` if `BESZEL_URL` happens to be set) with
  `validity: "unknown"` and an explicit "not implemented, deferred" reason; it is never
  shown as reachable.
- Topology visualization is deferred by design, not by omission — see item 6 above.
- The AO CLI bridge (session listing, history, controlled send) is reported as
  unavailable unless `AO_CLI_PATH` is configured — see item 11 above. No other AO
  surface (worker registry, realtime chat, HTTP API, or internal SQLite) is read.

## Files

- `index.html` — accessible responsive shell: overview, projects, tasks, adapters, and
  proposals nav targets, plus an explicit deferred-topology panel.
- `styles.css` — visual system, responsive layouts, reduced-motion support.
- `app.js` — adapter fetch, normalization, per-section evidence rendering, proposal-only
  submission form, and an explicitly gated visual fixture mode (`?demo=1`).
- `server.py` — loopback-only static server and narrow HIVE Core adapter. Normalizes
  project/task/adapter-health evidence (including `/health`/`/ready` provenance and
  `auth_required`), exposes a read-only CREATOR OPS aggregate-status adapter, bridges
  a fixed, verified slice of the AO CLI contract (session listing/history gated by
  `AO_CLI_PATH`; idempotent, caller-authenticated send/recover additionally gated by
  `AO_SEND_CALLER_TOKEN`), declares a static worker routing policy read-model
  (`WORKER_POLICY` / `evaluate_worker_policy()`, local-first + free/subscription-only
  cost-mode admission), and exposes only a proposal-only, fail-closed dispatch route.
  No arbitrary proxy, shell route, provider credential forwarding,
  apply/deploy/promote/rollback route, or topology/graph computation.
- `snapshot.example.json` — a real captured snapshot (worker list trimmed for length)
  showing the reachable-but-unauthenticated contract: `core.ready`, `auth_required`
  evidence on protected endpoints, the `/ready`-sourced worker fallback, and the
  `creator_ops` adapter.
- `tests/test_server.py` — stdlib `unittest` coverage for the adapter contract
  (evidence semantics, status bucketing, adapter health, `/health`+`/ready` probes,
  `auth_required` vs. `unavailable`/`unknown`, the `/ready` worker fallback, the
  CREATOR OPS adapter) and the proposal-only safety gates (confirmation required,
  non-proposal modes rejected, worker allowlist, fail closed on missing token or
  missing reachability evidence). Also covers the AO CLI bridge: `AO_CLI_PATH`
  configuration detection, the argv allowlist (refusing to spawn when unconfigured or
  when a subcommand prefix isn't allowlisted), `shell=False` and exact argv
  assertions, timeout/non-zero-exit/invalid-JSON handling, session-id/client-message-
  id/message/limit/offset validation, session-list normalization, the idempotent
  atomic-steer send contract (auto-generated vs. caller-supplied `client_message_id`,
  delivery-handle preservation on failure/timeout for recovery), `--recover-only`
  recovery, secret redaction, and the `AO_SEND_CALLER_TOKEN` caller-auth gate —
  including real HTTP-level requests against a loopback `ThreadingHTTPServer`
  (missing/malformed/wrong/unconfigured-token rejection before the body is ever
  read or AO ever invoked, plus one positive fixture with the `ao` CLI itself
  mocked at the `subprocess.run` boundary). Also covers the worker routing policy
  read-model: known-worker/unknown-worker record shape, free/subscription
  acceptance (including a synthetic fixture for `subscription`, since no currently
  declared worker carries that label), metered/unknown-cost-mode and unrecognized-
  worker-id blocking, local-first routing blocking a remote worker under
  `local_only`, no-side-effects (`subprocess.run`/`urlopen` never called), and
  `dispatch()` wiring (blocked worker → `400` with the policy reason; an allowed
  free local worker still succeeds end to end).

## CREATOR OPS adapter

Set `CREATOR_OPS_DB_PATH` to override the default location
(`C:\Users\Martin\Documents\ChatGPT\CREATOR OPS\data\creator_ops.sqlite3`). The
adapter opens this file in SQLite URI `mode=ro` (the connection cannot write) and
only ever runs fixed `SELECT COUNT(*)` queries against a hardcoded table allowlist —
no row content is read. A missing file, a locked file, or a non-SQLite file is
reported `unavailable` with a real reason.

## Tests

```powershell
python -m py_compile server.py tests/test_server.py
python -m unittest tests.test_server -v
```

Both commands were run in this session: `py_compile` succeeded with no output, and all
152 unit tests pass.
