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
FAIL: 0. Linux container results above. Windows: only the Python suite (242/242) was run, user-reported - see section 12; everything else on Windows is NOT_RUN. Baseline "211 Python + 20 Node": 211 `test_server` + 12 `test_fixture_server` + 20 UI-contract all pass; one baseline test was made platform-independent (not weakened).

## 3. Verified integrations (what was actually exercised)
- Local fixture server SSE and the live adapter's SSE endpoint with mocked upstream evidence (`tests/test_events.py`): contract shape, validity propagation, dedupe.
- Browser transport (SSE primary, guarded polling fallback, backoff, offline classification) against fake EventSource/fetch (unit) and the real fixture/live servers (E2E).
- Chat outbox and approvals logic with mock connectors (unit) and with no connector (E2E, zero non-GET requests).
That is all. Nothing below is verified.

## 4. Unavailable / NOT verified
- **Live HIVE Core**: unreachable from the container; the live adapter was only observed returning honest UNKNOWN. No live event, task or worker data was seen.
- **Internet events**: no fixture or live source produced one; the Internet-active path through the ULTRON ring is untested.
- **GPT/Claude/Codex providers, AO send, approval sources, Obsidian, WONG**: no connector exercised. SENT exists only against a mock; Approve/Reject are local-only; Edit is disabled.
- **Windows behavior**: partially verified by the owner (user-reported, section 12): Python suite, fixture launcher lifecycle, `start.ps1` launch and the live SSE status frame. NOT verified: Node tests, any browser/UI at real resolution, real `wsl.exe`/OpenCode execution, MTP/USB, and every live-Core behavior.
- **Production readiness**: not claimed. **Full visual parity with the target image**: not claimed.
- P1.x (system resources, model limits, profiles/avatars, Obsidian projection, ULTRON guard, EVOLVE, layout editor): not built. Those panels read UNKNOWN / NOT_PROVIDED / NOT CONNECTED.

## 5. Known limitations and tracked gaps (GAP-1..GAP-7 in ACCEPTANCE.md, all OPEN)
1. GAP-1 `correlation_id`: event links render with a fallback id (run/task/event id) when `correlation_id` is missing; spec says pulses need an observed correlation id. Pinned by a test, not resolved.
2. GAP-2 no authenticated provider send route (browser holds no token by design); UI can only reach NOT_CONNECTED/FAILED.
3. GAP-3 no approval source connector; decisions are local and labelled so.
4. GAP-4 live HIVE Core, Internet path, CORE-with-events at 1280/2560 unverified; Windows only partially verified (section 12). OPEN.
5. GAP-5 visual parity not achieved (no galaxy art, connectors, list icons, top task-card row, Layout card; rails sparse when data is absent).
6. GAP-6 redaction is best-effort regex (secrets under 32 opaque chars without a known prefix/key are not caught); JS/Python twins held identical by a shared fixture.
7. GAP-7 movement is only exercised on fixture events at 1920x1080; P0.2 PARTIAL statuses deliberately unchanged.
Other: top-bar text "ULTRON SECURITY: ACTIVE" from the spec is shown as NOT CONNECTED (no guard exists; truthfulness rule wins). Vertical CORE centring is not asserted. The ids of events from sources without `event_id` hash differently in JS and Python (mitigated: the live adapter's snapshot now carries the server id). Layout editor not built. `ACCEPTANCE.md` contradictions list (SSE vs polling, budget tables, Codex role wording) stands.

## 6. Acceptance checklist status (75 items in docs/hive/ACCEPTANCE.md)
PASS_AUTOMATED 39 | PASS_MANUAL 1 | PARTIAL 12 | NOT_VERIFIED 1 | NOT_RUN 22. All 22 NOT_RUN items and most of the 12 PARTIAL items belong to P1.x or to Windows/live checks; the spec section 15 summary rows are S15.1-S15.16 in that file.

## 7. Budget ledger summary
Rough effort, not observed spend: baseline ~1, P0.1 ~8 of 10, P0.2 ~11 of 18, P0.3 ~15 of 18, final QA so far ~3 of 9. Total about $38 of the $100 ceiling; P1.x allocations (~$45) and the unspent QA reserve remain. Subagents used: 4 of the 8 allowed (PM, UX, Test Engineer, independent final reviewer). See `BUDGET_LEDGER.md`.

## 8. Rollback
Branch `hive/dashboard-v1`. Remote tags (verified with `git ls-remote`): `backup/pre-p0.1` (ba0ad1e), `backup/pre-p0.2` (c9f38eb), `backup/pre-p0.3` (28fa51b). `backup/pre-p1.1` has deliberately NOT been created. P0 checkpoint commit: `11439e5`. `git checkout -B hive/dashboard-v1 <tag>` restores any earlier phase.

## 9. Verify manually on the Windows PC
1. `.\start-fixture.ps1`, open `http://127.0.0.1:4174/`: shell, CORE WORKING with a visible FIXTURE DATA tag, UATU moves to Obsidian, no console errors; try `?scenario=approval` and `?scenario=secrets`.
2. `.\start.ps1` with HIVE Core running and a token set only in the process env: does the CORE leave UNKNOWN only when `/events` is valid? Confirm nothing animates on silence. Confirm GPT/CODEX/CLAUDE chips only change from real worker records.
3. Run `python -m unittest tests.test_server tests.test_fixture_server tests.test_events -v` natively (the OpenCode test's real Windows-drive path logic is only unit-tested via `PureWindowsPath` here).
4. Check 1280x720, 1920x1080, 2560x1440 on the real monitor; compare against `docs/assets/hive-dashboard-target.png` yourself - parity is not claimed.
5. Attach files, send with no provider: expect NOT_CONNECTED; confirm no network write in DevTools.

## 10. Independent final review
A fresh-context reviewer re-ran every suite (counts matched this report), read the code behind claims (a)-(h) (UNKNOWN-not-WORKING, untrusted events dropped, movement gating, strict SENT gate, local-only approvals, no provider POSTs, nothing invented, provider symmetry), spot-checked acceptance rows and the diff file list, and reported no problems. It did not read `hive_events.py`/the server events code line by line, did not diff the OpenCode test against baseline, and did not scan file contents for secrets. The author's own content scan found secret-shaped strings only in redaction test inputs (`tests/ops.test.mjs`, `tests/redaction_cases.json`, `tests/test_events.py`, `tests/test_server.py`), all synthetic. Demo mode shows a visible DEMO banner (asserted in `tests/e2e/shell.e2e.mjs`).

## 11. Is P1.1 justified?
Conditionally. For: SYSTEM RESOURCES and AI MODELS / LIMITS are the most visible all-UNKNOWN panels and S15.12 depends on them; the work needs no credentials. Against: it can only be tested here with mocked OS output (real Windows CPU/RAM/GPU/USB/MTP behavior is NOT VERIFIED IN CLOUD), and its data would come through the same unverified live HIVE Core path. Default recommendation: do the Windows smoke test in section 9 first; if the P0 checkpoint behaves on the real machine, P1.1 is justified as a narrow phase (OS metrics + KNOWN/UNKNOWN/NOT_PROVIDED limits, mocked tests, no connectors). If the live path misbehaves, fix that (and GAP-1/GAP-2) before adding more panels. `backup/pre-p1.1` has not been created and no P1 work has started.

## 12. Windows smoke test (user-reported, partial) - commit 7dc6f70
Run by the project owner; the agent has not seen logs or screenshots and cannot independently confirm these results. No secrets were shared or used. Python/Node versions, browser, resolution and DPI were not reported.
- PASS: worktree at 7dc6f70, clean.
- PASS: `py_compile`; Python suite 242/242 OK (first native Windows run, including the OpenCode workspace test on real drive paths).
- PASS: `start-fixture.ps1` / `status-fixture.ps1` (RUNNING) / `stop-fixture.ps1`.
- PASS: live adapter with no token: after the owner verified and stopped a stale `server.py` on port 4173, `start.ps1` started it; `/api/events/stream` returned `validity: unavailable`, `event_count: 0` with HIVE Core refusing the connection; clean stop. This is the honest-unavailable behaviour, not evidence of a working Core.
- NOT_RUN: Node tests; fixture UI (home, `?scenario=approval`, `?scenario=secrets`); live UI and chat checks; live adapter with a token; visual comparison with the target; Playwright.
- Not reported: whether `start.ps1` auto-enabled AO session listing.
Consequences: GAP-1 through GAP-7 all remain OPEN. GAP-4 has partial progress only. The P1.1 recommendation in section 11 is unchanged: the browser-level Windows checks (steps 2-3 UI, and 5) that it depends on have not been run. `backup/pre-p1.1` has not been created and no P1 work has started.

## 13. P1.1 narrow implementation (system resources, devices, model limits)
Backup tag `backup/pre-p1.1` (146cb56) was created by the owner and verified remote before work started. Scope was kept narrow: no profiles, Obsidian, ULTRON, EVOLVE or layout editor.

**What was built**
- `hive_system.py` (new, stdlib): Windows adapter boundary. One fixed PowerShell script (CPU load, RAM, volumes with bus/read-only, GPU adapter names, USB/WPD devices, ACPI thermal zone) plus an optional fixed `nvidia-smi` argv; `shell=False`, 8 s timeout, bounded output, 5 s cache, no request-derived text in any argv. Strict validation: non-finite, boolean, out-of-range or inconsistent values become UNKNOWN with a reason; nothing is clamped or defaulted. Non-Windows hosts report UNKNOWN for everything and run no process. MTP/PTP phones (WPD/Image classes) are listed under USB with "Storage metrics unavailable" and are never disks. Empty lists are only "none" when the probe actually returned a list (`usb_known`/`disks_known`).
- Model limits: `model_limits()` always yields four equal rows (GPT, CLAUDE, CODEX, LOCAL) with status KNOWN (limits.basis == provider), ESTIMATED (basis == estimate), NOT_PROVIDED (record without usable limits), UNKNOWN (no record). Never inferred from model names.
- `server.py`: `GET /api/system/resources` (no parameters reach the probe), snapshot `model_limits`, worker `limits` pass-through (whitelisted keys only). `fixture_server.py`: synthetic, labelled fixture versions that exercise every state.
- UI: SYSTEM RESOURCES gauges (OS value first, Core metric only if a valid percent, else UNKNOWN), disk free-space and RAM sublabels, one-line USB/external summary, LOCAL DEVICES node text, a System section in the Details console, AI MODELS / LIMITS rows with distinct drawing for ESTIMATED.

**Tests (final run, Linux container; all OS/provider output mocked or synthetic)**
Python (`test_server`, `test_fixture_server`, `test_events`, `test_system`) 268/268 OK; UI contract 20/20; Node `core` 45/45, `ops` 30/30, `html_ids` 3/3; Playwright `shell` 7/7, `core` 10/10, `chat` 11/11, `system` 5/5; `py_compile` and `git diff --check` clean.

**Defects found while building (fixed, tested):** failed probe rendered "USB 0"; removable media classified as external; phone note truncated at 1280x720 (panel slightly taller now: resources row min height 164px).

**NOT verified (GAP-8, OPEN):** the PowerShell script was never executed anywhere (no PowerShell in the cloud container; no Windows run yet); real USB/external-disk detection; real MTP/PTP classification; nvidia-smi; elevation requirements for disk/temperature queries; the `limits` object shape from HIVE Core/providers (an assumption); any live Core or provider data. GAP-1..GAP-7 are unchanged and OPEN.

**Windows verification to run before relying on P1.1 (owner, no secrets involved)**
1. In a normal (non-admin) PowerShell, from the worktree: `python -c "import hive_system,json; print(json.dumps(hive_system.collect_system(), indent=1))"` - expected: `evidence.validity` valid or degraded; CPU/RAM/DISK numbers close to Task Manager; any field the OS refuses (often TEMP, GPU) is UNKNOWN with a reason. Report the validity words and which fields are UNKNOWN; do not paste hostnames, serial numbers or device names you consider private.
2. Plug in a USB disk and a phone (MTP/PTP) and re-run: the disk should appear with `kind` external or removable, size/free matching Explorer, drive letter correct; the phone must appear only under `usb` with "Storage metrics unavailable" and never in `disks`. Report if the phone is missing or classified differently (its class may not be WPD/Image).
3. Open the live dashboard (`.\start.ps1`) and compare the SYSTEM RESOURCES panel with Task Manager; confirm GPU/TEMP read UNKNOWN unless the OS returned values; confirm AI MODELS / LIMITS reads UNKNOWN or NOT_PROVIDED unless Core returns a `limits` object.

