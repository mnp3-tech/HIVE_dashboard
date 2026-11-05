# HIVE integrations — status and plan (read-only phase)

Evidence labels: VERIFIED (Linux container tests), USER-REPORTED (owner's Windows runs), MOCKED (fixtures/mocks), NOT_VERIFIED, USER-CONFIGURED (needs an environment variable on the owner's PC), UNAVAILABLE.

| Integration | Built (read-only) | Evidence | To verify / next step | Not allowed in this phase |
|---|---|---|---|---|
| HIVE Core agents/workers/tasks/capabilities | Registry part `core` (workers, task instances, event-derived agents, providers, capabilities, connectors) | VERIFIED with MOCKED Core; live Core NOT_VERIFIED (not running anywhere tested) | run with HIVE Core up; agents need Core events naming `role_id` (no agents route exists) | any write, dispatch or approval |
| Primary/secondary classification | Always UNKNOWN | VERIFIED | needs an authoritative source or an approved configuration (owner decision) | inferring it |
| ULTRON | Evidence-based status on the existing state enum, 120 s expiry, recent observations, blocked connectors | VERIFIED (unit + fixture); live NOT_VERIFIED | needs live ULTRON events from Core | a second state machine; ACTIVE without a fresh trusted event |
| Agent registry and lifecycle (P1.3) | `config/agents.json` + Core-observed identities; status and lifecycle; matrix | VERIFIED with MOCKED Core; live NOT_VERIFIED | needs Core events naming agents | start/stop/restart; inferring classification, capabilities or permissions |
| ULTRON control observations (P1.3) | agent/worker/task/connector/permission/failure/stability observations, `action: none` | VERIFIED with MOCKED Core | live Core events | any action, permission grant or skill activation |
| Internet health (P1.3) | `HIVE_INTERNET_PROBES` HTTPS HEAD probes | VERIFIED with a fake opener; USER-CONFIGURED; none configured | owner may list up to 5 public HTTPS URLs | default URLs, scanning, credentials, request bodies |
| Self-evolution v1 (P1.3) | proposal log v2, 3 fixture experiments, domain coverage | VERIFIED (deterministic, fixture only) | human review of EVO-0001..0003 in a commit | branches, patches, deployment, adoption |
| Creator Ops task catalog | `task_definitions` allowlist reader | VERIFIED with MOCKED SQLite; real DB NOT_VERIFIED, USER-CONFIGURED (`CREATOR_OPS_DB_PATH`) | on the owner's DB expect NOT_VERIFIED "schema unknown" unless a `task_definitions` table/view with `id, name` exists; the owner may add a read-only view | executing tasks; reading other tables |
| Obsidian | Metadata-only adapter (tags, backlinks, task counts, hashes) | VERIFIED with fixture vault; real vault NOT_VERIFIED, USER-CONFIGURED (`ORCHESTRATOR_VAULT_ROOT`) | owner runs `tools/registry_summary.py` with the variable set | note content, writes, renames, deletes |
| Skills | Two allowlisted roots by default | VERIFIED with fixtures; USER-REPORTED on Windows at ece0e43: `~/.codex/skills` 8 and `~/.agents/skills` 2 catalogued, 1 file not catalogued: `skill:agents/cinematic-web-design` resolves outside the root (link/junction), kept NOT_VERIFIED by owner decision | cataloguing it needs an explicit extra root in `HIVE_SKILLS_ROOTS` (owner decision); links are never followed | activation, import, execution |
| Prompts / bots | Formats defined, adapters built | VERIFIED with fixtures; USER-CONFIGURED (`HIVE_PROMPTS_ROOTS`, `HIVE_BOTS_ROOTS`), none configured | owner names roots | execution, exposing prompt bodies |
| Tool manifests | 6 repository manifests (`manifests/tools`), validation, `enabled=false` | VERIFIED; USER-REPORTED on Windows: 6 observed, all disabled | add manifests through review; execution is a later, separately approved phase | running tools; browser-to-shell |
| Self-evolution proposals | Display-only log with evidence hashes and statuses | VERIFIED | owner reviews statuses in a commit | any automatic change |

Previously hardcoded user paths in `server.py` (Creator Ops DB, Obsidian vault, project registry, self-evolution checkpoint, context sources) were removed: they now come only from `CREATOR_OPS_DB_PATH` and `ORCHESTRATOR_VAULT_ROOT`.

Next phases (each needs a backup tag and an explicit decision): live HIVE Core verification; a reviewed Creator Ops `task_definitions` view; owner-approved primary/secondary configuration; any execution path (separate design, approval, audit and sandbox).
