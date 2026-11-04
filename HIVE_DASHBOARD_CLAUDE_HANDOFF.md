# HIVE Dashboard — Claude Handoff Specification

**Document status:** consolidated implementation handoff  
**Audience:** Claude, primary HIVE dashboard implementer  
**Scope:** dashboard visual system, live central visualization, system resources, provider/agent relationships, Obsidian/WONG, ULTRON, EVOLVE, chat, Activity, Approvals, and budget discipline  
**Language:** English for direct use by Claude

## 1. Executive goal

Build a functional desktop-first HIVE control room that visually follows the supplied HIVE reference while truthfully showing the observed state of the system.

The dashboard is not a marketing page and not a static illustration. It must be a readable operational cockpit with:

- one centered, animated HIVE CORE;
- orbiting roles and agents;
- live relationships between agents, tasks, providers, models, Obsidian, Internet, and local devices;
- system resources and provider limits when actually available;
- a functional local-file chat composer;
- Activity and Approvals panels;
- ULTRON as a real security layer;
- a small, isolated-branch-only EVOLVE/self-evolution module.

The user explicitly prefers the original spacious composition: cards must float separately over the background and must not form a solid wall.

## 2. Authority, safety, and implementation lane

- Git is the code identity.
- WONG is the canonical memory and decision authority.
- The USER is the only promotion/deployment authority.
- Codex/GPT is an independent reviewer, not the primary HIVE implementer.
- Do not modify PROD, WONG, ROCKET, deployment state, release evidence, or production snapshots.
- Work only in the approved dashboard checkout or an isolated branch.
- Version every meaningful change.
- Create a backup before structural changes.
- Never silently invent provider status, quotas, approvals, telemetry, Internet activity, or hardware values.
- If a value is unavailable, display UNKNOWN, OFFLINE, NOT CONNECTED, or NOT PROVIDED.

## 3. Current verified dashboard state

Last independently verified dashboard checkout:

~~~
C:\Users\Martin\Documents\ChatGPT\DASHBOARD
HEAD: b3183120569002506f875a462e4f887c9cf8470f
Tree: bd6569f4d9d7a7981372bfeab3551f78119fb16c
~~~

Re-check the actual current state before editing. Do not assume the values above are still current.

Relevant files:

~~~
app.js
index.html
styles.css
server.py
tests/test_server.py
tests/ui_contract.test.mjs
~~~

Last verified tests:

~~~
python -m unittest tests.test_server -v
PASS — 211 tests

node --test tests/ui_contract.test.mjs
PASS — 20 tests

python -m py_compile server.py tests/test_server.py
PASS

git diff --check
PASS
~~~

Important current limitations:

- The current dashboard is primarily an evidence/proposal MVP, not a fully verified live cockpit.
- The browser live state remained UNKNOWN during the last live check.
- Chat draft → proposal → confirmation works, but real provider message delivery is not verified.
- chat_realtime_api_confirmed is false.
- AO/session listing and history adapters exist, but provider send remains gated.
- GPT, Claude, and Codex worker policies are declarative and do not prove live provider login/readiness.
- Obsidian fixture/read-context support exists, but live Obsidian projection is currently blocked because the vault is disabled/unconfigured.
- No reliable cross-provider GPT/Claude/Codex aggregation is currently proven.
- Demo fixtures exist and must always be visibly marked DEMO or REPLAY.
- Never use cookies, browser credentials, session scraping, or credential-file workarounds.

## 4. Visual references

Current full dashboard target:

~~~
C:\Users\Martin\.codex\generated_images\01a1a835-d314-7661-bf20-5238d8064a78\exec-a2ef8b57-2bec-4a04-be69-f61460d55805.png
~~~

![Current HIVE dashboard target](C:/Users/Martin/.codex/generated_images/01a1a835-d314-7661-bf20-5238d8064a78/exec-a2ef8b57-2bec-4a04-be69-f61460d55805.png)

Original central CORE reference:

~~~
C:\Users\Martin\AppData\Local\Temp\codex-clipboard-217d0f3d-e6d7-46f7-8ac3-a14dafa1b8b7.png
~~~

The image is a visual specification, not a static replacement for the functional dashboard. Telemetry values shown in the image are illustrative and must not be copied as real measurements.

## 5. Non-negotiable visual target

### Overall style

- Desktop monitor first.
- Dark space fused with a sophisticated computer-circuit substrate.
- Starfield, nebula, orbital rings, fine circuit traces, and subtle data paths.
- Separate translucent smoked/frosted-glass cards over the background.
- Visible dark gutters and empty space between every major section.
- No cards touching edge-to-edge.
- No light theme.
- No phone or tablet layout.
- No visible DONE section.
- No visible LOGS section.
- No visible system version.

### Fixed shell

Top bar:

~~~
HIVE
global status: IDLE / WORKING / WAITING / ERROR / UNKNOWN
GPT / CODEX / CLAUDE source indicators
ULTRON SECURITY: ACTIVE
JARVIS / VOICE LAYER — FUTURE
~~~

Left rail:

~~~
CHATS
PROJECTS
AGENTS / ROLES
~~~

Center:

~~~
HIVE CORE
FURY
SHURI
THOR
VISION
FALCON
UATU
OBSIDIAN
INTERNET
LOCAL DEVICES
ULTRON
~~~

Right rail:

~~~
ACTIVITY
APPROVALS
~~~

Bottom:

~~~
SYSTEM RESOURCES
AI MODELS / LIMITS
ASK HIVE...
attachment button
send button
VOICE button
~~~

The CORE remains fixed in the center. It may resize within safe limits but must never move.

### Panel material

Use a visual system equivalent to:

~~~css
background: rgba(4, 16, 29, 0.46);
backdrop-filter: blur(12px);
border: 1px solid rgba(90, 190, 255, 0.40);
~~~

The actual values may differ, but the result must be:

- transparent enough to reveal circuits and stars behind the cards;
- dark enough to preserve text contrast;
- visibly frosted rather than opaque;
- separated by intentional dark negative space.

## 6. Central CORE and animation semantics

Preserve the original HIVE CORE composition:

- luminous black-hole/energy vortex;
- orbital circular rings;
- FURY at the top;
- SHURI upper-left;
- THOR upper-right;
- VISION lower-left;
- FALCON lower-right;
- UATU at the bottom;
- Internet planet outside the upper-right;
- Obsidian/system/context labels around the orbit.

Do not replace the CORE with a generic node graph.

Recommended budget-efficient implementation:

~~~
1. Static CORE artwork/background for visual fidelity.
2. Transparent SVG/canvas/DOM overlay for live nodes and links.
3. CSS/SVG animation controlled by real HIVE events.
~~~

### CORE animation

The CORE is the only prominent functional animation. Its state must be observable and meaningful:

~~~
IDLE              low-energy slow motion
WORKING           active luminous rotation and event-linked pulses
WAITING_APPROVAL  amber/gold emphasis
REVIEW            violet emphasis
FAILED            red emphasis
SECURITY_BLOCKED  red lock/shield emphasis
OFFLINE           gray/dim
UNKNOWN           neutral/dim
~~~

Do not infer WORKING from silence. Missing telemetry must produce UNKNOWN.

### Ambient outer animation

Outside the CORE, circuit and link animation is allowed only as a secondary ambient layer:

- slow;
- sparse;
- low opacity;
- low contrast;
- relaxing rather than attention-seeking;
- never the dominant focal point;
- never presented as proof that an agent is working.

Real event-linked pulses may be stronger, but they must have an observed event and correlation ID. Decorative ambient motion must remain visually distinguishable from real task activity.

## 7. Equal provider weight and logical orbital movement

GPT and Claude have equal status and equal visual weight in HIVE. They perform different tasks, but neither provider is architecturally or visually privileged over the other.

Codex also remains a provider/worker, not a role identity.

Separate these concepts:

~~~
AgentRole
  FURY, SHURI, THOR, VISION, FALCON, UATU, ULTRON, EVOLVE

WorkerProvider
  GPT, Claude, Codex, Local

Model
  concrete provider/model identity

Task
  work item and state

Attempt
  execution attempt
~~~

Provider selection must depend on capability, availability, approval, task requirements, and budget—not provider favoritism.

### Agent orbital behavior

Agents may move around the orbit, but movement must be logical and event/state-driven.

Each agent has:

- a stable home sector;
- a current orbital angle;
- a target interaction node;
- a movement state;
- an interaction/task ID.

Examples:

~~~
Idle agent
  returns to its stable home sector.

Internet access
  agent moves toward the Internet gateway, with ULTRON between the agent and Internet.

Obsidian read/context lookup
  agent moves toward the Obsidian context node and emits a small read pulse.

Agent handoff
  source agent moves toward the destination agent; a task token/pulse travels between them.

Shared work
  both agents remain visible and are connected by a temporary task relationship.
~~~

Rules:

- Do not move agents randomly.
- Do not continuously orbit all agents merely for decoration.
- Do not make agents disappear while traveling.
- Avoid collisions and excessive simultaneous motion.
- Cap concurrent movement and pulse counts.
- Return agents to their home sector after the interaction ends or times out.
- Movement must be driven by an observed event, not by elapsed time alone.

Suggested event fields:

~~~
home_angle
target_node
target_angle
movement_state
interaction_id
started_at
completed_at
~~~

## 8. ULTRON and future JARVIS

### ULTRON

ULTRON has two visual elements:

1. A colored security/containment ring between the agent orbit and external Internet.
2. A small static circular agent-style icon/node, visually consistent with FURY, SHURI, THOR, VISION, FALCON, and UATU.

Ring states:

~~~
green/cyan  active and permitted
amber       attention or approval required
red         blocked/security event
gray        offline or unknown
~~~

Conceptually:

~~~
agent → ULTRON security check → Internet/external tool
~~~

ULTRON MVP must monitor:

- external connections;
- provider adapters;
- file attachments;
- tool permissions;
- path/sandbox violations;
- approval requirements;
- blocked actions.

Do not attempt to build a full antivirus or deep packet inspection system in this budget.

### JARVIS

JARVIS is future-only:

- inactive top-bar indicator;
- future voice-layer label;
- VOICE button remains visible;
- no active voice waveform;
- no real voice processing in this phase.

## 9. Event and integration contract

Normalize live events to a compact contract:

~~~
schema_version
event_id
timestamp
source
role_id
provider
model
task_id
run_id
correlation_id
event_type
state
severity
provenance
redacted_summary
~~~

Use SSE or an existing event stream as the primary live transport. Polling may be a fallback, but add:

- in-flight request guard;
- timeout;
- reconnect/backoff;
- stale/offline classification;
- bounded event buffer;
- duplicate event protection.

Current provider truth:

- GPT, Claude, and Codex must be represented equally.
- A configured adapter is not proof of a live connection.
- A provider response is required before claiming send success.
- Provider quotas are shown only when returned by the provider.
- Web application cookies and private browser sessions must not be scraped.

## 10. Required functionality

### Chat

- Attach one or more local files.
- Show attachment chips before sending.
- Enter sends.
- Shift+Enter creates a newline.
- Show QUEUED, SENT, FAILED, or NOT_CONNECTED.
- Do not fabricate provider replies.
- VOICE is a disabled future control.

### Activity

Show compact sanitized rows:

~~~
time | role | provider | current action | state
~~~

Do not show raw prompts, Chain-of-Thought, secrets, or private logs.

### Approvals

Show source-only rows:

~~~
GPT
CODEX
CLAUDE
~~~

with:

~~~
Approve | Edit | Reject
~~~

Behavior:

- Approve remotely only if the connector supports it.
- Otherwise mark the local proposal as approved and state that clearly.
- Edit opens the source task only if a valid adapter/deep link exists.
- Reject remotely only if supported.
- Never claim that an external source changed when only local state changed.

### Agent profiles

Each role/agent needs:

- editable display name;
- locally uploaded avatar;
- color;
- role;
- provider;
- model;
- capabilities;
- current task;
- current state;
- last observed time.

### Obsidian and WONG

- Obsidian is a visible central context node.
- WONG remains canonical memory and decision authority.
- Dashboard shows a human-readable project projection.
- Context includes decisions, tasks, handoffs, notes, and evolution proposals.
- Never guess a vault path.
- Do not write to Obsidian unless the configured connector is enabled and authorized.
- HIVE-local tasks remain HIVE-local and do not automatically propagate to GPT, Claude, or Codex.

### Internet

- Show Internet as a planet node with an aura.
- Connect it to the currently active agent.
- Only show active network activity when observed.
- Configured-but-unused Internet access must not appear active.

### System resources

Show only values returned by the operating system:

- CPU;
- RAM;
- GPU;
- disk;
- free space;
- temperature where available;
- attached USB devices;
- external disks.

Example:

~~~
USB Storage
Connected
2 TB
1.31 TB free
E:\
Read/Write
~~~

For a phone connected through MTP/PTP:

~~~
USB Phone
Connected
MTP
Storage metrics unavailable
~~~

Never represent a phone as a block disk unless the operating system exposes it as one.

### Model limits

Only show provider-returned values:

~~~
KNOWN
UNKNOWN
NOT_PROVIDED
ESTIMATED
~~~

Do not invent quotas.

## 11. EVOLVE/self-evolution MVP

Implement a small module named EVOLVE with its own profile.

Allowed:

~~~
read broadly
analyze evidence
inspect statistics
inspect tests
inspect configuration
prepare a proposal
create an isolated branch
apply a bounded patch
run tests
show diff
create backup
~~~

Not allowed:

~~~
direct production changes
silent WONG changes
automatic promotion
credential access
unbounded autonomous code changes
~~~

Workflow:

~~~
OBSERVE
→ ANALYZE
→ PROPOSE
→ ISOLATED BRANCH
→ TEST
→ DIFF + EVIDENCE
→ BACKUP
→ USER APPROVAL
→ PROMOTION
~~~

## 12. Layout editing and desktop scaling

Implement a bounded desktop layout editor:

- resize modular panels;
- drag/drop panels within allowed zones;
- green check confirms;
- red X cancels;
- preserve minimum gutters;
- keep CORE centered;
- CORE can resize but cannot move;
- persist layout locally;
- restore default layout when configuration is invalid.

Do not build a freeform pixel editor.

Recommended desktop behavior:

~~~
1280×720       compact desktop, gutters 10–12 px minimum
1920×1080      reference baseline, gutters 16–20 px
2560×1440+     expand negative space and central canvas
~~~

No mobile or tablet layout is required.

## 13. Budget discipline

Treat USD 100 as a hard ceiling. Pricing/credits are not independently verified; this is an execution ceiling, not proof of available provider credit.

Suggested allocation:

~~~
$10  shell, spacing, desktop scaling
$18  CORE, event model, live states
$18  chat, Activity, Approvals
$10  system resources and hardware
$7   profiles and avatars
$10  Obsidian/WONG and Internet
$8   ULTRON MVP
$10  EVOLVE MVP
$9   QA and reserve
~~~

Rules:

- Start with a short state receipt, not a broad audit.
- Use targeted rg searches and line-range reads.
- Do not dump large repositories, logs, databases, or generated assets into context.
- Do not spend the reserve on speculative connector work.
- If a provider connector is unavailable, implement the adapter boundary and honest UNKNOWN state.
- Stop at a phase acceptance gate before starting the next phase.
- Do not add large dependencies or WebGL unless absolutely necessary.
- Prefer existing vanilla HTML/CSS/JS and SVG/canvas.
- Preserve existing passing tests.
- Do not rewrite the entire dashboard unnecessarily.

## 14. Recommended implementation order

### P0.1 — Visual shell

Implement the fixed shell, frosted glass panels, empty space, desktop scaling, and removal of unwanted sections.

### P0.2 — Functional CORE

Implement the event-normalized central visualization, state-driven CORE animation, agent orbit positions, logical movement, ULTRON ring/icon, Internet, Obsidian, and event-linked relationships.

### P0.3 — Chat, Activity, Approvals

Implement local attachments, truthful send states, sanitized Activity, source-only Approvals, and supported connector fallbacks.

### P1.1 — System and provider data

Implement local system metrics, external-disk detection, MTP/PTP distinction, model availability, and provider-returned limits.

### P1.2 — Profiles and shared context

Implement editable role profiles, local avatars, Obsidian/WONG projection, and project-scoped context.

### P1.3 — ULTRON and EVOLVE

Implement the bounded ULTRON guard and the isolated-branch-only EVOLVE proposal/test workflow.

### P1.4 — QA and handoff

Run targeted tests and report exact results. Do not claim a live integration unless it was actually exercised.

## 15. Acceptance criteria

The implementation is acceptable only if:

1. The dashboard visually matches the supplied reference direction.
2. Panels have visible empty space and never touch.
3. The layout adapts between 1280×720, 1920×1080, and 2560×1440 desktop monitors.
4. The CORE remains centered and is the primary animation.
5. ULTRON has both a static agent-style icon and a state-changing security ring.
6. GPT and Claude have equal architectural and visual weight.
7. Agents move only in response to logical interactions or observed state transitions.
8. Ambient outer animation is sparse, slow, and visually subordinate.
9. No activity is invented when telemetry is missing.
10. Chat attachments and send states work honestly.
11. Activity and Approvals are readable and sanitized.
12. Hardware and model values show UNKNOWN when unavailable.
13. Obsidian/WONG authority boundaries are preserved.
14. EVOLVE changes only an isolated branch and produces evidence.
15. Existing tests remain passing or regressions are explicitly reported.
16. No production, WONG, ROCKET, deployment, or release state is modified.

At the end, report:

~~~
files changed
tests actually executed
PASS/FAIL/NOT_RUN
verified integrations
unavailable integrations
known limitations
remaining budget estimate
rollback/backup location
~~~

## 16. Historical budget evidence

These read-only historical artifacts explain why the execution must be phased:

- [Claude 100 USD execution plan](C:/Users/Martin/HIVE-work/codex-e3/audit-2026-11-03/21_CLAUDE_100_USD_EXECUTION_PLAN.md)
- [E4 Claude budget plan](C:/Users/Martin/HIVE-work/codex-e3/e4-master-2026-11-03/claude-budget-plan.json)
- [Token usage efficiency](C:/Users/Martin/HIVE-work/codex-e3/audit-2026-11-03/18_TOKEN_USAGE_EFFICIENCY.md)
- [Core evolution budget](C:/Users/Martin/HIVE-work/codex-e3/core-evo-execution-v3/HIVE_CORE_EVO_EXECUTION_v3/07_BUDGET_AND_ROUTINES.md)

Historical HIVE work showed that broad tasks consume context quickly through repeated tests, retries, integration checks, and evidence collection. The current dashboard scope must therefore be implemented in bounded phases with a reserve.

## 17. Final user corrections incorporated

- GPT and Claude have equal weight in HIVE; their capabilities differ, but neither is subordinate by provider identity.
- ULTRON keeps the colored security ring and also has a static agent-style icon.
- The CORE is the only dominant functional animation.
- Outer link/circuit animation is occasional ambient decoration and must not distract from the CORE.
- Agents move logically along the orbit toward Internet, Obsidian, or other agents when an observed interaction requires it.
- Agents return to stable home sectors after interaction completion or timeout.
- The original CORE composition remains the visual reference.
- Frosted glass panels float over a combined space/circuit background.

