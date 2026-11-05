# Visual review vs `docs/assets/hive-dashboard-target.png` (GAP-5)

**Status: GAP-5 stays OPEN.** This document records the review; it does not claim parity. No code was changed for it.

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
| 4 | CORE scale | CORE + tool lists fill the whole centre (ring ~85% of centre height, lists inside the stage) | Ring ~60% of the centre; wide empty margins at 1920/2560, very small at 1280 | Re-proportion the stage viewBox/ring radius; place context labels inside the stage | none |
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
