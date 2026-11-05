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
- Subagents: 0 (PM ACCEPTANCE.md and UX review not yet run).
- Effort: ~$6 of $10.
