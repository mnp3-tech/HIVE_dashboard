# HIVE / Beszel observability dashboard

Standalone Codex prototype based on `HIVE_Beszel_Codex_Implementation_Prompt.md`.
It is intentionally read-only and local-only. It does not modify PROD, WONG, ROCKET,
or any existing HIVE implementation. The existing HIVE UI was used as a visual reference;
this prototype is a separate surface.

## Run

From this directory:

```powershell
python -m http.server 4173 --bind 127.0.0.1
```

Open `http://127.0.0.1:4173/` for live-adapter mode. The UI requests one same-origin
endpoint: `GET /api/dashboard/snapshot`.

For visual QA only, use `http://127.0.0.1:4173/?demo=1`. The banner marks fixture mode;
the default route never fabricates metrics or events.

## Adapter contract

The endpoint must return the shape in [snapshot.example.json](snapshot.example.json).
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
  preferences and explicitly gated visual fixture mode.
- `snapshot.example.json` — backend contract example with unavailable/null semantics.
