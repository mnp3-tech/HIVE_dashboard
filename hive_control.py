"""Read-only agent / role control plane and ULTRON observation layer (P1.3, observation and proposal phase only).

* Agent profiles merge the reviewed configuration (config/agents.json) with identities HIVE Core events actually named.
  A documented-only agent is never active: its runtime validity is NOT_VERIFIED and its lifecycle CONFIGURED.
* Primary/secondary classification is always UNKNOWN until an authoritative source or approved mapping exists.
* Agents are never joined to workers or tasks unless the agent's own event names the task: no invented relationships.
* ULTRON observations are derived only from evidence (Core health, workers, tasks, events). ULTRON takes no action: it
  cannot grant permissions, activate skills, start/stop agents or change external systems. Silence is never ACTIVE.
Stdlib only; uses the registry envelope so every record carries source, observed_at, validity, reason and correlation_id.
"""
from __future__ import annotations

import collections
import json
import re
from pathlib import Path

import hive_registry as hr

AGENTS_CONFIG_PATH = hr.ROOT / "config" / "agents.json"
AGENT_STATUSES = ("IMPLEMENTED", "CONFIGURED", "OBSERVED", "PROPOSED", "NOT_VERIFIED", "DISABLED")
LIFECYCLES = ("DISCOVERED", "CONFIGURED", "HEALTHY", "DEGRADED", "OFFLINE", "PAUSED", "DISABLED", "PROPOSED", "UNKNOWN")
OBSERVATION_CATEGORIES = ("agent_health", "blocked_agent", "stale_agent", "worker_health", "task_routing", "connector_health",
                          "system_stability", "permission_failure", "repeated_failure", "internet_health")
SEVERITIES = ("info", "warning", "critical")
LIST_FIELDS = ("responsibilities", "capabilities", "required_permissions", "allowed_tools", "preferred_task_types", "worker_requirements", "health_checks")
CONFIG_MAX_BYTES = 256 * 1024
REPEATED_FAILURE_MIN = 3
ERROR_BURST_MIN = 5
_PERMISSION_EVENT = re.compile(r"PERMISSION|DENIED|FORBIDDEN|UNAUTHORI[SZ]ED|SANDBOX|BLOCKED", re.I)
HEALTHY_STATES, DEGRADED_STATES = ("IDLE", "WORKING", "REVIEW"), ("FAILED", "WAITING_APPROVAL", "SECURITY_BLOCKED")


def load_agent_config(path=AGENTS_CONFIG_PATH):
    """(agents, problem). Bounded read; a missing or malformed file is reported, never replaced by defaults."""
    try:
        p = Path(path)
        if p.stat().st_size > CONFIG_MAX_BYTES:
            return [], ("not_verified", f"agent configuration larger than {CONFIG_MAX_BYTES} bytes")
        doc = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return [], ("inaccessible", "agent configuration file is missing")
    except (OSError, ValueError) as error:
        return [], ("not_verified", f"agent configuration unreadable: {error}")
    agents = doc.get("agents") if isinstance(doc, dict) else None
    if not isinstance(agents, list):
        return [], ("not_verified", "agent configuration has no 'agents' list")
    return [a for a in agents if isinstance(a, dict) and isinstance(a.get("agent_id"), str) and a["agent_id"].strip()], None


def _lifecycle_from_observation(obs):
    if obs["validity"] == "stale":
        return "UNKNOWN", "last observation expired"
    if obs["validity"] == "untrusted":
        return "UNKNOWN", "only untrusted observations"
    state = obs.get("last_state") or "UNKNOWN"
    if state in HEALTHY_STATES:
        return "HEALTHY", None
    if state in DEGRADED_STATES:
        return "DEGRADED", f"latest observed state {state}"
    if state == "OFFLINE":
        return "OFFLINE", "latest observed state OFFLINE"
    return "UNKNOWN", "latest observed state UNKNOWN"


def agent_profiles(config_agents, config_problem, observed, core_reachable, observed_at, source="config/agents.json"):
    """Merge configured agents with observed identities. Returns (profiles, section_validity, section_reason)."""
    by_obs = {str(o.get("role_id") or "").upper(): o for o in observed}
    ids = collections.Counter(str(a["agent_id"]).strip().upper() for a in config_agents)
    profiles, seen = [], set()
    for a in config_agents:
        aid = str(a["agent_id"]).strip().upper()[:60]
        obs = by_obs.get(aid)
        lists = {f: hr._str_list(a.get(f)) or [] for f in LIST_FIELDS}
        configured = a.get("configured_status") if a.get("configured_status") in AGENT_STATUSES else "NOT_VERIFIED"
        excluded = hr._str_list(a.get("excluded")) or []
        status, lifecycle, validity, reason, last = configured, None, None, None, {}
        if obs is not None:
            last = obs
            if obs["validity"] in ("valid", "fixture"):
                status = "OBSERVED"
            lifecycle, why = _lifecycle_from_observation(obs)
            validity, reason = obs["validity"], why or "Observed in a fresh, trusted HIVE Core event."
            declared = obs.get("declared_role")
            if isinstance(declared, str) and declared.strip() and a.get("role") and declared.strip().lower() != str(a.get("role")).strip().lower():
                validity, reason = "conflict", f"role conflict: configuration says {a.get('role')!r}, HIVE Core event says {declared!r}"
        elif configured == "DISABLED":
            lifecycle, validity, reason = "DISABLED", "not_verified", "Disabled in the configuration (documented as future-only); never active."
        elif configured == "PROPOSED":
            lifecycle, validity, reason = "PROPOSED", "not_verified", "Proposed on owner instruction; no documentation, capabilities, permissions or runtime status."
        elif not core_reachable:
            lifecycle, validity, reason = "UNKNOWN", "unavailable", "Configured; HIVE Core transport unavailable, so runtime state cannot be observed."
        else:
            lifecycle, validity, reason = "CONFIGURED", "not_verified", "Documented/configured only; no HIVE Core observation. Not active."
        if ids[aid] > 1:
            validity, reason = "conflict", f"duplicate agent_id {aid} in the configuration ({ids[aid]} entries)"
        np = ["classification"] + [f for f in LIST_FIELDS if not lists[f]] + ([] if a.get("role") else ["role"])
        profiles.append(hr.envelope("agent_profile", f"agent-profile:{aid}" + (f"#{len([p for p in profiles if p['agent_id'] == aid]) + 1}" if aid in seen else ""),
                                    source if obs is None else f"{source} + hive:/events", last.get("observed_at") if obs else observed_at,
                                    validity, reason, source_id=aid, correlation_id=last.get("correlation_id"),
                                    agent_id=aid, display_name=hr.safe_text(a.get("display_name") or aid, 60), classification="UNKNOWN",
                                    classification_reason="No authoritative primary/secondary source or approved mapping exists.",
                                    role=hr.safe_text(a.get("role"), 120), role_basis=hr.safe_text(a.get("role_basis"), 200), status=status, lifecycle=lifecycle,
                                    last_state=last.get("last_state"), last_event_id=last.get("last_event_id"), task_id=last.get("task_id"), age_s=last.get("age_s"),
                                    documented_sources=hr._str_list(a.get("sources"), 10) or [], excluded=excluded[:20], not_provided=np, **lists))
        seen.add(aid)
    for key, obs in sorted(by_obs.items()):
        if not key or key in ids:
            continue
        lifecycle, why = _lifecycle_from_observation(obs)
        profiles.append(hr.envelope("agent_profile", f"agent-profile:{key}", "hive:/events", obs.get("observed_at"), obs["validity"],
                                    f"Discovered in HIVE Core events but not in the configuration. {why or ''}".strip(), source_id=key,
                                    correlation_id=obs.get("correlation_id"), agent_id=key, display_name=hr.safe_text(obs.get("role_id"), 60),
                                    classification="UNKNOWN", classification_reason="No authoritative primary/secondary source or approved mapping exists.",
                                    role=None, role_basis="not configured", status="OBSERVED" if obs["validity"] in ("valid", "fixture") else "NOT_VERIFIED",
                                    lifecycle="DISCOVERED" if obs["validity"] in ("valid", "fixture") else lifecycle, last_state=obs.get("last_state"),
                                    last_event_id=obs.get("last_event_id"), task_id=obs.get("task_id"), age_s=obs.get("age_s"), documented_sources=[], excluded=[],
                                    not_provided=["classification", "role"] + list(LIST_FIELDS), **{f: [] for f in LIST_FIELDS}))
    if config_problem:
        return profiles, config_problem[0], f"Agent configuration: {config_problem[1]}. Observed identities are still listed as DISCOVERED."
    return profiles, "valid", "Configuration read; runtime state only from HIVE Core events. Documented-only agents are NOT_VERIFIED, never active."


def _obs(category, severity, subject, reason, observed_at, evidence_ids=(), validity="valid", source="hive:/events", correlation_id=None):
    basis = f"{category}|{subject}|{reason}"
    return hr.envelope("ultron_observation", "ultron-obs:" + hr.sha256_text(basis)[7:23], source, observed_at, validity, reason,
                       source_id=subject, correlation_id=correlation_id, category=category, severity=severity, subject=hr.safe_text(subject, 120),
                       evidence_ids=[str(e)[:80] for e in evidence_ids][:20], action="none (observation only)")


def ultron_observations(connector, reachable, profiles, workers, tasks, events, observed_at, now):
    """Evidence-derived observations. Never an action; never ACTIVE from silence."""
    out = []
    if not reachable:
        out.append(_obs("connector_health", "critical", "HIVE Core", f"HIVE Core transport unavailable: {connector.get('reason')}. Agent, worker and task health cannot be observed.",
                        None, validity="unavailable", source=connector.get("source", "hive:/health")))
        return out
    for p in profiles:
        if p.get("last_state") == "SECURITY_BLOCKED" and p["validity"] in ("valid", "fixture"):
            out.append(_obs("blocked_agent", "critical", p["agent_id"], "Latest fresh event: SECURITY_BLOCKED.", p["observed_at"], [p.get("last_event_id")]))
        elif p.get("last_state") == "WAITING_APPROVAL" and p["validity"] in ("valid", "fixture"):
            out.append(_obs("blocked_agent", "warning", p["agent_id"], "Latest fresh event: WAITING_APPROVAL.", p["observed_at"], [p.get("last_event_id")]))
        elif p.get("lifecycle") == "DEGRADED":
            out.append(_obs("agent_health", "warning", p["agent_id"], p.get("reason") or "degraded", p["observed_at"], [p.get("last_event_id")]))
        if p["validity"] == "stale":
            out.append(_obs("stale_agent", "warning", p["agent_id"], p.get("reason") or "observation expired", p["observed_at"], [p.get("last_event_id")], validity="stale"))
        if p["validity"] == "conflict" and "role conflict" in (p.get("reason") or ""):
            out.append(_obs("agent_health", "warning", p["agent_id"], p["reason"], p["observed_at"], [p.get("last_event_id")], validity="conflict"))
    known_workers = {w["source_id"]: w for w in workers}
    for w in workers:
        if w.get("freshness") in ("offline", "stale"):
            out.append(_obs("worker_health", "warning" if w["freshness"] == "offline" else "info", w["source_id"],
                            f"worker heartbeat {w['freshness']} (last {w.get('heartbeat')})", observed_at, source=w["source"]))
        elif w.get("freshness") == "unknown":
            out.append(_obs("worker_health", "info", w["source_id"], "no usable heartbeat in the worker record", observed_at, source=w["source"]))
    for t in tasks:
        status = str(t.get("status_raw") or "").lower()
        if status in ("done", "completed", "succeeded", "cancelled", "canceled", "failed"):
            continue
        aw = t.get("assigned_worker")
        if not aw:
            out.append(_obs("task_routing", "info", t["source_id"], "no worker assignment in the source record (the dashboard does not route tasks)", observed_at, source=t["source"]))
        elif aw not in known_workers:
            out.append(_obs("task_routing", "warning", t["source_id"], f"assigned to worker {aw!r}, which HIVE Core did not report", observed_at, source=t["source"],
                            correlation_id=t.get("correlation_id")))
        elif known_workers[aw].get("freshness") == "offline":
            out.append(_obs("task_routing", "warning", t["source_id"], f"assigned to worker {aw!r}, whose heartbeat is offline", observed_at, source=t["source"],
                            correlation_id=t.get("correlation_id")))
    perm = [e for e in events if e.get("state") == "SECURITY_BLOCKED" or _PERMISSION_EVENT.search(str(e.get("event_type") or ""))]
    for e in perm[:20]:
        out.append(_obs("permission_failure", "critical", e.get("role_id") or e.get("task_id") or "unknown subject",
                        f"{e.get('event_type')} ({e.get('state')})", e.get("timestamp"), [e.get("event_id")], correlation_id=e.get("correlation_id")))
    failures = collections.defaultdict(list)
    for e in events:
        if e.get("state") == "FAILED":
            failures[e.get("task_id") or f"role:{e.get('role_id')}"].append(e.get("event_id"))
    for subject, ids in failures.items():
        if len(ids) >= REPEATED_FAILURE_MIN:
            out.append(_obs("repeated_failure", "warning", subject, f"{len(ids)} FAILED events in the latest window", observed_at, ids))
    errors = [e for e in events if e.get("severity") in ("error", "critical")]
    if len(errors) >= ERROR_BURST_MIN:
        out.append(_obs("system_stability", "warning", "HIVE Core events", f"{len(errors)} error/critical events in the latest window", observed_at, [e.get("event_id") for e in errors]))
    if not out:
        out.append(_obs("system_stability", "info", "HIVE Core events", f"No anomaly in {len(events)} latest event(s), {len(workers)} worker(s), {len(tasks)} task(s). This is not an ACTIVE claim.",
                        observed_at))
    return out
