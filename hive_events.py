"""HIVE event contract (spec section 9) and Server-Sent-Events framing.

Stdlib only, no I/O. Shared by server.py (live adapter) and fixture_server.py.
Nothing here invents data: missing fields stay None, unrecognised states stay
UNKNOWN, and every event carries the provenance it was normalised from.
"""
from __future__ import annotations

import hashlib
import json
import re

SCHEMA_VERSION = 1
STATES = ("IDLE", "WORKING", "WAITING_APPROVAL", "REVIEW", "FAILED", "SECURITY_BLOCKED", "OFFLINE", "UNKNOWN")
SEVERITIES = ("info", "warning", "error", "critical")

_STATE_WORDS = {
    "IDLE": ("idle", "ready", "completed", "complete", "done", "succeeded", "success", "finished"),
    "WORKING": ("working", "running", "active", "in_progress", "in-progress", "started", "executing", "routed"),
    "WAITING_APPROVAL": ("waiting_approval", "waiting-approval", "awaiting_approval", "approval_required", "waiting", "pending_approval"),
    "REVIEW": ("review", "in_review", "reviewing", "review_blocked"),
    "FAILED": ("failed", "failure", "error", "errored", "crashed"),
    "SECURITY_BLOCKED": ("security_blocked", "blocked_by_security", "policy_violation", "sandbox_violation", "denied"),
    "OFFLINE": ("offline", "unreachable", "disconnected"),
}
STATE_MAP = {word: state for state, words in _STATE_WORDS.items() for word in words}

_SECRET = re.compile(
    r"(?is)(-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)"
    r"|bearer\s+[a-z0-9._\-]{8,}|sk-[a-z0-9_\-]{10,}|ghp_[a-z0-9]{10,}|github_pat_[a-z0-9_]{20,}|xox[baprs]-[a-z0-9-]{10,}|AKIA[0-9A-Z]{12,}"
    r"|eyJ[a-z0-9_\-]{8,}\.[a-z0-9_\-]{8,}\.[a-z0-9_\-]{8,}"
    r"|(?:api[ _-]?key|token|secret|passw(?:or)?d|pwd|credential|cookie|session[ _-]?id|authorization)\s*[=:]\s*(?:\"[^\"]*\"|'[^']*'|(?:basic|bearer|token)\s+\S+|\S+)"
    r"|\b[a-z0-9_\-]{32,}\b)"
)
# Event types whose payload is a prompt/completion/reasoning: the summary is withheld entirely.
_WITHHOLD = re.compile(r"PROMPT|COMPLETION|CHAIN|THOUGHT|REASONING|TRANSCRIPT|MESSAGE_BODY", re.I)


def normalize_state(raw) -> str:
    """Map a raw status word to the CORE state enum; anything unrecognised is UNKNOWN."""
    if not isinstance(raw, str):
        return "UNKNOWN"
    word = raw.strip().lower().replace(" ", "_")
    return STATE_MAP.get(word) or (word.upper() if word.upper() in STATES else "UNKNOWN")


def redact_summary(text, limit: int = 160) -> str | None:
    if not isinstance(text, str) or not text.strip():
        return None
    return _SECRET.sub("[REDACTED]", " ".join(text.split()))[:limit]


def _disp(value, limit=80):
    """Display fields (role/provider/model/source) are redacted; identity fields (ids) are not."""
    return redact_summary(str(value), limit) if value not in (None, "") else None


def _text(value, limit=80):
    return str(value)[:limit] if value not in (None, "") else None


def contract_event(raw: dict, provenance: dict | None = None) -> dict | None:
    """Normalise one upstream event to the section 9 contract. Returns None for non-dicts."""
    if not isinstance(raw, dict):
        return None
    timestamp = raw.get("timestamp") or raw.get("created_at")
    event_type = raw.get("event_type") or raw.get("kind") or "OBSERVED_EVENT"
    role = raw.get("role_id") or raw.get("component_id")
    task_id = raw.get("task_id")
    event_id = raw.get("event_id") or raw.get("id")
    if not event_id:  # deterministic id so replays of the same upstream event dedupe
        basis = "|".join(str(x) for x in (raw.get("source"), timestamp, event_type, role, task_id, raw.get("title")))
        event_id = "derived-" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:20]
    severity = str(raw.get("severity") or "info").lower()
    severity = {"warn": "warning", "err": "error"}.get(severity, severity)
    state_raw = raw.get("state") or raw.get("status")
    event = {
        "schema_version": SCHEMA_VERSION,
        "event_id": str(event_id)[:80],
        "timestamp": timestamp if isinstance(timestamp, str) else None,
        "source": _disp(raw.get("source")),
        "role_id": _disp(role),
        "provider": _disp(raw.get("provider")),
        "model": _disp(raw.get("model")),
        "task_id": _text(task_id),
        "run_id": _text(raw.get("run_id")),
        "correlation_id": _text(raw.get("correlation_id") or raw.get("interaction_id")),
        "event_type": str(event_type)[:60],
        "state": normalize_state(state_raw) if state_raw else "UNKNOWN",
        "severity": severity if severity in SEVERITIES else "info",
        "provenance": dict(provenance or {}),
        "redacted_summary": None if _WITHHOLD.search(str(event_type)) else redact_summary(raw.get("redacted_summary") or raw.get("title") or raw.get("summary")),
    }
    # Optional interaction hints used only for orbital movement (never inferred):
    for key in ("target_node", "target_role_id"):
        if raw.get(key):
            event[key] = _text(raw[key], 40)
    return event


def sse_frame(data: dict, event: str = "hive", event_id: str | None = None) -> bytes:
    lines = []
    if event_id:
        lines.append("id: " + re.sub(r"[\r\n]", "", event_id))
    lines.append("event: " + event)
    lines.append("data: " + json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    return ("\n".join(lines) + "\n\n").encode("utf-8")


def sse_comment(text: str = "keepalive") -> bytes:
    return (": " + re.sub(r"[\r\n]", " ", text) + "\n\n").encode("utf-8")


def stream_frames(fetch, interval: float, cycles: int | None, sleep, seen_limit: int = 500):
    """Yield SSE frames. `fetch()` -> (list_of_contract_events, status_dict).

    A `status` frame is sent every cycle so clients can tell live/auth_required/unavailable
    apart from silence; events are sent once each (bounded dedupe memory).
    """
    seen: list[str] = []
    seen_set: set[str] = set()
    n = 0
    while cycles is None or n < cycles:
        events, status = fetch()
        yield sse_frame(status, "status")
        for ev in reversed(events):  # oldest first
            if ev["event_id"] in seen_set:
                continue
            seen.append(ev["event_id"]); seen_set.add(ev["event_id"])
            if len(seen) > seen_limit:
                seen_set.discard(seen.pop(0))
            yield sse_frame(ev, "hive", ev["event_id"])
        n += 1
        if cycles is None or n < cycles:
            yield sse_comment()
            sleep(interval)
