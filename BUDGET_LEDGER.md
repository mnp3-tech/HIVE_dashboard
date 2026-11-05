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
