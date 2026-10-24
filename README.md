# HIVE / Beszel observability dashboard

Standalone Codex prototype based on `HIVE_Beszel_Codex_Implementation_Prompt.md`.
It is intentionally read-only and local-only. It does not modify PROD, WONG, ROCKET,
or any existing HIVE implementation. The existing HIVE UI was used as a visual reference;
this prototype is a separate surface.

## Run

From this directory:

```powershell
.\start.ps1
```

Open `http://127.0.0.1:4173/` for live-adapter mode. The local adapter serves the UI and
requests HIVE Core on loopback. It exposes `GET /api/dashboard/snapshot`,
`GET /api/control/capabilities`, and the controlled `POST /api/control/dispatch` route.

Set the Core URL and token only in the process environment; never put the token in the
browser, source tree, or command output:

```powershell
$env:HIVE_CORE_URL = 'http://127.0.0.1:8765'
$env:HIVE_API_TOKEN = (Get-Content 'C:\HIVE\runtime\api-token' -Raw).Trim()
.\start.ps1
```

The dashboard can submit a single task, a Mission, or an `EVOLUTION_TASK` proposal. The
last option is explicitly no-apply/no-deploy and cannot promote or replace active Core.
Worker selection is passed to HIVE's allowlisted worker registry; the dashboard never
calls GPT, Claude, Codex, or another provider directly.

For visual QA only, use `http://127.0.0.1:4173/?demo=1`. The banner marks fixture mode;
the default route never fabricates metrics or events.

## Adapter contract

The snapshot endpoint returns the shape in [snapshot.example.json](snapshot.example.json).
The browser never receives Beszel credentials. A backend adapter is responsible for
authenticating to Beszel, normalizing upstream changes, redacting data, caching shared
polls, and setting `validity` to `valid`, `stale`, `unavailable`, or `unknown`.

The UI treats null as unavailable, not zero. Core health requires an application payload;
an open port alone is not sufficient. Events create topology pulses only while their
retained timestamps are inside the short TTL window.

## Current evidence and limits

- Verified upstream reference: Beszel `v0.21.1` release, observed 2026-10-24.
- Beszel's official REST API documentation warns that response structure can change in
  minor releases, so the adapter must isolate upstream schema from this UI contract.
- No Beszel hub/agent credentials or live Windows host evidence were available in this
  session. Live integration is therefore UNVERIFIED/BLOCKED, not simulated as complete.
- Diagnostic provider is intentionally unconfigured. Monitoring remains functional
  without GPT/Claude, and no cloud fallback or paid call is made by this prototype.

## Prototype files

- `index.html` — accessible responsive shell and semantic sections.
- `styles.css` — HIVE visual system, responsive layouts, reduced-motion support.
- `app.js` — adapter fetch, normalization, evidence states, filters, topology, details,
  preferences, controlled delegation form, and explicitly gated visual fixture mode.
- `server.py` — loopback-only static server and narrow HIVE Core adapter. It has no
  arbitrary proxy, shell route, provider credential forwarding, or self-upgrade apply route.
- `snapshot.example.json` — backend contract example with unavailable/null semantics.
