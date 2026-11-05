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

## 14. Visual parity phase (GAP-5 stays OPEN)
Backup tag `backup/pre-visual-parity` (6decc0a) was created by the owner and verified before work started. English labels are used throughout (owner decision). Details, per-difference status, measurements and the independent reviewer's verdict: `docs/hive/VISUAL_REVIEW.md` section 6.

**Built:** procedural galaxy background; spiral-arm vortex with horizon and photon ring; glowing orbit rings with nodes; role icons and "Descriptor · STATE" captions; 16 dim, not-observed context labels in four groups with connector curves that light up only from fresh trusted events naming them; textured Internet planet; a top row of four truthful task cards (current task, next in queue, shared context from real memory-status evidence, external connection) plus a LAYOUT card whose controls are disabled and labelled "editor not available"; panel icons, role avatars, colored approval buttons and gauges, provider accents, brand mark, clock + date.
**Not done on purpose (truthfulness):** target numbers/names/statuses, role-to-provider mappings, "ULTRON ACTIVE", "Online", Admin/bell/settings, a Logs label (spec forbids), enabled Layout controls, progress bars without data, selection highlights, "New chat"/"+"/drag handles.
**Tests (final run, Linux container):** see the final numbers in the commit message and BUDGET_LEDGER.md; new `tests/e2e/visual.e2e.mjs` (11), +2 core, +5 ops.
**Honest status:** not at visual parity. An independent reviewer's overall impression: recognisably the same family, subjectively ~60-65% of the visual impact. One earlier claim of mine (CORE under-scaled) was wrong and is corrected with measurements (ring 40/45/46% of viewport height at 1280/1920/2560 vs ~48% estimated for the target). Remaining visible differences: VISUAL_REVIEW.md 6.5. Not verified: Windows browser at the real monitor.


## 15. Measured hybrid 2.5D implementation (GAP-5 stays OPEN)
Architecture (local only, no new runtime): layer 0 `assets/hive-wallpaper.jpg` (2560x1440, ~181 KB, generated by `tools/make_wallpaper.py` with only `ImageDraw.line/ellipse`, so no text/numbers/statuses/controls can exist in it); layer 1 CORE art (canvas vortex drawn once + SVG rings/nodes/connectors/icons, generated into `index.html` by `tools/make_stage.py`); layer 2 a 1671x941 reference stage scaled by `--k=min(vw/1671,vh/941)` whose DOM panels sit at the measured rectangles (`stage-layout.css`, `docs/hive/measurements/stage-layout-final.json`); layer 3 live DOM (all text/status). `hive-core.js` remains the only state source (geometry now polar homes measured from the target). No Unity/Spline/Rive/Three.js/CDN/fonts added.
**Documented deviations from the measured plan:** uniform centring scale 0.985 (CORE centred +-2 px), card gap 14.5, resources/limits +10 px, internet label group +18 px, decorative top-bar title dropped (text-floor rule). Text floor 13.2 reference px (>=10 px on screen at 1280x720).
**Tests (Linux container, final run):** Python 280 OK (incl. new `tests/test_assets.py`, 12: wallpaper size/dimension/budget/reproducibility/dark centre, generator never draws text, no remote URLs, stage CSS equals final layout JSON, gutters >=10/16/20 px, panels inside stage); ui_contract 20; Node 88 (core 49, ops 36, html_ids 3); Playwright shell 7, core 10, chat 11, system 5, visual 15.
**QA images:** `docs/hive/screenshots/hybrid-compare-{1280x720,1920x1080,2560x1440}.png`, `overlay-after-*.png`, `hybrid-core-zoom-1920x1080.png`, `hybrid-live-*` (live adapter, everything UNKNOWN); metrics in `docs/hive/measurements/ours-after-*.json`.
**Visual deltas (measured, 1920x1080, target scaled x1.149):** panel rectangles equal the measured layout within 1.5 pp; ring centre within 2 px of viewport centre; agent homes within 1.5 px of measured polar positions (UATU appears displaced in the fixture capture because it is mid-trip). Orbit ring r 243.5 px vs target ~272 px (about 90 %).
**Remaining differences (honest):** vortex is softer/less luminous than the target's bright swirling disk; ULTRON ring is gray unless a fresh ULTRON event exists (by design, target shows "ACTIVE"); connectors dimmer than target; rails look sparse in live mode (no invented rows); at 1280x720 two adjacent "UNKNOWN" gauge captions (GPU/TEMP) touch; target numbers/provider mappings/Admin/bell are deliberately absent. Windows rendering not verified (GAP-4/GAP-8). Not at visual parity; GAP-5 stays OPEN pending explicit owner acceptance.
**Not part of this phase (noted only):** `server.py` and `fixture_server.py` serve any file under the repo root (pre-existing exposure).

## 16. Supplied wallpaper integrated (GAP-5 stays OPEN)
- Source: `assets/src/hive-wallpaper-v1.png` (from branch `hive/wallpaper-asset`, commit fd715dc), 1,836,402 bytes, 1672x941 RGB, SHA-256 `8AD50B3BA7F39462C0BD032A69BE97391388DF71FBC492023E60E48670D3A7A8` (verified before use; the 99 KB WebP preview was not used).
- Conversion (`tools/convert_wallpaper.py`, refuses any other source hash, draws nothing): RGB, Lanczos resize straight to 2560x1440 (1.53x upscale, so it is soft by nature), JPEG quality 90, 4:2:0, optimize, non-progressive, no EXIF/ICC. Output `assets/hive-wallpaper.jpg` = 356,131 bytes (budget 650 KB), byte-identical on two runs. Centre luminance 10.2 vs corner 24.0 (limit 40, and < corner + 5).
- Not touched: `hive-core.svg`, `hive-icons.svg`, `visual-tokens.css` (never imported), measured CORE geometry, `hive-core.js`, all DOM/state code. `tools/make_wallpaper.py` (previous procedural generator) is marked superseded and kept.
- Tests: `tests/test_assets.py` 14 (was 12): added source-hash pin (test and converter), converter-draws-nothing, reproducibility now re-runs the converter from the pinned source; size, centre-darkness, generator-no-text, no-external-URL, relative-URL tests unchanged; the image allow-list gains only the source PNG. Full suite once: Python 282, ui_contract 20, Node 88, Playwright 7+10+11+5+15, all green.
- Screenshots regenerated at 1280x720, 1920x1080, 2560x1440 (`hybrid-compare-*`, `overlay-after-*`). Only the 1920 compare was viewed after this change: real nebula and circuit traces behind the panels; no layout change. Remaining differences from section 15 are unchanged. Not at visual parity.

## 17. Owner decisions (documentation only)
Wallpaper integration accepted as an asset integration; visual parity not accepted; GAP-5 OPEN. Tracked: UI-1 (1280x720 gauge-caption collision) and ASSET-1 (soft upscaled wallpaper, no CSS sharpening). CORE geometry frozen; P1.2/P1.3 not started. Details in ACCEPTANCE.md "Owner decisions after the wallpaper integration".

## 18. SYSTEM RESOURCES data source confirmed and tightened (GAP-8 stays OPEN)
P1.1 already existed (section 13); this pass re-checked it against the owner's requirements and corrected it. **Source:** server-side, read-only, bounded (`hive_system.py`): one fixed PowerShell script (shell=False, 8 s timeout, 200 kB output cap, 5 s cache) plus optional `nvidia-smi`; no Task Manager/UI scraping. **Interface:** `SystemAdapter` (`read()`, `gpu_vendor_output()`), `PowerShellAdapter` (real Windows path), `MockAdapter` (Linux/tests; never used by the live server); `collect_system(adapter=...)`. **Per-metric contract:** `source`, `observed_at`, `validity`, `reason` (+ value/unit); unavailable metrics have `value: null`, `observed_at: null`, a reason.
**Corrections to the earlier P1.1 (explicit):** (1) CPU now comes from the OS performance counter `Win32_PerfFormattedData_PerfOS_Processor` (_Total, locale independent) instead of `Win32_Processor.LoadPercentage`; (2) the ACPI thermal-zone temperature was REMOVED: it is not a reliable CPU/GPU temperature, so TEMP is UNKNOWN unless `nvidia-smi` returns a well-formed GPU temperature (then source `nvidia-smi`, reason "GPU temperature"); (3) the GPU record's `adapters` list was renamed `hardware_present` and documented as a capability, never telemetry (GPU utilization is UNKNOWN unless `nvidia-smi` reports it). RAM and DISK unchanged (Win32_OperatingSystem, Get-Volume).
**Tests (Linux):** `tests/test_system.py` 33 (+7: full per-metric contract, GPU/TEMP UNKNOWN without a reliable source, nvidia source/time, adapter failure reasons, interface/mock starts no process, live module never touches fixtures, script has no UI/ACPI access). Full suite once: Python 289, ui_contract 20, Node 88, Playwright 7+10+11+7+15, all green.
**NOT verified:** the real PowerShell path, the performance-counter class and `nvidia-smi` on the Windows PC; this container has no PowerShell and no GPU. Run the Windows smoke test (section 9) on the target machine: expected CPU/RAM/DISK valid with source and time, GPU/TEMP UNKNOWN unless an NVIDIA GPU with `nvidia-smi` is present.

## 19. Windows smoke test of the real PowerShellAdapter (user-reported, partial)
Owner ran `tools/smoke_system_windows.py` at 450ecc1 on Windows: PASS (CPU 25.0 %, RAM 67.4 %, DISK 69.1 %, each with source and observed_at; GPU and TEMP UNKNOWN; hardware_present = AMD Radeon 780M Graphics; 1 volume, 5 USB devices). Details and what remains unverified are in ACCEPTANCE.md ("Windows smoke test of the real PowerShellAdapter"). GAP-8 stays OPEN: nvidia-smi success path, `--full` device detail, live UI on Windows and Node/Playwright on Windows are not verified. P1.2/P1.3 not started.
