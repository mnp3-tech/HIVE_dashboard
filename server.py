"""Loopback-only HIVE dashboard adapter.

Serves the static dashboard and exposes a deliberately narrow adapter surface:
read-only snapshot plus task/mission submission through the authenticated HIVE
Core API. Credentials stay in the server process environment and never reach the
browser or logs.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import secrets
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
CORE_URL = os.environ.get("HIVE_CORE_URL", "http://127.0.0.1:8765").rstrip("/")
API_TOKEN = os.environ.get("HIVE_API_TOKEN", "")
ALLOWED_WORKERS = {"deterministic", "lmstudio", "openrouter_free", "antigravity", "codex"}
MAX_BODY = 12_000


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


def core_json(path: str, method: str = "GET", body: dict | None = None, idempotency_key: str | None = None):
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


def optional_core(path: str, default):
    try:
        return core_json(path)
    except AdapterError:
        return default


def metric(value, unit="%", source="hive", validity="unavailable", reason="not supplied"):
    if value is None:
        return {"value": None, "unit": unit, "source": source, "observed_at": None, "validity": validity, "reason": reason}
    try:
        number = float(value)
    except (TypeError, ValueError):
        return {"value": None, "unit": unit, "source": source, "observed_at": None, "validity": "unknown", "reason": "non-numeric source value"}
    return {"value": number, "unit": unit, "source": source, "observed_at": utc_now(), "validity": "valid"}


def snapshot():
    health = optional_core("/health", {})
    system = optional_core("/system", {})
    raw_projects = unwrap_items(optional_core("/projects", []))
    projects = [{"id": item.get("id"), "name": item.get("name", item.get("id", "project")), "status": item.get("status", "unknown"), "description": item.get("description", ""), "protected": bool(item.get("protected", False))} for item in raw_projects if isinstance(item, dict) and item.get("id")]
    raw_workers = unwrap_items(optional_core("/workers", []))
    workers = [{"id": item.get("id") or item.get("worker_id"), "name": item.get("name", item.get("id", item.get("worker_id", "worker"))), "provider": item.get("provider", "unknown"), "model": item.get("model", "unknown"), "status": item.get("status", "unknown"), "capabilities": item.get("capabilities", []) if isinstance(item.get("capabilities", []), list) else []} for item in raw_workers if isinstance(item, dict) and (item.get("id") or item.get("worker_id"))]
    events = unwrap_items(optional_core("/events?limit=50", []))
    architecture = optional_core("/engineering/architecture", {})
    host = (system.get("host", {}) if isinstance(system, dict) else {}) or {}
    health_status = str(health.get("status", "unknown")).lower() if isinstance(health, dict) else "unknown"
    if health_status in {"ok", "healthy", "ready", "online"}:
        core_status, core_reason = "running", "HIVE Core application health responded"
    elif health_status in {"degraded", "warning"}:
        core_status, core_reason = "degraded", "HIVE Core health reported degradation"
    else:
        core_status, core_reason = "unknown", "Application health payload unavailable"
    components = [{"id": "hive-core", "name": "HIVE Core", "project": "HIVE", "role": "orchestrator", "status": core_status, "heartbeat_at": utc_now(), "version": health.get("version", "unknown") if isinstance(health, dict) else "unknown", "capabilities": ["health", "tasks", "missions"], "health_evidence": core_reason}]
    for project in projects:
        if isinstance(project, dict) and project.get("id"):
            components.append({"id": project["id"], "name": project.get("name", project["id"]), "project": project.get("name", project["id"]), "role": "project workspace", "status": "waiting" if project.get("status") == "active" else "offline", "heartbeat_at": None, "version": "unknown", "capabilities": ["task-target"], "health_evidence": "project registry record"})
    for worker in workers:
        if isinstance(worker, dict) and (worker.get("id") or worker.get("worker_id")):
            worker_id = worker.get("id") or worker.get("worker_id")
            components.append({"id": f"worker:{worker_id}", "name": worker.get("name", worker_id), "project": "HIVE", "role": worker.get("provider", "worker"), "status": worker.get("status", "unknown"), "heartbeat_at": worker.get("last_heartbeat"), "version": worker.get("model", "unknown"), "capabilities": worker.get("capabilities", []), "health_evidence": "worker registry record"})
    normalized_events = []
    for event in events:
        if not isinstance(event, dict):
            continue
        normalized_events.append({"timestamp": event.get("timestamp") or event.get("created_at") or utc_now(), "kind": event.get("event_type", "OBSERVED_EVENT"), "title": event.get("event_type", "Observed HIVE event"), "source": event.get("source", "HIVE Core"), "component_id": event.get("worker_id") or event.get("project_id") or "hive-core", "severity": str(event.get("severity", "info")).lower()})
    return {"received_at": utc_now(), "environment": "LOCAL / HIVE CORE", "core": {"status": core_status, "observed_at": utc_now() if health else None, "reason": core_reason}, "metrics": {"cpu": metric(host.get("cpu_percent"), source="hive"), "memory": metric(host.get("ram_percent", host.get("memory_percent")), source="hive"), "gpu": metric(host.get("gpu_percent"), source="hive", reason="GPU sensor not supplied by HIVE snapshot"), "disk": metric(host.get("disk_percent"), source="hive"), "network": metric(host.get("network_percent"), source="hive", reason="Network utilization not supplied by HIVE snapshot")}, "components": components[:40], "events": normalized_events[:50], "incidents": [], "history": {}, "projects": projects, "workers": workers, "capabilities": {"hive": {"configured": True, "authenticated": bool(API_TOKEN), "endpoint": CORE_URL}, "beszel": {"configured": bool(os.environ.get("BESZEL_URL")), "host": os.environ.get("BESZEL_URL", "")}, "architecture": bool(architecture)}}


def dispatch(payload: dict, idempotency_key: str | None):
    if not API_TOKEN:
        raise AdapterError("HIVE_API_TOKEN is not configured; no request was sent", 503)
    if not isinstance(payload, dict) or payload.get("confirm") is not True:
        raise AdapterError("Explicit confirmation is required", 400)
    mode = payload.get("mode")
    goal = str(payload.get("goal", "")).strip()
    if mode not in {"task", "mission", "evolution-proposal"}:
        raise AdapterError("Only task, mission, and evolution-proposal are supported", 400)
    if len(goal) < 8 or len(goal) > 8000:
        raise AdapterError("Goal must be between 8 and 8000 characters", 400)
    project_id = payload.get("project_id") or None
    worker = payload.get("preferred_worker") or None
    if worker not in ALLOWED_WORKERS and worker is not None:
        raise AdapterError("Worker preference is not in the HIVE allowlist", 400)
    local_only = bool(payload.get("local_only"))
    if local_only and worker in {"openrouter_free", "antigravity", "codex"}:
        raise AdapterError("Local-only routing conflicts with the selected external worker", 400)
    if mode == "mission":
        body = {"goal": goal, "project_id": project_id, "constraints": {"local_only": local_only, "forbidden_workers": []}}
        result = core_json("/missions", "POST", body, idempotency_key or secrets.token_urlsafe(18))
        return {"kind": "mission", "id": result.get("id") or result.get("mission_id"), "status": "accepted", "core": result}
    task_type = payload.get("task_type") or ("EVOLUTION_TASK" if mode == "evolution-proposal" else None)
    task_prompt = goal if mode == "task" else f"Prepare an immutable self-upgrade proposal only. Do not apply, deploy, promote, or replace active Core. Proposal scope: {goal}"
    body = {"prompt": task_prompt, "task_type": task_type, "project_id": project_id, "preferred_worker": worker, "local_only": local_only, "apply_artifacts": False, "allowed_files": []}
    result = core_json("/tasks", "POST", body, idempotency_key or secrets.token_urlsafe(18))
    return {"kind": "evolution_proposal" if mode == "evolution-proposal" else "task", "id": result.get("id") or result.get("task_id"), "status": "accepted", "core": result}


class Handler(BaseHTTPRequestHandler):
    server_version = "HIVE-Dashboard-Adapter/0.1"

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
                return self.json_response({"delegation": {"task": True, "mission": True, "evolution_proposal": True, "self_upgrade_apply": False}, "provider": {"route": "HIVE Core worker registry", "direct_browser_provider_calls": False}, "core_endpoint": CORE_URL})
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
                return self.json_response({"detail": "Only controlled dispatch is available"}, 404)
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
    parser = argparse.ArgumentParser(description="Local HIVE dashboard adapter")
    parser.add_argument("--port", type=int, default=4173)
    parser.add_argument("--bind", default="127.0.0.1")
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.bind, args.port), Handler)
    print(f"HIVE dashboard adapter listening on http://{args.bind}:{args.port}/", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
