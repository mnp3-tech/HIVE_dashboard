"""Loopback-only unified dashboard adapter.

Serves the static dashboard and exposes a deliberately narrow, bounded MVP
adapter surface: read-only project catalog, task queue, and adapter health,
plus a proposal-only submission route through the authenticated HIVE Core
API. Credentials stay in the server process environment and never reach the
browser or logs. Topology visualization is explicitly deferred: this adapter
does not compute or expose graph/topology data.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import mimetypes
import os
import secrets
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def _is_loopback_hostname(hostname: str | None) -> bool:
    if not hostname:
        return False
    if hostname.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


ROOT = Path(__file__).resolve().parent
CORE_URL = os.environ.get("HIVE_CORE_URL", "http://127.0.0.1:8765").rstrip("/")
CORE_URL_IS_LOOPBACK = _is_loopback_hostname(urlparse(CORE_URL).hostname)
API_TOKEN = os.environ.get("HIVE_API_TOKEN", "")
ALLOWED_WORKERS = {"deterministic", "lmstudio", "openrouter_free", "antigravity", "codex"}
LOCAL_ONLY_INCOMPATIBLE_WORKERS = {"openrouter_free", "antigravity", "codex"}
ALLOWED_TASK_TYPES = {"EVOLUTION_TASK", "GENERAL", "ANALYSIS", "PROJECT_TASK", "RESEARCH"}
MAX_BODY = 12_000
# A successful /health response does not, by itself, prove the bearer token was
# checked: /health may be a public endpoint with no auth requirement at all. Operators
# must explicitly document (and set) this flag only if they have verified that this
# specific HIVE Core deployment's /health route requires and validates the bearer
# token. Left unset, authentication is reported as unknown rather than fabricated true.
HIVE_HEALTH_REQUIRES_AUTH = os.environ.get("HIVE_HEALTH_REQUIRES_AUTH", "").strip().lower() in {"1", "true", "yes"}

STATUS_BUCKETS = {
    "queued": {"queued", "pending", "new", "submitted", "waiting"},
    "active": {"active", "running", "in_progress", "in-progress", "started", "working"},
    "completed": {"completed", "done", "success", "succeeded", "finished"},
    "blocked": {"blocked", "failed", "error", "cancelled", "canceled", "rejected"},
}


class AdapterError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def unwrap_items(value):
    if isinstance(value, dict) and isinstance(value.get("items"), list):
        return value["items"]
    return value if isinstance(value, list) else []


def evidence(source: str, observed_at, validity: str, reason: str | None = None) -> dict:
    return {"source": source, "observed_at": observed_at, "validity": validity, "reason": reason}


def core_json(path: str, method: str = "GET", body: dict | None = None, idempotency_key: str | None = None):
    if not CORE_URL_IS_LOOPBACK:
        raise AdapterError("HIVE_CORE_URL does not resolve to a loopback address; refusing to contact a non-loopback Core", 503)
    if not path.startswith(("/health", "/ready", "/projects", "/workers", "/system", "/events", "/engineering/architecture", "/tasks", "/missions")):
        raise AdapterError("Adapter path is not allowlisted", 403)
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if API_TOKEN:
        headers["Authorization"] = f"Bearer {API_TOKEN}"
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    request = Request(f"{CORE_URL}{path}", data=payload, headers=headers, method=method)
    try:
        with urlopen(request, timeout=4) as response:
            raw = response.read(512_000)
            return json.loads(raw.decode("utf-8")) if raw else {}
    except HTTPError as error:
        detail = error.read(4_000).decode("utf-8", "replace")
        if error.code in (401, 403):
            raise AdapterError("HIVE Core rejected authentication or authorization", error.code) from None
        raise AdapterError(f"HIVE Core returned HTTP {error.code}: {detail[:240]}", error.code) from None
    except (URLError, TimeoutError, OSError) as error:
        raise AdapterError(f"HIVE Core is unavailable: {error.reason if hasattr(error, 'reason') else error}", 503) from None
    except (ValueError, UnicodeError) as error:
        raise AdapterError(f"HIVE Core returned invalid JSON: {error}", 502) from None


def fetch_with_evidence(path: str):
    """Fetch an optional Core path, preserving unavailable/unknown provenance on failure
    instead of silently collapsing to an untagged default."""
    try:
        raw = core_json(path)
    except AdapterError as error:
        return None, evidence(f"hive:{path}", None, unavailability_validity(error), str(error))
    return raw, evidence(f"hive:{path}", utc_now(), "valid")


def metric(value, unit="%", source="hive", reason=None):
    if value is None:
        return {"value": None, "unit": unit, "source": source, "observed_at": None, "validity": "unavailable", "reason": reason or "not supplied"}
    try:
        number = float(value)
    except (TypeError, ValueError):
        return {"value": None, "unit": unit, "source": source, "observed_at": None, "validity": "unknown", "reason": "non-numeric source value"}
    return {"value": number, "unit": unit, "source": source, "observed_at": utc_now(), "validity": "valid"}


def bucket_for(status) -> str:
    normalized = str(status or "").strip().lower()
    for bucket, names in STATUS_BUCKETS.items():
        if normalized in names:
            return bucket
    return "unknown"


def unavailability_validity(error: AdapterError) -> str:
    return "unknown" if error.status == 404 else "unavailable"


def project_catalog():
    try:
        raw = core_json("/projects")
    except AdapterError as error:
        return [], evidence("hive:/projects", None, unavailability_validity(error), str(error))
    observed = utc_now()
    projects = []
    for item in unwrap_items(raw):
        if not isinstance(item, dict) or not item.get("id"):
            continue
        projects.append({
            "id": item["id"],
            "name": item.get("name", item["id"]),
            "status": item.get("status", "unknown"),
            "description": item.get("description", ""),
            "protected": bool(item.get("protected", False)),
        })
    return projects, evidence("hive:/projects", observed, "valid")


def task_queue():
    try:
        raw = core_json("/tasks?limit=100")
    except AdapterError as error:
        return [], evidence("hive:/tasks", None, unavailability_validity(error), str(error))
    observed = utc_now()
    tasks = []
    for item in unwrap_items(raw):
        if not isinstance(item, dict):
            continue
        task_id = item.get("id") or item.get("task_id")
        if not task_id:
            continue
        raw_status = item.get("status", "unknown")
        title = item.get("title") or (str(item.get("prompt", ""))[:140]) or "Untitled task"
        tasks.append({
            "id": task_id,
            "title": title,
            "status": bucket_for(raw_status),
            "raw_status": raw_status,
            "project_id": item.get("project_id"),
            "worker": item.get("preferred_worker") or item.get("worker_id"),
            "created_at": item.get("created_at"),
            "updated_at": item.get("updated_at"),
        })
    return tasks, evidence("hive:/tasks", observed, "valid")


def worker_registry():
    raw, workers_evidence = fetch_with_evidence("/workers")
    workers = []
    for item in unwrap_items(raw):
        if not isinstance(item, dict):
            continue
        worker_id = item.get("id") or item.get("worker_id")
        if not worker_id:
            continue
        workers.append({
            "id": worker_id,
            "name": item.get("name", worker_id),
            "provider": item.get("provider", "unknown"),
            "model": item.get("model", "unknown"),
            "status": item.get("status", "unknown"),
        })
    return workers, workers_evidence


def adapter_health(health_error: AdapterError | None, status_recognized: bool, observed_at: str, reason: str):
    """status_recognized is True only when a /health call succeeded AND returned a
    status value we recognize; a successful call with a missing/invalid status field
    is reported as unknown, never fabricated as valid.

    authenticated is fail-closed: a successful /health call does NOT by itself prove
    the bearer token was checked, because /health may require no authentication at
    all. authenticated is only ever true when HIVE_HEALTH_REQUIRES_AUTH documents that
    this specific Core deployment's /health route validates the token. Otherwise
    authenticated stays false and authentication_validity reports "unknown" (call
    succeeded but auth was never proven) as distinct from token_configured (merely
    that a token string is present) and from an explicit 401/403 rejection.
    """
    beszel_url = os.environ.get("BESZEL_URL", "")
    token_configured = bool(API_TOKEN)
    if health_error is not None:
        hive_validity = unavailability_validity(health_error)
        hive_reachable = False
    elif status_recognized:
        hive_validity = "valid"
        hive_reachable = True
    else:
        hive_validity = "unknown"
        hive_reachable = True

    if not token_configured:
        authenticated, auth_validity, auth_reason = False, "unavailable", "No bearer token is configured; nothing to authenticate."
    elif health_error is not None and health_error.status in (401, 403):
        authenticated, auth_validity, auth_reason = False, "unavailable", "HIVE Core explicitly rejected the configured bearer token."
    elif health_error is not None:
        authenticated, auth_validity, auth_reason = False, "unavailable", "HIVE Core was unreachable; the configured token was never verified."
    elif HIVE_HEALTH_REQUIRES_AUTH:
        authenticated, auth_validity, auth_reason = True, "valid", "HIVE_HEALTH_REQUIRES_AUTH documents that /health validates the bearer token, and the call succeeded."
    else:
        authenticated, auth_validity, auth_reason = False, "unknown", "A successful /health response does not prove the token was checked (HIVE_HEALTH_REQUIRES_AUTH is unset); authentication is unverified."

    return {
        "hive": {
            "configured": True,
            "token_configured": token_configured,
            "authenticated": authenticated,
            "authentication_validity": auth_validity,
            "authentication_reason": auth_reason,
            "reachable": hive_reachable,
            "last_observed_at": observed_at if hive_reachable else None,
            "validity": hive_validity,
            "reason": reason,
        },
        "beszel": {
            "configured": bool(beszel_url),
            "token_configured": False,
            "authenticated": False,
            "authentication_validity": "unavailable",
            "authentication_reason": "Beszel integration is not implemented in this MVP; deferred",
            "reachable": False,
            "last_observed_at": None,
            "validity": "unknown",
            "reason": "Beszel integration is not implemented in this MVP; deferred",
        },
    }


def snapshot():
    try:
        health = core_json("/health")
        health_error = None
    except AdapterError as error:
        health = {}
        health_error = error
    observed = utc_now()
    health_status = str(health.get("status", "unknown")).lower() if isinstance(health, dict) else "unknown"
    status_recognized = health_status in {"ok", "healthy", "ready", "online", "degraded", "warning"}
    if health_error is not None:
        core_status, core_reason, core_observed = "unknown", str(health_error), None
    elif health_status in {"ok", "healthy", "ready", "online"}:
        core_status, core_reason, core_observed = "running", "HIVE Core application health responded", observed
    elif health_status in {"degraded", "warning"}:
        core_status, core_reason, core_observed = "degraded", "HIVE Core health reported degradation", observed
    else:
        core_status, core_reason, core_observed = "unknown", "Application health payload missing expected status field", observed

    adapters = adapter_health(health_error, status_recognized, observed, core_reason)

    system_raw, system_evidence = fetch_with_evidence("/system")
    host = (system_raw.get("host", {}) if isinstance(system_raw, dict) else {}) or {}
    metrics_reason = None if system_evidence["validity"] == "valid" else system_evidence["reason"]

    projects, projects_evidence = project_catalog()
    tasks, tasks_evidence = task_queue()
    workers, workers_evidence = worker_registry()
    events_raw, events_evidence = fetch_with_evidence("/events?limit=50")
    normalized_events = []
    for event in unwrap_items(events_raw):
        if not isinstance(event, dict):
            continue
        raw_timestamp = event.get("timestamp") or event.get("created_at")
        normalized_events.append({
            "timestamp": raw_timestamp,
            "timestamp_validity": "valid" if raw_timestamp else "unknown",
            "kind": event.get("event_type", "OBSERVED_EVENT"),
            "title": event.get("event_type", "Observed HIVE event"),
            "source": event.get("source", "HIVE Core"),
            "component_id": event.get("worker_id") or event.get("project_id") or "hive-core",
            "severity": str(event.get("severity", "info")).lower(),
        })

    return {
        "received_at": utc_now(),
        "environment": "LOCAL / HIVE CORE",
        "core": {"status": core_status, "observed_at": core_observed, "reason": core_reason},
        "metrics": {
            "cpu": metric(host.get("cpu_percent"), source="hive", reason=metrics_reason),
            "memory": metric(host.get("ram_percent", host.get("memory_percent")), source="hive", reason=metrics_reason),
            "disk": metric(host.get("disk_percent"), source="hive", reason=metrics_reason),
        },
        "adapters": adapters,
        "projects": {"items": projects, "evidence": projects_evidence},
        "tasks": {"items": tasks, "evidence": tasks_evidence},
        "workers": {"items": workers, "evidence": workers_evidence},
        "events": {"items": normalized_events[:50], "evidence": events_evidence},
        "topology": {"status": "deferred", "reason": "Topology visualization is deferred for this MVP; no graph or event-derived topology is computed."},
    }


def dispatch(payload: dict, idempotency_key: str | None):
    if not API_TOKEN:
        raise AdapterError("HIVE_API_TOKEN is not configured; no request was sent", 503)
    if not isinstance(payload, dict) or payload.get("confirm") is not True:
        raise AdapterError("Explicit confirmation is required", 400)
    mode = payload.get("mode")
    if mode != "proposal":
        raise AdapterError("Only proposal-only submissions are supported in this MVP", 400)
    goal = str(payload.get("goal", "")).strip()
    if len(goal) < 8 or len(goal) > 8000:
        raise AdapterError("Goal must be between 8 and 8000 characters", 400)
    project_id = payload.get("project_id") or None
    worker = payload.get("preferred_worker") or None
    if worker is not None and worker not in ALLOWED_WORKERS:
        raise AdapterError("Worker preference is not in the HIVE allowlist", 400)
    local_only = bool(payload.get("local_only"))
    if local_only and worker in LOCAL_ONLY_INCOMPATIBLE_WORKERS:
        raise AdapterError("Local-only routing conflicts with the selected external worker", 400)
    task_type = payload.get("task_type") or "EVOLUTION_TASK"
    if task_type not in ALLOWED_TASK_TYPES:
        raise AdapterError("Task type is not in the proposal allowlist", 400)

    try:
        core_json("/health")
    except AdapterError as error:
        raise AdapterError(f"Proposal not submitted: HIVE Core reachability evidence is absent ({error})", 503) from None

    task_prompt = (
        "Prepare an immutable proposal only. Do not apply, deploy, promote, or replace "
        f"active state. Proposal scope: {goal}"
    )
    body = {
        "prompt": task_prompt,
        "task_type": task_type,
        "project_id": project_id,
        "preferred_worker": worker,
        "local_only": local_only,
        "apply_artifacts": False,
        "allowed_files": [],
    }
    result = core_json("/tasks", "POST", body, idempotency_key or secrets.token_urlsafe(18))
    return {"kind": "proposal", "id": result.get("id") or result.get("task_id"), "status": "accepted", "core": result}


class Handler(BaseHTTPRequestHandler):
    server_version = "Unified-Dashboard-Adapter/0.2"

    def log_message(self, format, *args):
        # Do not log query strings, headers, payloads, or credentials.
        if self.path.startswith("/api/"):
            super().log_message("%s", self.command + " " + urlparse(self.path).path)
        else:
            super().log_message(format, *args)

    def json_response(self, payload, status=200):
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path = urlparse(self.path).path
        try:
            if path == "/api/dashboard/snapshot":
                return self.json_response(snapshot())
            if path == "/api/control/capabilities":
                return self.json_response({
                    "delegation": {"proposal": True, "task": False, "mission": False, "self_upgrade_apply": False},
                    "provider": {"route": "HIVE Core worker registry", "direct_browser_provider_calls": False},
                    "core_endpoint": CORE_URL,
                    "security": {"loopback_only": True, "core_endpoint_is_loopback": CORE_URL_IS_LOOPBACK},
                })
            if path.startswith("/api/"):
                return self.json_response({"detail": "Unknown adapter endpoint"}, 404)
            self.serve_static(path)
        except AdapterError as error:
            self.json_response({"detail": str(error)}, error.status)
        except Exception as error:
            self.json_response({"detail": f"Adapter error: {error}"}, 500)

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            if path != "/api/control/dispatch":
                return self.json_response({"detail": "Only controlled proposal dispatch is available"}, 404)
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_BODY:
                raise AdapterError("Request body is missing or too large", 413)
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            result = dispatch(body, self.headers.get("Idempotency-Key"))
            self.json_response(result, 202)
        except (ValueError, UnicodeError):
            self.json_response({"detail": "Invalid JSON request"}, 400)
        except AdapterError as error:
            self.json_response({"detail": str(error)}, error.status)
        except Exception as error:
            self.json_response({"detail": f"Adapter error: {error}"}, 500)

    def serve_static(self, path):
        relative = Path(urlparse(path).path.lstrip("/")) if path != "/" else Path("index.html")
        candidate = (ROOT / relative).resolve()
        if ROOT not in candidate.parents and candidate != ROOT:
            return self.json_response({"detail": "Invalid path"}, 400)
        if not candidate.is_file():
            return self.json_response({"detail": "Not found"}, 404)
        body = candidate.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(candidate.name)[0] or "application/octet-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    parser = argparse.ArgumentParser(description="Local unified dashboard adapter")
    parser.add_argument("--port", type=int, default=4173)
    parser.add_argument("--bind", default="127.0.0.1")
    args = parser.parse_args()
    if not _is_loopback_hostname(args.bind):
        parser.error(f"--bind must be a loopback address (127.0.0.1, ::1, or localhost); got {args.bind!r}")
    if not CORE_URL_IS_LOOPBACK:
        parser.error(f"HIVE_CORE_URL must target a loopback address; got {CORE_URL!r}")
    server = ThreadingHTTPServer((args.bind, args.port), Handler)
    print(f"Unified dashboard adapter listening on http://{args.bind}:{args.port}/", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
