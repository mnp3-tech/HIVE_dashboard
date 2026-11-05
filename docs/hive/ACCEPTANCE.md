# HIVE Dashboard - Acceptance Checklist

Source: `HIVE_DASHBOARD_CLAUDE_HANDOFF.md` section 15 (items 1-16), with derived sub-items from sections 5-12 and 14.
Branch: `hive/dashboard-v1`. Status values: `NOT_RUN`, `PASS_AUTOMATED`, `PASS_MANUAL`, `FAIL`.
Planned tests (not yet existing) are marked `(planned)`. A status of PASS_AUTOMATED is used only where the named file's assertions actually cover the requirement.

Existing test files: `tests/e2e/shell.e2e.mjs`, `tests/ui_contract.test.mjs`, `tests/test_server.py`, `tests/test_fixture_server.py`.

## A. Spec section 15 items

| ID | Requirement | Phase | Verification | Status |
|----|-------------|-------|--------------|--------|
| S15.1 | Dashboard visually matches the supplied reference direction (docs/assets/hive-dashboard-target.png, hive-core-reference.png) | P0.1 | Visual parity is NOT claimed. UX review + own screenshot inspection: layout skeleton matches; vortex art, connector lines, list icons, top task-card row, Layout card absent; rails sparse (GAP-5). | NOT_VERIFIED |
| S15.2 | Panels have visible empty space and never touch | P0.1 | tests/e2e/shell.e2e.mjs `P0.1 shell @ WxH` (pairwise overlap + min gutter + edge margin, 10 boxes) | PASS_AUTOMATED |
| S15.3 | Layout adapts at 1280x720, 1920x1080, 2560x1440 (no page scroll) | P0.1 | tests/e2e/shell.e2e.mjs (3 resolution tests, scroll check) | PASS_AUTOMATED |
| S15.4 | CORE remains centered and is the primary animation | P0.1/P0.2 | Horizontal centring tested at 3 resolutions (tests/e2e/shell.e2e.mjs); CORE is the only state-driven animation (tests/e2e/core.e2e.mjs). Vertical centring not asserted. | PARTIAL |
| S15.5 | ULTRON has a static agent-style icon and a state-changing security ring | P0.2 | Static icon + ring exist; ring colour rule unit-tested (tests/core.test.mjs) and stays gray without a fresh ULTRON event. Green/amber/red ring not exercised end-to-end with real ULTRON events (guard is P1.3). | PARTIAL |
| S15.6 | GPT and Claude (and Codex) have equal architectural and visual weight | P0.1/P0.2 | Equal chip widths, equal approval/limit rows, no provider-specific code paths (tests/e2e/shell.e2e.mjs, chat.e2e.mjs). "Architectural" equality is by inspection, not by test. | PARTIAL |
| S15.7 | Agents move only in response to logical interactions or observed state transitions | P0.2 | Movement unit-tested and exercised on fixture events only (see P0.2 PARTIAL items, GAP-1, GAP-7). | PARTIAL |
| S15.8 | Ambient outer animation is sparse, slow, visually subordinate | P0.2 | Ambient style distinct from event links and disabled under reduced motion (tests/e2e/core.e2e.mjs); "sparse/subordinate" is a visual judgement, not asserted. | PARTIAL |
| S15.9 | No activity invented when telemetry is missing (UNKNOWN, never WORKING) | P0.2 | tests/core.test.mjs + tests/e2e/core.e2e.mjs (live adapter, Core unreachable => UNKNOWN, nothing moves/active). Says nothing about a reachable live Core (GAP-4). | PASS_AUTOMATED |
| S15.10 | Chat attachments and send states work honestly | P0.3 | Attachments, chips, Enter/Shift+Enter, QUEUED/FAILED/NOT_CONNECTED tested. SENT only with a mock connector; no real send route (GAP-2). | PARTIAL |
| S15.11 | Activity and Approvals readable and sanitized | P0.3 | Rows sanitized and tested; approvals local-only with truthful label (GAP-3). Redaction is best-effort (GAP-6). | PARTIAL |
| S15.12 | Hardware and model values show UNKNOWN when unavailable | P1.1 | Mocked/fixture tests show UNKNOWN for every missing value (tests/e2e/system.e2e.mjs live host: all UNKNOWN, no "USB 0"). No real Windows OS values or real provider limits verified (GAP-8). | PARTIAL |
| S15.13 | Obsidian/WONG authority boundaries preserved (no vault path guess, no write unless connector enabled) | P1.2 | tests/test_server.py (planned cases) + tests/ui_contract.test.mjs | NOT_RUN |
| S15.14 | EVOLVE changes only an isolated branch and produces evidence (diff, test result, backup) | P1.3 | tests/test_evolve.py (planned) | NOT_RUN |
| S15.15 | Existing tests remain passing or regressions are reported | All | Baseline 211 Python + 12 fixture + 20 UI contract tests all pass. One baseline test (OpenCode workspace) was made platform-independent without weakening it, and a Linux import fix was added; see BUDGET_LEDGER.md. Windows behavior not run. | PASS_AUTOMATED |
| S15.16 | No production, WONG, ROCKET, deployment, or release state modified | All | `git diff --name-only 107d880..HEAD` inspected: only dashboard files, docs and tests changed; no PROD/WONG/ROCKET/deploy/release/secret-like paths. Agent-inspected, not independently reviewed. | PASS_MANUAL |

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
| P1.1.1 | CPU/RAM/GPU/disk/free space/temperature shown only from OS-returned values; otherwise UNKNOWN | P1.1 | tests/test_system.py (parse/validate/collect with MOCKED PowerShell+nvidia-smi output; invalid, NaN, out-of-range, bool, inconsistent values => UNKNOWN), tests/ops.test.mjs (view helpers), tests/e2e/system.e2e.mjs (fixture values; live non-Windows host => all UNKNOWN). The real Windows PowerShell script and nvidia-smi were NEVER executed (no PowerShell in the cloud container; Windows run pending) | PARTIAL |
| P1.1.2 | External USB disk shown with size, free space, drive letter, R/W | P1.1 | tests/test_system.py + tests/e2e/system.e2e.mjs with MOCKED/FIXTURE data: size, free space, drive letter, kind (external/removable/fixed), access. Summary line omits R/W for space (shown in the System console list). Real USB disk on Windows NOT VERIFIED | PARTIAL |
| P1.1.3 | Phone over MTP/PTP shown as "MTP, Storage metrics unavailable", never as a block disk | P1.1 | tests/test_system.py + ops.test.mjs + system.e2e.mjs: MOCKED/FIXTURE phone (class WPD/Image) is listed under USB only, never as a disk, text "Storage metrics unavailable". Real phone, and whether Windows reports it with these classes, NOT VERIFIED | PARTIAL |
| P1.1.4 | Model limits use only KNOWN/UNKNOWN/NOT_PROVIDED/ESTIMATED; no invented quotas | P1.1 | tests/test_system.py (normaliser), ops.test.mjs, system.e2e.mjs: statuses KNOWN/ESTIMATED/NOT_PROVIDED/UNKNOWN only; malformed numbers rejected; four equal rows. The `limits` object schema read from HIVE Core worker records is MY ASSUMPTION; no real provider/Core response was ever seen (GAP-8) | PARTIAL |

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
| GAP-4 | Live HIVE Core events, Internet-active path through the ULTRON ring, CORE-with-events at 1280/2560, and Windows behavior were not verified. | P0.2 Windows progress (user-reported, partial): Python suite, fixture launcher and live-adapter launch + SSE status frame verified on Windows; see the Windows smoke test section. Still NOT verified: live HIVE Core, Internet-active path, CORE-with-events at 1280/2560, Windows browser/UI, Node tests on Windows. | OPEN |
| GAP-5 | Visual parity with the target image is NOT claimed. Implementation of the review items is done in part (see `docs/hive/VISUAL_REVIEW.md` section 6: artwork, context groups/connectors, task-card row, Layout card (disabled), icons, colours). An independent reviewer judged it recognisably the same family but not at parity; remaining differences are listed in section 6.5. The CORE-scale claim in the first review was wrong and is corrected there. Closes only on the owner's explicit acceptance of a side-by-side review. | P0.1 / visual phase Measured visual spec written (`docs/hive/VISUAL_SPEC.md`, tools/measure_*.py/mjs): the layout is NOT a grid in the target (rails are shorter and unequal, card row spans the centre only), type is ~0.57-0.88x the target's cap height at 1920x1080, CORE ring is 79-91 % of the target's size, agent nodes/planet ~1.2-1.7x too small. The hybrid 2.5D implementation is now built and tested (local wallpaper, canvas/SVG CORE, measured absolutely positioned DOM stage; HANDOFF_REPORT section 15; Python 280, Node 88, Playwright 48 on Linux). Panel geometry matches the measurement within 1.5 pp; vortex luminosity, connector brightness and a 1280x720 gauge-caption touch remain visible differences. Not claimed as parity; owner has not accepted. | OPEN |
| GAP-6 | Redaction is best-effort regex. Known, pinned limits: secrets shorter than 32 opaque characters without a recognised prefix/key name are not redacted; free-form prose secrets are not detected. JS and Python twins are held identical by `tests/redaction_cases.json`. | P0.3 review | OPEN (limit documented) |
| GAP-7 | Movement/Internet/Obsidian animations are only exercised on fixture events at 1920x1080; the P0.2 PARTIAL statuses above are intentionally unchanged. Review added unit coverage for "never disappear in transit" (100 ms sampling) but the status is left PARTIAL until the owner reviews it. | P0.2 review | OPEN |

### Test Engineer review outcome (P0.1-P0.3)
Verified by reproduction before fixing (all were real): a one-hour-old event moved an agent; a future telemetry timestamp read as IDLE; working-then-completed without task/run ids left WORKING stuck; a queued trip survived its own completion; ULTRON "observed" never expired; `{ok:"yes"}` from a connector counted as a source approval; `provider_response_id: 0` counted as a provider response; a throwing `connected()` rejected unhandled; quoted/Basic-auth/spaced-key secrets and secret-bearing role/provider fields leaked; events received while the source was untrusted stayed in the buffer and became "valid" when validity flipped; an in-flight poll finishing after SSE took over overwrote the stream's validity; the CORE could show fixture-driven WORKING before the environment label loaded. All fixed with tests. Not acted on: the review's request to make GAP-1 a failing test (the owner asked for it to stay tracked, so a test pins the current fallback behaviour instead).

## Windows smoke test - commit 7dc6f70 (USER-REPORTED, partial)
Reported by the project owner after running the section 9 checklist on the real Windows PC. Not independently verified by the agent; no screenshots or raw logs were supplied. No token, credential, cookie or secret was shared or used. Python version, Node version, browser, resolution and DPI scaling were NOT reported.

| Step | Result | What it evidences | What it does NOT evidence |
|---|---|---|---|
| 0 Checkout | PASS: HEAD 7dc6f70, working tree clean | The Windows worktree is the P0 checkpoint | - |
| 1 Python | PASS: `py_compile` OK; `unittest` 242/242 OK | The Python suite, including the OpenCode workspace test on real Windows drive paths, passes natively | Real `wsl.exe` / OpenCode execution (the suite mocks subprocess); Python version unknown |
| 1 Node | NOT_RUN | - | Node unit tests and UI contract on Windows |
| 2 Fixture launcher | PASS: `start-fixture.ps1`, `status-fixture.ps1` (RUNNING), `stop-fixture.ps1` | The fixture PowerShell lifecycle works on Windows | Anything the fixture UI shows |
| 2 Fixture UI scenarios | NOT_RUN (home page not inspected; approval and secrets scenarios not run) | - | Layout/CORE/approvals/redaction in a real Windows browser |
| 3 Live adapter, no token | PASS: stale `server.py` process on port 4173 (PID 1016) was verified and stopped by the owner, then `start.ps1` started it (PID 57896); `/api/events/stream` returned `validity: unavailable`, `event_count: 0`; HIVE Core actively refused the connection; clean stop | `start.ps1` and the live SSE endpoint report honest "unavailable" with zero events when Core is down | Whether the UI rendered UNKNOWN; whether AO session listing auto-enabled (not reported); any state with a reachable Core |
| 3 Live UI / chat | NOT_RUN | - | UNKNOWN rendering, NOT_CONNECTED outbox, absence of POSTs/uploads in a real browser |
| 4 Live with token | NOT_RUN (no token set or exposed) | - | Everything about a reachable, authenticated HIVE Core |
| 5 Visual comparison | NOT_RUN | - | Any visual judgement on the real monitor |
| 6 Playwright | NOT_RUN | - | Browser tests on Windows |

Effect on tracked items (statuses unchanged unless stated): S15.15 gains a user-reported Windows Python result (242/242) but remains PASS_AUTOMATED on the Linux evidence plus this partial Windows evidence; it does not cover the Node suites on Windows. GAP-4 has partial progress noted in its row and stays OPEN. GAP-1, GAP-2, GAP-3, GAP-5, GAP-6 and GAP-7 are unaffected by this run and stay OPEN. No P1 item changed.
| GAP-8 | P1.1 is verified only against MOCKED OS/provider output and the synthetic fixture. NOT verified: the real PowerShell script (cmdlet availability, permissions/elevation for Get-Disk and MSAcpi temperature), real USB/external-disk detection, real MTP/PTP classification (WPD/Image classes are best-effort), nvidia-smi on a real GPU, and the shape of any provider/Core limits (the `limits` object is an assumption). No live Core or provider was queried. | P1.1 | CLOSED (scoped: System Resources on one Windows configuration, owner decision; residuals listed below) |

## P1.1 follow-up findings (found while building, all fixed with tests)
- A failed/unavailable OS probe rendered "USB 0" (a false claim of zero devices); adapter now returns `usb_known`/`disks_known` and the UI shows UNKNOWN unless the probe actually returned a list.
- Removable USB media was classified "external" instead of "removable"; classifier order fixed.
- The compact summary truncated the phone note at 1280x720; the line now wraps and the panel is slightly taller (resources row min height 164px); a test asserts the text is not truncated.
- Not done in P1.1 (still NOT_RUN): GPU utilization without nvidia-smi, per-core/other temperature sources, any provider quota fetching.

(Visual phase: S15.1 stays NOT_VERIFIED; new automated checks for the visual phase live in tests/e2e/visual.e2e.mjs, tests/core.test.mjs (context labels) and tests/ops.test.mjs (task cards). They verify truthfulness constraints and layout, not visual similarity.)

## Owner decisions after the wallpaper integration
- Wallpaper integration (commit 305bc87) accepted by the owner as a provenance-safe asset integration only. Full visual parity is NOT accepted; GAP-5 stays OPEN. The owner will inspect the regenerated comparisons at 1280x720, 1920x1080 and 2560x1440 before any further visual change or P1 phase.
- UI-1 (OPEN, targeted issue): at 1280x720 the UNKNOWN captions under the GPU and TEMP gauges in System Resources touch. Fix only when the owner approves further visual work; must keep the "UNKNOWN" label and the 13.2 reference-px text floor.
- ASSET-1 (OPEN, accepted limitation): the wallpaper source is 1672x941 and is upscaled 1.53x to 2560x1440, so it is soft. Not to be masked with CSS sharpening or filters; resolved only by a higher-resolution source.
- Measured CORE geometry is frozen. P1.2 and P1.3 are not started and wait for an explicit owner decision.
- UI-1 update: GPU and TEMP gauges now show a neutral `?` glyph instead of the UNKNOWN caption (all viewport sizes, same stage). Semantics unchanged: `data-status="UNKNOWN"` on the gauge, glyph `role="img"` with `aria-label="UNKNOWN — no fresh telemetry"`, keyboard-focusable, tooltip on hover and focus (Escape hides), full text kept in the System evidence line ("GPU UNKNOWN, TEMP UNKNOWN (no fresh telemetry)"). `?` is used for no other state. Two new tests in tests/e2e/system.e2e.mjs. STILL OPEN: in the live adapter (everything unknown) the CPU/RAM/DISK captions "UNKNOWN" still touch each other at 1280x720; the owner scoped this change to GPU/TEMP, so it is not changed.
- GAP-8 update: SYSTEM RESOURCES source re-confirmed and tightened (HANDOFF_REPORT section 18): adapter interface with Mock on Linux, CPU from the OS performance counter, ACPI temperature removed (TEMP UNKNOWN unless nvidia-smi), GPU capability renamed `hardware_present`. Real Windows path still NOT VERIFIED; GAP-8 stays OPEN.

## Windows smoke test of the real PowerShellAdapter (user-reported, partial) - commit 450ecc1
Reported by the owner on the Windows PC, default mode (no `--full`), `python tools/smoke_system_windows.py`: **PASS**. Evidence: `adapter: PowerShellAdapter (real)`, evidence validity `valid` @ 2026-11-05T03:35:35Z (`windows:powershell`); CPU valid 25.0 % (`Win32_PerfFormattedData_PerfOS_Processor`), memory valid 67.4 % (`Win32_OperatingSystem`), disk valid 69.1 % (`Get-Volume`); GPU unavailable (no reliable utilization source), temperature unavailable (no reliable temperature source); `gpu.hardware_present` = AMD Radeon 780M Graphics (capability, not telemetry); `disks_known=True` (1 volume), `usb_known=True` (5 devices). No token or credential used. This is a user-reported result, not reproduced in the Linux container.
- **Now verified on Windows (user-reported):** the real PowerShell path runs, returns CPU/RAM/disk with source and `observed_at`, and GPU/TEMP stay UNKNOWN on a machine without nvidia-smi telemetry (AMD GPU).
- **Still NOT verified (GAP-8 stays OPEN):** the `nvidia-smi` success path (this PC has an AMD GPU; only the "absent/not applicable" path was exercised); the per-volume/USB/MTP detail (`--full` not run); the dashboard UI fed by the live Windows adapter (gauges, Local Devices, System console); Node/Playwright suites on Windows; model limits against a real provider. Treat the 5 USB devices as reported by the OS, not as verified classification.
- P1.1 single-path update (HANDOFF_REPORT section 20): System Resources gauges read only /api/system/resources; the HIVE Core metric fallback was removed; hover shows source/observed_at/validity/reason. The Windows live-dashboard check is NOT_RUN until the owner runs tools/live_check_windows.mjs at the new commit. GAP-8 stays OPEN.
- Windows live-dashboard check at f7162c2: NOT_RUN (checker crashed on Node v24.21.0 / undici `assert(!this.paused)`; user-reported; no hardware result claimed). Checker hardened in the next commit (HANDOFF_REPORT section 21); a valid Windows run is still required. Windows Node/Playwright suites: NOT_RUN. GAP-8 stays OPEN.
- Windows live check at 28383fb (user-reported): FAIL - the OS probe timed out inside server.py (evidence unavailable; CPU/RAM/disk unavailable; snapshot request also timed out) although the smoke test passed earlier on the same PC. Root cause NOT established; probe instrumented and a Windows diagnostic added (HANDOFF_REPORT section 22). A timeout is a failure, not a valid UNKNOWN. A valid Windows live-check PASS is still required; Windows Node/Playwright suites: NOT_RUN. GAP-8 stays OPEN.
- Windows diagnostic at 1a59ce2 (user-reported): the system probe takes ~4.5 s (cold 6.7 s) in every runner variant and through the live server it returned valid CPU 41 % / memory 67.6 % / disk 69.1 % with source and observed_at; GPU/TEMP unavailable with reasons. The live-check API phase PASSED. The earlier 28383fb timeout is not reproduced (cause unknown; stdin/console hypothesis refuted). Remaining FAIL: `/api/dashboard/snapshot` took more than 10 s on Windows (pre-existing, outside System Resources; cause not yet measured - run tools/diagnose_snapshot.py). New open finding **GAP-9: snapshot latency on Windows**. Browser phase of the live check and Windows Node/Playwright: NOT_RUN. GAP-8 stays OPEN until a full live-check run completes (PASS or exit 6 with the browser phase).
- GAP-9 (snapshot latency on Windows) - user-reported confirmation: `diagnose_snapshot.py` whole snapshot 18 339 ms, ~9 unreachable-Core probes at ~2 s each. Narrow fix implemented (one 1.5 s preflight per snapshot; remaining Core probes skipped with `unavailable` + reason; HANDOFF_REPORT section 24; tests/test_snapshot_latency.py, 9 tests). **Status: fix verified on Linux with mocks only; NOT re-measured on Windows; GAP-9 stays OPEN.** Also recorded: in a second Windows live check the OS probe timed out after 8 s while in the `cpu` section (normally ~0.56 s); cause unexplained, timeout not raised, mitigation pending the owner's decision; GAP-8 stays OPEN. Browser phase of the live check remains NOT_RUN.
- Windows re-measurement at 4456991 (user-reported): whole `snapshot()` 3 534 ms (was 18 339 ms), live-check snapshot request 3 563 ms; OS probe valid with probe_ms 6 948 (CPU 13 %, memory 68 %, disk 69.1 %); API PASS; browser phase NOT_RUN (Playwright not installed on the Windows PC). **GAP-9: RESOLVED on this configuration** (one Windows PC, HIVE Core not running; not measured with Core running). **GAP-8: stays OPEN** - browser checks not yet run, Windows Node/Playwright suites NOT_RUN, and the OS probe's margin is small (4.4-6.9 s observed against the 8 s limit; two earlier live runs timed out, one stalled in the `cpu` section); mitigation awaits the owner's decision. Playwright has no documented project procedure (no package.json); the verified-on-Linux local install is `npm install --no-save --no-package-lock playwright@1.63.0` followed by `npx playwright install chromium` (the browser download is NOT verified on Windows) - see HANDOFF_REPORT section 25.

## Windows live check at 8db4330 (user-reported): PASS - GAP-8 closed for one configuration, GAP-9 resolved
Owner ran `node tools/live_check_windows.mjs` at 8db4330 on the Windows PC after `npm install --no-save --no-package-lock playwright@1.63.0` and `npx playwright install chromium`: **PASS, exit code 0**. Reported: API PASS; CPU, RAM and disk valid (with source and observed_at); snapshot request about 3.56 s; GPU and TEMP shown as UNKNOWN (`?`); browser phase passed at 1280x720 and 1920x1080; System Resources and Local Devices not clipped or overlapping; model-limit rows invent no values; no console or page errors; no LISTENING process left on port 4195. This is a user-reported result, not reproduced in the Linux container. It also shows that Playwright 1.63.0 runs on this Windows PC.
- **GAP-9: RESOLVED** for this configuration (one Windows PC, HIVE Core not running; not measured with Core running).
- **GAP-8: CLOSED for System Resources on this one Windows configuration, on the owner's decision.** The scope is: the real PowerShell adapter plus the dashboard display of CPU/RAM/disk (valid, with source and observed_at), GPU/TEMP UNKNOWN, Local Devices, and no invented model-limit values, on this PC with an AMD GPU.
- **Residuals that this closure does NOT cover (still unverified):** (1) the Windows Node unit tests (`tests/*.test.mjs`) and the Windows Playwright e2e suites (`tests/e2e/*.e2e.mjs`) were NOT run - only the live-check browser phase was; (2) the `nvidia-smi` success path (AMD GPU here, platform-unverified; only mocked); (3) model limits against a real provider or live HIVE Core (the rows only showed UNKNOWN, which proves nothing is invented, not that real limits parse); (4) other Windows machines; (5) intermittent OS-probe timeouts: two earlier live runs timed out (one stalled in the `cpu` section) and observed probe time ranged 4.4-6.9 s against the 8 s limit; one passing run does not show they cannot recur, the cause is unexplained and the timeout was deliberately not raised. If it recurs the evidence line now names the stalled section.
- Unchanged and still OPEN: GAP-1 to GAP-7 (GAP-5 visual parity awaits the owner's explicit acceptance), UI-1 for the CPU/RAM/DISK captions in an all-unknown live view, ASSET-1. P1.2 and P1.3 not started.

## UI-1 finalization pass (base e0aac8c, backup tag backup/pre-ui1-fix verified remotely by the owner)
- **UI-1: DONE (display only).** Every UNAVAILABLE System Resources gauge (CPU, RAM, DISK, GPU, TEMP) now shows a compact `?` glyph instead of an `UNKNOWN` caption. Unchanged: `data-status="UNKNOWN"`, the validity logic, the API contract, and the exact `aria-label="UNKNOWN — no fresh telemetry"`. New: hover and keyboard-focus details (multi-line tooltip, also `aria-description`) with `Reason`, `Source` and `Observed at` (`none (no valid observation)` when absent; a rejected out-of-range value never shows as observed). Known gauges never get a glyph. `?` is still not used for OFFLINE, UNVERIFIED, NOT CONNECTED or NOT PROVIDED. The all-unknown live view at 1280x720 no longer has colliding captions.
- **Also (display only):** the full text of truncated task-card lines is available on hover (authored titles such as the Layout note are never overridden). A regression I introduced here (overriding the Layout note title) was caught by the existing visual test, fixed, and covered by a new test.
- **Unchanged and verified by diff against e0aac8c:** `server.py`, `hive_system.py`, `hive-core.js`, `stage-layout.css`, `index.html`, `fixture_server.py`, `assets/`; the measured geometry JSON (`docs/hive/measurements/ours-after-*.json`) is byte-identical after the change. OS probe, snapshot preflight, Overview cards, P1.2/P1.3 untouched.
- **Tests run in the Linux container (once, on the final code):** Python 310 OK; UI contract OK (20); Node `core`+`ops`+`html_ids`+`live_check` 97/97; Playwright shell 7/7, core 10/10, chat 11/11, system 7/7, visual 16/16; py_compile OK; `git diff --check` clean. **Windows tests were NOT rerun.** The Windows live-check PASS at 8db4330 (user-reported) predates this change and is not evidence for it; `tools/live_check_windows.mjs` now also asserts that every UNKNOWN gauge shows the glyph, and has not been run on Windows since.
- **GAP-5 stays OPEN** (visual parity is not claimed; awaiting the owner's explicit acceptance). GAP-1 to GAP-7, ASSET-1 and the GAP-8 residuals are unchanged. P1.2 and P1.3 are not started.

## Read-only foundation: registry, ULTRON status, catalogs, proposal log (base b02e82d, tag backup/pre-readonly-foundation)
Gate A (USER-REPORTED, Windows at b02e82d): live check exit 0; UI-1 verified at 1280x720 and 1920x1080; every UNKNOWN gauge shows `?`, no KNOWN gauge does; no clipping, overlap or console errors. Tag `backup/pre-readonly-foundation` -> b02e82d VERIFIED with `git ls-remote --tags`.

**Built (read-only; nothing is executed, activated or written externally):**
- `hive_registry.py` + generated `schemas/hive-readonly-v1.schema.json` (schema `hive.readonly.v1`): one evidence envelope on every record (`id, kind, source, source_id, observed_at, validity, reason, correlation_id, schema_version, display, not_provided`); kinds: connector, agent, role, worker, provider, capability, task_instance, catalog_item, ultron_status, proposal, evidence_record. Display states stay distinct: OBSERVED, STALE, OFFLINE, NOT_CONNECTED, UNKNOWN, UNVERIFIED, CONFLICT, AUTH_REQUIRED, FIXTURE; fields no source provides are null and listed in `not_provided`.
- `GET /api/registry` (server.py, inside the snapshot preflight scope) and a fixture twin (fixture_server.py, every record relabelled FIXTURE); a **Registry** view in the DETAILS console that loads only when opened.
- HIVE Core adapter (wraps the existing transport): workers (or the labelled public `/ready` fallback), task instances, events. **Agents** are only identities named by HIVE Core events; **primary/secondary classification is UNKNOWN** everywhere (owner decision). Roles are the dashboard's catalog definitions with no provider mapping. Providers link to a worker only when that worker's own `provider` field names them exactly. Duplicate worker ids are flagged CONFLICT; malformed items are dropped.
- **ULTRON status** on the existing state contract: OFFLINE when the Core transport is unavailable; UNKNOWN with no ULTRON event (silence is never ACTIVE); UNVERIFIED for future or missing timestamps; ACTIVE only for a trusted ULTRON event within 120 s (the same window as `hive-core.js` `roleFresh`); STALE after that, with state expired to UNKNOWN. Source, event id and timestamp are shown. The CORE ring logic is unchanged.
- Catalogs: skills from the two allowlisted roots (`~/.codex/skills`, `~/.agents/skills`, or `HIVE_SKILL_ROOTS`), bounded and symlink-safe, frontmatter parsed as data, SKILL.md and tree sha256, declared capabilities, every item `enabled=false` ("discovered, not activated"); Obsidian metadata only (tags, link counts, mtime, hash; never note content) and **only** from the `ORCHESTRATOR_VAULT_ROOT` environment variable with a `.obsidian` folder; Creator Ops wraps the existing counts-only adapter; prompts and bots NOT_CONNECTED (no root configured); configured tools listed, never run.
- Self-evolution **proposal log** (display only): `docs/hive/proposals/proposals-v1.json`, three proposals citing GAP-1, GAP-3 and GAP-6 by exact row hash, each with problem, benefit, affected files, risk, test plan, rollback plan and expiry; review status is always PENDING_HUMAN_REVIEW; a changed GAP row or expiry makes a proposal STALE.
- Bounded in-memory evidence log (one per mode, so fixture and live entries never mix).

**Evidence classes:**
- VERIFIED (Linux container): full suite below; fixture and live registries validate against the schema with zero errors; with HIVE Core down the registry costs exactly one bounded Core call; measured dashboard geometry byte-identical.
- MOCKED: HIVE Core workers/tasks/events (injected fetch and fixtures); Creator Ops counts; skill and vault data (synthetic `tests/fixtures/skills` and `tests/fixtures/vault`).
- USER-REPORTED: Gate A Windows results above.
- NOT_VERIFIED: the real skill roots on the Windows PC; Obsidian (the environment variable is not configured here, so it reports NOT_CONNECTED); any real HIVE Core agent/worker/task data; the Creator Ops task catalog (schema unknown, row content deliberately not read); the Registry view on Windows.

**Tests (Linux, once on the final code):** Python 351 OK (incl. new `tests/test_registry.py`, 41); UI contract 20; Node core/ops/html_ids/live_check 97/97; Playwright shell 7, core 10, chat 11, system 7, visual 16, registry 4 (new); py_compile OK; `git diff --check` clean; diff scan found no secret-shaped strings outside the labelled synthetic fixture and no new hardcoded user paths. A real defect was caught and fixed during the work: the evidence log was shared between fixture and live reads.

- **GAP-10 (new, OPEN): registry real-source verification.** Close only after the owner runs `python tools/registry_summary.py` on the Windows PC (real skill roots; Obsidian if `ORCHESTRATOR_VAULT_ROOT` is set) and views the Registry view; real HIVE Core agent/worker records need a running Core.
- Not done (needs a decision or authority): a Creator Ops task catalog (needs the authoritative schema and approval to read row content); prompts/bots roots (none named); any execution, approval or write path. GAP-1 to GAP-7, GAP-5 (visual parity) and ASSET-1 unchanged and OPEN. P1.2/P1.3 not started.

## Registry v2 and read-only operational integrations (base bb9f00a)
Gate (VERIFIED): HEAD = origin/hive/dashboard-v1 = bb9f00a; `backup/pre-readonly-foundation` -> b02e82d present; worktree clean. No new tag was requested before starting; the rollback point for this phase is bb9f00a (a tag such as `backup/pre-registry-v2` can be created on it at any time).

**Built (read-only; nothing executed, activated or written):** schema `hive.readonly.v2` (`schemas/hive-readonly-v2.schema.json`); explicit configuration only (`HIVE_SKILLS_ROOTS`, `HIVE_PROMPTS_ROOTS`, `HIVE_BOTS_ROOTS`, `ORCHESTRATOR_VAULT_ROOT`, `CREATOR_OPS_DB_PATH`, `HIVE_TOOL_MANIFEST_DIR`) with path rules (absolute, no `..`, not a filesystem root or the bare home, no symlinked root); the four hardcoded user paths in server.py removed; Creator Ops `task_definitions` catalog with a table/column allowlist; Obsidian metadata with backlinks, task counts and bounds; skills/prompts/bots catalogs; manifest-only tool registry (6 repository manifests); ULTRON recent observations and blocked connectors; proposal statuses (PENDING_HUMAN_REVIEW, APPROVED_FOR_PROTOTYPE, REJECTED, STALE, EXPIRED); per-source isolation with timeouts and cache; lazy per-source loading in the Registry view; compact `?` for NOT_PROVIDED fields with accessible labels; no aggregate state chips. Details: `docs/hive/DATA_CONTRACTS.md`, `docs/hive/INTEGRATION_PLAN.md`.

**Evidence:**
- VERIFIED (Linux): full suite below; fixture and live registries validate against v2; Core down costs one bounded Core call; a slow source times out without blocking the others; Creator Ops SQL is traced and only `task_definitions` is queried; no note, prompt or account content and no secret-shaped string reaches a response; main-dashboard geometry unchanged; registry not requested until the view is opened.
- MOCKED: HIVE Core, Creator Ops database (temporary SQLite), skill/prompt/bot/vault/tool fixtures under `tests/fixtures/`.
- USER-REPORTED: Gate A Windows results at b02e82d (UI-1); no Windows run of this phase yet.
- USER-CONFIGURED / NOT_VERIFIED: real skill roots (default allowlist), Obsidian (`ORCHESTRATOR_VAULT_ROOT`), Creator Ops (`CREATOR_OPS_DB_PATH`; expected NOT_VERIFIED "schema unknown" unless a `task_definitions` table/view exists), prompts/bots roots (none named), live HIVE Core data.
- **Behaviour change on the Windows PC:** Creator Ops counts and the Obsidian project-registry / self-evolution / context projections now report "not configured" until `CREATOR_OPS_DB_PATH` and `ORCHESTRATOR_VAULT_ROOT` are set (they previously relied on hardcoded paths).

**Tests (Linux, once on the final code):** Python 356 OK (`tests/test_registry.py` 46); UI contract 20; Node core/ops/html_ids/live_check 97/97; Playwright shell 7, core 10, chat 11, system 7, visual 16, registry 6; py_compile OK; `git diff --check` clean; content scan: no secret-shaped strings outside the labelled synthetic fixtures, no user-specific path in code (owner-authored README/handoff text still describes the owner's machine layout). Registry screenshots: `docs/hive/screenshots/registry-fixture-{1280x720,1920x1080,2560x1440}.png`, `registry-live-1920x1080.png`.

- GAP-10 stays OPEN (Windows run of `tools/registry_summary.py` and the Registry view not done for v2). GAP-1 to GAP-7, GAP-5 and ASSET-1 unchanged. P1.2 work is limited to this read-only registry; P1.3 and any execution or write path are not started.
