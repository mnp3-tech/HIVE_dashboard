# Unified Dashboard — bounded MVP

> **Start here before changing code.** This README explains where the dashboard lives on
> Martin's PC, which stores are authoritative, how local components communicate, and
> which parts are current MVP behavior versus the target HIVE cockpit. The complete
> implementation handoff is [HIVE_DASHBOARD_CLAUDE_HANDOFF.md](HIVE_DASHBOARD_CLAUDE_HANDOFF.md).

## 0. Required reading order for Claude

1. Read this README for the storage, authority, runtime, and communication map.
2. Read [HIVE_DASHBOARD_CLAUDE_HANDOFF.md](HIVE_DASHBOARD_CLAUDE_HANDOFF.md) for the
   target visual/functional contract and acceptance criteria.
3. Inspect the actual Git state with `git status --short --branch` and `git rev-parse HEAD`.
4. Inspect only the relevant source files and tests; do not dump the whole repository or
   historical HIVE workspaces into context.
5. Run the smallest relevant test before and after each implementation phase.

The README describes the current bounded adapter MVP. The handoff document describes
the desired next-stage dashboard. A statement such as `topology: deferred` is therefore
current-state evidence, not a rejection of the target CORE visualization.

## 1. PC storage and authority map

| Location | Purpose | Authority / write policy |
|---|---|---|
| `C:\Users\Martin\Documents\ChatGPT\DASHBOARD` | This dashboard repository: UI, local adapter, fixtures, tests, launcher scripts, handoff | Claude may implement here or in an isolated branch; do not put secrets in Git |
| `C:\Users\Martin\HIVE` | HIVE production/runtime checkout | PROD; read-only for review; never modify from this dashboard task |
| `C:\Users\Martin\HIVE-work\codex-e3` | Codex independent-review/prototype lane and historical evidence | Read-only reference for this dashboard handoff; do not copy the whole tree into context |
| `C:\Users\Martin\HIVE-work\coordination` | Coordination artifacts and handoffs | Read-only unless explicitly authorized for a specific output |
| `C:\Users\Martin\Documents\ChatGPT\CREATOR OPS\data\creator_ops.sqlite3` | Local CREATOR OPS SQLite database | Used only when `CREATOR_OPS_DB_PATH` points at it; opened read-only (aggregate counts, plus the allowlisted `task_definitions` catalog for the Registry) |
| `C:\Users\Martin\AppData\Local\Programs\agent-orchestrator\resources\daemon\ao.exe` | Optional local AO CLI binary | Discovered by `start.ps1` when present; invoked only through the fixed allowlist |
| `docs/assets/` | Stable visual references committed with this repository | Safe read-only design input for Claude and UI review |
| Obsidian vault | Human-readable shared project projection | Path is intentionally not guessed; WONG remains canonical and live projection is disabled until explicitly configured |
| runtime token/config locations | HIVE/AO/provider credentials | Never copied into Git, browser storage, README, fixtures, or screenshots |

The dashboard repository is a separate surface. It is not the HIVE Core source tree and
must not become a second memory, release, or security authority.

## 2. Component map

```text
Desktop browser
    │  same-origin HTTP only
    ▼
Dashboard server: server.py
    │  loopback adapter, normalization, evidence, fail-closed proposal routes
    ├── HIVE Core: http://127.0.0.1:8765 by default
    │     /health, /ready, and authenticated read-only resources when a token exists
    ├── AO CLI: local subprocess only when AO_CLI_PATH is configured
    │     session listing/history; controlled send/recover with separate gates
    ├── CREATOR OPS SQLite: local mode=ro aggregate queries only
    ├── local worker adapters: LM Studio/OpenCode only through bounded contracts
    └── future explicit adapters: GPT / Claude / Codex / Obsidian / Internet
          no cookie scraping, credential forwarding, or guessed private APIs
```

For isolated UI/API work, use `fixture_server.py` instead of `server.py`. It is a
separate loopback-only runtime with deterministic synthetic data, no credential
loading, no external connections, no subprocesses, and no write routes. It does
not touch HIVE Core, AO, WONG, ROCKET, or provider sessions.

The browser never receives HIVE Core credentials and never calls HIVE Core directly.
The server is the trust boundary for URL validation, bearer-token use, normalization,
redaction, evidence, timeouts, and proposal-only writes.

Default local dashboard URL:

```text
http://127.0.0.1:4173/
```

Default local HIVE Core target configured by `server.py`:

```text
http://127.0.0.1:8765
```

The Core target must remain loopback-only. A different local port may be supplied through
`HIVE_CORE_URL`, but the adapter refuses non-loopback targets.

## 3. Where data is stored

### Dashboard repository

- `app.js` — browser rendering, evidence states, demo fixture handling, and proposal UI.
- `index.html` — dashboard shell and accessible navigation targets.
- `styles.css` — current visual system and responsive desktop styling.
- `server.py` — local loopback server and narrow HIVE/AO/CREATOR OPS adapters.
- `fixture_server.py` — standalone read-only runtime fixture/API for safe UI testing.
- `snapshot.example.json` — captured example of the normalized adapter contract; it is
  evidence/fixture data, not a live database.
- `tests/` — server and UI contract tests.
- `start.ps1`, `status.ps1`, `stop.ps1` — live-adapter launcher/status/stop helpers.
- `start-fixture.ps1`, `status-fixture.ps1`, `stop-fixture.ps1` — isolated fixture helpers.
- `HIVE_DASHBOARD_CLAUDE_HANDOFF.md` — target implementation contract for Claude.
- `docs/assets/` — committed dashboard and CORE reference images.

### Runtime-generated files

The launcher may create:

```text
.dashboard.pid
.dashboard.launch.json
```

These are local runtime state and are excluded by `.gitignore`. They must not be
committed or treated as evidence of HIVE Core state.

The fixture launcher may create the separate files `.fixture-dashboard.pid` and
`.fixture-dashboard.launch.json`. They identify only the local fixture process and
are also excluded from Git.

### HIVE Core and WONG

The dashboard does not read HIVE Core's internal database directly. It calls the documented
loopback API and records source, timestamp, validity, and reason for each observation.

WONG is the canonical memory and decision authority. The dashboard may display a
human-readable projection of project context, but it must not silently create a competing
canonical store.

### Obsidian

Obsidian is a shared project-context and human-readable projection layer. The vault path
is not hardcoded or guessed. Until an explicit connector and vault selection are enabled,
the dashboard must show the integration as disabled/unconfigured rather than inventing a
live connection.

### Provider state

GPT, Claude, and Codex are worker providers, not competing HIVE authorities. They have
equal weight in HIVE; routing depends on capabilities, task requirements, availability,
approval, and cost. Provider credentials and private web sessions are never stored here.

## 4. Communication and write matrix

| Component | Reads | Writes | Notes |
|---|---|---|---|
| Browser UI | Normalized dashboard API | Proposal request only | No provider credentials; no direct Core access |
| `server.py` | HIVE API, AO CLI output, local read-only SQLite | Immutable local proposal request | Normalizes evidence and fails closed |
| HIVE Core | Its own runtime state | Its own runtime state | Accessed through documented API only |
| AO CLI bridge | Session list/history and documented delivery outcomes | Controlled send only when all gates pass | `AO_CLI_PATH`, caller token, and authorized session are separate gates |
| Obsidian adapter | Explicitly selected project context | Only explicitly authorized projection | Never guess vault; no scope expansion |
| WONG | Canonical memory/decisions | Canonical decisions | Higher authority than dashboard fixtures or provider claims |
| ULTRON | Connections, tools, attachments, policy events | Security decisions/audit events | MVP guard; not a full antivirus |
| EVOLVE | Broad sanitized evidence | Isolated branch/proposal/backup | Never direct production or silent WONG mutation |
| GPT/Claude/Codex adapters | Provider-returned data only | Provider action only if supported and authorized | Unsupported operations remain UNKNOWN/NOT_CONNECTED |

Normal dashboard data flow:

```text
HIVE Core / AO / local adapters
       │
       ▼
server.py normalizes evidence
       │
       ▼
GET /api/dashboard/snapshot
       │
       ▼
browser UI and CORE overlay
```

The future live visualization should consume normalized events rather than inventing
activity. A real event can animate the CORE, move an agent toward Internet/Obsidian/another
agent, and create a correlation pulse. Silence alone must never create a WORKING state.

## 5. Runtime configuration contract

Environment variable values are local runtime inputs and must never be committed:

| Variable | Meaning | Safe default |
|---|---|---|
| `HIVE_CORE_URL` | Loopback HIVE Core URL | `http://127.0.0.1:8765` |
| `HIVE_API_TOKEN` | Server-side bearer token for protected Core resources | unset; protected resources report `auth_required` |
| `HIVE_HEALTH_REQUIRES_AUTH` | Explicit operator assertion that this Core validates auth on `/health` | false/unset |
| `AO_CLI_PATH` | Absolute path to the local `ao.exe` | auto-discover known local path or disabled |
| `AO_SEND_CALLER_TOKEN` | Server-held caller-auth token for send/recover | unset; send rejected |
| `AO_SEND_SESSION_ID` | One explicitly authorized AO session for send | unset; send rejected |
| `CREATOR_OPS_DB_PATH` | Local CREATOR OPS SQLite path | documented local default |
| `LMSTUDIO_ENDPOINT` | Loopback LM Studio endpoint override | `http://127.0.0.1:1234` |
| `CODEX_SUBSCRIPTION_CONFIRMED` | Operator confirmation of actual Codex billing mode | false/unset; metered/unknown blocked |
| `OPENCODE_EXECUTION_CONFIRMED` | Explicit opt-in for bounded disposable execution | false/unset |
| `BESZEL_URL` | Optional future Beszel configuration | not implemented in current MVP |

Never place the actual values in `.env`, Git, screenshots, prompt text, or browser local
storage. If an environment file is added later, commit only a redacted `.env.example`.

## 6. Current state versus target state

### Verified current MVP

- Local server and browser shell exist.
- Evidence-aware snapshot contract exists.
- HIVE `/health` and `/ready` probing exists.
- Protected HIVE resources can be reported as `auth_required` rather than fabricated empty data.
- AO session listing/history and a separately gated send/recover bridge exist.
- CREATOR OPS local read-only aggregate adapter exists.
- Proposal-only dispatch exists; no apply/deploy/promote/rollback path exists.
- Demo fixtures exist and must be explicitly labeled.
- A standalone read-only runtime fixture/API exists for safe UI testing; it is not live state.
- Topology/live CORE target is not yet fully implemented in this checkout.
- Live GPT/Claude/Codex aggregation is not verified.
- Live Obsidian projection is disabled/unconfigured.

### Required target from the handoff

- Reference-faithful centered CORE with functional event-driven animation.
- Logical agent orbital movement toward Internet, Obsidian, or other agents.
- ULTRON ring plus static agent-style icon.
- GPT and Claude equal visual/architectural weight with different capabilities.
- Frosted-glass modular panels with intentional empty space.
- Desktop scaling at 1280×720, 1920×1080, and 2560×1440.
- Functional attachments, chat send states, Activity, Approvals, resources, limits, profiles,
  Obsidian projection, and small isolated-branch EVOLVE module.

Do not claim the target features are live merely because the handoff or mockup describes them.

## 7. Visual assets and handoff files

Stable repository assets:

- [Dashboard target](docs/assets/hive-dashboard-target.png)
- [Original CORE reference](docs/assets/hive-core-reference.png)
- [Claude handoff](HIVE_DASHBOARD_CLAUDE_HANDOFF.md)
- [Captured adapter snapshot](snapshot.example.json)

The images are design references. The production dashboard must implement live overlays and
state transitions with HTML/CSS/SVG/canvas rather than use the screenshot as the entire UI.

## 8. Run and verify

Start the dashboard:

```powershell
.\start.ps1
```

Open:

```text
http://127.0.0.1:4173/
```

Start the safe runtime fixture instead when testing UI/API behavior without HIVE Core,
AO, provider credentials, subprocesses, or write access:

```powershell
.\start-fixture.ps1
```

Open `http://127.0.0.1:4174/`. Fixture metadata and the main read-only contract are
available at `http://127.0.0.1:4174/api/fixture/metadata` and
`http://127.0.0.1:4174/api/dashboard/snapshot`. Stop it with
`.\stop-fixture.ps1` and inspect it with `.\status-fixture.ps1`.

All `POST`, `PUT`, `PATCH`, and `DELETE` requests receive HTTP 405. The fixture
returns explicit `LOCAL / RUNTIME FIXTURE` and `fixture` markers; it must never be
used to claim live provider, hardware, Internet, HIVE Core, or Obsidian connectivity.

For visual fixture mode only:

```text
http://127.0.0.1:4173/?demo=1
```

Run targeted checks:

```powershell
python -m py_compile server.py fixture_server.py tests/test_server.py tests/test_fixture_server.py
python -m unittest tests.test_server -v
python -m unittest tests.test_fixture_server -v
node --test tests/ui_contract.test.mjs
git diff --check
```

The fixture mode is not proof of provider connectivity. A live claim requires a real
observed endpoint response and preserved provenance.

## 9. Claude onboarding checklist

Before editing:

1. Confirm repository path, branch, HEAD, and dirty state.
2. Read this README and the handoff document.
3. Confirm that the two assets under `docs/assets/` are present.
4. Run the existing targeted tests.
5. Inspect current runtime configuration without printing secret values.
6. Implement only the next accepted phase from the handoff budget plan.
7. Keep GPT and Claude equal in HIVE; do not make one provider the hidden authority.
8. Use real events for functional CORE movement and keep non-core animation ambient.
9. Stop and report `UNKNOWN` or `BLOCKED` when a connector or credential is unavailable.
10. Report files, tests, verified integrations, limitations, backup, and remaining budget.

Do not modify PROD, WONG, ROCKET, deployment state, or release evidence. Do not add a
second canonical memory store. Do not commit credentials or temporary runtime files.

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

    **`send` is additionally scoped to a single operator-authorized session via
    `AO_SEND_SESSION_ID`.** The `<id>` in the request path is never trusted by
    itself, even once it passes format validation — `require_authorized_ao_send_session()`
    requires it to equal the server-configured `AO_SEND_SESSION_ID` exactly. Unset
    or malformed `AO_SEND_SESSION_ID` fails every send closed, with no exceptions.
    As defense in depth on top of that equality check, the authorized session id
    must additionally appear, and not be terminated, in that call's own live
    `ao session ls` result — an unavailable session list fails the send closed
    rather than trusting a stale authorization. `send/recover` is intentionally not
    scoped by `AO_SEND_SESSION_ID`: it only recovers the daemon's already-recorded
    outcome for a prior send's delivery handle and never delivers new message
    content.

    `/api/control/capabilities` reports `ao.session_list_confirmed` /
    `session_history_confirmed` as `true` whenever `AO_CLI_PATH` is configured.
    `send_confirmed` additionally requires `AO_SEND_CALLER_TOKEN` and
    `AO_SEND_SESSION_ID` to both be configured — `ao.caller_auth_configured` and
    `ao.send_session_authorized` report those facts directly, and
    `ao.authorized_send_session_id` echoes the configured target — since the route
    cannot actually deliver a message otherwise. `send_recover_confirmed` only
    requires `AO_SEND_CALLER_TOKEN`. `worker_api_confirmed` and
    `chat_realtime_api_confirmed` remain `false` always — no such contract is
    documented for AO.
12. **Worker routing policy read-model (`GET /api/control/worker-policy`).**
    `WORKER_POLICY` is a static, in-memory table declaring `capability`,
    `execution_mode` (`local`/`remote`), `cost_mode` (`free`/`subscription`/
    `metered`/`unknown`), `network_requirement`, `fallback_policy`, and `endpoint`
    for every canonical worker id this adapter accepts as `preferred_worker`:
    `deterministic`, `lmstudio-local`, `openrouter_free`, `antigravity`,
    `codex-subscription`. It is purely declarative — reading it never probes a
    port, calls a service, or starts one (no LM Studio autostart).
    `evaluate_worker_policy()` is the fail-closed admission check `dispatch()`
    runs instead of a flat allowlist: only `cost_mode` `free`/`subscription` is
    ever accepted — `metered` and `unknown` (including any worker id outside the
    table/alias map) are always blocked, never allowed through by default — and
    local-first routing means a remote (`execution_mode: "remote"`) worker is
    blocked whenever the caller sets `local_only`, regardless of its cost_mode. A
    blocked worker makes `dispatch()` fail closed with `400` and the specific
    `blocked_reason`; no proposal is ever submitted to HIVE Core for it.

    **`endpoint` is loopback-only for local workers and always `None` for remote
    ones — never invented.** `deterministic` runs in-process inside HIVE Core (not
    a separately dialable service), so its `endpoint` is `None`
    (`endpoint_basis: "not_applicable"`). `lmstudio-local`'s `endpoint` defaults to
    LM Studio's own documented local-server address (`http://127.0.0.1:1234`,
    `endpoint_basis: "documented_default"`) — a static declaration, never probed
    or dialed by this adapter — overridable via `LMSTUDIO_ENDPOINT` only when the
    override itself resolves to a loopback host (`endpoint_basis:
    "operator_override"`); a non-loopback override is rejected outright
    (`endpoint: None`, `endpoint_basis:
    "invalid_non_loopback_override_rejected"`), never exposed. `openrouter_free`,
    `antigravity`, and `codex-subscription` are remote/cloud-routed and always get
    `endpoint: None` (`endpoint_basis: "not_applicable"`) — this adapter never
    declares a remote worker's endpoint. `worker_policy_record()` also enforces
    this as defense in depth: it rejects (clears to `None`) any endpoint that is
    non-loopback or attached to a non-`local` worker, regardless of source.

    **Canonical worker ids are aligned with the evidenced Orchestrator registry
    naming, with old ids preserved as an explicit alias map.** `lmstudio` and
    `codex` now resolve via `WORKER_ID_ALIASES` to the canonical
    `lmstudio-local`/`codex-subscription` entries (`canonical_worker_id` on every
    record shows the resolution); any id that resolves to neither a canonical key
    nor an alias is unknown and fails closed exactly like a metered worker, never
    guessed into an existing entry. `codex-subscription`'s `cost_mode` stays
    `"unknown"` (blocked) by default — `ao agent ls` reporting Codex "authorized"
    on this machine does not by itself distinguish a ChatGPT-subscription login
    from a metered, pay-per-token API key — and only becomes `"subscription"`
    (accepted) when the operator sets `CODEX_SUBSCRIPTION_CONFIRMED=true`, an
    explicit confirmation of the actual billing plan in use, mirroring
    `HIVE_HEALTH_REQUIRES_AUTH`'s existing pattern of never fabricating a
    safety-relevant claim from ambiguous evidence.

13. **Explicit LM Studio inference (`POST /api/local-workers/lmstudio/infer`).**
    This route is a local-only execution surface, not a remote proxy: it requires
    `confirm: true`, a project-scoped Obsidian context pack and a model present in
    the live loopback `/v1/models` listing. The request sends no credentials,
    disables thinking where supported, bounds instruction/tokens, redacts context
    and output, and never writes canonical state or starts a worker. Empty output
    is returned as `status: "degraded"` with evidence, never as a successful answer.

14. **CLI worker availability (`GET /api/local-workers/cli-status`).** OpenCode and
    Freebuff are checked only with fixed WSL `--version` argv. The adapter never
    accepts a command, path, prompt or workspace from the request, and never runs a
    model/task; unavailable or non-zero probes remain unavailable evidence.

15. **OpenCode disposable execution (`POST /api/local-workers/opencode/run`).** The
    route is disabled by default and requires explicit confirmation, a verified
    provider-session flag, network confirmation, an existing workspace below the
    disposable root, scoped context and fixed WSL argv. It never accepts arbitrary
    commands, sessions, forks, server mode or workspace escape. Freebuff has no
    execution route until its non-interactive output contract is verified.

## Run

From this directory:

```powershell
.\start.ps1
```

Open `http://127.0.0.1:4173/` for live-adapter mode. The local adapter serves the UI and
requests HIVE Core on loopback only. It exposes `GET /api/dashboard/snapshot`,
`GET /api/control/capabilities`, `GET /api/control/worker-policy`, the controlled
`POST /api/control/dispatch` route, and
the proposal-only `POST /api/control/routing-decision` and
`POST /api/control/handoff-proposal` routes (attestation, attempt and idempotency
evidence only; no provider execution, delivery or retry),
the AO CLI bridge routes (`GET /api/ao/sessions`, `GET /api/ao/sessions/<id>/history`,
`POST /api/ao/sessions/<id>/send`, `POST /api/ao/sessions/<id>/send/recover`)
described in item 11 above.

The dashboard snapshot also exposes a read-only `readiness` model. Its aggregate
state is `ready`, `degraded`, or `blocked`; each component carries `status`,
`validity`, `source`, `observed_at`, `reason`, and `next_safe_action`. Protected
HIVE resources remain `auth_required`, missing AO transport is `unavailable`, and
provider execution remains `blocked` until server-observed identity is verified.

The launcher automatically uses the existing per-user AO binary at
`%LOCALAPPDATA%\Programs\agent-orchestrator\resources\daemon\ao.exe` when present;
otherwise set `AO_CLI_PATH` to an absolute path to the `ao` binary before starting
the adapter. This enables read-only session listing/history only. To additionally enable `send`/`send/recover`, also set
`AO_SEND_CALLER_TOKEN` to a secret value, and present it as a bearer token on every
request to those two routes. `send` further requires `AO_SEND_SESSION_ID`, set to
the exact session id the operator is authorizing for delivery — any other session
id in the request path is refused regardless of the caller token:

```powershell
$env:AO_CLI_PATH = 'C:\Users\Martin\AppData\Local\Programs\agent-orchestrator\resources\daemon\ao.exe'
$env:AO_SEND_CALLER_TOKEN = (New-Guid).Guid
$env:AO_SEND_SESSION_ID = 'mer-3'
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
is configured, since there is no way to authenticate a caller without it. Leaving
`AO_SEND_SESSION_ID` unset (or setting it to a malformed value) is the safe default
for `send` specifically: every send is refused with `403`, even with a valid
`AO_CLI_PATH` and a correct `AO_SEND_CALLER_TOKEN`, since there is no server-held
target session to authorize against.

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

### System resources (`GET /api/system/resources`)

Takes no parameters (none reach the probe). On Windows the request never runs a probe: it answers at once from the
latest observations of two independent background tiers (`hive_system.TieredSystem`, two fixed PowerShell scripts):

| Tier | Sections | Refresh after | Fresh window | Feeds |
|---|---|---|---|---|
| fast | cpu, memory, volumes (`Get-Volume`: same source and meaning as the full probe's disk gauge) | 5 s | 15 s | CPU, RAM, DISK gauges |
| slow | gpu, disks, usb, then optional `nvidia-smi` | 60 s | 180 s | GPU/TEMP, Local Devices inventory |

- One probe per tier at a time, each bounded by `PROBE_TIMEOUT_S` = 8 s (unchanged); a failed tier waits one refresh
  interval before retrying. On a cold start the slow tier starts only after the first fast result or failure, so the two
  PowerShell processes do not compete for CPU.
- No observation yet: `value: null`, validity `unknown` ("first fast probe in progress") or `unavailable` (the failure;
  a timeout names the finished and stalled sections). Older than the fresh window: validity `stale` with the age in the
  reason; the UI shows `?` with a STALE label and the old `observed_at`, never the old value. Without a fresh slow
  observation the inventory is `disks: []`, `usb: []`, `disks_known`/`usb_known: false` plus `items.inventory_reason`.
- Unchanged: `items.{cpu,memory,disk,gpu,temperature}` (`value, unit, validity, source, observed_at, reason`),
  `items.{disks,usb,disks_known,usb_known}`, `evidence.{source,validity,observed_at,reason,probe_ms,probe_timings_ms}`
  (the evidence now describes the fast tier; its validity can also be `stale` or `unknown`). Added: per-metric
  `freshness` and `age_s`, `items.inventory_reason`, and `tiers.{fast,slow}` with `state`
  (fresh | stale | failed | pending | not_started), `observed_at`, `age_s`, `refreshing`, `probe_ms`, `timings_ms`,
  `last_error`, `fresh_window_s`, `refresh_after_s`, `reason`. Other platforms: an immediate answer with every value
  UNKNOWN (no probe exists there).
- The browser renders the shell first, requests system resources ahead of and independently from the other endpoints
  (4 s abort), renders each response as it arrives, and re-polls every 1 s (at most 20 times) while a tier is pending
  or STALE with a refresh already running (e.g. after the tab was hidden); a failing tier is not re-polled faster.
  `/api/local-workers/cli-status` (`--version` probes) is cached for 60 s and is no longer on the gauge path.

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
  `AO_SEND_CALLER_TOKEN`; send further scoped to one operator-authorized session via
  `AO_SEND_SESSION_ID`), declares a static worker routing policy read-model
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
  declared worker carries that label by default), metered/unknown-cost-mode and
  unrecognized-worker-id blocking, local-first routing blocking a remote worker
  under `local_only`, no-side-effects (`subprocess.run`/`urlopen` never called),
  and `dispatch()` wiring (blocked worker → `400` with the policy reason; an
  allowed free local worker still succeeds end to end). Additionally covers the
  endpoint field (loopback-only default and override for `lmstudio-local`,
  rejection of a non-loopback override, `None` for in-process/remote/unrecognized
  workers, defense-in-depth rejection of a malformed or misattached endpoint) and
  worker-id alignment (`lmstudio`/`codex` aliases resolving to
  `lmstudio-local`/`codex-subscription`, `codex-subscription` defaulting to
  blocked until `CODEX_SUBSCRIPTION_CONFIRMED` is set, an unaliased unknown id
  still failing closed, and `dispatch()` still accepting the old bare ids).

## CREATOR OPS adapter

Set `CREATOR_OPS_DB_PATH` to the database file (there is no built-in default path any more;
unset means the adapter reports "not configured"). The
adapter opens this file in SQLite URI `mode=ro` (the connection cannot write) and
only ever runs fixed `SELECT COUNT(*)` queries against a hardcoded table allowlist —
no row content is read. A missing file, a locked file, or a non-SQLite file is
reported `unavailable` with a real reason.

## Tests

```powershell
python -m py_compile server.py tests/test_server.py
python -m unittest tests.test_server -v
```

The current verified run executed `py_compile` successfully and completed all 211 unit
tests with `OK` (the first sandbox attempt was blocked by temporary-directory
permissions; the external test run passed).

## Read-only registry configuration (DETAILS → Registry)

All registry paths come from environment variables; nothing user-specific is built in. See `docs/hive/DATA_CONTRACTS.md`
for every variable, file format and bound. Example for a PowerShell session before `start.ps1`:

```powershell
$env:ORCHESTRATOR_VAULT_ROOT = '<path to the Orchestrator.inc folder of your vault>'
$env:CREATOR_OPS_DB_PATH     = '<path to creator_ops.sqlite3>'
# optional: $env:HIVE_SKILLS_ROOTS, $env:HIVE_PROMPTS_ROOTS, $env:HIVE_BOTS_ROOTS (';'-separated), $env:HIVE_TOOL_MANIFEST_DIR
# optional Internet health for ULTRON (https only, max 5, HEAD requests, no redirects): $env:HIVE_INTERNET_PROBES = 'https://example.org/'
```

Without `HIVE_SKILLS_ROOTS` the skill catalog reads only `~/.codex/skills` and `~/.agents/skills`. Without
`ORCHESTRATOR_VAULT_ROOT` / `CREATOR_OPS_DB_PATH` the Obsidian projections and Creator Ops report "not configured".
