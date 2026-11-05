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
