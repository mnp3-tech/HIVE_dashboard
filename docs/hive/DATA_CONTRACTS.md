# HIVE read-only registry — data contracts (schema `hive.readonly.v2`)

Machine-readable schema: `schemas/hive-readonly-v2.schema.json` (generated from `hive_registry.build_schema()`; a test fails if it drifts).
Served by `GET /api/registry` (all parts) and `GET /api/registry?part=<core|creator_ops|obsidian|catalogs|tools|proposals>` (one or more,
comma-separated; unknown parts → HTTP 400). There is no write route. The main snapshot (`/api/dashboard/snapshot`) never builds the registry.

## 1. Evidence envelope (every record)
| Field | Meaning |
|---|---|
| `kind` | connector, agent, role, worker, provider, capability, task_instance, catalog_item, ultron_status, proposal, evidence_record |
| `id` | stable registry id (`worker:<id>`, `skill:<root>/<relpath>`, `tool:<id>`, `creator-task:<id>`, `note:<relpath>`, …) |
| `source` / `source_id` | where the fact came from (`hive:/workers`, `skills:codex`, `creator-ops:task_definitions`, `fixture:…`) and its id there |
| `observed_at` | when the source was read (UTC ISO-8601) or the event timestamp; `null` when nothing was observed |
| `validity` → `display` | valid→OBSERVED, stale→STALE, unavailable→OFFLINE (transport down), inaccessible→UNAVAILABLE (configured path missing/unreadable), untrusted→UNVERIFIED, conflict→CONFLICT, unknown→UNKNOWN, auth_required→AUTH_REQUIRED, not_configured→NOT_CONNECTED, not_verified→NOT_VERIFIED (rejected path or unknown schema), fixture→FIXTURE |
| `reason` | why the state is what it is (always set when not OBSERVED) |
| `correlation_id` | only when the source supplies it; otherwise `null` (and listed in `not_provided`) |
| `schema_version` | `hive.readonly.v2` |
| `not_provided` | fields the source did not supply (rendered as a compact `?` with an accessible label) |

Section evidence (`{evidence, items}`): an aggregate over several sources has `display: null` (no state chip); each source reports its own connector.

## 2. Configuration (explicit only; nothing user-specific is committed)
| Variable | Used for | Unset | Rejected (NOT_VERIFIED) |
|---|---|---|---|
| `HIVE_SKILLS_ROOTS` (alias `HIVE_SKILL_ROOTS`) | skill roots, `os.pathsep`-separated, max 6 | allowlisted defaults `~/.codex/skills`, `~/.agents/skills` (an empty value disables them) | relative path, `..`, filesystem root, the bare home directory, a symlinked root |
| `HIVE_PROMPTS_ROOTS` | prompt roots | prompts NOT_CONNECTED | same rules |
| `HIVE_BOTS_ROOTS` | bot-manifest roots | bots NOT_CONNECTED | same rules |
| `ORCHESTRATOR_VAULT_ROOT` | Obsidian metadata (registry) and the existing project-registry / self-evolution / context projections in server.py | Obsidian NOT_CONNECTED; projections "not configured" | same rules |
| `CREATOR_OPS_DB_PATH` | Creator Ops counts (existing) and the `task_definitions` catalog | NOT_CONNECTED | relative path or `..` |
| `HIVE_TOOL_MANIFEST_DIR` | tool manifests | repository default `manifests/tools` | same rules as roots |
A configured path that is allowed but missing or unreadable is UNAVAILABLE. No fallback location is ever scanned.

## 3. Sources and their contracts
- **HIVE Core** (`core`): `/health` (preflight + connector), `/workers` or the labelled public `/ready` list, `/tasks?limit=100`, `/events?limit=50`, through the existing loopback transport and the snapshot preflight gate (Core down ⇒ one bounded call). **Agents**: HIVE Core has no agents route, so agents are only identities named by events (`role_id`); `classification` is always `UNKNOWN`. Providers link to a worker only when that worker's own `provider` field names them exactly. Duplicate worker ids ⇒ CONFLICT.
- **ULTRON** (`ultron_status`, part `core`): existing state enum (`hive_events.STATES`). OFFLINE (transport down) · UNKNOWN (no ULTRON event; silence is never ACTIVE) · UNVERIFIED (future/missing timestamps only) · ACTIVE (trusted event ≤ 120 s old, the `roleFresh` window) · STALE (older; state expires to UNKNOWN). Includes up to 10 recent ULTRON observations with trust and age.
- **Creator Ops** (`creator_ops`): SQLite `mode=ro`, timeout 2 s, **only** table or view `task_definitions` and **only** columns `id, name` (required) and `version, input_schema, output_schema, required_capabilities, risk_class, availability, updated_at` (optional), `LIMIT 501` (500 listed). Schemas are summarised (field names only). Missing table/columns ⇒ NOT_VERIFIED "schema unknown"; no other table is ever queried (a test traces every SQL statement). Tasks are never executed (`activation: cataloged_not_executable`).
- **Obsidian** (`obsidian`): root = `ORCHESTRATOR_VAULT_ROOT` only. Metadata per note: relative path, size, mtime, tags, outgoing links, backlinks (among scanned notes), open/done checkbox counts, sha256. **Never note content.** Bounds: 5000 notes scanned, 200 listed, 1 MB per note, 64 MB total, 3 s time budget (partial ⇒ UNVERIFIED with reason). Hidden folders, `.obsidian`, `.trash`, symlinks and anything resolving outside the root are skipped. A root without `.obsidian` (e.g. the `Orchestrator.inc` subfolder) is scanned but its vault identity is UNVERIFIED; parent folders are never read.
- **Skills / prompts / bots** (`catalogs`): skills = `*/SKILL.md` and `*/*/SKILL.md` (frontmatter `name, version, description, allowed-tools|tools, capabilities, permissions, risk`); prompts = `*.md|*.prompt|*.txt` up to one folder deep (optional frontmatter; body never returned); bots = `*/bot.json` or `*.bot.json` JSON objects (`name, version, description, runtime, tools, capabilities, permissions, risk`). Max 400 items per root, 256 KB per file, skill tree hash over ≤ 300 files / 20 MB. Hidden folders (except `.system`) and symlinks are skipped. `enabled` is always `false` (a file asking for `enabled: true` is noted and ignored). `risk_class` is declared, or derived from declared tools (`risk_basis: derived_from_declared_tools`; shell/write/network-like tools ⇒ high), or `unclassified`. Same name in several locations ⇒ CONFLICT. Descriptions are plain text, secrets redacted, rendered escaped (no markup, images, scripts or links).
- **Tool manifests** (`tools`): `*.json` in the manifest directory, ≤ 100 files, ≤ 64 KB each. Required: `id, name, version, transport (cli|http-loopback), input_schema, output_schema, capabilities, required_permissions, risk (low|medium|high), timeout_s (1–120), output_limit_bytes (1–1048576)`; `cli` needs a fixed `argv` list without shell metacharacters; `http-loopback` needs a loopback endpoint. Invalid ⇒ NOT_VERIFIED with the reasons; duplicate ids ⇒ CONFLICT; `enabled` is always `false`. The registry never runs a tool and there is no browser-to-shell path.
- **Proposals** (`proposals`): `docs/hive/proposals/proposals-v1.json`. Each cites a GAP row by exact sha256. Status = the reviewed value in the file (`PENDING_HUMAN_REVIEW | APPROVED_FOR_PROTOTYPE | REJECTED`; anything else ⇒ pending) unless the GAP row changed (STALE) or the proposal expired (EXPIRED). No status triggers any action; changes happen only through a reviewed commit.

## 4. Isolation, timeouts and caching
Each part runs in its own worker thread with its own timeout (core 6 s, creator_ops 3 s, obsidian 5 s, catalogs 5 s, tools 2 s, proposals 2 s) and cache TTL (3 / 30 / 60 / 60 / 60 / 10 s). A part that times out or raises is reported as `connector:part:<name>` OFFLINE with the reason; the other parts are unaffected. The browser requests each part separately, so one slow source never blocks the rest of the view. Cached results are keyed by mode and configuration, and are deep-copied before use.

## 5. Fixture mode
`fixture_server.py` serves the same contract from `tests/fixtures/` (synthetic skills, prompts, bots, vault, tool manifests) and a temporary synthetic Creator Ops database. Every record and section is relabelled FIXTURE / `fixture:` and the fixture evidence log is separate from the live one.
