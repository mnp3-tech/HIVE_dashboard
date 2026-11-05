# HIVE integrations — status and plan (read-only phase)

Evidence labels: VERIFIED (Linux container tests), USER-REPORTED (owner's Windows runs), MOCKED (fixtures/mocks), NOT_VERIFIED, USER-CONFIGURED (needs an environment variable on the owner's PC), UNAVAILABLE.

| Integration | Built (read-only) | Evidence | To verify / next step | Not allowed in this phase |
|---|---|---|---|---|
| HIVE Core agents/workers/tasks/capabilities | Registry part `core` (workers, task instances, event-derived agents, providers, capabilities, connectors) | VERIFIED with MOCKED Core; live Core NOT_VERIFIED (not running anywhere tested) | run with HIVE Core up; agents need Core events naming `role_id` (no agents route exists) | any write, dispatch or approval |
| Primary/secondary classification | Always UNKNOWN | VERIFIED | needs an authoritative source or an approved configuration (owner decision) | inferring it |
| ULTRON | Evidence-based status on the existing state enum, 120 s expiry, recent observations, blocked connectors | VERIFIED (unit + fixture); live NOT_VERIFIED | needs live ULTRON events from Core | a second state machine; ACTIVE without a fresh trusted event |
| Creator Ops task catalog | `task_definitions` allowlist reader | VERIFIED with MOCKED SQLite; real DB NOT_VERIFIED, USER-CONFIGURED (`CREATOR_OPS_DB_PATH`) | on the owner's DB expect NOT_VERIFIED "schema unknown" unless a `task_definitions` table/view with `id, name` exists; the owner may add a read-only view | executing tasks; reading other tables |
| Obsidian | Metadata-only adapter (tags, backlinks, task counts, hashes) | VERIFIED with fixture vault; real vault NOT_VERIFIED, USER-CONFIGURED (`ORCHESTRATOR_VAULT_ROOT`) | owner runs `tools/registry_summary.py` with the variable set | note content, writes, renames, deletes |
| Skills | Two allowlisted roots by default | VERIFIED with fixtures; real roots NOT_VERIFIED | owner runs `tools/registry_summary.py` (GAP-10) | activation, import, execution |
| Prompts / bots | Formats defined, adapters built | VERIFIED with fixtures; USER-CONFIGURED (`HIVE_PROMPTS_ROOTS`, `HIVE_BOTS_ROOTS`), none configured | owner names roots | execution, exposing prompt bodies |
| Tool manifests | 6 repository manifests (`manifests/tools`), validation, `enabled=false` | VERIFIED | add manifests through review; execution is a later, separately approved phase | running tools; browser-to-shell |
| Self-evolution proposals | Display-only log with evidence hashes and statuses | VERIFIED | owner reviews statuses in a commit | any automatic change |

Previously hardcoded user paths in `server.py` (Creator Ops DB, Obsidian vault, project registry, self-evolution checkpoint, context sources) were removed: they now come only from `CREATOR_OPS_DB_PATH` and `ORCHESTRATOR_VAULT_ROOT`.

Next phases (each needs a backup tag and an explicit decision): live HIVE Core verification; a reviewed Creator Ops `task_definitions` view; owner-approved primary/secondary configuration; any execution path (separate design, approval, audit and sandbox).
