"""Read-only HIVE registry v2: agents, roles, workers, providers, capabilities, tasks, ULTRON status, Creator Ops task catalog,
Obsidian metadata, skills / prompts / bots catalogs, tool manifests and the display-only self-evolution proposal log.

Rules enforced here:
  * nothing is executed or activated: no task, tool, bot, prompt or skill is run, imported or loaded; files are only read
    (bounded) and hashed; every catalog item is enabled=false;
  * nothing is written to any external system; the only state is an in-memory evidence log and a result cache;
  * nothing is invented: a field no source provides is null and listed in `not_provided`; primary/secondary classification
    is UNKNOWN; agents exist only when HIVE Core events name them (Core has no agents route);
  * paths come only from explicit configuration (environment variables) or two allowlisted defaults relative to the user's
    home directory; relative paths, '..', filesystem roots and the bare home directory are rejected;
  * every source runs isolated in its own thread with its own timeout, so one slow source cannot block the others;
  * fixture mode relabels every record as fixture so fixture data can never look live.
Stdlib only. The HIVE Core transport and its preflight scope are injected by server.py, so this module never imports server.
"""
from __future__ import annotations

import collections
import contextlib
import hashlib
import json
import os
import re
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import hive_events

SCHEMA_VERSION = "hive.readonly.v3"
ROOT = Path(__file__).resolve().parent
SCHEMA_PATH = ROOT / "schemas" / "hive-readonly-v3.schema.json"
PROPOSALS_PATH = ROOT / "docs" / "hive" / "proposals" / "proposals.json"
ACCEPTANCE_PATH = ROOT / "docs" / "hive" / "ACCEPTANCE.md"
DEFAULT_TOOL_MANIFEST_DIR = ROOT / "manifests" / "tools"

# Same windows as hive-core.js: roleFresh() 120 s for an observed role; classifyFreshness() 30 s live / 90 s offline.
ULTRON_FRESH_S = 120
HEARTBEAT_LIVE_S, HEARTBEAT_OFFLINE_S = 30, 90
FUTURE_TOLERANCE_S = 5

VALIDITIES = ("valid", "stale", "unavailable", "inaccessible", "untrusted", "conflict", "unknown", "auth_required",
              "not_configured", "not_verified", "fixture")
DISPLAY = {"valid": "OBSERVED", "stale": "STALE", "unavailable": "OFFLINE", "inaccessible": "UNAVAILABLE", "untrusted": "UNVERIFIED",
           "conflict": "CONFLICT", "unknown": "UNKNOWN", "auth_required": "AUTH_REQUIRED", "not_configured": "NOT_CONNECTED",
           "not_verified": "NOT_VERIFIED", "fixture": "FIXTURE"}
ULTRON_DISPLAY = ("ACTIVE", "STALE", "UNKNOWN", "OFFLINE", "UNVERIFIED", "FIXTURE")
PROPOSAL_STATUSES = ("PENDING_HUMAN_REVIEW", "APPROVED_FOR_PROTOTYPE", "REJECTED", "STALE", "EXPIRED")
HUMAN_STATUSES = PROPOSAL_STATUSES[:3]
RISKS = ("low", "medium", "high", "unclassified")
ELEVATED = re.compile(r"bash|shell|exec|write|edit|delete|network|webfetch|websearch|http|curl|ssh|sudo|admin|deploy", re.I)

ROLE_CATALOG = (("ULTRON", "Orchestration / guardian"), ("FURY", "Planning"), ("SHURI", "Coding"), ("THOR", "Research"),
                ("VISION", "Analysis"), ("FALCON", "Monitoring"), ("UATU", "Watching"))
PROVIDER_CATALOG = (("gpt", "GPT"), ("claude", "CLAUDE"), ("codex", "CODEX"), ("local", "LOCAL"))

# Bounds
FILE_MAX = 256 * 1024
TREE_MAX_FILES, TREE_FILE_MAX, TREE_TOTAL_MAX = 300, 2 * 1024 * 1024, 20 * 1024 * 1024
MAX_ITEMS_PER_ROOT = 400
NOTE_MAX_BYTES, NOTES_LISTED_MAX, NOTES_SCANNED_MAX, VAULT_BYTES_MAX = 1024 * 1024, 200, 5000, 64 * 1024 * 1024
VAULT_TIME_BUDGET_S = 3.0
MANIFESTS_MAX, MANIFEST_MAX_BYTES = 100, 64 * 1024
CREATOR_TASKS_MAX = 500
SKIP_DIRS = {".obsidian", ".trash", ".git", "node_modules", "__pycache__"}

# Per-source isolation: (timeout seconds, cache TTL seconds)
PART_LIMITS = {"core": (6.0, 3.0), "creator_ops": (3.0, 30.0), "obsidian": (5.0, 60.0), "catalogs": (5.0, 60.0),
               "tools": (2.0, 60.0), "proposals": (3.0, 10.0), "internet": (5.0, 30.0)}
PARTS = tuple(PART_LIMITS)

# Creator Ops: the only table and columns this adapter will ever read (explicit allowlist; nothing else is queried).
CREATOR_TASK_TABLE = "task_definitions"
CREATOR_REQUIRED_COLS = ("id", "name")
CREATOR_OPTIONAL_COLS = ("version", "input_schema", "output_schema", "required_capabilities", "risk_class", "availability", "updated_at")

_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_TAG = re.compile(r"(?:^|\s)#([A-Za-z][\w/-]{0,60})")
_WIKILINK = re.compile(r"\[\[([^\]|#]{1,200})")
_TASK_OPEN = re.compile(r"^\s*[-*] \[ \]", re.M)
_TASK_DONE = re.compile(r"^\s*[-*] \[[xX]\]", re.M)
_SHELL_META = re.compile(r"[;&|`$<>]")


# ------------------------------------------------------------------ helpers
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
    """Display text from a source: control characters stripped, secrets redacted, length bounded. It is data, never markup."""
    if value in (None, ""):
        return None
    return hive_events.redact_summary(_CTRL.sub(" ", str(value)), limit)


def sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def envelope(kind, record_id, source, observed_at, validity, reason=None, source_id=None, correlation_id=None, **fields):
    if validity not in VALIDITIES:
        validity, reason = "unknown", f"unrecognised validity {validity!r}" + (f"; {reason}" if reason else "")
    rec = {"kind": kind, "id": str(record_id)[:200], "source": str(source)[:160], "source_id": None if source_id in (None, "") else str(source_id)[:200],
           "observed_at": observed_at, "validity": validity, "reason": reason, "correlation_id": correlation_id,
           "schema_version": SCHEMA_VERSION, "display": DISPLAY[validity]}
    rec.update(fields)
    rec.setdefault("not_provided", [])
    return rec


def section(items, source, observed_at, validity, reason=None, aggregate=False):
    """Section evidence. An aggregate over several sources has no state of its own (display None => no chip in the UI)."""
    return {"evidence": {"source": source, "observed_at": observed_at, "validity": validity, "reason": reason,
                         "display": None if aggregate else DISPLAY.get(validity, "UNKNOWN")}, "items": items}


def freshness(ts, now, live_s=HEARTBEAT_LIVE_S, offline_s=HEARTBEAT_OFFLINE_S):
    """Mirror of hive-core.js classifyFreshness(): live / stale / offline / unknown (missing or future timestamp)."""
    dt = parse_ts(ts)
    if dt is None:
        return "unknown"
    age = (now - dt).total_seconds()
    if age < -FUTURE_TOLERANCE_S:
        return "unknown"
    return "live" if age <= live_s else "stale" if age <= offline_s else "offline"


def _str_list(value, limit=40):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            value = [v.strip() for v in value.split(",")]
    if not isinstance(value, list):
        return None
    return [str(v)[:80] for v in value if isinstance(v, str) and v.strip()][:limit]


def _risk(declared, tools):
    if isinstance(declared, str) and declared.strip().lower() in RISKS[:3]:
        return declared.strip().lower(), "declared"
    if tools:
        return ("high", "derived_from_declared_tools") if any(ELEVATED.search(t) for t in tools) else ("low", "derived_from_declared_tools")
    return "unclassified", "none"


# ------------------------------------------------------------------ configuration (explicit only)
def check_root(raw, must_exist=True):
    """(Path, None) for an acceptable root, else (None, (validity, reason)). Never falls back to another location."""
    if raw is None or not str(raw).strip():
        return None, ("not_configured", "not configured")
    p = Path(str(raw).strip()).expanduser()
    if not p.is_absolute():
        return None, ("not_verified", f"rejected: not an absolute path ({raw})")
    if ".." in p.parts:
        return None, ("not_verified", "rejected: '..' is not allowed in a root")
    if p == Path(p.anchor) or p == Path.home():
        return None, ("not_verified", "rejected: a filesystem root or the bare home directory is too broad")
    if p.is_symlink():
        return None, ("not_verified", "rejected: the root itself is a symbolic link")
    if must_exist and not p.is_dir():
        return None, ("inaccessible", f"configured root is missing or not a directory: {p}")
    return p, None


def _roots_from_env(*names):
    for name in names:
        raw = os.environ.get(name)
        if raw is not None:
            return [(f"{name.lower()}#{i + 1}", p) for i, p in enumerate(raw.split(os.pathsep)) if p.strip()][:6], name
    return None, None


@dataclass
class RegistryConfig:
    skill_roots: list = field(default_factory=list)      # [(label, raw path)]
    prompt_roots: list = field(default_factory=list)
    bot_roots: list = field(default_factory=list)
    vault_root: str | None = None
    creator_ops_db: str | None = None
    tool_manifest_dir: str | None = None
    internet_probes: str | None = None
    agents_config: str | None = None
    sources: dict = field(default_factory=dict)          # which variable or default produced each setting (for the UI)


def config_from_env() -> RegistryConfig:
    skills, skill_var = _roots_from_env("HIVE_SKILLS_ROOTS", "HIVE_SKILL_ROOTS")
    if skills is None:  # allowlisted defaults, relative to the user's home directory (no user name is committed)
        home = Path.home()
        skills, skill_var = [("codex", str(home / ".codex" / "skills")), ("agents", str(home / ".agents" / "skills"))], "default allowlist (~/.codex/skills, ~/.agents/skills)"
    prompts, prompt_var = _roots_from_env("HIVE_PROMPTS_ROOTS")
    bots, bot_var = _roots_from_env("HIVE_BOTS_ROOTS")
    tool_dir = os.environ.get("HIVE_TOOL_MANIFEST_DIR") or str(DEFAULT_TOOL_MANIFEST_DIR)
    vault, db = os.environ.get("ORCHESTRATOR_VAULT_ROOT") or None, os.environ.get("CREATOR_OPS_DB_PATH") or None
    probes = os.environ.get("HIVE_INTERNET_PROBES") or None
    return RegistryConfig(skill_roots=skills, prompt_roots=prompts or [], bot_roots=bots or [], vault_root=vault, creator_ops_db=db, tool_manifest_dir=tool_dir,
                          internet_probes=probes,
                          sources={"internet": "HIVE_INTERNET_PROBES" if probes else "not configured (HIVE_INTERNET_PROBES)","skills": skill_var, "prompts": prompt_var or "not configured (HIVE_PROMPTS_ROOTS)", "bots": bot_var or "not configured (HIVE_BOTS_ROOTS)",
                                   "obsidian": "ORCHESTRATOR_VAULT_ROOT" if vault else "not configured (ORCHESTRATOR_VAULT_ROOT)",
                                   "creator_ops": "CREATOR_OPS_DB_PATH" if db else "not configured (CREATOR_OPS_DB_PATH)",
                                   "tools": "HIVE_TOOL_MANIFEST_DIR" if os.environ.get("HIVE_TOOL_MANIFEST_DIR") else "repository default (manifests/tools)"})


def config_signature(cfg: RegistryConfig) -> str:
    return sha256_text(json.dumps([cfg.skill_roots, cfg.prompt_roots, cfg.bot_roots, cfg.vault_root, cfg.creator_ops_db, cfg.tool_manifest_dir,
                                   cfg.internet_probes, cfg.agents_config], default=str))


# ------------------------------------------------------------------ HIVE Core adapter
def _unwrap(raw):
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for key in ("items", "workers", "tasks", "events", "data"):
            if isinstance(raw.get(key), list):
                return raw[key]
    return []


class HiveCoreRegistryAdapter:
    """Read-only view of HIVE Core: /health (preflight + connector), /workers (or the labelled public /ready list), /tasks, /events.
    `fetch(path) -> (raw, evidence)` is server.fetch_with_evidence. HIVE Core has no agents route: agents are derived from events."""

    def __init__(self, fetch, bucket=lambda s: str(s).lower(), now=None):
        self.fetch, self.bucket = fetch, bucket
        self.now = now or (lambda: datetime.now(timezone.utc))

    def read(self):
        now = self.now()
        _, health_ev = self.fetch("/health")
        connector = envelope("connector", "connector:hive-core", health_ev.get("source", "hive:/health"), health_ev.get("observed_at"),
                             health_ev.get("validity", "unknown"), health_ev.get("reason"), name="HIVE Core", transport="http loopback", part="core")
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
        events = []
        if events_ev.get("validity") == "valid":
            for raw_event in _unwrap(events_raw)[:200]:
                e = hive_events.contract_event(raw_event, {"source": "hive:/events"})
                if e:
                    e["declared_role"] = raw_event.get("role")[:80] if isinstance(raw_event.get("role"), str) else None
                    events.append(e)
        return {"connector": connector, "reachable": reachable, "now": now, "events": events, "events_evidence": events_ev,
                "workers": section(workers, worker_source.get("source", "hive:/workers"), worker_source.get("observed_at"), worker_source.get("validity", "unknown"), worker_source.get("reason")),
                "tasks": section(tasks, tasks_ev.get("source", "hive:/tasks"), tasks_ev.get("observed_at"), tasks_ev.get("validity", "unknown"), tasks_ev.get("reason"))}

    def _workers(self, raw, ev, now):
        out, seen = [], {}
        for item in _unwrap(raw):
            if not isinstance(item, dict) or not (item.get("id") or item.get("worker_id")):
                continue
            wid = str(item.get("id") or item.get("worker_id"))[:120]
            provider = item.get("provider") if isinstance(item.get("provider"), str) and item["provider"].strip().lower() not in ("", "unknown") else None
            model = item.get("model") if isinstance(item.get("model"), str) and item["model"].strip().lower() not in ("", "unknown") else None
            heartbeat = next((item.get(k) for k in ("last_seen", "heartbeat_at", "updated_at") if isinstance(item.get(k), str)), None)
            caps = _str_list(item.get("capabilities")) if isinstance(item.get("capabilities"), list) else None
            current = item.get("current_task") or item.get("task_id")
            corr = item.get("correlation_id") if isinstance(item.get("correlation_id"), str) else None
            np = [k for k, v in (("provider", provider), ("model", model), ("capabilities", caps), ("current_task", current), ("heartbeat", heartbeat), ("correlation_id", corr)) if v in (None, [])]
            rec = envelope("worker", f"worker:{wid}", ev.get("source"), ev.get("observed_at"), "valid", None, source_id=wid, correlation_id=corr,
                           name=safe_text(item.get("name") or wid, 80), provider=safe_text(provider, 40), model=safe_text(model, 80),
                           status_raw=safe_text(item.get("status"), 40), status=self.bucket(item.get("status", "unknown")),
                           capabilities=caps or [], current_task=None if current is None else str(current)[:120],
                           heartbeat=heartbeat, freshness=freshness(heartbeat, now), not_provided=np)
            if wid in seen:  # duplicate identity in one response: keep the first, mark it conflict, drop the duplicate
                seen[wid].update(validity="conflict", display=DISPLAY["conflict"], reason="duplicate worker id in the source response")
                continue
            seen[wid] = rec
            out.append(rec)
        return out

    def _tasks(self, raw, ev):
        out = []
        for item in _unwrap(raw):
            if not isinstance(item, dict) or not (item.get("id") or item.get("task_id")):
                continue
            tid = str(item.get("id") or item.get("task_id"))[:120]
            assigned = item.get("worker_id") or item.get("preferred_worker")
            req = _str_list(item.get("required_capabilities")) if isinstance(item.get("required_capabilities"), list) else None
            corr = item.get("correlation_id") if isinstance(item.get("correlation_id"), str) else None
            np = [k for k, v in (("assigned_worker", assigned), ("required_capabilities", req), ("correlation_id", corr)) if v in (None, [])]
            out.append(envelope("task_instance", f"task:{tid}", ev.get("source"), ev.get("observed_at"), "valid", None, source_id=tid, correlation_id=corr,
                                title=safe_text(item.get("title"), 160), status_raw=safe_text(item.get("status"), 40), status=self.bucket(item.get("status", "unknown")),
                                assigned_worker=None if assigned is None else str(assigned)[:120], project_id=None if item.get("project_id") is None else str(item.get("project_id"))[:120],
                                required_capabilities=req or [], created_at=item.get("created_at") if isinstance(item.get("created_at"), str) else None,
                                updated_at=item.get("updated_at") if isinstance(item.get("updated_at"), str) else None, not_provided=np))
        return out


def event_trust(event, now):
    dt = parse_ts(event.get("timestamp"))
    if dt is None:
        return "untrusted", "event has no parseable timestamp", None
    if (dt - now).total_seconds() > FUTURE_TOLERANCE_S:
        return "untrusted", "event timestamp is in the future", dt
    return "trusted", None, dt


def observed_agents(events, now):
    """Agents = execution identities that HIVE Core events named (role_id). Never created from the role catalog."""
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
        np = ["classification"] + [k for k in ("provider", "model", "task_id", "correlation_id") if not ev.get(k)]
        out.append(envelope("agent", f"agent:{key}", "hive:/events", ev.get("timestamp"), validity, reason, source_id=ev.get("role_id"),
                            correlation_id=ev.get("correlation_id"), role_id=ev.get("role_id"), classification="UNKNOWN",
                            classification_reason="No authoritative primary/secondary source or approved configuration exists.",
                            provider=ev.get("provider"), model=ev.get("model"), last_state=ev.get("state"), last_event_id=ev.get("event_id"),
                            last_event_type=ev.get("event_type"), task_id=ev.get("task_id"), age_s=None if age is None else round(age, 1),
                            declared_role=ev.get("declared_role"), not_provided=np))
    return out


def ultron_status(core, now):
    """Evidence-based ULTRON status on the existing state contract (hive_events.STATES).
    OFFLINE: Core transport unavailable. UNKNOWN: no ULTRON event. UNVERIFIED: only untrusted ULTRON events.
    ACTIVE: a trusted ULTRON event within ULTRON_FRESH_S. STALE: the latest trusted ULTRON event is older. Silence is never ACTIVE."""
    conn = core["connector"]
    ultron = [e for e in core["events"] if (e.get("role_id") or "").upper() == "ULTRON"]
    recent = []
    for e in ultron[:10]:
        trust, why, dt = event_trust(e, now)
        recent.append({"event_id": e.get("event_id"), "timestamp": e.get("timestamp"), "state": e.get("state"), "event_type": e.get("event_type"),
                       "trust": trust, "age_s": None if dt is None else round((now - dt).total_seconds(), 1)})
    base = dict(kind="ultron_status", id="ultron", schema_version=SCHEMA_VERSION, correlation_id=None, source_id=None,
                freshness_window_s=ULTRON_FRESH_S, last_event_id=None, last_event_type=None, last_state=None, age_s=None, recent=recent, not_provided=[])
    if not core["reachable"]:
        return dict(base, display="OFFLINE", state="OFFLINE", source=conn["source"], observed_at=None, validity="unavailable",
                    reason=f"HIVE Core transport unavailable: {conn['reason']}")
    if core["events_evidence"].get("validity") != "valid":
        return dict(base, display="UNKNOWN", state="UNKNOWN", source="hive:/events", observed_at=None, validity=core["events_evidence"].get("validity", "unknown"),
                    reason=f"HIVE Core events unavailable: {core['events_evidence'].get('reason')}")
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


def capability_index(records):
    caps = collections.OrderedDict()
    for rec in records:
        for cap in rec.get("capabilities") or rec.get("declared_capabilities") or rec.get("required_capabilities") or []:
            entry = caps.setdefault(cap, {"declared_by": [], "sources": set(), "observed_at": rec.get("observed_at")})
            entry["declared_by"].append(rec["id"])
            entry["sources"].add(rec["source"])
    return [envelope("capability", f"capability:{name}", ", ".join(sorted(v["sources"]))[:160], v["observed_at"], "valid",
                     "Declared by the listed records; a declaration is not a permission.", source_id=name, name=name[:80],
                     declared_by=v["declared_by"][:50]) for name, v in caps.items()]


def read_core(fetch, bucket, clock, core_scope, agents_config=None):
    import hive_control  # local import: hive_control builds on this module
    with (core_scope() if core_scope else contextlib.nullcontext()):
        core = HiveCoreRegistryAdapter(fetch, bucket, clock).read()
    t = core["now"]
    observed = utc_iso(t)
    workers = core["workers"]["items"]
    ev = core["events_evidence"]
    agents = observed_agents(core["events"], t)
    cfg_agents, cfg_problem = hive_control.load_agent_config(agents_config or hive_control.AGENTS_CONFIG_PATH)
    profiles, prof_validity, prof_reason = hive_control.agent_profiles(cfg_agents, cfg_problem, agents, core["reachable"], observed)
    observations = hive_control.ultron_observations(core["connector"], core["reachable"], profiles, workers, core["tasks"]["items"], core["events"], observed, t)
    return {
        "agent_registry": section(profiles, "config/agents.json + hive:/events", observed, prof_validity, prof_reason),
        "ultron_observations": section(observations, "derived: HIVE Core health, workers, tasks, events", observed, "valid",
                                       "Observations only: ULTRON takes no action, grants no permission and changes no external system.", aggregate=True),
        "connectors": [core["connector"]],
        "ultron": ultron_status(core, t),
        "agents": section(agents, "hive:/events", ev.get("observed_at"), ev.get("validity", "unknown"),
                          ev.get("reason") or "Derived from HIVE Core events (Core has no agents route); primary/secondary classification is UNKNOWN."),
        "roles": section(role_catalog(observed), "local:dashboard-role-catalog", observed, "valid",
                         "Catalog definitions, not runtime evidence; the list has no runtime state of its own.", aggregate=True),
        "workers": core["workers"],
        "providers": section(provider_catalog(workers, observed), "local:provider-catalog", observed, "valid",
                             "Catalog list: a provider's runtime status is known only when a worker record names it explicitly. "
                             "Listing a provider is not evidence of connectivity.", aggregate=True),
        "capabilities": section(capability_index(workers + core["tasks"]["items"]), "derived: worker and task records", observed, "valid",
                                "Declared or required by HIVE Core records; a declaration is not a permission.", aggregate=True),
        "tasks": {"instances": core["tasks"]},
    }


# ------------------------------------------------------------------ Creator Ops task catalog (explicit table + column allowlist)
def _schema_summary(value):
    if value in (None, ""):
        return None
    try:
        obj = json.loads(value) if isinstance(value, str) else value
    except ValueError:
        return "unparseable (not shown)"
    if isinstance(obj, dict) and isinstance(obj.get("properties"), dict):
        keys = [str(k)[:40] for k in list(obj["properties"])[:12]]
        return f"fields: {', '.join(keys)}" + (" …" if len(obj["properties"]) > 12 else "")
    if isinstance(obj, dict) and isinstance(obj.get("type"), str):
        return f"type: {obj['type'][:20]}"
    return "present (shape not recognised; not shown)"


def _co_result(src, validity, reason, observed=None, counts=None, items=None):
    extra = {"table_counts": counts} if counts else {}
    conn = envelope("connector", "connector:creator-ops", src, observed, validity, reason, name="Creator Ops", transport="sqlite mode=ro", part="creator_ops", **extra)
    return {"connectors": [conn], "catalogs": {"creator_ops": section(items or [], src, observed, validity, reason)}}


def read_creator_ops(db_raw, observed, counts=None, source="creator-ops"):
    """Reads only `task_definitions` and only allowlisted columns, in SQLite read-only mode with a bounded LIMIT. No task is run."""
    src = f"{source}:task_definitions"
    if not db_raw:
        return _co_result(src, "not_configured", "CREATOR_OPS_DB_PATH is not configured.", counts=counts)
    path = Path(str(db_raw)).expanduser()
    if not path.is_absolute() or ".." in path.parts:
        return _co_result(src, "not_verified", "rejected: CREATOR_OPS_DB_PATH must be an absolute path without '..'", counts=counts)
    if not path.is_file():
        return _co_result(src, "inaccessible", "configured database file is missing or not a file", counts=counts)
    try:
        db = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=2)
        try:
            cur = db.cursor()
            has_table = cur.execute("SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name=?", (CREATOR_TASK_TABLE,)).fetchone()
            cols = {row[1] for row in cur.execute(f'PRAGMA table_info("{CREATOR_TASK_TABLE}")')} if has_table else set()
            if not has_table or not set(CREATOR_REQUIRED_COLS) <= cols:
                reason = (f"schema unknown: expected table or view {CREATOR_TASK_TABLE}({', '.join(CREATOR_REQUIRED_COLS)}; optional {', '.join(CREATOR_OPTIONAL_COLS)}); "
                          "no other table is read.")
                return _co_result(src, "not_verified", reason, observed, counts)
            select = [c for c in CREATOR_REQUIRED_COLS + CREATOR_OPTIONAL_COLS if c in cols]
            quoted = ", ".join(f'"{c}"' for c in select)
            rows = cur.execute(f'SELECT {quoted} FROM "{CREATOR_TASK_TABLE}" ORDER BY "id" LIMIT ?', (CREATOR_TASKS_MAX + 1,)).fetchall()
        finally:
            db.close()
    except sqlite3.Error as error:
        return _co_result(src, "inaccessible", f"read failed: {error}", counts=counts)
    truncated = len(rows) > CREATOR_TASKS_MAX
    items, seen = [], {}
    for row in rows[:CREATOR_TASKS_MAX]:
        r = dict(zip(select, row))
        tid = str(r.get("id"))[:120]
        caps = _str_list(r.get("required_capabilities"))
        risk, basis = _risk(r.get("risk_class"), None)
        np = [k for k in ("version", "input_schema", "output_schema", "required_capabilities", "risk_class", "availability") if r.get(k) in (None, "")]
        rec = envelope("catalog_item", f"creator-task:{tid}", src, observed, "valid", "Catalog metadata only; tasks are never executed from the dashboard.",
                       source_id=tid, item_type="task_definition", name=safe_text(r.get("name"), 120), version=safe_text(r.get("version"), 40),
                       content_hash=sha256_text(json.dumps(r, sort_keys=True, default=str)), input_schema_summary=_schema_summary(r.get("input_schema")),
                       output_schema_summary=_schema_summary(r.get("output_schema")), declared_capabilities=caps or [], risk_class=risk, risk_basis=basis,
                       availability=safe_text(r.get("availability"), 40), enabled=False, activation="cataloged_not_executable", not_provided=np)
        if tid in seen:
            seen[tid].update(validity="conflict", display=DISPLAY["conflict"], reason="duplicate task id in task_definitions")
            continue
        seen[tid] = rec
        items.append(rec)
    reason = f"{len(items)} task definition(s)" + (f"; truncated at {CREATOR_TASKS_MAX}" if truncated else "")
    return _co_result(src, "valid", reason, observed, counts, items)


# ------------------------------------------------------------------ filesystem catalogs (skills / prompts / bots)
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


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root)
        return True
    except (ValueError, OSError):
        return False


def _tree_hash(directory: Path, root: Path):
    """Bounded, symlink-free content hash of a directory: sha256 over 'relpath\\0size\\0sha256' lines. Files are read, never run."""
    lines, total, count, truncated = [], 0, 0, False
    for path in sorted(directory.rglob("*")):
        if count >= TREE_MAX_FILES:
            truncated = True
            break
        if path.is_symlink() or not path.is_file() or not _inside(path, root):
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


def _candidates(kind, root: Path):
    if kind == "skill":
        return sorted(root.glob("*/SKILL.md")) + sorted(root.glob("*/*/SKILL.md"))
    if kind == "prompt":
        return sorted({p for pat in ("*.md", "*/*.md", "*.prompt", "*/*.prompt", "*.txt", "*/*.txt") for p in root.glob(pat)})
    return sorted(root.glob("*/bot.json")) + sorted(root.glob("*.bot.json"))


def _parse_item(kind, path: Path, root: Path):
    raw = path.read_bytes()
    text = raw.decode("utf-8", "replace")
    if kind == "bot":
        try:
            meta = json.loads(text)
        except ValueError as error:
            raise ValueError(f"bot manifest is not valid JSON: {error}") from None
        if not isinstance(meta, dict):
            raise ValueError("bot manifest must be a JSON object")
        meta = {str(k).lower(): v for k, v in meta.items()}
        tools = _str_list(meta.get("tools")) or []
    else:
        meta = _frontmatter(text)
        tools = _str_list(meta.get("allowed-tools") or meta.get("tools")) or []
    caps = _str_list(meta.get("capabilities")) or tools
    perms = _str_list(meta.get("permissions"))
    if kind == "skill":
        tree, nfiles, truncated = _tree_hash(path.parent, root)
    else:
        tree, nfiles, truncated = None, 1, False
    return meta, raw, caps, perms, tools, tree, nfiles, truncated


class CatalogRootAdapter:
    """Allowlisted, read-only catalog roots for one item type. Discovery is not activation: every item is enabled=false.
    Files are read (bounded) and hashed; nothing is executed, imported or loaded. Content is never returned, only metadata."""

    def __init__(self, kind, roots, now=None, source_prefix=None):
        self.kind, self.roots = kind, roots
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.prefix = source_prefix or f"{kind}s"

    def read(self):
        observed = utc_iso(self.now())
        connectors, items = [], []
        for label, raw_path in self.roots:
            src = f"{self.prefix}:{label}"
            root, problem = check_root(raw_path)
            if problem:
                connectors.append(envelope("connector", f"connector:{src}", src, None, problem[0], f"{self.kind} root {problem[1]}",
                                           name=f"{self.kind.capitalize()} root {label}", transport="filesystem read-only", part="catalogs"))
                continue
            root = root.resolve()
            found, errors = 0, 0
            for path in _candidates(self.kind, root):
                if found >= MAX_ITEMS_PER_ROOT:
                    break
                rel = path.relative_to(root)
                rel_id = (rel.parent if self.kind == "skill" else rel).as_posix()
                if any(p.startswith(".") and p != ".system" for p in rel.parts) or path.is_symlink() or (self.kind == "skill" and path.parent.is_symlink()):
                    continue
                item_id = f"{self.kind}:{label}/{rel_id}"
                try:
                    if not _inside(path, root):
                        raise ValueError("resolves outside the configured root")
                    if path.stat().st_size > FILE_MAX:
                        raise ValueError(f"file larger than {FILE_MAX} bytes")
                    meta, raw, caps, perms, tools, tree, nfiles, truncated = _parse_item(self.kind, path, root)
                except (OSError, ValueError) as error:
                    errors += 1
                    items.append(envelope("catalog_item", item_id, src, observed, "not_verified", f"not catalogued: {error}", source_id=rel_id, source_path=rel.as_posix(),
                                          item_type=self.kind, name=rel_id, enabled=False, activation="discovered_not_activated",
                                          not_provided=["name", "version", "content_hash"]))
                    continue
                name = meta.get("name") if isinstance(meta.get("name"), str) else None
                version = meta.get("version") if isinstance(meta.get("version"), str) else None
                risk, basis = _risk(meta.get("risk") or meta.get("risk_class"), tools)
                np = [k for k, v in (("name", name), ("version", version), ("declared_capabilities", caps), ("required_permissions", perms)) if v in (None, [], "")]
                if basis == "none":
                    np.append("risk_class")
                requested_enable = meta.get("enabled") is True or str(meta.get("enabled")).lower() == "true"
                reason = "Discovered read-only; not activated, not executed." + (" The file asks for enabled=true; ignored (discovery is not activation)." if requested_enable else "")
                items.append(envelope("catalog_item", item_id, src, observed, "valid", reason, source_id=rel_id, source_path=rel.as_posix(),
                                      item_type=self.kind, name=safe_text(name or (path.parent.name if self.kind == "skill" else path.stem), 80),
                                      version=safe_text(version, 40), description=safe_text(meta.get("description"), 240),
                                      runtime=safe_text(meta.get("runtime"), 60) if self.kind == "bot" else None,
                                      content_hash=sha256_bytes(raw), tree_hash=tree, file_count=nfiles, tree_truncated=truncated,
                                      declared_capabilities=caps[:40], required_permissions=perms or [], risk_class=risk, risk_basis=basis,
                                      enabled=False, activation="discovered_not_activated", not_provided=np))
                found += 1
            connectors.append(envelope("connector", f"connector:{src}", src, observed, "valid",
                                       f"{found} {self.kind}(s) catalogued" + (f"; {errors} file(s) not catalogued (see items marked NOT_VERIFIED)" if errors else ""),
                                       name=f"{self.kind.capitalize()} root {label}", transport="filesystem read-only", part="catalogs"))
        _mark_duplicate_names(items)
        return connectors, items


def _mark_duplicate_names(items):
    groups = collections.defaultdict(list)
    for it in items:
        if it.get("validity") == "valid" and it.get("name"):
            groups[(it["item_type"], it["name"].lower())].append(it)
    for group in groups.values():
        if len(group) > 1:
            where = ", ".join(i["id"] for i in group)[:300]
            for it in group:
                it.update(validity="conflict", display=DISPLAY["conflict"], reason=f"duplicate name in {len(group)} locations: {where}")


# ------------------------------------------------------------------ Obsidian (metadata only)
class ObsidianAdapter:
    """Metadata-only, read-only vault view rooted ONLY at ORCHESTRATOR_VAULT_ROOT. Note content is never returned; tags, backlinks,
    link counts and task-checkbox counts are derived. If the root has no .obsidian folder (it may be a vault subfolder) the vault
    identity is UNVERIFIED; parent directories are never read."""

    def __init__(self, root, now=None, source="obsidian", clock=time.monotonic):
        self.root, self.source, self.clock = root, source, clock
        self.now = now or (lambda: datetime.now(timezone.utc))

    def read(self):
        observed = utc_iso(self.now())
        root, problem = check_root(self.root)
        if problem:
            reason = ("ORCHESTRATOR_VAULT_ROOT is not configured; Obsidian is NOT_VERIFIED." if problem[0] == "not_configured" else f"ORCHESTRATOR_VAULT_ROOT {problem[1]}")
            return envelope("connector", "connector:obsidian", self.source, None, problem[0], reason, name="Obsidian vault", transport="filesystem read-only", part="obsidian"), []
        root = root.resolve()
        identity_verified = (root / ".obsidian").is_dir()
        start, notes, scanned, skipped, bytes_read, stopped = self.clock(), [], 0, 0, 0, None
        link_targets = collections.Counter()
        for path in root.rglob("*.md"):
            if scanned >= NOTES_SCANNED_MAX:
                stopped = f"note scan cap {NOTES_SCANNED_MAX}"
                break
            if self.clock() - start > VAULT_TIME_BUDGET_S:
                stopped = f"time budget {VAULT_TIME_BUDGET_S} s"
                break
            rel = path.relative_to(root)
            if any(part in SKIP_DIRS or part.startswith(".") for part in rel.parts[:-1]) or path.is_symlink() or not _inside(path, root):
                skipped += 1
                continue
            scanned += 1
            try:
                st = path.stat()
                if st.st_size > NOTE_MAX_BYTES or bytes_read + st.st_size > VAULT_BYTES_MAX:
                    tags, links, digest, open_t, done_t = [], [], None, None, None
                else:
                    data = path.read_bytes()
                    bytes_read += len(data)
                    text = data.decode("utf-8", "replace")
                    tags = sorted(set(_TAG.findall(text)))[:20]
                    links = [l.strip() for l in _WIKILINK.findall(text)][:200]
                    digest, open_t, done_t = sha256_bytes(data), len(_TASK_OPEN.findall(text)), len(_TASK_DONE.findall(text))
            except OSError:
                skipped += 1
                continue
            for target in links:
                link_targets[Path(target).stem.lower()] += 1
            if len(notes) < NOTES_LISTED_MAX:
                notes.append(envelope("catalog_item", f"note:{rel.as_posix()}", self.source, observed, "valid", "Metadata only; note content is not returned.",
                                      source_id=rel.as_posix(), source_path=rel.as_posix(), item_type="note", name=safe_text(rel.as_posix(), 160), size=st.st_size,
                                      modified_at=utc_iso(datetime.fromtimestamp(st.st_mtime, timezone.utc)), tags=[safe_text(t, 60) for t in tags],
                                      outgoing_links=len(links), backlinks=0, open_tasks=open_t, done_tasks=done_t, content_hash=digest,
                                      enabled=False, activation="metadata_only",
                                      not_provided=[] if digest else ["content_hash", "tags", "open_tasks", "done_tasks"]))
        for n in notes:  # backlinks among the scanned notes only (bounded)
            n["backlinks"] = link_targets.get(Path(n["source_id"]).stem.lower(), 0)
        reason = (f"{scanned} note(s) scanned, {len(notes)} listed (cap {NOTES_LISTED_MAX})" + (f", {skipped} skipped" if skipped else "")
                  + (f"; scan stopped at {stopped} (partial)" if stopped else "")
                  + ("" if identity_verified else "; no .obsidian folder in the configured root, so vault identity is NOT_VERIFIED"))
        conn = envelope("connector", "connector:obsidian", self.source, observed, "valid" if identity_verified and not stopped else "untrusted", reason,
                        name="Obsidian vault", transport="filesystem read-only", part="obsidian", vault_name=root.name,
                        vault_id=sha256_text(str(root))[:23], notes_scanned=scanned, identity_verified=identity_verified)
        return conn, notes


# ------------------------------------------------------------------ tool manifests (manifest-only; nothing is executed)
TOOL_REQUIRED = ("id", "name", "version", "transport", "input_schema", "output_schema", "capabilities", "required_permissions", "risk", "timeout_s", "output_limit_bytes")


def _validate_tool(m):
    errs = [f"missing {k}" for k in TOOL_REQUIRED if k not in m]
    if m.get("transport") not in ("cli", "http-loopback"):
        errs.append("transport must be cli or http-loopback")
    if m.get("transport") == "cli":
        argv = m.get("argv")
        if not (isinstance(argv, list) and argv and all(isinstance(a, str) for a in argv)):
            errs.append("cli tools need a fixed argv list of strings (no shell command line)")
        elif any(_SHELL_META.search(a) for a in argv):
            errs.append("shell metacharacters in argv are rejected")
    if m.get("transport") == "http-loopback":
        host = urlparse(str(m.get("endpoint", ""))).hostname
        if host not in ("127.0.0.1", "localhost", "::1"):
            errs.append("http-loopback tools need a loopback endpoint")
    t = m.get("timeout_s")
    if not isinstance(t, (int, float)) or isinstance(t, bool) or not 1 <= t <= 120:
        errs.append("timeout_s must be 1..120")
    o = m.get("output_limit_bytes")
    if not isinstance(o, int) or isinstance(o, bool) or not 1 <= o <= 1_048_576:
        errs.append("output_limit_bytes must be 1..1048576")
    if m.get("risk") not in RISKS[:3]:
        errs.append("risk must be low, medium or high")
    for k in ("input_schema", "output_schema"):
        if k in m and not isinstance(m[k], dict):
            errs.append(f"{k} must be an object")
    for k in ("capabilities", "required_permissions"):
        if k in m and not isinstance(m[k], list):
            errs.append(f"{k} must be a list")
    return errs


def read_tool_manifests(dir_raw, observed, source="tools"):
    src = f"{source}:manifests"
    root, problem = check_root(dir_raw)
    if problem:
        conn = envelope("connector", "connector:tool-manifests", src, None, problem[0], f"tool manifest directory {problem[1]}", name="Tool manifests",
                        transport="filesystem read-only", part="tools")
        return {"connectors": [conn], "catalogs": {"tools": section([], src, None, problem[0], conn["reason"])}}
    root = root.resolve()
    items, seen = [], {}
    for path in sorted(root.glob("*.json"))[:MANIFESTS_MAX]:
        if path.is_symlink() or not _inside(path, root):
            continue
        rel = path.name
        try:
            if path.stat().st_size > MANIFEST_MAX_BYTES:
                raise ValueError(f"manifest larger than {MANIFEST_MAX_BYTES} bytes")
            raw = path.read_bytes()
            m = json.loads(raw.decode("utf-8"))
            if not isinstance(m, dict):
                raise ValueError("manifest must be a JSON object")
        except (OSError, ValueError) as error:
            items.append(envelope("catalog_item", f"tool:{rel}", src, observed, "not_verified", f"not catalogued: {error}", source_id=rel, source_path=rel,
                                  item_type="tool", name=rel, enabled=False, activation="manifest_only"))
            continue
        errs = _validate_tool(m)
        tid = str(m.get("id") or rel)[:80]
        enable_note = " The manifest asks for enabled=true; ignored (manifest-only registry)." if m.get("enabled") is True else ""
        t, o = m.get("timeout_s"), m.get("output_limit_bytes")
        rec = envelope("catalog_item", f"tool:{tid}", src, observed, "not_verified" if errs else "valid",
                       ("manifest invalid: " + "; ".join(errs)) if errs else "Manifest only; this registry never executes tools." + enable_note,
                       source_id=tid, source_path=rel, item_type="tool", name=safe_text(m.get("name"), 80), version=safe_text(m.get("version"), 40),
                       transport=safe_text(m.get("transport"), 20), target=safe_text(" ".join(m["argv"]) if isinstance(m.get("argv"), list) else m.get("endpoint"), 160),
                       input_schema_summary=_schema_summary(m.get("input_schema")), output_schema_summary=_schema_summary(m.get("output_schema")),
                       declared_capabilities=_str_list(m.get("capabilities")) or [], required_permissions=_str_list(m.get("required_permissions")) or [],
                       risk_class=m.get("risk") if m.get("risk") in RISKS[:3] else "unclassified", risk_basis="declared" if m.get("risk") in RISKS[:3] else "none",
                       timeout_s=t if isinstance(t, (int, float)) and not isinstance(t, bool) else None,
                       output_limit_bytes=o if isinstance(o, int) and not isinstance(o, bool) else None,
                       content_hash=sha256_bytes(raw), enabled=False, activation="manifest_only")
        if tid in seen:
            seen[tid].update(validity="conflict", display=DISPLAY["conflict"], reason=f"duplicate tool id also in {rel}")
            rec.update(validity="conflict", display=DISPLAY["conflict"], reason=f"duplicate tool id also in {seen[tid]['source_path']}")
        seen.setdefault(tid, rec)
        items.append(rec)
    conn = envelope("connector", "connector:tool-manifests", src, observed, "valid", f"{len(items)} manifest(s)", name="Tool manifests",
                    transport="filesystem read-only", part="tools")
    return {"connectors": [conn], "catalogs": {"tools": section(items, src, observed, "valid", "Manifest-only registry; no tool is executed.")}}


# Self-evolution proposals and experiments: see hive_evolution.py (read by the `proposals` part).


# ------------------------------------------------------------------ evidence log, cache, isolation
_LOGS = {"live": collections.deque(maxlen=200), "fixture": collections.deque(maxlen=200)}
_LOG_LOCK = threading.Lock()


def record_evidence(connectors, observed, mode="live"):
    log = _LOGS["fixture" if mode == "fixture" else "live"]
    with _LOG_LOCK:
        for c in connectors:
            basis = f"{c['id']}|{observed}|{c['validity']}"
            log.appendleft(envelope("evidence_record", "evidence:" + hashlib.sha256(basis.encode()).hexdigest()[:16], c["source"], observed, c["validity"],
                                    c.get("reason"), source_id=c["id"], subject=c["id"]))
        return list(log)[:50]


class RegistryCache:
    """Per-part result cache (TTL from PART_LIMITS) so a page refresh does not rescan filesystems or the database."""

    def __init__(self, clock=time.monotonic):
        self.clock, self.data, self.lock = clock, {}, threading.Lock()

    def get(self, key, ttl):
        with self.lock:
            hit = self.data.get(key)
            if hit and self.clock() - hit[0] < ttl:
                return hit[1], round(self.clock() - hit[0], 1)
        return None, None

    def put(self, key, value):
        with self.lock:
            self.data[key] = (self.clock(), value)


_EXECUTOR = ThreadPoolExecutor(max_workers=8, thread_name_prefix="hive-registry")


def _run_parts(jobs, cache, cache_prefix):
    """Run each part in its own thread with its own timeout. A part that times out is reported unavailable; the others are unaffected.
    A late result still fills the cache for the next request. Returns {part: (result | None, meta)}."""
    out, futures = {}, {}
    for part, fn in jobs.items():
        timeout, ttl = PART_LIMITS[part]
        key = f"{cache_prefix}|{part}"
        if cache is not None:
            hit, age = cache.get(key, ttl)
            if hit is not None:
                out[part] = (hit, {"cached": True, "age_s": age, "timeout_s": timeout})
                continue

        def runner(fn=fn, key=key):
            t0 = time.monotonic()
            res = fn()
            if cache is not None:
                cache.put(key, res)
            return res, round(time.monotonic() - t0, 3)
        futures[part] = (_EXECUTOR.submit(runner), time.monotonic(), timeout)
    for part, (fut, started, timeout) in futures.items():
        remaining = max(0.0, timeout - (time.monotonic() - started))
        done, _ = wait([fut], timeout=remaining)
        if not done:
            out[part] = (None, {"cached": False, "timed_out": True, "timeout_s": timeout, "error": f"source did not answer within {timeout} s"})
            continue
        try:
            res, took = fut.result()
            out[part] = (res, {"cached": False, "duration_s": took, "timeout_s": timeout})
        except Exception as error:  # an adapter bug must not take down the other parts
            out[part] = (None, {"cached": False, "timeout_s": timeout, "error": f"{type(error).__name__}: {str(error)[:160]}"})
    return out


def build_registry(fetch, config: RegistryConfig | None = None, *, bucket=lambda s: str(s).lower(), now=None, mode="live", parts=None,
                   cache=None, core_scope=None, creator_ops_counts=None, proposals_path=PROPOSALS_PATH, acceptance_path=ACCEPTANCE_PATH,
                   probe_opener=None, datasets_path=None):
    cfg = config if config is not None else config_from_env()
    clock = now or (lambda: datetime.now(timezone.utc))
    wanted = [p for p in (parts or PARTS) if p in PART_LIMITS]
    fx = mode == "fixture"
    observed = utc_iso(clock())

    def creator():
        counts = None
        if creator_ops_counts:
            try:
                counts = (creator_ops_counts() or {}).get("counts") or None
            except Exception:  # counts are optional context only
                counts = None
        return read_creator_ops(cfg.creator_ops_db, observed, counts, "fixture:creator-ops" if fx else "creator-ops")

    def obsidian():
        conn, notes = ObsidianAdapter(cfg.vault_root, clock, "fixture:obsidian" if fx else "obsidian").read()
        return {"connectors": [conn], "catalogs": {"obsidian": section(notes, conn["source"], conn["observed_at"], conn["validity"], conn["reason"])}}

    def catalogs():
        out = {"connectors": [], "catalogs": {}}
        for kind, roots, key in (("skill", cfg.skill_roots, "skills"), ("prompt", cfg.prompt_roots, "prompts"), ("bot", cfg.bot_roots, "bots")):
            conns, items = CatalogRootAdapter(kind, roots, clock, ("fixture:" if fx else "") + key).read()
            out["connectors"] += conns
            if not roots:
                out["catalogs"][key] = section([], "none", None, "not_configured", f"No {key} root is configured ({cfg.sources.get(key, '')}).")
            else:
                out["catalogs"][key] = section(items, f"{key}: {len(roots)} configured root(s)", observed, "valid",
                                               f"Aggregate of {len(roots)} root(s); each root reports its own state. Discovered read-only; nothing is activated or executed.",
                                               aggregate=True)
        return out

    def evolution():
        import hive_evolution
        return hive_evolution.read_evolution(proposals_path, acceptance_path, clock(), datasets_path or hive_evolution.DATASETS)

    def internet():
        import hive_probes
        return hive_probes.read_internet(cfg.internet_probes, observed, probe_opener, "fixture:internet" if fx else "internet")

    jobs = {"core": lambda: read_core(fetch, bucket, clock, core_scope, cfg.agents_config), "creator_ops": creator, "obsidian": obsidian, "catalogs": catalogs,
            "tools": lambda: read_tool_manifests(cfg.tool_manifest_dir, observed, "fixture:tools" if fx else "tools"),
            "proposals": evolution, "internet": internet}
    results = _run_parts({p: jobs[p] for p in wanted}, cache, f"{mode}|{config_signature(cfg)}")
    reg = {"schema_version": SCHEMA_VERSION, "generated_at": observed, "mode": mode, "read_only": True, "executes_nothing": True,
           "parts": {}, "config_sources": dict(cfg.sources), "connectors": []}
    for part in wanted:
        res, meta = results[part]
        reg["parts"][part] = meta
        if res is None:
            reg["connectors"].append(envelope("connector", f"connector:part:{part}", f"registry:{part}", None, "unavailable", meta.get("error"),
                                              name=f"{part} source", transport="isolated adapter", part=part))
            continue
        res = json.loads(json.dumps(res))  # never hand out (or later mutate) the cached object
        for key, value in res.items():
            if key == "connectors":
                reg["connectors"] += value
            elif key in ("catalogs", "tasks"):
                reg.setdefault(key, {}).update(value)
            else:
                reg[key] = value
    if fx:
        _label_fixture(reg)
    reg["evidence_log"] = record_evidence(reg["connectors"], observed, mode)
    return reg


def _label_fixture(node):
    """Fixture mode: every record and section is visibly fixture data and can never read as live."""
    if isinstance(node, dict):
        if node.get("validity") == "valid":
            node["validity"] = "fixture"
            if node.get("display") is not None:
                node["display"] = DISPLAY["fixture"]
        if isinstance(node.get("source"), str) and not node["source"].startswith("fixture"):
            node["source"] = "fixture:" + node["source"]
        for v in node.values():
            _label_fixture(v)
    elif isinstance(node, list):
        for v in node:
            _label_fixture(v)


# ------------------------------------------------------------------ schema (generated; schemas/hive-readonly-v2.schema.json must equal it)
_S, _N, _I, _B, _A = {"type": "string"}, {"type": ["string", "null"]}, {"type": "integer"}, {"type": "boolean"}, {"type": "array", "items": {"type": "string"}}
_NI = {"type": ["integer", "null"]}
_ENVELOPE = {"kind": _S, "id": _S, "source": _S, "source_id": _N, "observed_at": _N, "validity": {"enum": list(VALIDITIES)}, "reason": _N,
             "correlation_id": _N, "schema_version": {"const": SCHEMA_VERSION}, "display": {"enum": sorted(set(DISPLAY.values()))}, "not_provided": _A}
_KINDS = {
    "connector": {"name": _S, "transport": _S, "part": {"enum": list(PARTS)}, "vault_name": _S, "vault_id": _S, "notes_scanned": _I, "identity_verified": _B,
                  "table_counts": {"type": "object"}, "target_host": _N, "status_code": _NI, "latency_ms": _NI},
    "agent": {"role_id": _N, "classification": {"const": "UNKNOWN"}, "classification_reason": _S, "provider": _N, "model": _N, "last_state": {"enum": list(hive_events.STATES)},
              "last_event_id": _N, "last_event_type": _N, "task_id": _N, "age_s": {"type": ["number", "null"]}, "declared_role": _N},
    "agent_profile": {"agent_id": _S, "display_name": _N, "classification": {"const": "UNKNOWN"}, "classification_reason": _S, "role": _N, "role_basis": _N,
                      "status": {"enum": ["IMPLEMENTED", "CONFIGURED", "OBSERVED", "PROPOSED", "NOT_VERIFIED", "DISABLED"]},
                      "lifecycle": {"enum": ["DISCOVERED", "CONFIGURED", "HEALTHY", "DEGRADED", "OFFLINE", "PAUSED", "DISABLED", "PROPOSED", "UNKNOWN"]},
                      "last_state": {"enum": list(hive_events.STATES) + [None]}, "last_event_id": _N, "task_id": _N, "age_s": {"type": ["number", "null"]},
                      "documented_sources": _A, "excluded": _A, "responsibilities": _A, "capabilities": _A, "required_permissions": _A, "allowed_tools": _A,
                      "preferred_task_types": _A, "worker_requirements": _A, "health_checks": _A},
    "ultron_observation": {"category": {"enum": ["agent_health", "blocked_agent", "stale_agent", "worker_health", "task_routing", "connector_health",
                                                 "system_stability", "permission_failure", "repeated_failure", "internet_health"]},
                           "severity": {"enum": ["info", "warning", "critical"]}, "subject": _N, "evidence_ids": _A, "action": {"const": "none (observation only)"}},
    "experiment": {"experiment_id": _S, "domain": _S, "dataset_path": _S, "dataset_sha256": _N, "baseline": {"type": ["object", "null"]},
                   "candidates": {"type": "array"}, "fixture_only": {"const": True}, "adopted": {"const": False}},
    "role": {"role_id": _S, "descriptor": _S, "classification": {"const": "UNKNOWN"}, "provider": {"type": "null"}},
    "worker": {"name": _N, "provider": _N, "model": _N, "status_raw": _N, "status": _S, "capabilities": _A, "current_task": _N, "heartbeat": _N,
               "freshness": {"enum": ["live", "stale", "offline", "unknown"]}},
    "provider": {"label": _S, "observed_workers": _A},
    "capability": {"name": _S, "declared_by": _A},
    "task_instance": {"title": _N, "status_raw": _N, "status": _S, "assigned_worker": _N, "project_id": _N, "required_capabilities": _A, "created_at": _N, "updated_at": _N},
    "catalog_item": {"item_type": {"enum": ["skill", "prompt", "bot", "note", "tool", "task_definition"]}, "name": _N, "version": _N, "description": _N,
                     "source_path": _S, "runtime": _N, "content_hash": _N, "tree_hash": _N, "file_count": _I, "tree_truncated": _B, "declared_capabilities": _A,
                     "required_permissions": _A, "risk_class": {"enum": list(RISKS)}, "risk_basis": {"enum": ["declared", "derived_from_declared_tools", "none"]},
                     "enabled": {"const": False}, "activation": {"enum": ["discovered_not_activated", "metadata_only", "manifest_only", "cataloged_not_executable"]},
                     "size": _I, "modified_at": _N, "tags": {"type": "array"}, "outgoing_links": _I, "backlinks": _I, "open_tasks": _NI, "done_tasks": _NI,
                     "transport": _N, "target": _N, "input_schema_summary": _N, "output_schema_summary": _N, "availability": _N,
                     "timeout_s": {"type": ["number", "null"]}, "output_limit_bytes": _NI},
    "proposal": {"proposal_id": _S, "domain": _S, "gap_id": _N, "baseline": _N, "candidate": _N, "evidence": {"type": "array"}, "hypothesis": _N, "problem": _N,
                 "expected_benefit": _N, "success_metrics": {"type": "array"}, "success_met": {"type": ["array", "null"]}, "experiment_id": _N,
                 "affected_area": _N, "affected_files": _A, "risk": {"enum": list(RISKS)}, "required_permissions": _A, "test_plan": _A, "rollback_plan": _N,
                 "rollback_ref": _N, "status": {"enum": list(PROPOSAL_STATUSES)},
                 "stage": {"enum": ["OBSERVE", "MEASURE", "DETECT", "HYPOTHESIZE", "PROPOSE", "SANDBOX_FIXTURE_TEST", "COMPARE_WITH_BASELINE", "HUMAN_REVIEW",
                                    "VERSION", "MONITOR", "ROLLBACK"]},
                 "proposal_only": {"const": True}, "applied": {"const": False}, "created_at": _N, "expires_at": _N},
    "evidence_record": {"subject": _S},
    "ultron_status": {"state": {"enum": list(hive_events.STATES)}, "freshness_window_s": _I, "last_event_id": _N, "last_event_type": _N,
                      "last_state": {"enum": list(hive_events.STATES) + [None]}, "age_s": {"type": ["number", "null"]}, "recent": {"type": "array"}},
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
                                "properties": {"source": _S, "observed_at": _N, "validity": {"enum": list(VALIDITIES)}, "reason": _N, "display": _N},
                                "additionalProperties": False}
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


def iter_sections(reg):
    """Every section evidence block in a registry response."""
    if isinstance(reg, dict):
        if "kind" in reg and "schema_version" in reg:
            return
        if "evidence" in reg and "items" in reg:
            yield reg["evidence"]
        for value in reg.values():
            yield from iter_sections(value)
    elif isinstance(reg, list):
        for value in reg:
            yield from iter_sections(value)


def validate_registry(reg):
    schema = build_schema()
    errs = []
    for rec in iter_records(reg):
        kind = rec.get("kind")
        if kind not in schema["$defs"]:
            errs.append(f"{rec.get('id')}: unknown kind {kind!r}")
            continue
        errs += validate(rec, {"$ref": f"#/$defs/{kind}"}, schema, rec.get("id", "?"))
    for ev in iter_sections(reg):
        errs += validate(ev, {"$ref": "#/$defs/section_evidence"}, schema, "section")
    return errs


if __name__ == "__main__":  # python hive_registry.py --write-schema
    import sys
    if "--write-schema" in sys.argv:
        SCHEMA_PATH.parent.mkdir(parents=True, exist_ok=True)
        SCHEMA_PATH.write_text(json.dumps(build_schema(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print("wrote", SCHEMA_PATH)
