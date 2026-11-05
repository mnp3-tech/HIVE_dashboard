# HIVE Dashboard - Acceptance Checklist

Source: `HIVE_DASHBOARD_CLAUDE_HANDOFF.md` section 15 (items 1-16), with derived sub-items from sections 5-12 and 14.
Branch: `hive/dashboard-v1`. Status values: `NOT_RUN`, `PASS_AUTOMATED`, `PASS_MANUAL`, `FAIL`.
Planned tests (not yet existing) are marked `(planned)`. A status of PASS_AUTOMATED is used only where the named file's assertions actually cover the requirement.

Existing test files: `tests/e2e/shell.e2e.mjs`, `tests/ui_contract.test.mjs`, `tests/test_server.py`, `tests/test_fixture_server.py`.

## A. Spec section 15 items

| ID | Requirement | Phase | Verification | Status |
|----|-------------|-------|--------------|--------|
| S15.1 | Dashboard visually matches the supplied reference direction (docs/assets/hive-dashboard-target.png, hive-core-reference.png) | P0.1 | MANUAL: compare 1920x1080 screenshot (docs/hive/screenshots/shell-1920x1080.png) with reference on the Windows PC; e2e takes screenshots but asserts no visual match | NOT_RUN |
| S15.2 | Panels have visible empty space and never touch | P0.1 | tests/e2e/shell.e2e.mjs `P0.1 shell @ WxH` (pairwise overlap + min gutter + edge margin, 10 boxes) | PASS_AUTOMATED |
| S15.3 | Layout adapts at 1280x720, 1920x1080, 2560x1440 (no page scroll) | P0.1 | tests/e2e/shell.e2e.mjs (3 resolution tests, scroll check) | PASS_AUTOMATED |
| S15.4 | CORE remains centered and is the primary animation | P0.1/P0.2 | Centering: tests/e2e/shell.e2e.mjs (horizontal +-2px only). "Primary animation": tests/core_visual.e2e.mjs (planned) + MANUAL | NOT_RUN |
| S15.5 | ULTRON has a static agent-style icon and a state-changing security ring | P0.2 | tests/core_visual.e2e.mjs (planned): icon node present, ring class changes per state; MANUAL visual check | NOT_RUN |
| S15.6 | GPT and Claude (and Codex) have equal architectural and visual weight | P0.1/P0.2 | Chip width equality: tests/e2e/shell.e2e.mjs (covers top-bar chips only); node size/provider parity: tests/core_state.test.mjs (planned) | NOT_RUN |
| S15.7 | Agents move only in response to logical interactions or observed state transitions | P0.2 | tests/core_movement.test.mjs (planned) | NOT_RUN |
| S15.8 | Ambient outer animation is sparse, slow, visually subordinate | P0.2 | tests/core_visual.e2e.mjs (planned: ambient opacity/duration bounds, distinct class from event pulses) + MANUAL | NOT_RUN |
| S15.9 | No activity invented when telemetry is missing (UNKNOWN, never WORKING) | P0.2 | tests/core_state.test.mjs (planned); shell.e2e.mjs covers only ULTRON "NOT CONNECTED" and NOT_PROVIDED limits | NOT_RUN |
| S15.10 | Chat attachments and send states work honestly | P0.3 | tests/chat.test.mjs + tests/e2e/chat.e2e.mjs (planned) | NOT_RUN |
| S15.11 | Activity and Approvals readable and sanitized | P0.3 | tests/activity_sanitize.test.mjs (planned) + MANUAL readability at 1280x720 | NOT_RUN |
| S15.12 | Hardware and model values show UNKNOWN when unavailable | P1.1 | tests/test_server.py (system metrics, planned cases); shell.e2e.mjs asserts NOT_PROVIDED in limits panel only (not hardware) | NOT_RUN |
| S15.13 | Obsidian/WONG authority boundaries preserved (no vault path guess, no write unless connector enabled) | P1.2 | tests/test_server.py (planned cases) + tests/ui_contract.test.mjs | NOT_RUN |
| S15.14 | EVOLVE changes only an isolated branch and produces evidence (diff, test result, backup) | P1.3 | tests/test_evolve.py (planned) | NOT_RUN |
| S15.15 | Existing tests remain passing or regressions are reported | All | Run `node --test tests/ui_contract.test.mjs`, `python -m pytest tests/test_server.py tests/test_fixture_server.py`, `node --test tests/e2e/shell.e2e.mjs`; record exact results | NOT_RUN |
| S15.16 | No production, WONG, ROCKET, deployment, or release state modified | All | MANUAL: `git diff --stat` shows only dashboard checkout files; tests/test_fixture_server.py (fixture server has no write routes) | NOT_RUN |

## B. Derived sub-items

### P0.1 Visual shell

| ID | Requirement | Phase | Verification | Status |
|----|-------------|-------|--------------|--------|
| P0.1.1 | At 1280x720 no panel overlap, gutters >=10px, edge margin >=10px | P0.1 | tests/e2e/shell.e2e.mjs `P0.1 shell @ 1280x720` | PASS_AUTOMATED |
| P0.1.2 | At 1920x1080 no overlap, gutters >=16px | P0.1 | tests/e2e/shell.e2e.mjs `P0.1 shell @ 1920x1080` | PASS_AUTOMATED |
| P0.1.3 | At 2560x1440 no overlap, gutters >=20px | P0.1 | tests/e2e/shell.e2e.mjs `P0.1 shell @ 2560x1440` | PASS_AUTOMATED |
| P0.1.4 | CORE art centered within +-2px at all three resolutions | P0.1 | tests/e2e/shell.e2e.mjs (horizontal axis only; vertical not asserted) | PASS_AUTOMATED |
| P0.1.5 | No visible DONE, LOGS, or version text | P0.1 | tests/e2e/shell.e2e.mjs (innerText regex) | PASS_AUTOMATED |
| P0.1.6 | Required shell labels present (HIVE, GPT, CODEX, CLAUDE, ULTRON, JARVIS / VOICE LAYER, CHATS, PROJECTS, AGENTS / ROLES, ACTIVITY, APPROVALS, SYSTEM RESOURCES, AI MODELS / LIMITS, VOICE) | P0.1 | tests/e2e/shell.e2e.mjs asserts the listed labels (PROJECTS and ULTRON included); ASK HIVE input, attach and send buttons are NOT asserted | NOT_RUN |
| P0.1.7 | Panel material rgba(4,16,29,0.46), blur(12px), border rgba(90,190,255,0.40) | P0.1 | tests/e2e/shell.e2e.mjs `panel material...` (checks #panel-chats only) | PASS_AUTOMATED |
| P0.1.8 | Shell has no page errors on load | P0.1 | tests/e2e/shell.e2e.mjs (pageerror collection) | PASS_AUTOMATED |
| P0.1.9 | VOICE button disabled; JARVIS indicator inactive; no waveform | P0.1 | tests/e2e/shell.e2e.mjs (disabled + `.inactive`; no-waveform not asserted) | NOT_RUN |
| P0.1.10 | Data environment tag (FIXTURE/UNVERIFIED/LOCAL) always visible; demo mode labelled | P0.1 | tests/e2e/shell.e2e.mjs | PASS_AUTOMATED |
| P0.1.11 | Legacy views reachable via details console (open/Escape closes) | P0.1 | tests/e2e/shell.e2e.mjs | PASS_AUTOMATED |
| P0.1.12 | No light theme, no phone/tablet layout | P0.1 | MANUAL: confirm dark at all sizes; no media queries below 1280 wide required | NOT_RUN |
| P0.1.13 | Visual check on the Windows PC native monitor(s) at each resolution | P0.1 | MANUAL: open on Windows PC, confirm frosted glass shows circuits/stars behind cards, text contrast OK | NOT_RUN |

Note on P0.1.6: the e2e asserts every listed label; the bottom ASK HIVE input, attachment and send buttons required by spec section 5 are not asserted, so the item stays NOT_RUN until a test covers them.

### P0.2 Functional CORE

| ID | Requirement | Phase | Verification | Status |
|----|-------------|-------|--------------|--------|
| P0.2.1 | Event normalization maps raw events to the section 9 contract (schema_version ... redacted_summary); malformed input rejected or marked UNKNOWN | P0.2 | tests/core.test.mjs + tests/test_events.py | PASS_AUTOMATED |
| P0.2.2 | Duplicate events (same event_id) are dropped | P0.2 | tests/core.test.mjs (buffer, derived ids) | PASS_AUTOMATED |
| P0.2.3 | Stale/offline classification from last-observed time; silence yields UNKNOWN, never WORKING | P0.2 | tests/core.test.mjs (freshness + deriveCoreState); tests/e2e/core.e2e.mjs (live adapter, Core unreachable => UNKNOWN) | PASS_AUTOMATED |
| P0.2.4 | State to visual-class mapping for all 8 CORE states (IDLE, WORKING, WAITING_APPROVAL, REVIEW, FAILED, SECURITY_BLOCKED, OFFLINE, UNKNOWN) | P0.2 | tests/core.test.mjs (8 states, distinct classes) | PASS_AUTOMATED |
| P0.2.5 | Agent movement: event -> target node -> return to home sector on completion | P0.2 | tests/core.test.mjs (internet/obsidian/handoff, completion return) | PASS_AUTOMATED |
| P0.2.6 | Agent movement: return home on timeout | P0.2 | tests/core.test.mjs (timeout return) | PASS_AUTOMATED |
| P0.2.7 | No movement without an observed event (elapsed time alone never moves agents) | P0.2 | tests/core.test.mjs + tests/e2e/core.e2e.mjs (no movement without events) | PASS_AUTOMATED |
| P0.2.8 | Concurrent movement and pulse counts are capped; agents never disappear in transit | P0.2 | tests/core.test.mjs (cap + queue + one trip/agent). "Never disappear in transit" not asserted | PARTIAL |
| P0.2.9 | Event-linked pulses require an observed event and correlation_id; ambient motion is visually distinct | P0.2 | tests/e2e/core.e2e.mjs (ambient vs event link styles). Interaction id falls back to run/task/event id when no correlation_id exists - strict correlation_id requirement NOT enforced | PARTIAL |
| P0.2.10 | SSE is the primary live transport when a stream endpoint exists | P0.2 | tests/core.test.mjs (fake EventSource) + tests/e2e/core.e2e.mjs (real SSE from fixture server) | PASS_AUTOMATED |
| P0.2.11 | Polling fallback has in-flight guard (no overlapping requests) | P0.2 | tests/core.test.mjs | PASS_AUTOMATED |
| P0.2.12 | Polling fallback has request timeout | P0.2 | tests/core.test.mjs | PASS_AUTOMATED |
| P0.2.13 | Reconnect with exponential backoff (bounded max) | P0.2 | tests/core.test.mjs (1s,2s,4s...; max 30s) | PASS_AUTOMATED |
| P0.2.14 | Event buffer is bounded (oldest evicted) | P0.2 | tests/core.test.mjs | PASS_AUTOMATED |
| P0.2.15 | prefers-reduced-motion disables/minimizes CORE, ambient and movement animation | P0.2 | tests/e2e/core.e2e.mjs (reducedMotion emulation: animation none; movement model snaps) | PASS_AUTOMATED |
| P0.2.16 | Internet planet active only on observed network event; Obsidian node visible; ULTRON between agent and Internet during external access | P0.2 | tests/e2e/core.e2e.mjs covers Internet inactive without traffic and Obsidian active on read. Internet-active path through the ULTRON ring is NOT asserted (no fixture internet event) | PARTIAL |
| P0.2.17 | Server exposes an event stream (SSE) or the UI documents "polling only" and runs on fallback | P0.2 | tests/test_events.py (fixture + live SSE with mocked upstream) | PASS_AUTOMATED |
| P0.2.18 | CORE animation observable in a real browser at 3 resolutions; no console errors | P0.2 | tests/e2e/core.e2e.mjs runs at 1920x1080 only; 1280/2560 CORE-with-events and Windows browser NOT_RUN | PARTIAL |

### P0.3 Chat, Activity, Approvals

| ID | Requirement | Phase | Verification | Status |
|----|-------------|-------|--------------|--------|
| P0.3.1 | Attach one or more local files; chips shown before send; chips removable | P0.3 | tests/e2e/chat.e2e.mjs (3 files, chips, remove, "not uploaded"); tests/ops.test.mjs (limits, name sanitising, contents never read) | PASS_AUTOMATED |
| P0.3.2 | Enter sends; Shift+Enter inserts newline | P0.3 | tests/e2e/chat.e2e.mjs (Shift+Enter keeps text, Enter sends, empty Enter sends nothing) | PASS_AUTOMATED |
| P0.3.3 | Send state QUEUED shown while pending | P0.3 | tests/ops.test.mjs (QUEUED observed before resolution; onChange). Not visually asserted in E2E: it is transient | PASS_AUTOMATED |
| P0.3.4 | SENT only after a real provider response; never on adapter-configured alone | P0.3 | tests/ops.test.mjs with a MOCK connector only (delivered + provider_response_id required). No real provider send route exists, so the browser UI cannot reach SENT today | PASS_AUTOMATED |
| P0.3.5 | FAILED shown on provider error/timeout | P0.3 | tests/ops.test.mjs (error, timeout, unconfirmed, malformed response) - mock connector only | PASS_AUTOMATED |
| P0.3.6 | NOT_CONNECTED shown when no provider adapter connected; no fabricated replies | P0.3 | tests/ops.test.mjs + tests/e2e/chat.e2e.mjs (live adapter, no provider => NOT_CONNECTED, zero non-GET requests, no reply objects) | PASS_AUTOMATED |
| P0.3.7 | VOICE remains a disabled future control | P0.3 | tests/e2e/shell.e2e.mjs (disabled asserted) | PASS_AUTOMATED |
| P0.3.8 | Activity rows are `time / role / provider / action / state`, sanitized (no raw prompts, chain-of-thought, secrets, private logs) | P0.3 | tests/ops.test.mjs + tests/test_events.py + tests/e2e/chat.e2e.mjs (secrets, prompts, chain-of-thought fields never reach DOM). Redaction is best-effort regex, not a guarantee | PASS_AUTOMATED |
| P0.3.9 | Approvals show source-only rows GPT / CODEX / CLAUDE with Approve / Edit / Reject | P0.3 | tests/e2e/chat.e2e.mjs (3 provider rows, 3 buttons each) | PASS_AUTOMATED |
| P0.3.10 | Approve without connector support shows local label "Approved locally, source not updated" | P0.3 | tests/e2e/chat.e2e.mjs (fixture approval scenario: label shown, persists across reload, no non-GET request) + tests/ops.test.mjs | PASS_AUTOMATED |
| P0.3.11 | Edit/Reject act on source only when valid adapter/deep link exists; otherwise disabled or labelled local | P0.3 | tests/ops.test.mjs (remote path with MOCK connector; unsupported => local) + E2E (Edit disabled; Reject local). No real source connector exists/verified | PASS_AUTOMATED |
| P0.3.12 | Never claim an external source changed when only local state changed | P0.3 | tests/e2e/chat.e2e.mjs + tests/ops.test.mjs (local label never says "at source") | PASS_AUTOMATED |
| P0.3.13 | Attachment path/size handling: no upload of unapproved paths; ULTRON file-attachment check hook | P0.3 | tests/ops.test.mjs (metadata only; no upload). ULTRON file-attachment check hook NOT built (P1.3) | PARTIAL |
| P0.3.14 | End-to-end check with a real connected provider on the Windows PC (only if one is configured) | P0.3 | MANUAL: send one message, confirm SENT appears only after the provider reply; otherwise record NOT_CONNECTED as expected | NOT_RUN |

### P1.1 System and provider data

| ID | Requirement | Phase | Verification | Status |
|----|-------------|-------|--------------|--------|
| P1.1.1 | CPU/RAM/GPU/disk/free space/temperature shown only from OS-returned values; otherwise UNKNOWN | P1.1 | tests/test_server.py (planned) + tests/ui_contract.test.mjs | NOT_RUN |
| P1.1.2 | External USB disk shown with size, free space, drive letter, R/W | P1.1 | tests/test_server.py (planned, mocked OS data) + MANUAL with a real USB disk on Windows PC | NOT_RUN |
| P1.1.3 | Phone over MTP/PTP shown as "MTP, Storage metrics unavailable", never as a block disk | P1.1 | tests/test_server.py (planned) + MANUAL with a phone | NOT_RUN |
| P1.1.4 | Model limits use only KNOWN/UNKNOWN/NOT_PROVIDED/ESTIMATED; no invented quotas | P1.1 | tests/e2e/shell.e2e.mjs (NOT_PROVIDED present in default state only) + tests/ui_contract.test.mjs (planned cases) | NOT_RUN |

### P1.2 Profiles and shared context

| ID | Requirement | Phase | Verification | Status |
|----|-------------|-------|--------------|--------|
| P1.2.1 | Role profile editable (display name, color, role, provider, model, capabilities) and persisted locally | P1.2 | tests/profiles.test.mjs (planned) | NOT_RUN |
| P1.2.2 | Local avatar upload; stays local; type/size validated | P1.2 | tests/profiles.test.mjs (planned) | NOT_RUN |
| P1.2.3 | Obsidian/WONG projection read-only; no guessed vault path; no write unless connector enabled and authorized | P1.2 | tests/test_server.py (planned) | NOT_RUN |
| P1.2.4 | HIVE-local tasks do not propagate to GPT/Claude/Codex | P1.2 | tests/test_server.py (planned) | NOT_RUN |
| P1.2.5 | Project-scoped context does not leak across projects | P1.2 | tests/profiles.test.mjs (planned) | NOT_RUN |

### P1.3 ULTRON and EVOLVE

| ID | Requirement | Phase | Verification | Status |
|----|-------------|-------|--------------|--------|
| P1.3.1 | ULTRON guard monitors external connections, provider adapters, attachments, tool permissions, path/sandbox violations, approvals, blocked actions (bounded MVP) | P1.3 | tests/test_ultron.py (planned) | NOT_RUN |
| P1.3.2 | ULTRON ring: green/cyan permitted, amber attention, red blocked, gray offline/unknown | P1.3 | tests/core_state.test.mjs + tests/core_visual.e2e.mjs (planned) | NOT_RUN |
| P1.3.3 | EVOLVE workflow OBSERVE to PROMOTION enforced in order; promotion requires USER APPROVAL | P1.3 | tests/test_evolve.py (planned) | NOT_RUN |
| P1.3.4 | EVOLVE writes only on an isolated branch; backup created; diff and test evidence produced | P1.3 | tests/test_evolve.py (planned) | NOT_RUN |
| P1.3.5 | EVOLVE never performs production changes, silent WONG changes, auto-promotion, or credential access | P1.3 | tests/test_evolve.py (planned negative tests) | NOT_RUN |

## C. Contradictions / risks

Each item was verified against `HIVE_DASHBOARD_CLAUDE_HANDOFF.md` (line numbers) and the repo.

1. **ULTRON status vs no-invention rule.** Spec section 5 top bar (line 156) lists the literal `ULTRON SECURITY: ACTIVE`; section 2 (lines 35-36) forbids inventing status and requires UNKNOWN/NOT CONNECTED when unavailable. Current `index.html` renders `SECURITY: NOT CONNECTED`, and shell.e2e.mjs asserts `NOT CONNECTED`. Resolution: treat `ACTIVE` as a state shown only when observed (section 8 ring states). Also, section 5 global status (IDLE/WORKING/WAITING/ERROR/UNKNOWN) uses different names from section 6 CORE states (WAITING_APPROVAL, REVIEW, FAILED, SECURITY_BLOCKED, OFFLINE); mapping is unspecified.
2. **Budget table vs model allocation.** Section 13 table sums to $100 with only a $9 "QA and reserve" line (9%); section 17 (lines 794-801) allots a separate 10% reserve plus 70-80% Sonnet, 10-20% Opus, 5-10% Haiku (maxima sum to 120%). Neither maps to the task-based table, and Opus/Haiku shares are not tied to any phase.
3. **Codex role.** Section 2 (line 30) says Codex/GPT is an independent reviewer, not the primary implementer; section 7 (line 281) calls Codex a provider/worker, and sections 5, 9, 10 require Codex to be an equal-weight source indicator and approval row alongside GPT and Claude. "Equal visual weight" (S15.6) conflicts with a reviewer-only role if the UI is meant to reflect roles; the spec does not say which wins. Also GPT is grouped with Codex as reviewer in line 30 while section 7 demands GPT and Claude equal status.
4. **SSE primary vs server reality.** Section 9 (line 425) says use SSE or an existing event stream as the primary transport. Grep of `server.py`, `fixture_server.py`, `app.js`, `index.html` finds no `EventSource`, `text/event-stream` or SSE route; the server serves snapshot polling only. The "or an existing event stream" clause is the only escape; P0.2 must either add a stream endpoint (server change not in the P0.2 scope text) or ship polling as the de facto primary.
5. **Layout editor not scheduled or accepted.** Section 12 requires a bounded drag/resize layout editor with persistence, but it is absent from section 13's budget table, section 14's phases and section 15's acceptance criteria. This checklist has no item for it; decide whether it is in scope.
6. **Section 14 vs user phases.** Section 14 defines P1.4 (QA and handoff) which this checklist omits by instruction; the spec's final report (lines 720-731) requires PASS/FAIL/NOT_RUN reporting that this file feeds.
7. **Gutter ranges.** Section 12 gives 10-12px at 1280 and 16-20px at 1920; the gate here (10/16/20) and the e2e assert only minima, and use 20px at 2560 though section 12 gives no number for 2560+ ("expand negative space").
8. **Approvals local fallback vs acceptance.** Section 10 allows marking a proposal "approved" locally; S15.16 and section 2 forbid claiming external change. The label "Approved locally, source not updated" is the only safeguard; it is not in the spec text and was set by the user's phase definition.
9. **E2E coverage gap.** shell.e2e.mjs checks CORE centering horizontally only and uses `#hive-core-art`, not the full CORE composition; it cannot establish S15.1 (visual match) or S15.4 (primary animation).

## Tracked gaps (carry forward; do not close without a test)

| ID | Gap | Origin | Status |
|---|---|---|---|
| GAP-1 | `correlation_id` contract: spec requires event-linked pulses to carry an observed correlation id. The movement model falls back to `run_id`, `task_id`, then `event_id` when `correlation_id` is missing, and event links render regardless. Needs: (a) decide whether pulses without a real correlation_id must be suppressed or labelled, (b) enforce in `hive-core.js` `applyEvent`, (c) test. | P0.2 (P0.2.9 PARTIAL) | OPEN |
| GAP-2 | No authenticated provider send route exists: the browser holds no caller token by design, so Chat can only reach NOT_CONNECTED/FAILED today; SENT is exercised with a mock connector only. A real path needs a server-side, authenticated, explicitly-scoped route. | P0.3 | OPEN |
| GAP-3 | No approval source connector exists: Approve/Reject are always local; Edit is always disabled. | P0.3 | OPEN |
| GAP-4 | Live HIVE Core events, Internet-active path through the ULTRON ring, CORE-with-events at 1280/2560, and Windows behavior were not verified. | P0.2 | OPEN |
| GAP-5 | Visual parity with the target image is not claimed (UX review: skeleton matches; art, connectors, icons, task-card row, Layout card absent). | P0.1 | OPEN |

