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
