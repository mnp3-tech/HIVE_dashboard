# BUDGET_LEDGER

Rough effort estimates against the USD 100 allocation (dollar spend is not observable from the session).

## Baseline (pre-P0.1)
- Files: server.py (portable ORCHESTRATOR_VAULT_ROOT), tests/test_server.py (platform-independent OpenCode test + 2 WSL path tests).
- Tests: Python `tests.test_server tests.test_fixture_server` 225/225 OK; `node --test tests/ui_contract.test.mjs` 20/20 (1 file); py_compile OK.
- Windows-specific behavior (real `C:\` workspaces, wsl.exe, PowerShell launchers) was NOT verified in the Linux container.
- Subagents: 0. Effort: ~$1 of baseline/sync work.

## P0.1 Visual shell (allocation $10)
- Files: index.html (new fixed shell; legacy views moved unchanged into a hidden details console), styles.css (cockpit section appended), app.js (renderShell, console wiring), tests/e2e/shell.e2e.mjs, docs/hive/screenshots/shell-*.png, BUDGET_LEDGER.md.
- Tests: Python 225/225 OK; UI contract 20/20 OK; Playwright E2E tests/e2e/shell.e2e.mjs 7/7 (1280x720, 1920x1080, 2560x1440: no overlaps, gutters >= 10/16/20 px, CORE centre within 2 px, no DONE/LOGS/version text, panel material, equal provider chips, JARVIS/VOICE inactive, env tag).
- Review + fixes (follow-up commit): PM subagent wrote docs/hive/ACCEPTANCE.md; UX subagent reviewed 1280/1920/2560 screenshots against the target. Verdict: layout skeleton matches, NOT visual parity (no galaxy vortex art, connector lines, list icons, top task-card row, Layout card; rails are sparsely populated because no data is invented). Fixed real defects found: top bar clipped DETAILS at 1280, approval buttons clipped, chips overflowed, tiny top-bar tags at 2560. My first fix attempt regressed layout (gauges stacked, CORE collapsed) and the E2E did not catch it; E2E now also asserts CORE height >= 40% of viewport, no content outside its panel, no overflow/collision in chips/approval rows/limits.
- Subagents: 2 (PM, UX). Effort: ~$8 of $10.

## P0.2 Functional CORE (allocation $18)
- Files: hive_events.py (new, section 9 contract + SSE framing), server.py (`GET /api/events/stream`, live /events -> contract events with provenance), fixture_server.py (synthetic SSE, labelled fixture), hive-core.js (new: normalization, bounded dedupe buffer, freshness, CORE state derivation, visual mapping, ULTRON ring rule, movement model, SSE+polling transport), app.js (wiring, SVG overlay, rAF only while moving), index.html/styles.css (arms, lock, ambient layer, event links, 8 state looks), tests/core.test.mjs, tests/test_events.py, tests/e2e/core.e2e.mjs, ACCEPTANCE.md statuses.
- Tests: Python test_server+test_fixture_server+test_events 235/235 OK; ui_contract 20/20 OK; tests/core.test.mjs 27/27; Playwright shell 7/7, core 7/7. py_compile + git diff --check clean.
- Real defect found by looking at the screenshot and fixed: Obsidian trip parked UATU on top of SHURI; rest angles now keep >= 26 deg from every other agent's home (unit-tested for all roles x nodes).
- Not verified: live HIVE Core events (Core unreachable here => honest UNKNOWN); real Internet-active path through ULTRON ring (no internet event in any fixture); CORE-with-events at 1280/2560; Windows browser. ULTRON ring is gray unless an ULTRON event is observed (ULTRON guard is P1.3).
- Subagents: 0 new (2 total). Effort: ~$11 of $18.

## P0.3 Chat, Activity, Approvals (allocation $18)
- Files: hive-ops.js (new: outbox state machine, attachment metadata, approvals logic), hive-core.js (sanitizeActivityRow, stronger redaction, prompt-type withholding), hive_events.py (redaction/withholding parity), app.js (composer, chips, outbox, Activity rows, Approvals), index.html (textarea composer, chips, outbox; removed duplicate ids), styles.css, fixture_server.py (opt-in `scenario=approval|secrets`), tests/ops.test.mjs, tests/html_ids.test.mjs, tests/e2e/chat.e2e.mjs, tests/test_events.py, ACCEPTANCE.md (P0.3 statuses + tracked gaps).
- Tests: Python test_server+test_fixture_server+test_events 237/237 OK; ui_contract 20/20; core 27/27; ops 15/15; html_ids 2/2; Playwright shell 7/7, core 7/7, chat 9/9. py_compile + git diff --check clean.
- Defects I introduced earlier or missed, found by looking at screenshots (not by tests) and then covered by new assertions: duplicate element ids from P0.1 (composer vs legacy chat form, core-state ids) - removed + html_ids test; legacy `.empty-state` min-height 220-270px crushed CHATS/neighbours in live (empty) mode - overridden; outbox row text squeezed to a sliver - restructured. All earlier screenshots had used the fixture server, which hid the empty-state problem.
- Preserved as-is: all P0.2 PARTIAL statuses. Added GAP-1..5 to ACCEPTANCE.md, including the correlation_id contract gap (GAP-1, OPEN).
- Not verified: any real provider send (no route exists; SENT is exercised with a mock connector only), any approval source connector, live HIVE Core, Windows.
- Subagents: 0 new (2 total; Test Engineer review of coverage vs ACCEPTANCE.md still to run per plan). Effort: ~$12 of $18.

## P0.3 follow-up: Test Engineer review fixes
- Subagent #3 (Test Engineer) reviewed coverage; I reproduced each claim before acting. 12 real defects fixed (listed in ACCEPTANCE.md "Test Engineer review outcome"), among them two honesty bugs: connector `ok:'yes'` counted as source approval, and untrusted-source events surviving in the state buffer.
- New/extended tests: core.test.mjs 27 -> 45, ops.test.mjs 15 -> 22, html_ids 2 -> 3 (ids used by app.js must exist), test_events.py 10 -> 17 (shared JS/Python redaction fixture, 0 mismatches), E2E shell 7, core 7 -> 10, chat 9 -> 11. E2E runs repeated 5x for stability after fixing real races and my own test mistakes (wrong regex escape, wrong expectations after fallback polling).
- Totals now: Python 242/242 OK; ui_contract 20/20; Node unit 45+22+3; Playwright 7+10+11. py_compile + git diff --check clean.
- Preserved: all P0.2 PARTIAL statuses and GAP-1 (correlation_id), unchanged.
- Subagents: 3 total. Effort: P0.3 now ~$15 of $18 (including review fixes).

## Final QA (P0 checkpoint) - allocation $9 reserve
- Verified remote: branch `hive/dashboard-v1` at 11439e5 before QA; tags `backup/pre-p0.1`, `pre-p0.2`, `pre-p0.3` present; `backup/pre-p1.1` intentionally not created.
- Final suite once (+ the E2E re-runs needed for stability): Python 242/242; ui_contract 20/20; core 45/45; ops 22/22; html_ids 3/3; Playwright shell 7/7, core 10/10, chat 11/11; py_compile and git diff --check clean.
- Screenshots inspected at 1280x720, 1920x1080, 2560x1440 for both the fixture shell and the LIVE adapter (Core unreachable): no clipping/overlap/scroll; every value reads UNKNOWN / NOT PROVIDED / NOT CONNECTED. Not parity with the target.
- QA found and fixed one more honesty defect: the server's static label "LOCAL / HIVE CORE" displayed next to an unreachable Core; the tag now appends "UNVERIFIED" unless Core health was observed (test added).
- ACCEPTANCE.md: spec section 15 rows updated honestly (39 PASS_AUTOMATED, 1 PASS_MANUAL, 12 PARTIAL, 1 NOT_VERIFIED, 22 NOT_RUN of 75). GAP-1..GAP-7 all remain OPEN. docs/hive/HANDOFF_REPORT.md written.
- Effort: ~$3 of $9 reserve so far; running total about $38 of $100 (rough). P1.x not started.
- Independent final reviewer (subagent #4, fresh context): re-ran all suites, counts matched; verified behavioural claims (a)-(h) by reading code; no problems reported. Own follow-ups: py_compile + diff --check re-run clean; content scan found secret-shaped strings only in synthetic redaction test inputs; demo banner assertion exists.
- Subagents total: 4 of 8. Final QA effort ~$4 of the $9 reserve. Running total about $39 of $100 (rough, not observed). P1.1 not started; recommendation recorded in HANDOFF_REPORT.md section 11.

## P1.1 System resources + model limits (allocation $10, narrow scope)
- Files: hive_system.py (new), server.py (`/api/system/resources`, snapshot `model_limits`, worker `limits` whitelist), fixture_server.py (synthetic system + limits), hive-ops.js (view helpers), app.js, index.html, styles.css, tests/test_system.py (new, 26), tests/ops.test.mjs (+8), tests/e2e/system.e2e.mjs (new, 5), docs (ACCEPTANCE P1.1 rows PARTIAL + GAP-8, HANDOFF_REPORT section 13).
- Tests: Python 268/268; ui_contract 20/20; core 45; ops 30; html_ids 3; Playwright shell 7, core 10, chat 11, system 5. All OS/provider output mocked or synthetic; Windows script never executed.
- Defects found and fixed: "USB 0" shown for a failed probe; removable media classified external; phone note truncated at 1280x720.
- Not started: P1.2 (profiles, Obsidian/WONG/Internet), P1.3 (ULTRON, EVOLVE), layout editor. GAP-1..GAP-7 unchanged and OPEN; GAP-8 added.
- Subagents: 4 total (none used in P1.1). Effort: ~$7 of $10 for P1.1; running total about $46 of $100 (rough, not observed spend).

## Visual parity review (GAP-5), documentation only
- Produced docs/hive/screenshots/compare-{1280,1920,2560}.png (target vs fixture UI), docs/hive/VISUAL_REVIEW.md (16 differences, deliberate truthfulness deviations, task-card data sources, plan). No code or test changes. GAP-5 stays OPEN; GAP-1..GAP-8 unchanged.
- Effort ~$1. Implementation (~$12-15 est.) not started; it changes the layout grid, so it waits for a backup tag created by the owner.

## Visual parity phase (GAP-5 stays OPEN)
- Backup tag backup/pre-visual-parity (6decc0a) created by the owner, verified remote before work. Order followed: A background/vortex/rings -> B role icons/context groups/connectors -> C task-card row + Layout card -> D rails/resources/limits/top-bar styling -> E QA + independent UX review.
- Files: index.html (icon sprite, new CORE SVG, card row, header icons), styles.css (A/B, C, D, review-fix blocks), app.js (procedural artwork, cards, context activation, role avatars), hive-core.js (`activeContextNodes`, `CONTEXT_NODES`), hive-ops.js (`taskCardViews`, `contextCardView`, `obsidianNodeText`), tests (core +2, ops +5, shell counts, new tests/e2e/visual.e2e.mjs with 11 tests), docs (VISUAL_REVIEW.md section 6, ACCEPTANCE GAP-5, HANDOFF_REPORT section 14), screenshots (compare-after-*, live-after-*, parity-*).
- Tests (final): Python 268/268; ui_contract 20/20; Node core 47, ops 35, html_ids 3; Playwright shell 7, core 10, chat 11, system 5, visual 11; py_compile + git diff --check clean.
- Defects found along the way and fixed: gauge label icons inherited the ring size and broke the Resources panel; long "WAITING APPROVAL" caption collided with Local Devices; `progress_percent: true` would have rendered a 1% bar; a test blocked "Online Tools" label by mistake (test fixed).
- Subagent #5 (independent UX review, images only): not at parity (~60-65% of the visual impact, subjective). Accepted and fixed: green dots beside "PROVIDER UNKNOWN"; identity colours equal to status colours; label collisions during agent trips; empty-glass stretching; ghost-text contrast. Rejected with measurements: "CORE about half the size". One of my own earlier conclusions (CORE under-scaled) was wrong and is corrected in VISUAL_REVIEW.md 6.1.
- Subagents total: 5 of 8. Effort: ~$14 for this phase; running total about $60 of $100 (rough, not observed spend). P1.2/P1.3 not started.

## Visual spec + measurements (documentation/tools only; no application code changed)
- New: tools/measure_target.py (Pillow/numpy: panel edges, ring/node/planet geometry, cap heights, label-group rows, colours), tools/measure_ours.mjs (Playwright: same metrics on the real UI at 1280/1920/2560 + overlay screenshots), tools/make_visual_spec.py (generates docs/hive/VISUAL_SPEC.md from the JSON), docs/hive/measurements/{target.json, ours-before-*.json, layout-spec.json}, docs/hive/screenshots/overlay-before-*.png.
- Findings that corrected earlier statements: the target layout is not a grid (rails end at 84 % / 65 % of H, unequal widths 15.5 % / 19.9 % of W, centre-only card row) - my last phase's "anchor rails to the composer line" went the wrong way; type is 0.57-0.88x target at 1920x1080; measured target ring diameter is 50.4 % of H (my "~48 %" was an eyeball estimate), ours 39.6-45.8 %.
- Rive evaluated and NOT adopted (needs an editor-authored .riv plus a JS/WASM runtime; criteria for adopting later are in VISUAL_SPEC.md 9). Implementation (wallpaper, canvas/SVG CORE, stage layout) deliberately not started: it is structural and needs a backup tag first.
- Tests: no code changed; suites not re-run for this documentation-only step. GAP-1..GAP-8 unchanged; GAP-5 OPEN.
- Effort ~$3; running total about $63 of $100 (rough, not observed spend).

## Measured hybrid 2.5D implementation (GAP-5 stays OPEN)
- One implementation pass plus one screenshot-diff QA pass (1280x720, 1920x1080, 2560x1440); affected tests during iteration, full suite once at the end. No Unity/Spline/Rive/Three.js/CDN/fonts evaluated or added.
- Files: new assets/hive-wallpaper.jpg, tools/{make_wallpaper.py,make_stage.py,make_compare.mjs}, stage.css, stage-layout.css, tests/test_assets.py, measurements (stage-layout-final.json, ours-after-*.json), screenshots (hybrid-*, overlay-after-*); changed index.html, app.js, hive-core.js, hive-ops.js, tests (core, ops, e2e shell/chat/system/visual), docs (HANDOFF_REPORT s15, ACCEPTANCE GAP-5).
- Tests: Python 280, ui_contract 20, Node 88, Playwright 7+10+11+5+15, all green on Linux.
- Subagents: still 5 of 8 (none used). Effort ~$14 (rough, not observed spend); running total about $77 of $100. Not started: P1.2, P1.3, any further visual iteration.

## Supplied wallpaper integration (GAP-5 stays OPEN)
- Verified SHA-256 of assets/src/hive-wallpaper-v1.png, added tools/convert_wallpaper.py, regenerated assets/hive-wallpaper.jpg (356 KB), updated tests/test_assets.py (+2 tests, reproducibility test re-pointed, nothing weakened), docs (HANDOFF_REPORT s16). One screenshot pass, full suite once (all green). No core/svg/icon/token assets used.
- Subagents: still 5 of 8. Effort ~$2 (rough); running total about $79 of $100.

## UI-1 compact UNKNOWN gauge glyph (GAP-5 stays OPEN)
- app.js (glyph, focus/hover tooltip on .stage, no re-render when markup unchanged, evidence line), stage.css (glyph/tooltip), tests/e2e/system.e2e.mjs (+2, helper reads data-status), docs. CORE geometry untouched. Full suite once: Python 282, ui_contract 20, Node 88, Playwright 7+10+11+7+15 green. Effort ~$1.5 (rough); running total about $80.5 of $100. Subagents 5 of 8. P1.2/P1.3 not started.

## P1.1 data-source confirmation and adapter tightening (GAP-8 stays OPEN)
- hive_system.py (adapter interface, perf-counter CPU, ACPI temperature removed, hardware_present), fixture_server.py (field rename), tests/test_system.py (+7), docs. Full suite once: Python 289, ui_contract 20, Node 88, Playwright 7+10+11+7+15 green. Windows path NOT verified. Effort ~$2 (rough); running total about $82.5 of $100. Subagents 5 of 8. P1.2/P1.3 not started.

## P1.1 single data path (GAP-8 stays OPEN)
- hive-ops.js (no Core-metric fallback, richer hover), app.js (call), tests/ops.test.mjs (1 replaced, 1 added), docs. Full suite once: Python 292, ui_contract 20, Node 89, Playwright 7+10+11+7+15 green. Effort ~$1.5 (rough); running total about $84 of $100 (tool-building and docs included). Subagents 5 of 8. P1.2/P1.3 not started.

## Live-check tool hardening (GAP-8 stays OPEN)
- tools/live_check_windows.mjs (node:http, crash handlers, NOT_RUN/FAIL exit codes, server cleanup, stderr kept), tests/live_check.test.mjs (+4), docs. Effort ~$1.5 (rough); running total about $85.5 of $100. Subagents 5 of 8. P1.2/P1.3 not started.

## Live-check timeout investigation (GAP-8 stays OPEN)
- hive_system.py (section progress markers, timings, stdin/console hygiene, timeout detail), tools/diagnose_system_probe.py (new), tools/live_check_windows.mjs (timings, timeout FAIL, skip browser), tests (+8 Python, +1 Node), docs. Root cause not established without Windows data; no timeout increase. Full suite once: Python 300, ui_contract 20, Node 94, Playwright 7+10+11+7+15 green. Effort ~$3 (rough); running total about $88.5 of $100. Subagents 5 of 8. P1.2/P1.3 not started.

## Windows diagnostic follow-up: snapshot latency finding (GAP-8 open, GAP-9 added)
- tools/diagnose_snapshot.py (new), tools/live_check_windows.mjs (snapshot latency separated, exit 6, --skip-browser), tests (+1 Python, +1 Node), docs. No product timeout changed. Full suite once: Python 301, ui_contract 20, Node 95, Playwright 7+10+11+7+15 green. Effort ~$2 (rough); running total about $90.5 of $100 - remaining budget is small, so further Windows iterations should be run-then-fix with minimal tooling. Subagents 5 of 8. P1.2/P1.3 not started.

## GAP-9 narrow fix: Core preflight gate (GAP-8/GAP-9 open)
- server.py (preflight gate in core_json + snapshot wrapper), tests/test_snapshot_latency.py (+9), docs. No timeout increased. Full suite once: Python 310, ui_contract 20, Node 95, Playwright 7+10+11+7+15 green. Effort ~$2 (rough); running total about $92.5 of $100 - remaining budget is small; further Windows rounds should stay run-then-fix. Subagents 5 of 8. P1.2/P1.3 not started.

## Windows result record + Playwright procedure (GAP-9 resolved on this configuration, GAP-8 open)
- .gitignore (node_modules/), tools/live_check_windows.mjs (NOT_RUN + install hint), tests/live_check.test.mjs (+1), docs. No application code changed; full suite not re-run (last green at 4456991). Effort ~$1 (rough); running total about $93.5 of $100 - only ~$6 remain, so the next round should be the Windows browser run and, if needed, one small fix. Subagents 5 of 8. P1.2/P1.3 not started.

## Windows live check PASS recorded (documentation only)
- ACCEPTANCE.md (GAP-8 closed scoped, GAP-9 resolved, residuals listed), HANDOFF_REPORT.md section 26. No code or tests changed. Effort ~$0.5 (rough); running total about $94 of $100 - about $6 remain, which is less than any earlier P1 phase cost ($7-14), so P1.2 would need either more budget or a much narrower scope. Subagents 5 of 8. P1.2/P1.3 not started.

## UI-1 finalization + visual review (GAP-5 stays OPEN)
- app.js, hive-ops.js, stage.css (glyph for every unavailable gauge, detail tooltip, card hover titles), tests (system e2e, ops, visual e2e +1, live-check tool), 12 small before/after crops, docs. One regression found by the suite (title override) and fixed; full suite run twice on code changes (the first run caught it). Effort ~$3 (rough); running total about $97 of $100 - about $3 remain. Subagents 5 of 8. No new backup tag. P1.2/P1.3 not started.

## Budget reconciliation (recorded at Gate A of the read-only foundation)
- ESTIMATED (this ledger): running total about $97 of $100. Every figure above is a rough effort estimate written by the assistant; the ledger has always stated that dollar spend is not observable from the session.
- USER-REPORTED (owner, at Gate A): about $30 actually spent, about $70 remaining of the original $100; timebox about 2.5 hours.
- Not reconciled: neither figure can be verified from the session. Historical entries above are left unchanged. Planning from Gate A onward uses the USER-REPORTED remaining budget.

## Read-only foundation (GAP-10 added; GAP-5 still OPEN)
- hive_registry.py, schemas/hive-readonly-v1.schema.json, server.py and fixture_server.py (`/api/registry`), app.js/index.html/styles.css (Registry view), docs/hive/proposals/proposals-v1.json, tools/registry_summary.py, tests/test_registry.py (+41), tests/e2e/registry.e2e.mjs (+4), tests/fixtures/ (synthetic), docs. Full suite once on the final code: Python 351, UI contract 20, Node 97, Playwright 7+10+11+7+16+4, all green. One defect caught by the tests and fixed (shared evidence log).
- Effort: rough estimate about $12-15 of the USER-REPORTED ~$70 remaining (not observed). Subagents: 5 of 8 (none used). Nothing executed, nothing written externally, no PROD/WONG/ROCKET access. P1.2/P1.3 not started.

## Registry v2 and read-only operational integrations
- Basis: USER-REPORTED ~$70 remaining at Gate A (before the read-only foundation). ESTIMATED effort (rough, not observed): read-only foundation ~$12-15; this phase ~$18-22; estimated remaining on the user-reported basis ~$33-40. The historical ESTIMATED running total (~$97) is left unchanged above; the two bases are recorded side by side and remain unreconciled.
- Files: see HANDOFF_REPORT section 29. Tests once on the final code: Python 356, UI contract 20, Node 97, Playwright 7+10+11+7+16+6, all green. Subagents: 5 of 8 (none used). No execution path, no external write, no PROD/WONG/ROCKET access. P1.3 not started.

## Windows registry evidence recorded; summary-tool clarity fix
- Docs (ACCEPTANCE, HANDOFF section 30, INTEGRATION_PLAN), hive_registry.py (provider/role lists without a section chip), tools/registry_summary.py (`--uncatalogued`, provider runtime breakdown, path masking), tests (+2 Python, registry E2E updated). Effort ~$2 (rough, not observed); estimated remaining on the USER-REPORTED basis ~$31-38. No execution or write path.

## Uncatalogued skill identified (documentation only)
- ACCEPTANCE, HANDOFF section 31, INTEGRATION_PLAN. No code or test change. Effort ~$0.5 (rough, not observed); estimated remaining on the USER-REPORTED basis ~$30-37.

## P1.3 control plane (observation and proposals)
- Basis: USER-REPORTED ~$70 remaining at Gate A. ESTIMATED effort since then (rough, not observed): read-only foundation ~$12-15, Registry v2 ~$18-22, follow-ups ~$3, this phase ~$20-24. Estimated remaining on the user-reported basis: about $6-17. The historical ESTIMATED running total (~$97) stays unchanged above; the bases remain unreconciled.
- Recommendation: the remaining budget covers Windows verification and small fixes, not another phase of this size.
- Files: see HANDOFF_REPORT section 32. Tests once on the final code: Python 387, UI contract 20, Node 97, Playwright 7+10+11+7+16+6+4, all green. Subagents 5 of 8 (none used). No execution, lifecycle control, external write or PROD/WONG/ROCKET access.

## Phase A: System Resources latency (performance checkpoint)
- Basis: USER-REPORTED ~$70 remaining at Gate A. ESTIMATED effort since then (rough, not observed): read-only foundation ~$12-15, Registry v2 ~$18-22, follow-ups ~$3, P1.3 ~$20-24, this phase ~$10-14. Estimated remaining on the user-reported basis: about -$8 to +$7, i.e. at or below any reserve. The historical ESTIMATED running total (~$97) stays unchanged above; the bases remain unreconciled.
- Decision: Phase B (visual finalization) is NOT started; it needs a fresh budget figure from the owner.
- Files: see HANDOFF_REPORT section 33. Tests on the final code: Python 400, UI contract OK, Node 98, Playwright 7+10+11+11+16+6+4, all green. Subagents 5 of 8 (none used). No execution path, external write or PROD/WONG/ROCKET access.
