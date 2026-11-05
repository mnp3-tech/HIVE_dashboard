# HIVE Dashboard - P0 checkpoint handoff report

Checkpoint: branch `hive/dashboard-v1`, commit `11439e5` plus the final-QA commit that adds this report (see `git log`).
Scope delivered: P0.1 shell, P0.2 CORE/events, P0.3 chat/Activity/Approvals, final QA. **P1.1-P1.3 were not started.**
All estimates of effort are rough; dollar spend is not observable from the session.

## 1. Files changed (vs handoff commit 107d880; 19 files in source/tests/docs, +2625/-144 excluding screenshots)
- New: `hive_events.py` (spec section 9 contract, SSE framing), `hive-core.js` (state/movement/transport), `hive-ops.js` (outbox, approvals), `docs/hive/ACCEPTANCE.md`, `BUDGET_LEDGER.md`, this report, `tests/core.test.mjs`, `tests/ops.test.mjs`, `tests/html_ids.test.mjs`, `tests/test_events.py`, `tests/redaction_cases.json`, `tests/e2e/{shell,core,chat}.e2e.mjs`, `docs/hive/screenshots/*`.
- Modified: `index.html` (new fixed shell; legacy views kept in a hidden Details console), `styles.css`, `app.js`, `server.py` (portable vault-root; `GET /api/events/stream`; snapshot events carry `event_id`), `fixture_server.py` (synthetic SSE, opt-in scenarios), `tests/test_server.py` (platform-independent OpenCode test + 2 WSL-path tests).
- Not touched: PROD, WONG, ROCKET, deployment/release state, production snapshots (file list inspected; no such paths).

## 2. Tests actually executed (final run, Linux container)
| Check | Result |
|---|---|
| `python -m unittest tests.test_server tests.test_fixture_server tests.test_events` | PASS 242/242 |
| `node tests/ui_contract.test.mjs` (`node --test` reports it as 1 file) | PASS 20/20 |
| `node --test tests/core.test.mjs` | PASS 45/45 |
| `node --test tests/ops.test.mjs` | PASS 22/22 |
| `node --test tests/html_ids.test.mjs` | PASS 3/3 |
| Playwright `tests/e2e/shell.e2e.mjs` (1280x720, 1920x1080, 2560x1440) | PASS 7/7 |
| Playwright `tests/e2e/core.e2e.mjs` | PASS 10/10 (repeated 5+ times after fixing races) |
| Playwright `tests/e2e/chat.e2e.mjs` | PASS 11/11 |
| `python -m py_compile ...`, `git diff --check` | PASS |
FAIL: 0. NOT_RUN: everything on Windows (see section 8). Baseline "211 Python + 20 Node": 211 `test_server` + 12 `test_fixture_server` + 20 UI-contract all pass; one baseline test was made platform-independent (not weakened).

## 3. Verified integrations (what was actually exercised)
- Local fixture server SSE and the live adapter's SSE endpoint with mocked upstream evidence (`tests/test_events.py`): contract shape, validity propagation, dedupe.
- Browser transport (SSE primary, guarded polling fallback, backoff, offline classification) against fake EventSource/fetch (unit) and the real fixture/live servers (E2E).
- Chat outbox and approvals logic with mock connectors (unit) and with no connector (E2E, zero non-GET requests).
That is all. Nothing below is verified.

## 4. Unavailable / NOT verified
- **Live HIVE Core**: unreachable from the container; the live adapter was only observed returning honest UNKNOWN. No live event, task or worker data was seen.
- **Internet events**: no fixture or live source produced one; the Internet-active path through the ULTRON ring is untested.
- **GPT/Claude/Codex providers, AO send, approval sources, Obsidian, WONG**: no connector exercised. SENT exists only against a mock; Approve/Reject are local-only; Edit is disabled.
- **Windows behavior**: launchers, `wsl.exe`/OpenCode, real `C:\` paths, Windows browsers, MTP/USB: NOT VERIFIED IN CLOUD.
- **Production readiness**: not claimed. **Full visual parity with the target image**: not claimed.
- P1.x (system resources, model limits, profiles/avatars, Obsidian projection, ULTRON guard, EVOLVE, layout editor): not built. Those panels read UNKNOWN / NOT_PROVIDED / NOT CONNECTED.

## 5. Known limitations and tracked gaps (GAP-1..GAP-7 in ACCEPTANCE.md, all OPEN)
1. GAP-1 `correlation_id`: event links render with a fallback id (run/task/event id) when `correlation_id` is missing; spec says pulses need an observed correlation id. Pinned by a test, not resolved.
2. GAP-2 no authenticated provider send route (browser holds no token by design); UI can only reach NOT_CONNECTED/FAILED.
3. GAP-3 no approval source connector; decisions are local and labelled so.
4. GAP-4 live HIVE Core, Internet path, CORE-with-events at 1280/2560, Windows unverified.
5. GAP-5 visual parity not achieved (no galaxy art, connectors, list icons, top task-card row, Layout card; rails sparse when data is absent).
6. GAP-6 redaction is best-effort regex (secrets under 32 opaque chars without a known prefix/key are not caught); JS/Python twins held identical by a shared fixture.
7. GAP-7 movement is only exercised on fixture events at 1920x1080; P0.2 PARTIAL statuses deliberately unchanged.
Other: top-bar text "ULTRON SECURITY: ACTIVE" from the spec is shown as NOT CONNECTED (no guard exists; truthfulness rule wins). Vertical CORE centring is not asserted. The ids of events from sources without `event_id` hash differently in JS and Python (mitigated: the live adapter's snapshot now carries the server id). Layout editor not built. `ACCEPTANCE.md` contradictions list (SSE vs polling, budget tables, Codex role wording) stands.

## 6. Acceptance checklist status (75 items in docs/hive/ACCEPTANCE.md)
PASS_AUTOMATED 39 | PASS_MANUAL 1 | PARTIAL 12 | NOT_VERIFIED 1 | NOT_RUN 22. All 22 NOT_RUN items and most of the 12 PARTIAL items belong to P1.x or to Windows/live checks; the spec section 15 summary rows are S15.1-S15.16 in that file.

## 7. Budget ledger summary
Rough effort, not observed spend: baseline ~1, P0.1 ~8 of 10, P0.2 ~11 of 18, P0.3 ~15 of 18, final QA so far ~3 of 9. Total about $38 of the $100 ceiling; P1.x allocations (~$45) and the unspent QA reserve remain. Subagents used: PM, UX, Test Engineer (+ the final independent reviewer, if listed in BUDGET_LEDGER.md). See `BUDGET_LEDGER.md`.

## 8. Rollback
Branch `hive/dashboard-v1`. Remote tags (verified with `git ls-remote`): `backup/pre-p0.1` (ba0ad1e), `backup/pre-p0.2` (c9f38eb), `backup/pre-p0.3` (28fa51b). `backup/pre-p1.1` has deliberately NOT been created. P0 checkpoint commit: `11439e5`. `git checkout -B hive/dashboard-v1 <tag>` restores any earlier phase.

## 9. Verify manually on the Windows PC
1. `.\start-fixture.ps1`, open `http://127.0.0.1:4174/`: shell, CORE WORKING with a visible FIXTURE DATA tag, UATU moves to Obsidian, no console errors; try `?scenario=approval` and `?scenario=secrets`.
2. `.\start.ps1` with HIVE Core running and a token set only in the process env: does the CORE leave UNKNOWN only when `/events` is valid? Confirm nothing animates on silence. Confirm GPT/CODEX/CLAUDE chips only change from real worker records.
3. Run `python -m unittest tests.test_server tests.test_fixture_server tests.test_events -v` natively (the OpenCode test's real Windows-drive path logic is only unit-tested via `PureWindowsPath` here).
4. Check 1280x720, 1920x1080, 2560x1440 on the real monitor; compare against `docs/assets/hive-dashboard-target.png` yourself - parity is not claimed.
5. Attach files, send with no provider: expect NOT_CONNECTED; confirm no network write in DevTools.

## 10. Is P1.1 justified?
See the final QA message in the conversation and the last section of `BUDGET_LEDGER.md`.
