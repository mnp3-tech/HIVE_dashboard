# Visual review vs `docs/assets/hive-dashboard-target.png` (GAP-5)

**Status: GAP-5 stays OPEN.** Sections 1-5 are the review written BEFORE implementation; section 6 records the implementation and the post-implementation review. Parity is NOT claimed; it needs the owner's explicit acceptance.

**Method.** Side-by-side images at each desktop size, target (1671x941, scaled) on the left, the real UI on the right, using the fixture server so panels are populated:
`docs/hive/screenshots/compare-1280.png`, `compare-1920.png`, `compare-2560.png`. Live-adapter (Core unreachable) screenshots, `live-*.png`, show the same layout with every value UNKNOWN. The target is visual direction only; none of its numbers, names or statuses are data.

## 1. What already matches
Overall composition (top bar, three columns, centred CORE, resources + limits row, composer under the centre), frosted-glass cards with visible gutters, six agents at the original home sectors, ULTRON icon on the top of the ring, Internet planet upper right, Obsidian/Local devices nodes at left, Activity above Approvals, GPT/CODEX/CLAUDE chips of equal size, gauges + limit bars, disabled VOICE.

## 2. Differences found (all three sizes unless noted)
| # | Element | Target | Ours now | Truthful way to close it | Deliberate deviation |
|---|---|---|---|---|---|
| 1 | Background | Rich nebula, dust, many stars, galaxy bands, faint circuit | Two soft gradients, ~12 star dots, faint circuit | Procedural SVG/CSS layers (stars at several depths, blurred nebula blobs, circuit traces). Decorative only | none |
| 2 | Vortex | Spiralling accretion disk: blue/violet/orange arms, black centre, bright photon ring | Flat radial gradient disk with four short arcs | Procedural spiral arms (log-spiral paths + blur + gradients) in the existing SVG; slow rotation only in WORKING/IDLE as now | none |
| 3 | Rings | Multi-colour glowing neon rings (green/cyan/blue/orange segments), glowing nodes on the ring | Thin teal orbit ring, gray dashed ULTRON ring | Glowing decorative orbit rings and ring nodes. The ULTRON ring keeps its state colour | **ULTRON ring is gray/amber/red by observed state; the target's green "ACTIVE" ring is not shown without an ULTRON event** |
| 4 | CORE scale | CORE + tool lists fill the whole centre | **CORRECTED in section 6: measured ring sizes are close to the target (see numbers there); the emptiness came from missing context groups/background, not from an under-scaled CORE** | Fill the stage with the context groups and artwork | none |
| 5 | Agent nodes | Illustrated avatars in glowing coloured rings, role subtitle ("Planning", "Coding"...) | Letter glyph in a thin ring, state word | Original monoline role icons (no film-character art), colour per role, role descriptor + state ("Planning · UNKNOWN") | state text stays visible |
| 6 | Connector lines / context groups | Glowing curved connectors from nodes to grouped labels: Files/GitHub/Development, Data/Documents/Models, System/Security/Performance/Uptime, Internet categories, a purple ULTRON-to-Internet link | None except event links; ambient dashes | Static connector curves + label groups rendered **dim and marked not-observed**; a group/link lights up only when a real event names it (`target_node`) | **No "Logs / Patterns / Anomalies" label: spec forbids a visible LOGS section and a test enforces it. Tool labels (YouTube, Social Media...) are never shown as active/connected** |
| 7 | Internet planet | Textured Earth, category list, purple link via ULTRON, text "Online" | Flat blue sphere, "NO ACTIVITY OBSERVED" | Textured planet (gradients/blur); link only on observed traffic | **"Online" is not shown: configured/reachable is not observed traffic** |
| 8 | Top task-card row | Four cards (current task + progress, next in queue, shared context, external connection) and a Layout card | Absent | See section 3 | Card contents come only from the snapshot; no progress bar without a real progress field |
| 9 | Layout card | Check / X buttons | Absent (layout editor not built) | Card present but both buttons disabled, caption "layout editor not available" | Buttons must not imply an editor that does not exist |
| 10 | Left rail | Panel icons, drag handles, "+" buttons, "New chat" button, per-item icons and status dots, coloured project icons, agent avatars with provider label and dot | Text only | Add panel and list icons, status dots tied to real status, role avatars | **No provider next to a role (target: FURY=CLAUDE...) until observed: stays "PROVIDER UNKNOWN". No drag handles or "+" / "New chat" until they do something** |
| 11 | Right rail | Activity rows with coloured role names and a WORKING chip; Approvals rows with ring marker and green/blue/red icon buttons | Plain rows; outline buttons | Coloured role names, status chip from derived CORE state, coloured icon buttons (dimmed when disabled) | Buttons remain disabled/local-only exactly as now |
| 12 | Resources | Coloured gauge rings, thermometer icon, external-disk block with icon | Dim rings, no icons | Per-metric colour, thermometer and disk icons, same UNKNOWN rules | colour is decoration, not a status |
| 13 | Models / limits | Per-provider colour dot and bar | Status-coloured dot | Provider accent on the name, status stays in dot + text | equal provider treatment kept |
| 14 | Top bar | Logo mark, coloured source chips (GPT green, CODEX purple, CLAUDE gold), shield badge, clock **and date**, bell, settings, user menu | Plain chips, clock only | Brand mark, provider accent colours, shield icon, add date | **No "Admin", bell or settings: there is no user/notification system. ULTRON stays NOT CONNECTED, not "ACTIVE"** |
| 15 | Density / contrast | Brighter, larger body text, no empty cards | Dimmer small text; rails mostly empty without data | Raise contrast/size within the 1280x720 fit tests | emptiness without data is honest and stays |
| 16 | Language | Czech labels on five cards/panels (AKTUALNI UKOL, DALSI V FRONTE, SDILENY KONTEXT, EXTERNI PRIPOJENI, SYSTEMOVE ZDROJE, AI MODELY / LIMITY) | English | **Owner decision needed**; default stays English per the spec's label list | - |

Per-size notes: at **1280x720** the CORE is much smaller than the target and the centre column has wide empty margins; at **1920x1080** the structure reads closest to the target; at **2560x1440** text is proportionally small, rails are very empty and the CORE is under-scaled.

## 3. Task-card row: truthful content (planned)
| Card | Source | When there is no data |
|---|---|---|
| CURRENT TASK | first `active` task in the snapshot; progress bar only if the record carries a real numeric progress | "NO ACTIVE TASK OBSERVED" / UNKNOWN |
| NEXT IN QUEUE | first `queued` task + queued count | "NONE OBSERVED" / UNKNOWN |
| SHARED CONTEXT | Obsidian/WONG projection status from the existing memory/adapter evidence | "NOT CONFIGURED" |
| EXTERNAL CONNECTION | Internet = observed traffic only; allowed targets only if provided | "NO ACTIVITY OBSERVED" |
| LAYOUT | static card, disabled check/X | "editor not available" |

## 4. Never copied from the target
Telemetry (72/64/58/84 %, 46 C, 2 TB / 1.31 TB, limits 200K/187K/165K), activity-row text and times, chat and project names, the role-to-provider mapping, "ULTRON SECURITY: ACTIVE", "INTERNET: Online", "Admin", the date/time, and the Czech wording of task text. They are illustrative.

## 5. Implementation plan and checks (not started)
Order: A background + vortex + rings + CORE scale; B role icons + context groups + connectors; C task-card row + Layout card; D rail/resources/limits/top-bar styling; E QA. Guards: the existing shell/core/chat/system E2E suites must keep passing (panel overlap, gutters, centring, forbidden text DONE/LOGS/version, UNKNOWN rules); new E2E for each card's no-data state and for "connector/label inactive without an event". Parity is then judged by a new side-by-side review at three sizes by the owner; GAP-5 closes only on the owner's explicit acceptance.
Estimated effort: about $12-15 of the remaining budget (rough, not observed spend). It touches the layout grid (new row), so a backup tag is required first.


## 6. Implementation and post-implementation review (backup tag: backup/pre-visual-parity at 6decc0a)

### 6.1 Correction of an earlier conclusion
Item 4 above said the CORE was under-scaled. That was wrong. Measured on the real UI (outer ULTRON ring height / viewport height) against an estimate from the target image (~48%, +-3%):

| Size | Ring px | Ring / viewport | Stage (WxH) | Agent name px on screen |
|---|---|---|---|---|
| 1280x720 | 285 | 40% | 734x348 | 11.6 |
| 1920x1080 | 487 | 45% | 1198x587 | 15.4 |
| 2560x1440 | 660 | 46% | 1598x796 | 20.8 |

So the CORE is close to the target's proportion at 1920 and 2560 and about 17% smaller than the target's at 1280x720, where the new card row takes vertical space. An independent reviewer's claim that the core is "about half" the target's size is not supported by these measurements.

### 6.2 What was done, per difference (# = row in section 2)
| # | Status | What changed |
|---|---|---|
| 1 | Largely closed | Seeded procedural starfield (340 stars, 14 glow stars), 6 blurred nebula blobs and dust bands behind everything; faint circuit kept. Static, decorative. |
| 2 | Partly closed | Spiral arms (6 x glow+line), black horizon and glowing photon ring replace the flat disk. It reads as a spiral black hole, not as the target's detailed galaxy render; arms only spin in IDLE/WORKING and are dim + grayscale in UNKNOWN/OFFLINE. |
| 3 | Partly closed | Gradient glowing orbit ring with ring nodes, outer and inner rings, glowing ULTRON ring. ULTRON ring colour is still state-driven (gray without an ULTRON event) - deliberate. |
| 4 | Corrected | See 6.1. |
| 5 | Partly closed | Original monoline role icons in role-coloured glowing rings, "Descriptor · STATE" captions. Not the target's illustrated avatars (deliberately not film-character art). |
| 6 | Partly closed | 16 context labels in four groups around the orbit plus dashed connector curves, all dim "not observed" until a fresh, trusted event names them (`target_node`); event links remain separate and brighter. No Logs/Patterns/Anomalies label (spec). |
| 7 | Mostly closed | Textured planet with aura and rim glow. No "Online". Active only via an observed event. |
| 8 | Closed (with truthful content) | Four task cards: current task (no progress bar unless a numeric `progress_percent` 0..100 exists), next in queue (+ count), shared context (real memory-status evidence: READABLE / UNAVAILABLE / AUTH REQUIRED / UNKNOWN), external connection ("INTERNET / NO ACTIVITY OBSERVED" unless observed). |
| 9 | Closed (as a disabled card) | LAYOUT card with disabled check and X, titled and captioned "editor not available". |
| 10 | Partly closed | Panel icons, chat/folder icons (project icons coloured), role avatars in Agents, observed-state text per role when observed. Not done on purpose: highlighted "selected" rows, "New chat", "+" buttons, drag handles, provider next to a role. |
| 11 | Mostly closed | Role names coloured in Activity, derived-state chip (WAITING/WORKING/...), approval rows with provider ring marker and coloured icon buttons (disabled ones dimmed). |
| 12 | Mostly closed | Per-metric gauge colours and label icons (decorative, not status). |
| 13 | Closed | Provider accent colours on names; status stays in dot + text. |
| 14 | Partly closed | Brand mark, shield icon, provider identity dots, clock + date. Not added: Admin, bell, settings. |
| 15 | Partly closed | Text-halo for legibility over rings, higher contrast for ghost text; larger caption fonts at heights <= 800px. |
| 16 | Decided | English labels throughout (owner decision). |

### 6.3 Truthfulness rules kept, with the tests that enforce them (`tests/e2e/visual.e2e.mjs`, `tests/core.test.mjs`, `tests/ops.test.mjs`)
No target numbers/names/statuses appear as data (live and fixture); bare "Online" and "INTERNET: ACTIVE/Online" never appear without an observed event; Layout buttons disabled; no progress bar without `progress_percent`; task cards UNKNOWN without trusted evidence; context labels light only from fresh, trusted, named events (and never "logs"); ULTRON stays NOT CONNECTED with a gray ring; agents' provider stays UNKNOWN; identity colours never equal status colours; unobserved roles show a hollow neutral dot; equal visual weight of GPT/CODEX/CLAUDE (chip, approval and limit row sizes).

### 6.4 Independent UX review (subagent, evidence from images, source not read)
Verdict: "Not at parity ... recognisably the same family, about 60-65% of the visual impact"; direction acceptable if the owner accepts the deliberate truthful-state differences. That percentage is the reviewer's subjective estimate, not a measurement. Findings I **accepted and fixed**: contradictory green dots beside "PROVIDER UNKNOWN" (now hollow neutral dots, plus observed state in words); identity colours colliding with status colours (GPT mint = ok, CLAUDE amber = warn; palettes changed); label collisions while an agent travels (caption hidden while moving); empty-glass rails stretching (panels now take natural height and bottom panels anchor to the composer line); low-contrast ghost text. Findings I **did not accept**: "CORE about half the size" (contradicted by 6.1); highlighted selected rows / "New chat" (no such concept exists); larger 56-64px gauges at 1280 (would shrink the CORE further).

### 6.5 Remaining differences an owner will still see (not hidden)
1. Vortex and nebula are procedural SVG, noticeably simpler than the target's rendered artwork; ring glow is weaker.
2. Rails look sparse whenever there is no data (live mode): CHATS, PROJECTS and ACTIVITY show a few lines. The target's density comes from illustrative content that must not be invented.
3. At 1280x720 the CORE is ~40% of the viewport height (target ~48%), gauges are small (~35px), some card sublines are ellipsized.
4. Role icons are abstract line icons, not illustrated avatars; no selection highlight; no Admin/bell/settings; no "+"/drag-handle controls; Layout card is inert.
5. While an agent travels beside a neighbour (e.g. to Obsidian), its caption is hidden to avoid overlap; rings and labels can still touch at 1280.
6. Gauges and bars in the fixture look like data because they are synthetic fixture values (clearly labelled FIXTURE); in live mode they read UNKNOWN.
7. Not run: Windows browser at the real monitor; owner side-by-side acceptance.

Screenshots for this review: `docs/hive/screenshots/compare-after-{1280,1920,2560}.png` (target vs fixture), `live-after-*.png` (live adapter, all UNKNOWN), `parity-*.png` (approval scenario, from the E2E).
