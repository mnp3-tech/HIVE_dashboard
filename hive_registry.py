"""Read-only HIVE registry: agents, roles, workers, providers, capabilities, tasks, ULTRON status, catalogs, proposals.

Every record carries one evidence envelope (id, kind, source, source_id, observed_at, validity, reason, correlation_id,
schema_version, display). Rules enforced here:
  * nothing is executed: no task, tool, bot, prompt or skill is run; skill files are only read (bounded) and hashed;
  * nothing is written to any external system; the only state is an in-memory, bounded evidence log;
  * nothing is invented: a field no source provides is null and listed in `not_provided`; primary/secondary
    classification is UNKNOWN until an authoritative source or approved configuration exists;
  * relationships are only explicit ones (a worker names its provider in its own record; no substring matching);
  * fixture mode re-labels every record as fixture so fixture data can never look live.
Stdlib only. The HIVE Core transport is injected (server.fetch_with_evidence), so this module never imports server.py.
"""
from __future__ import annotations

import collections
import hashlib
import json
import os
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import hive_events

SCHEMA_VERSION = "hive.readonly.v1"
ROOT = Path(__file__).resolve().parent
SCHEMA_PATH = ROOT / "schemas" / "hive-readonly-v1.schema.json"
PROPOSALS_PATH = ROOT / "docs" / "hive" / "proposals" / "proposals-v1.json"
ACCEPTANCE_PATH = ROOT / "docs" / "hive" / "ACCEPTANCE.md"

# Same windows as hive-core.js: roleFresh() 120 s for an observed role; classifyFreshness() 30 s live / 90 s offline.
ULTRON_FRESH_S = 120
HEARTBEAT_LIVE_S, HEARTBEAT_OFFLINE_S = 30, 90
FUTURE_TOLERANCE_S = 5

VALIDITIES = ("valid", "stale", "unavailable", "untrusted", "conflict", "unknown", "auth_required", "not_configured", "fixture")
DISPLAY = {"valid": "OBSERVED", "stale": "STALE", "unavailable": "OFFLINE", "untrusted": "UNVERIFIED", "conflict": "CONFLICT",
           "unknown": "UNKNOWN", "auth_required": "AUTH_REQUIRED", "not_configured": "NOT_CONNECTED", "fixture": "FIXTURE"}
ULTRON_DISPLAY = ("ACTIVE", "STALE", "UNKNOWN", "OFFLINE", "UNVERIFIED", "FIXTURE")

# Role catalog = the dashboard's own role definitions (CORE labels), not runtime evidence and not a provider mapping.
ROLE_CATALOG = (("ULTRON", "Orchestration / guardian"), ("FURY", "Planning"), ("SHURI", "Coding"), ("THOR", "Research"),
                ("VISION", "Analysis"), ("FALCON", "Monitoring"), ("UATU", "Watching"))
PROVIDER_CATALOG = (("gpt", "GPT"), ("claude", "CLAUDE"), ("codex", "CODEX"), ("local", "LOCAL"))

# Skill catalog bounds
SKILL_MD_MAX = 256 * 1024
TREE_MAX_FILES = 300
TREE_FILE_MAX = 2 * 1024 * 1024
TREE_TOTAL_MAX = 20 * 1024 * 1024
MAX_SKILLS_PER_ROOT = 400
# Obsidian bounds
NOTE_MAX_BYTES = 1024 * 1024
NOTES_LISTED_MAX = 200
NOTES_SCANNED_MAX = 5000
SKIP_DIRS = {".obsidian", ".trash", ".git", "node_modules", "__pycache__"}

_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_TAG = re.compile(r"(?:^|\s)#([A-Za-z][\w/-]{0,60})")
_WIKILINK = re.compile(r"\[\[([^\]|#]{1,200})")


# ------------------------------------------------------------------ envelope
def utc_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_ts(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def safe_text(value, limit=240):
    """Display text from a source: control characters stripped, secrets redacted, length bounded. Never interpreted."""
    if value in (None, ""):
        return None
    return hive_events.redact_summary(_CTRL.sub(" ", str(value)), limit)


def sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def envelope(kind, record_id, source, observed_at, validity, reason=None, source_id=None, correlation_id=None, **fields):
    if validity not in VALIDITIES:
        validity, reason = "unknown", f"unrecognised validity {validity!r}" + (f"; {reason}" if reason else "")
    rec = {"kind": kind, "id": str(record_id)[:160], "source": str(source)[:120], "source_id": None if source_id in (None, "") else str(source_id)[:160],
           "observed_at": observed_at, "validity": validity, "reason": reason, "correlation_id": correlation_id,
           "schema_version": SCHEMA_VERSION, "display": DISPLAY[validity]}
    rec.update(fields)
    rec.setdefault("not_provided", [])
    return rec


def section(items, source, observed_at, validity, reason=None):
    return {"evidence": {"source": source, "observed_at": observed_at, "validity": validity, "reason": reason, "display": DISPLAY.get(validity, "UNKNOWN")}, "items": items}


def freshness(ts, now, live_s=HEARTBEAT_LIVE_S, offline_s=HEARTBEAT_OFFLINE_S):
    """Mirror of hive-core.js classifyFreshness(): live / stale / offline / unknown (missing or future timestamp)."""
    dt = parse_ts(ts)
    if dt is None:
        return "unknown"
    age = (now - dt).total_seconds()
    if age < -FUTURE_TOLERANCE_S:
        return "unknown"
    return "live" if age <= live_s else "stale" if age <= offline_s else "offline"


# ------------------------------------------------------------------ HIVE Core adapter
def _unwrap(raw):
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for key in ("items", "workers", "tasks", "events", "data"):
            if isinstance(raw.get(key), list):
                return raw[key]
    return []


def _str_list(value, limit=40):
    if not isinstance(value, list):
        return None
    out = [str(v)[:80] for v in value if isinstance(v, str) and v.strip()]
    return out[:limit]


class HiveCoreRegistryAdapter:
    """Read-only view of HIVE Core: /health (preflight + connector), /workers (or the public /ready list), /tasks, /events.
    `fetch(path) -> (raw, evidence)` is server.fetch_with_evidence; inside server.core_snapshot_scope() an unreachable
    Core costs one bounded preflight, not one timeout per call."""

    def __init__(self, fetch, bucket=lambda s: str(s).lower(), now=None):
        self.fetch, self.bucket = fetch, bucket
        self.now = now or (lambda: datetime.now(timezone.utc))

    def read(self):
        now = self.now()
        health_raw, health_ev = self.fetch("/health")
        connector = envelope("connector", "connector:hive-core", health_ev.get("source", "hive:/health"), health_ev.get("observed_at"),
                             health_ev.get("validity", "unknown"), health_ev.get("reason"), name="HIVE Core", transport="http loopback")
        reachable = health_ev.get("validity") in ("valid", "auth_required")
        workers_raw, workers_ev = self.fetch("/workers")
        worker_source = workers_ev
        if workers_ev.get("validity") != "valid":
            ready_raw, ready_ev = self.fetch("/ready")
            ready_workers = ready_raw.get("workers") if isinstance(ready_raw, dict) else None
            if ready_ev.get("validity") == "valid" and isinstance(ready_workers, list) and ready_workers:
                workers_raw = ready_workers
                worker_source = dict(ready_ev, source="hive:/ready (public worker-availability list)",
                                     reason=f"Authenticated /workers is {workers_ev.get('validity')}: {workers_ev.get('reason')}; public /ready list shown instead.")
        tasks_raw, tasks_ev = self.fetch("/tasks?limit=100")
        events_raw, events_ev = self.fetch("/events?limit=50")
        workers = self._workers(workers_raw, worker_source, now) if worker_source.get("validity") == "valid" else []
        tasks = self._tasks(tasks_raw, tasks_ev) if tasks_ev.get("validity") == "valid" else []
        events = self._events(events_raw) if events_ev.get("validity") == "valid" else []
        return {"connector": connector, "reachable": reachable, "now": now,
                "workers": section(workers, worker_source.get("source", "hive:/workers"), worker_source.get("observed_at"), worker_source.get("validity", "unknown"), worker_source.get("reason")),
                "tasks": section(tasks, tasks_ev.get("source", "hive:/tasks"), tasks_ev.get("observed_at"), tasks_ev.get("validity", "unknown"), tasks_ev.get("reason")),
                "events": events, "events_evidence": events_ev}

    def _workers(self, raw, ev, now):
        out, seen = [], {}
        for item in _unwrap(raw):
            if not isinstance(item, dict):
                continue
            wid = item.get("id") or item.get("worker_id")
            if not wid:
                continue
            wid = str(wid)[:120]
            provider = item.get("provider") if isinstance(item.get("provider"), str) and item["provider"].strip().lower() not in ("", "unknown") else None
            model = item.get("model") if isinstance(item.get("model"), str) and item["model"].strip().lower() not in ("", "unknown") else None
            heartbeat = next((item.get(k) for k in ("last_seen", "heartbeat_at", "updated_at") if isinstance(item.get(k), str)), None)
            caps = _str_list(item.get("capabilities"))
            current = item.get("current_task") or item.get("task_id")
            np = [k for k, v in (("provider", provider), ("model", model), ("capabilities", caps), ("current_task", current), ("heartbeat", heartbeat)) if v in (None, [])]
            rec = envelope("worker", f"worker:{wid}", ev.get("source"), ev.get("observed_at"), "valid", None, source_id=wid,
                           correlation_id=item.get("correlation_id") if isinstance(item.get("correlation_id"), str) else None,
                           name=safe_text(item.get("name") or wid, 80), provider=safe_text(provider, 40), model=safe_text(model, 80),
                           status_raw=safe_text(item.get("status"), 40), status=self.bucket(item.get("status", "unknown")),
                           capabilities=caps or [], current_task=None if current is None else str(current)[:120],
                           heartbeat=heartbeat, freshness=freshness(heartbeat, now), not_provided=np)
            if wid in seen:  # duplicate identity from one source: keep the first, flag both as conflict
                seen[wid]["validity"], seen[wid]["display"], seen[wid]["reason"] = "conflict", DISPLAY["conflict"], "duplicate worker id in the source response"
                continue
            seen[wid] = rec
            out.append(rec)
        return out

    def _tasks(self, raw, ev):
        out = []
        for item in _unwrap(raw):
            if not isinstance(item, dict):
                continue
            tid = item.get("id") or item.get("task_id")
            if not tid:
                continue
            assigned = item.get("worker_id") or item.get("preferred_worker")
            req = _str_list(item.get("required_capabilities"))
            np = [k for k, v in (("assigned_worker", assigned), ("required_capabilities", req), ("correlation_id", item.get("correlation_id"))) if v in (None, [])]
            out.append(envelope("task_instance", f"task:{str(tid)[:120]}", ev.get("source"), ev.get("observed_at"), "valid", None, source_id=str(tid)[:120],
                                correlation_id=item.get("correlation_id") if isinstance(item.get("correlation_id"), str) else None,
                                title=safe_text(item.get("title"), 160), status_raw=safe_text(item.get("status"), 40), status=self.bucket(item.get("status", "unknown")),
                                assigned_worker=None if assigned is None else str(assigned)[:120], project_id=None if item.get("project_id") is None else str(item.get("project_id"))[:120],
                                required_capabilities=req or [], created_at=item.get("created_at") if isinstance(item.get("created_at"), str) else None,
                                updated_at=item.get("updated_at") if isinstance(item.get("updated_at"), str) else None, not_provided=np))
        return out

    @staticmethod
    def _events(raw):
        return [e for e in (hive_events.contract_event(item, {"source": "hive:/events"}) for item in _unwrap(raw)[:200]) if e]


def event_trust(event, now):
    """'trusted' only with a parseable, non-future timestamp; otherwise 'untrusted'."""
    dt = parse_ts(event.get("timestamp"))
    if dt is None:
        return "untrusted", "event has no parseable timestamp", None
    if (dt - now).total_seconds() > FUTURE_TOLERANCE_S:
        return "untrusted", "event timestamp is in the future", dt
    return "trusted", None, dt


def observed_agents(events, events_ev, now):
    """Agents = execution identities that HIVE Core events actually named (role_id). Never from the role catalog."""
    latest = {}
    for ev in events:
        role = (ev.get("role_id") or "").strip()
        if not role:
            continue
        trust, why, dt = event_trust(ev, now)
        prev = latest.get(role.upper())
        if prev is None or (dt and (prev[2] is None or dt > prev[2])):
            latest[role.upper()] = (ev, trust, dt, why)
    out = []
    for key, (ev, trust, dt, why) in sorted(latest.items()):
        age = (now - dt).total_seconds() if dt else None
        validity = "untrusted" if trust != "trusted" else ("valid" if age is not None and age <= ULTRON_FRESH_S else "stale")
        reason = why if trust != "trusted" else (None if validity == "valid" else f"last event is {int(age)} s old (window {ULTRON_FRESH_S} s)")
        np = ["classification"] + [k for k in ("provider", "model", "task_id") if not ev.get(k)]
        out.append(envelope("agent", f"agent:{key}", "hive:/events", ev.get("timestamp"), validity, reason, source_id=ev.get("role_id"),
                            correlation_id=ev.get("correlation_id"), role_id=ev.get("role_id"), classification="UNKNOWN",
                            classification_reason="No authoritative primary/secondary source or approved configuration exists.",
                            provider=ev.get("provider"), model=ev.get("model"), last_state=ev.get("state"), last_event_id=ev.get("event_id"),
                            last_event_type=ev.get("event_type"), task_id=ev.get("task_id"), not_provided=np))
    return out


def ultron_status(core, now):
    """Evidence-based ULTRON status on the existing state contract (hive_events.STATES).
    OFFLINE: Core transport unavailable. UNKNOWN: no ULTRON event. UNVERIFIED: only untrusted ULTRON events.
    ACTIVE: a trusted ULTRON event within ULTRON_FRESH_S. STALE: the latest trusted ULTRON event is older. Silence is never ACTIVE."""
    conn = core["connector"]
    base = dict(kind="ultron_status", id="ultron", schema_version=SCHEMA_VERSION, correlation_id=None, source_id=None,
                freshness_window_s=ULTRON_FRESH_S, last_event_id=None, last_event_type=None, last_state=None, age_s=None, not_provided=[])
    if not core["reachable"]:
        return dict(base, display="OFFLINE", state="OFFLINE", source=conn["source"], observed_at=None, validity="unavailable",
                    reason=f"HIVE Core transport unavailable: {conn['reason']}")
    if core["events_evidence"].get("validity") != "valid":
        return dict(base, display="UNKNOWN", state="UNKNOWN", source="hive:/events", observed_at=None, validity=core["events_evidence"].get("validity", "unknown"),
                    reason=f"HIVE Core events unavailable: {core['events_evidence'].get('reason')}")
    ultron = [e for e in core["events"] if (e.get("role_id") or "").upper() == "ULTRON"]
    if not ultron:
        return dict(base, display="UNKNOWN", state="UNKNOWN", source="hive:/events", observed_at=None, validity="unknown",
                    reason="No ULTRON event observed in the latest HIVE Core events; silence is not ACTIVE.")
    judged = [(e, *event_trust(e, now)) for e in ultron]
    trusted = [j for j in judged if j[1] == "trusted"]
    if not trusted:
        e = judged[0][0]
        return dict(base, display="UNVERIFIED", state="UNKNOWN", source="hive:/events", observed_at=e.get("timestamp"), validity="untrusted",
                    reason=f"Only untrusted ULTRON events: {judged[0][2]}", last_event_id=e.get("event_id"), last_event_type=e.get("event_type"),
                    correlation_id=e.get("correlation_id"))
    e, _, _, dt = max(trusted, key=lambda j: j[3])
    age = (now - dt).total_seconds()
    fresh = age <= ULTRON_FRESH_S
    return dict(base, display="ACTIVE" if fresh else "STALE", state=e.get("state") if fresh else "UNKNOWN", source="hive:/events",
                observed_at=e.get("timestamp"), validity="valid" if fresh else "stale",
                reason=None if fresh else f"Latest ULTRON event is {int(age)} s old (window {ULTRON_FRESH_S} s); state expired to UNKNOWN.",
                last_event_id=e.get("event_id"), last_event_type=e.get("event_type"), last_state=e.get("state"), age_s=round(age, 1),
                correlation_id=e.get("correlation_id"))


# ------------------------------------------------------------------ catalogs
def role_catalog(observed_at):
    return [envelope("role", f"role:{rid}", "local:dashboard-role-catalog", observed_at, "valid",
                     "Dashboard role definition (catalog), not runtime evidence; no provider is mapped to a role.",
                     source_id=rid, role_id=rid, descriptor=desc, classification="UNKNOWN", provider=None,
                     not_provided=["classification", "provider"]) for rid, desc in ROLE_CATALOG]


def provider_catalog(workers, observed_at):
    out = []
    for pid, label in PROVIDER_CATALOG:
        named = [w["source_id"] for w in workers if isinstance(w.get("provider"), str) and w["provider"].strip().lower() == pid]
        out.append(envelope("provider", f"provider:{pid}", "local:provider-catalog", observed_at, "valid" if named else "unknown",
                            None if named else "No worker record names this provider explicitly; runtime status unknown.",
                            source_id=pid, label=label, observed_workers=named, not_provided=[] if named else ["observed_workers"]))
    return out


def capability_index(workers, skills):
    caps = collections.OrderedDict()
    for rec, source in [(w, w["source"]) for w in workers] + [(s, s["source"]) for s in skills]:
        for cap in rec.get("capabilities") or rec.get("declared_capabilities") or []:
            entry = caps.setdefault(cap, {"declared_by": [], "sources": set(), "observed_at": rec.get("observed_at")})
            entry["declared_by"].append(rec["id"])
            entry["sources"].add(source)
    return [envelope("capability", f"capability:{name}", ", ".join(sorted(v["sources"])), v["observed_at"], "valid",
                     "Declared by the listed records; a declaration is not a permission.", source_id=name, name=name[:80],
                     declared_by=v["declared_by"][:50]) for name, v in caps.items()]


def _frontmatter(text):
    """Minimal, non-executing frontmatter reader: `key: value` lines and `- item` lists between the first two '---' lines."""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    meta, key = {}, None
    for line in text[3:end].splitlines()[:200]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = re.match(r"^([A-Za-z][\w-]{0,40}):\s*(.*)$", line)
        if m:
            key, val = m.group(1).lower(), m.group(2).strip()
            if val.startswith("[") and val.endswith("]"):
                meta[key] = [v.strip().strip("'\"") for v in val[1:-1].split(",") if v.strip()]
            elif val:
                meta[key] = val.strip("'\"")
            else:
                meta[key] = []
            continue
        m = re.match(r"^\s+-\s+(.+)$", line)
        if m and key and isinstance(meta.get(key), list):
            meta[key].append(m.group(1).strip().strip("'\""))
    return meta


def _tree_hash(directory: Path, root: Path):
    """Bounded, symlink-free content hash of a directory: sha256 over 'relpath\\0size\\0sha256' lines. Files are read, never run."""
    lines, total, count, truncated = [], 0, 0, False
    for path in sorted(directory.rglob("*")):
        if count >= TREE_MAX_FILES:
            truncated = True
            break
        if path.is_symlink() or not path.is_file():
            continue
        try:
            path.resolve().relative_to(root)
        except ValueError:
            continue
        size = path.stat().st_size
        rel = path.relative_to(directory).as_posix()
        if size > TREE_FILE_MAX or total + size > TREE_TOTAL_MAX:
            lines.append(f"{rel}\0{size}\0oversize")
            truncated = True
        else:
            lines.append(f"{rel}\0{size}\0{hashlib.sha256(path.read_bytes()).hexdigest()}")
            total += size
        count += 1
    return sha256_text("\n".join(lines)), count, truncated


class SkillCatalogAdapter:
    """Allowlisted, read-only skill roots. Discovery is not activation: every item is enabled=false."""

    def __init__(self, roots, now=None, source_prefix="skills"):
        self.roots = roots  # [(label, path)]
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.prefix = source_prefix

    def read(self):
        observed = utc_iso(self.now())
        connectors, items = [], []
        for label, raw_path in self.roots:
            src = f"{self.prefix}:{label}"
            root = Path(raw_path).expanduser()
            if not root.is_dir() or root.is_symlink():
                connectors.append(envelope("connector", f"connector:{src}", src, None, "not_configured", f"Allowlisted root not present on this host: {root}",
                                           name=f"Skill root {label}", transport="filesystem read-only", root=str(root)))
                continue
            root = root.resolve()
            found, errors = 0, 0
            for skill_md in sorted(root.glob("*/SKILL.md")) + sorted(root.glob("*/*/SKILL.md")):
                if found >= MAX_SKILLS_PER_ROOT:
                    break
                skill_dir = skill_md.parent
                rel_parts = skill_dir.relative_to(root).parts
                if any(p.startswith(".") and p != ".system" for p in rel_parts) or skill_md.is_symlink() or skill_dir.is_symlink():
                    continue
                try:
                    skill_md.resolve().relative_to(root)
                    if skill_md.stat().st_size > SKILL_MD_MAX:
                        raise ValueError(f"SKILL.md larger than {SKILL_MD_MAX} bytes")
                    text = skill_md.read_text(encoding="utf-8", errors="replace")
                    meta = _frontmatter(text)
                    tree, nfiles, truncated = _tree_hash(skill_dir, root)
                except (OSError, ValueError) as error:
                    errors += 1
                    items.append(envelope("catalog_item", f"skill:{label}/{'/'.join(rel_parts)}", src, observed, "unknown", f"unreadable: {error}",
                                          source_id="/".join(rel_parts), item_type="skill", name="/".join(rel_parts), enabled=False,
                                          activation="discovered_not_activated", not_provided=["name", "version", "content_hash"]))
                    continue
                caps = meta.get("allowed-tools") or meta.get("capabilities") or meta.get("tools")
                caps = [str(c)[:60] for c in caps] if isinstance(caps, list) else ([c.strip()[:60] for c in str(caps).split(",") if c.strip()] if caps else [])
                perms = meta.get("permissions")
                version = meta.get("version") if isinstance(meta.get("version"), str) else None
                name = meta.get("name") if isinstance(meta.get("name"), str) else None
                np = [k for k, v in (("name", name), ("version", version), ("declared_capabilities", caps), ("required_permissions", perms), ("risk_class", None)) if v in (None, [], "")]
                items.append(envelope("catalog_item", f"skill:{label}/{'/'.join(rel_parts)}", src, observed, "valid",
                                      "Discovered read-only; not activated, not executed.", source_id="/".join(rel_parts), item_type="skill",
                                      name=safe_text(name or skill_dir.name, 80), version=safe_text(version, 40), description=safe_text(meta.get("description"), 240),
                                      content_hash=sha256_text(text), tree_hash=tree, file_count=nfiles, tree_truncated=truncated,
                                      declared_capabilities=caps[:40], required_permissions=_str_list(perms) if isinstance(perms, list) else (safe_text(perms, 120) if perms else None),
                                      risk_class=None, enabled=False, activation="discovered_not_activated", not_provided=np))
                found += 1
            connectors.append(envelope("connector", f"connector:{src}", src, observed, "valid" if not errors else "conflict",
                                       f"{found} skill(s) catalogued" + (f"; {errors} unreadable" if errors else ""), name=f"Skill root {label}",
                                       transport="filesystem read-only", root=str(root)))
        return connectors, items


class ObsidianAdapter:
    """Metadata-only, read-only vault view. Root only from the ORCHESTRATOR_VAULT_ROOT environment variable (no hardcoded path),
    and only if it is a directory containing `.obsidian`. Note content is never returned; tags/links are derived counts."""

    def __init__(self, root, now=None, source="obsidian"):
        self.root, self.source = root, source
        self.now = now or (lambda: datetime.now(timezone.utc))

    def read(self):
        observed = utc_iso(self.now())
        if not self.root:
            return envelope("connector", "connector:obsidian", self.source, None, "not_configured",
                            "ORCHESTRATOR_VAULT_ROOT is not configured in the environment; Obsidian is NOT_VERIFIED.", name="Obsidian vault",
                            transport="filesystem read-only"), []
        root = Path(self.root).expanduser()
        if not root.is_dir() or root.is_symlink() or not (root / ".obsidian").is_dir():
            return envelope("connector", "connector:obsidian", self.source, None, "unavailable",
                            "Configured vault root is missing, a symlink, or has no .obsidian folder.", name="Obsidian vault",
                            transport="filesystem read-only"), []
        root = root.resolve()
        notes, scanned, skipped = [], 0, 0
        for path in sorted(root.rglob("*.md")):
            if scanned >= NOTES_SCANNED_MAX:
                break
            rel = path.relative_to(root)
            if any(part in SKIP_DIRS or part.startswith(".") for part in rel.parts[:-1]) or path.is_symlink():
                continue
            try:
                path.resolve().relative_to(root)
            except ValueError:
                skipped += 1
                continue
            scanned += 1
            if len(notes) >= NOTES_LISTED_MAX:
                continue
            try:
                st = path.stat()
                if st.st_size > NOTE_MAX_BYTES:
                    tags, links, digest = [], 0, None
                else:
                    data = path.read_bytes()
                    text = data.decode("utf-8", "replace")
                    tags = sorted({t for t in _TAG.findall(text)})[:20]
                    links, digest = len(_WIKILINK.findall(text)), "sha256:" + hashlib.sha256(data).hexdigest()
            except OSError as error:
                skipped += 1
                notes.append(envelope("catalog_item", f"note:{rel.as_posix()}", self.source, observed, "unknown", f"unreadable: {error}",
                                      source_id=rel.as_posix(), item_type="note", name=safe_text(rel.as_posix(), 160), enabled=False, activation="metadata_only"))
                continue
            notes.append(envelope("catalog_item", f"note:{rel.as_posix()}", self.source, observed, "valid", "Metadata only; note content is not returned.",
                                  source_id=rel.as_posix(), item_type="note", name=safe_text(rel.as_posix(), 160), size=st.st_size,
                                  modified_at=utc_iso(datetime.fromtimestamp(st.st_mtime, timezone.utc)), tags=[safe_text(t, 60) for t in tags],
                                  outgoing_links=links, content_hash=digest, enabled=False, activation="metadata_only"))
        conn = envelope("connector", "connector:obsidian", self.source, observed, "valid",
                        f"{scanned} note(s) scanned, {len(notes)} listed (cap {NOTES_LISTED_MAX})" + (f", {skipped} skipped" if skipped else ""),
                        name="Obsidian vault", transport="filesystem read-only", vault_name=root.name)
        return conn, notes


def creator_ops_catalog(status: dict, observed_fallback):
    """Wraps the existing counts-only Creator Ops adapter. The task catalog is NOT read: its schema is not verified and reading
    row content would widen the adapter's privacy boundary, which needs the owner's approval."""
    validity = status.get("validity", "unknown")
    conn = envelope("connector", "connector:creator-ops", "creator-ops:sqlite (read-only)", status.get("last_observed_at"), validity,
                    status.get("reason"), name="Creator Ops", transport="sqlite mode=ro", table_counts=status.get("counts") or {})
    return conn, section([], "creator-ops:sqlite (read-only)", None, "not_configured",
                         "Task catalog NOT_VERIFIED: the task-definition schema is unknown here and row content is deliberately not read (counts only).")


def tool_catalog(tools, observed_at):
    """Configured tool definitions only. The registry never runs a tool, so availability is not verified here."""
    return [envelope("catalog_item", f"tool:{t['id']}", "local:server-config", observed_at, "unknown",
                     "Configured, not executed by the registry; availability NOT_VERIFIED.", source_id=t["id"], item_type="tool",
                     name=t["name"], transport=t["transport"], target=t["target"], enabled=False, activation="configured_not_run",
                     not_provided=["availability"]) for t in tools]


def proposal_records(path=PROPOSALS_PATH, acceptance=ACCEPTANCE_PATH, now=None):
    """Display-only self-evolution proposals. Each must cite a documented GAP row by exact text hash; a changed or missing row
    or an expired proposal is STALE. Review status is never changed here; nothing is applied."""
    now = now or datetime.now(timezone.utc)
    observed = utc_iso(now)
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8")) if Path(path).stat().st_size <= 512_000 else None
        rows = {}
        for line in Path(acceptance).read_text(encoding="utf-8").splitlines():
            m = re.match(r"^\| (GAP-\d+) \|", line)
            if m:
                rows[m.group(1)] = line
    except (OSError, ValueError) as error:
        return section([], "local:proposal-log", None, "unavailable", f"Proposal log unreadable: {error}")
    items = []
    for p in raw if isinstance(raw, list) else []:
        if not isinstance(p, dict) or not p.get("proposal_id"):
            continue
        row = rows.get(p.get("gap_id"))
        cited = (p.get("evidence") or {}).get("row_sha256")
        expires = parse_ts(p.get("expires_at"))
        if row is None:
            validity, reason = "stale", f"{p.get('gap_id')} is no longer in ACCEPTANCE.md"
        elif sha256_text(row) != cited:
            validity, reason = "stale", f"{p.get('gap_id')} row changed since the proposal was written; re-review required"
        elif expires is None or expires < now:
            validity, reason = "stale", "proposal expired"
        else:
            validity, reason = "valid", "Evidence row matches; awaiting human review. Display only - nothing is applied."
        items.append(envelope("proposal", f"proposal:{p['proposal_id']}", "local:proposal-log (docs/hive/proposals/proposals-v1.json)", observed,
                              validity, reason, source_id=p.get("gap_id"), proposal_id=str(p["proposal_id"])[:80], gap_id=p.get("gap_id"),
                              problem=safe_text(p.get("problem"), 400), expected_benefit=safe_text(p.get("expected_benefit"), 300),
                              affected_files=_str_list(p.get("affected_files")) or [], risk=p.get("risk") if p.get("risk") in ("low", "medium", "high") else "unclassified",
                              test_plan=_str_list(p.get("test_plan")) or [], rollback_plan=safe_text(p.get("rollback_plan"), 300),
                              review_status="PENDING_HUMAN_REVIEW", proposal_only=True, created_at=p.get("created_at"), expires_at=p.get("expires_at")))
    return section(items, "local:proposal-log", observed, "valid", f"{len(items)} proposal(s); review status is never changed automatically.")


# ------------------------------------------------------------------ evidence log (bounded, in memory, read-only to clients)
# One log per mode, so fixture observations can never appear in a live response (or the reverse).
_LOGS = {"live": collections.deque(maxlen=200), "fixture": collections.deque(maxlen=200)}
_LOG = _LOGS["live"]
_LOG_LOCK = threading.Lock()


def record_evidence(connectors, observed, mode="live"):
    log = _LOGS["fixture" if mode == "fixture" else "live"]
    with _LOG_LOCK:
        for c in connectors:
            basis = f"{c['id']}|{observed}|{c['validity']}"
            log.appendleft(envelope("evidence_record", "evidence:" + hashlib.sha256(basis.encode()).hexdigest()[:16], c["source"], observed, c["validity"],
                                     c.get("reason"), source_id=c["id"], subject=c["id"]))
        return list(log)[:50]


# ------------------------------------------------------------------ assembly
def default_skill_roots():
    env = os.environ.get("HIVE_SKILL_ROOTS")
    if env:
        return [(f"root{i + 1}", p) for i, p in enumerate(env.split(os.pathsep)) if p.strip()][:4]
    home = Path.home()
    return [("codex", str(home / ".codex" / "skills")), ("agents", str(home / ".agents" / "skills"))]


def build_registry(fetch, creator_ops, tools, skill_roots=None, vault_root=None, bucket=lambda s: str(s).lower(), now=None, mode="live",
                   proposals_path=PROPOSALS_PATH, acceptance_path=ACCEPTANCE_PATH):
    clock = now or (lambda: datetime.now(timezone.utc))
    core = HiveCoreRegistryAdapter(fetch, bucket, clock).read()
    t = core["now"]
    observed = utc_iso(t)
    skill_conns, skills = SkillCatalogAdapter(skill_roots if skill_roots is not None else default_skill_roots(), clock,
                                              "fixture:skills" if mode == "fixture" else "skills").read()
    obs_conn, notes = ObsidianAdapter(vault_root, clock, "fixture:obsidian" if mode == "fixture" else "obsidian").read()
    co_conn, co_catalog = creator_ops_catalog(creator_ops(), observed)
    workers = core["workers"]["items"]
    reg = {
        "schema_version": SCHEMA_VERSION, "generated_at": observed, "mode": mode,
        "read_only": True, "executes_nothing": True,
        "connectors": [core["connector"], co_conn, obs_conn] + skill_conns,
        "ultron": ultron_status(core, t),
        "agents": section(observed_agents(core["events"], core["events_evidence"], t), "hive:/events", core["events_evidence"].get("observed_at"),
                          core["events_evidence"].get("validity", "unknown"), core["events_evidence"].get("reason") or
                          "Agents are execution identities named by HIVE Core events; primary/secondary classification is UNKNOWN."),
        "roles": section(role_catalog(observed), "local:dashboard-role-catalog", observed, "valid", "Catalog definitions, not runtime evidence."),
        "workers": core["workers"],
        "providers": section(provider_catalog(workers, observed), "local:provider-catalog", observed, "valid",
                             "Provider status is known only when a worker record names the provider explicitly."),
        "capabilities": section(capability_index(workers, skills), "derived: worker records + skill manifests", observed, "valid",
                                "Declared capabilities; a declaration is not a permission."),
        "tasks": {"instances": core["tasks"],
                  "definitions": section([], "none", None, "not_configured", "No authoritative task-definition source is connected.")},
        "catalogs": {
            "creator_ops": co_catalog,
            "obsidian": section(notes, obs_conn["source"], obs_conn["observed_at"], obs_conn["validity"], obs_conn["reason"]),
            "skills": section(skills, "skills (allowlisted roots)", observed, "valid" if any(c["validity"] in ("valid", "conflict") for c in skill_conns) else "not_configured",
                              "Discovered read-only; nothing is activated or executed."),
            "prompts": section([], "none", None, "not_configured", "No prompts root is configured."),
            "bots": section([], "none", None, "not_configured", "No bots root is configured."),
            "tools": section(tool_catalog(tools, observed), "local:server-config", observed, "valid", "Configured tools; none is executed by the registry."),
        },
        "proposals": proposal_records(proposals_path, acceptance_path, t),
    }
    if mode == "fixture":
        _label_fixture(reg)
    reg["evidence_log"] = record_evidence(reg["connectors"], observed, mode)
    return reg


def _label_fixture(node):
    """Fixture mode: every record and section is visibly fixture data and can never read as live."""
    if isinstance(node, dict):
        if "validity" in node and node.get("validity") == "valid":
            node["validity"], node["display"] = "fixture", DISPLAY["fixture"]
        if node.get("kind") == "ultron_status" and node.get("display") == "ACTIVE":
            node["display"] = "FIXTURE"
        if isinstance(node.get("source"), str) and not node["source"].startswith("fixture"):
            node["source"] = "fixture:" + node["source"]
        for v in node.values():
            _label_fixture(v)
    elif isinstance(node, list):
        for v in node:
            _label_fixture(v)


# ------------------------------------------------------------------ schema (generated; schemas/hive-readonly-v1.schema.json must equal it)
_S, _N, _I, _B, _A = {"type": "string"}, {"type": ["string", "null"]}, {"type": "integer"}, {"type": "boolean"}, {"type": "array", "items": {"type": "string"}}
_ENVELOPE = {"kind": _S, "id": _S, "source": _S, "source_id": _N, "observed_at": _N, "validity": {"enum": list(VALIDITIES)}, "reason": _N,
             "correlation_id": _N, "schema_version": {"const": SCHEMA_VERSION}, "display": {"enum": sorted(set(DISPLAY.values()))}, "not_provided": _A}
_KINDS = {
    "connector": {"name": _S, "transport": _S, "root": _S, "vault_name": _S, "table_counts": {"type": "object"}},
    "agent": {"role_id": _N, "classification": {"const": "UNKNOWN"}, "classification_reason": _S, "provider": _N, "model": _N, "last_state": {"enum": list(hive_events.STATES)},
              "last_event_id": _N, "last_event_type": _N, "task_id": _N},
    "role": {"role_id": _S, "descriptor": _S, "classification": {"const": "UNKNOWN"}, "provider": {"type": "null"}},
    "worker": {"name": _N, "provider": _N, "model": _N, "status_raw": _N, "status": _S, "capabilities": _A, "current_task": _N, "heartbeat": _N,
               "freshness": {"enum": ["live", "stale", "offline", "unknown"]}},
    "provider": {"label": _S, "observed_workers": _A},
    "capability": {"name": _S, "declared_by": _A},
    "task_instance": {"title": _N, "status_raw": _N, "status": _S, "assigned_worker": _N, "project_id": _N, "required_capabilities": _A, "created_at": _N, "updated_at": _N},
    "catalog_item": {"item_type": {"enum": ["skill", "note", "tool", "prompt", "bot", "task_definition"]}, "name": _N, "version": _N, "description": _N, "content_hash": _N,
                     "tree_hash": _N, "file_count": _I, "tree_truncated": _B, "declared_capabilities": _A, "required_permissions": {"type": ["array", "string", "null"]},
                     "risk_class": {"type": "null"}, "enabled": {"const": False}, "activation": {"enum": ["discovered_not_activated", "metadata_only", "configured_not_run"]},
                     "size": _I, "modified_at": _N, "tags": {"type": "array"}, "outgoing_links": _I, "transport": _S, "target": _S},
    "proposal": {"proposal_id": _S, "gap_id": _N, "problem": _N, "expected_benefit": _N, "affected_files": _A, "risk": {"enum": ["low", "medium", "high", "unclassified"]},
                 "test_plan": _A, "rollback_plan": _N, "review_status": {"const": "PENDING_HUMAN_REVIEW"}, "proposal_only": {"const": True}, "created_at": _N, "expires_at": _N},
    "evidence_record": {"subject": _S},
    "ultron_status": {"state": {"enum": list(hive_events.STATES)}, "freshness_window_s": _I, "last_event_id": _N, "last_event_type": _N,
                      "last_state": {"enum": list(hive_events.STATES) + [None]}, "age_s": {"type": ["number", "null"]}},
}
_REQUIRED = ["kind", "id", "source", "source_id", "observed_at", "validity", "reason", "correlation_id", "schema_version", "display"]


def build_schema():
    defs = {}
    for kind, props in _KINDS.items():
        p = dict(_ENVELOPE)
        p.update(props)
        p["kind"] = {"const": kind}
        if kind == "ultron_status":
            p["display"] = {"enum": list(ULTRON_DISPLAY)}
        defs[kind] = {"type": "object", "required": _REQUIRED, "properties": p, "additionalProperties": False}
    defs["section_evidence"] = {"type": "object", "required": ["source", "observed_at", "validity", "reason", "display"],
                                "properties": {"source": _S, "observed_at": _N, "validity": {"enum": list(VALIDITIES)}, "reason": _N, "display": _S}, "additionalProperties": False}
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": f"urn:hive:{SCHEMA_VERSION}", "title": "HIVE read-only registry records",
            "description": "Evidence envelope + record kinds served by /api/registry. Generated from hive_registry.build_schema(); do not edit by hand.",
            "$defs": defs}


def validate(instance, schema, root=None, path="$"):
    """Small JSON-Schema subset validator (type, enum, const, required, properties, additionalProperties, items, $ref). Returns errors."""
    root = root or schema
    if "$ref" in schema:
        schema = root["$defs"][schema["$ref"].split("/")[-1]]
    errs = []
    types = {"string": str, "integer": int, "boolean": bool, "object": dict, "array": list, "null": type(None), "number": (int, float)}
    if "type" in schema:
        allowed = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        ok = any(isinstance(instance, types[t]) and not (t in ("integer", "number") and isinstance(instance, bool)) for t in allowed)
        if not ok:
            return [f"{path}: expected {allowed}, got {type(instance).__name__}"]
    if "const" in schema and instance != schema["const"]:
        errs.append(f"{path}: expected const {schema['const']!r}, got {instance!r}")
    if "enum" in schema and instance not in schema["enum"]:
        errs.append(f"{path}: {instance!r} not in enum")
    if isinstance(instance, dict):
        for key in schema.get("required", []):
            if key not in instance:
                errs.append(f"{path}: missing {key}")
        props = schema.get("properties", {})
        for key, value in instance.items():
            if key in props:
                errs += validate(value, props[key], root, f"{path}.{key}")
            elif schema.get("additionalProperties") is False:
                errs.append(f"{path}: unexpected property {key}")
    if isinstance(instance, list) and "items" in schema:
        for i, value in enumerate(instance):
            errs += validate(value, schema["items"], root, f"{path}[{i}]")
    return errs


def iter_records(reg):
    """Every enveloped record in a registry response. Records are leaves: their own fields are not searched for records."""
    if isinstance(reg, dict):
        if "kind" in reg and "schema_version" in reg:
            yield reg
            return
        for value in reg.values():
            yield from iter_records(value)
    elif isinstance(reg, list):
        for value in reg:
            yield from iter_records(value)


def validate_registry(reg):
    schema = build_schema()
    errs = []
    for rec in iter_records(reg):
        kind = rec.get("kind")
        if kind not in schema["$defs"]:
            errs.append(f"{rec.get('id')}: unknown kind {kind!r}")
            continue
        errs += validate(rec, {"$ref": f"#/$defs/{kind}"}, schema, rec.get("id", "?"))
    return errs


if __name__ == "__main__":  # python hive_registry.py --write-schema
    import sys
    if "--write-schema" in sys.argv:
        SCHEMA_PATH.parent.mkdir(parents=True, exist_ok=True)
        SCHEMA_PATH.write_text(json.dumps(build_schema(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print("wrote", SCHEMA_PATH)
