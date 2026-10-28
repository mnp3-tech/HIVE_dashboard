# Unified Dashboard — bounded MVP

Local-only, read-only-by-default operating picture for HIVE Core. It does not modify
PROD, WONG, ROCKET, or any existing HIVE implementation. The existing HIVE UI was used
as a visual reference; this is a separate surface.

## Scope of this MVP

1. **Project catalog** — projects known to HIVE Core, with explicit `valid` /
   `unavailable` / `unknown` evidence instead of a fabricated empty or zeroed list.
2. **Task queue** — queued / active / completed / blocked task records, bucketed only
   from statuses the adapter actually receives. Unrecognized upstream statuses land in
   an explicit `unknown` bucket rather than being guessed into one of the four.
3. **Adapter health** — per-adapter `configured` / `authenticated` / `reachable` /
   `last_observed_at` / `validity` / `reason`, kept distinct from each other (e.g. a
   stale adapter is never shown as `unavailable`, and an unconfigured one is never
   shown as `reachable`).
4. **Evidence everywhere** — every metric, project-catalog fetch, and task-queue fetch
   carries `source`, `observed_at`, `validity`, and `reason`. Missing or weak evidence
   is surfaced as `unavailable`/`unknown`, never silently treated as "no change".
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

## Run

From this directory:

```powershell
.\start.ps1
```

Open `http://127.0.0.1:4173/` for live-adapter mode. The local adapter serves the UI and
requests HIVE Core on loopback only. It exposes `GET /api/dashboard/snapshot`,
`GET /api/control/capabilities`, and the controlled `POST /api/control/dispatch` route.

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

- No HIVE Core credentials or live Core instance were available in this session. Live
  integration is therefore UNVERIFIED/BLOCKED, not simulated as complete. Every example
  above was exercised against a deliberately unreachable Core (see the test run) and
  produces the documented `unavailable` evidence rather than fabricated data.
- Beszel is intentionally **not implemented** in this MVP. The adapter reports it as
  `configured: false` (or `true` if `BESZEL_URL` happens to be set) with
  `validity: "unknown"` and an explicit "not implemented, deferred" reason; it is never
  shown as reachable.
- Topology visualization is deferred by design, not by omission — see item 6 above.

## Files

- `index.html` — accessible responsive shell: overview, projects, tasks, adapters, and
  proposals nav targets, plus an explicit deferred-topology panel.
- `styles.css` — visual system, responsive layouts, reduced-motion support.
- `app.js` — adapter fetch, normalization, per-section evidence rendering, proposal-only
  submission form, and an explicitly gated visual fixture mode (`?demo=1`).
- `server.py` — loopback-only static server and narrow HIVE Core adapter. Normalizes
  project/task/adapter-health evidence, and exposes only a proposal-only, fail-closed
  dispatch route. No arbitrary proxy, shell route, provider credential forwarding,
  apply/deploy/promote/rollback route, or topology/graph computation.
- `snapshot.example.json` — backend contract example with unavailable/unknown semantics.
- `tests/test_server.py` — stdlib `unittest` coverage for the adapter contract
  (evidence semantics, status bucketing, adapter health) and the proposal-only safety
  gates (confirmation required, non-proposal modes rejected, worker allowlist, fail
  closed on missing token or missing reachability evidence).

## Tests

```powershell
python -m py_compile server.py tests/test_server.py
python -m unittest tests.test_server -v
```

Both commands were run in this session: `py_compile` succeeded with no output, and all
24 unit tests pass.
