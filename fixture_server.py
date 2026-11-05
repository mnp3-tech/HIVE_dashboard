"""Safe, deterministic runtime fixture for the HIVE dashboard.

This is deliberately separate from ``server.py``.  It never imports the live
adapter, reads environment credentials, contacts HIVE Core/AO/provider
services, starts subprocesses, or implements a write route.  It exists so a
reviewer or Claude can exercise the real browser/API contract without touching
the live runtime.

Run locally with::

    python fixture_server.py --port 4174 --bind 127.0.0.1

The fixture is synthetic and every API payload carries an explicit fixture
marker.  It is not evidence of provider connectivity or HIVE Core state.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import mimetypes
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import hive_events
from urllib.parse import parse_qs, unquote, urlsplit


ROOT = Path(__file__).resolve().parent
FIXTURE_VERSION = "hive-dashboard-runtime-fixture.v1"
FIXTURE_SESSION_ID = "fixture-hive"
MAX_BODY_TO_DRAIN = 64 * 1024


def validate_bind(value: str) -> bool:
    """Return true only for a literal IPv4 loopback bind address."""

    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return address.version == 4 and address.is_loopback


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _observed(now: datetime, seconds_ago: int = 0) -> str:
    return _iso(now - timedelta(seconds=seconds_ago))


def _evidence(now: datetime, source: str, reason: str = "Synthetic runtime fixture only.") -> dict:
    return {
        "source": source,
        "observed_at": _observed(now, 4),
        "validity": "valid",
        "reason": reason,
    }


def build_snapshot(now: datetime | None = None) -> dict:
    """Build the same normalized shape consumed by the browser UI."""

    now = now or datetime.now(timezone.utc)
    return {
        "fixture_only": True,
        "received_at": _observed(now),
        "environment": "LOCAL / RUNTIME FIXTURE",
        "core": {
            "status": "working",
            "observed_at": _observed(now, 4),
            "reason": "Synthetic HIVE Core activity for UI/API testing; no live Core call.",
        },
        "metrics": {
            "cpu": {"value": 42, "unit": "%", "source": "fixture", "observed_at": _observed(now, 12), "validity": "valid"},
            "memory": {"value": 58, "unit": "%", "source": "fixture", "observed_at": _observed(now, 12), "validity": "valid"},
            "disk": {"value": 71, "unit": "%", "source": "fixture", "observed_at": _observed(now, 12), "validity": "valid"},
        },
        "adapters": {
            "hive": {
                "configured": True,
                "token_configured": False,
                "authenticated": False,
                "authentication_validity": "not_applicable",
                "authentication_reason": "Runtime fixture does not load credentials.",
                "reachable": True,
                "last_observed_at": _observed(now, 4),
                "validity": "valid",
                "reason": "Fixture endpoint responded; this is not HIVE Core.",
            },
            "obsidian": {
                "configured": True,
                "reachable": True,
                "validity": "valid",
                "last_observed_at": _observed(now, 6),
                "reason": "Synthetic WONG/Obsidian projection for UI testing.",
            },
            "internet": {
                "configured": False,
                "reachable": False,
                "validity": "unknown",
                "last_observed_at": None,
                "reason": "Fixture never opens an Internet connection.",
            },
        },
        "projects": {
            "items": [
                {"id": "seed", "name": "SEED", "status": "active", "description": "Build / test pipeline", "protected": False},
                {"id": "hive-dashboard", "name": "HIVE Dashboard", "status": "active", "description": "Desktop cockpit and evidence UI", "protected": True},
            ],
            "evidence": _evidence(now, "fixture:projects"),
        },
        "project_registry": {
            "items": [
                {"id": "hive-core-seed", "name": "HIVE / seed core", "status": "active", "registration": "registered", "workspace_present": True},
                {"id": "hive-dashboard", "name": "HIVE Dashboard", "status": "active", "registration": "fixture", "workspace_present": True},
                {"id": "obsidian-wong", "name": "WONG / Obsidian projection", "status": "active", "registration": "fixture", "workspace_present": True},
                {"id": "ultron", "name": "ULTRON security layer", "status": "working", "registration": "fixture", "workspace_present": False},
                {"id": "jarvis", "name": "JARVIS voice layer", "status": "waiting", "registration": "planned", "workspace_present": False},
            ],
            "evidence": _evidence(now, "fixture:project-registry"),
        },
        "self_evolution": {
            "item": {
                "id": "EVOLVE-FIXTURE",
                "name": "EVOLVE self-evolution proposal",
                "status": "proposal-only",
                "completed_steps": 1,
                "open_steps": 1,
                "next_action": "Inspect fixture/API contract and prepare a bounded proposal.",
                "blocker": "User approval required before any promotion.",
                "proposal_only": True,
            },
            "evidence": _evidence(now, "fixture:evolve"),
        },
        "local_workers": {
            "items": [
                {"id": "lmstudio-local", "name": "LM Studio", "endpoint": "http://127.0.0.1:1234/v1/models", "protocol": "openai-compatible", "status": "available", "models": ["fixture-qwen"], "reason": "Synthetic worker record; no probe was made."},
                {"id": "ollama-local", "name": "Ollama", "endpoint": "http://127.0.0.1:11434/api/tags", "protocol": "ollama", "status": "available", "models": ["fixture-llama"], "reason": "Synthetic worker record; no probe was made."},
            ],
            "evidence": _evidence(now, "fixture:local-workers"),
        },
        "tasks": {
            "items": [
                {"id": "fixture-task-1", "title": "Render live CORE state", "status": "active", "raw_status": "running", "project_id": "hive-dashboard", "worker": "claude-subscription", "created_at": _observed(now, 300)},
                {"id": "fixture-task-2", "title": "Read WONG projection", "status": "queued", "raw_status": "pending", "project_id": "hive-dashboard", "worker": "codex-subscription", "created_at": _observed(now, 900)},
                {"id": "fixture-task-3", "title": "Check attached storage card", "status": "completed", "raw_status": "done", "project_id": "hive-dashboard", "worker": "deterministic", "created_at": _observed(now, 1800)},
            ],
            "evidence": _evidence(now, "fixture:tasks"),
        },
        "workers": {
            "items": [
                {"id": "claude-subscription", "name": "Claude", "provider": "claude", "model": "sonnet-fixture", "status": "working"},
                {"id": "codex-subscription", "name": "Codex / GPT", "provider": "gpt", "model": "codex-fixture", "status": "waiting"},
                {"id": "ultron", "name": "ULTRON", "provider": "system", "model": "security-fixture", "status": "working"},
                {"id": "obsidian-wong", "name": "WONG / Obsidian", "provider": "memory", "model": "projection-fixture", "status": "ready"},
            ],
            "evidence": _evidence(now, "fixture:workers"),
        },
        "events": {
            "items": [
                {"timestamp": _observed(now, 5), "timestamp_validity": "valid", "kind": "TASK_ROUTED", "title": "Task routed to Claude", "source": "fixture event bus", "component_id": "claude-subscription", "severity": "info"},
                {"timestamp": _observed(now, 42), "timestamp_validity": "valid", "kind": "WONG_READ", "title": "WONG projection read", "source": "fixture memory bridge", "component_id": "obsidian-wong", "severity": "info"},
                {"timestamp": _observed(now, 75), "timestamp_validity": "valid", "kind": "ULTRON_CHECK", "title": "ULTRON connection check passed", "source": "fixture security layer", "component_id": "ultron", "severity": "info"},
            ],
            "evidence": _evidence(now, "fixture:events"),
        },
        "topology": {
            "status": "fixture",
            "reason": "Synthetic topology records are present only to exercise the current orbit renderer.",
        },
        "readiness": {
            "aggregate": "fixture",
            "items": [
                {"id": "fixture-api", "status": "ready", "reason": "Read-only loopback fixture is listening."},
                {"id": "live-core", "status": "not_connected", "reason": "The fixture never contacts HIVE Core."},
            ],
            "evidence": _evidence(now, "fixture:readiness"),
        },
    }


def build_worker_policy(now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    workers = [
        {"worker_id": "deterministic", "canonical_worker_id": "deterministic", "capability": "deterministic_arithmetic_evaluator", "execution_mode": "local", "cost_mode": "free", "network_requirement": "none", "fallback_policy": "none_required", "endpoint": None, "endpoint_basis": "not_applicable", "cost_mode_allowed": True},
        {"worker_id": "lmstudio-local", "canonical_worker_id": "lmstudio-local", "capability": "local_llm_inference", "execution_mode": "local", "cost_mode": "free", "network_requirement": "loopback", "fallback_policy": "none_required", "endpoint": "http://127.0.0.1:1234", "endpoint_basis": "fixture_only", "cost_mode_allowed": True},
        {"worker_id": "ollama-local", "canonical_worker_id": "ollama-local", "capability": "local_llm_inference", "execution_mode": "local", "cost_mode": "free", "network_requirement": "loopback", "fallback_policy": "none_required", "endpoint": "http://127.0.0.1:11434", "endpoint_basis": "fixture_only", "cost_mode_allowed": True},
        {"worker_id": "claude-subscription", "canonical_worker_id": "claude-subscription", "capability": "remote_llm_inference", "execution_mode": "remote", "cost_mode": "unknown", "network_requirement": "internet", "fallback_policy": "local_preferred", "endpoint": None, "endpoint_basis": "fixture_only", "cost_mode_allowed": False},
        {"worker_id": "codex-subscription", "canonical_worker_id": "codex-subscription", "capability": "remote_llm_inference", "execution_mode": "remote", "cost_mode": "unknown", "network_requirement": "internet", "fallback_policy": "local_preferred", "endpoint": None, "endpoint_basis": "fixture_only", "cost_mode_allowed": False},
    ]
    return {
        "local_first_enforced": True,
        "accepted_cost_modes": ["free"],
        "fixture_only": True,
        "evidence": _evidence(now, "fixture:worker-policy"),
        "workers": workers,
    }


def build_capabilities() -> dict:
    return {
        "fixture_only": True,
        "delegation": {"proposal": False, "task": False, "mission": False, "self_upgrade_apply": False},
        "provider": {"route": "synthetic fixture", "direct_browser_provider_calls": False, "provider_execution": False},
        "memory": {"operations": ["status", "search", "get", "build_context"], "canonical_write": False, "project_scoped": True},
        "routing": {"route": "synthetic fixture", "proposal_only": True, "provider_execution": False, "attestation_shape_only": True},
        "security": {"loopback_only": True, "credentials_loaded": False, "write_routes": False},
        "ao": {"configured": True, "session_listing": True, "history": True, "send": False, "recover": False},
    }


def build_cli_status(now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    return {
        "items": [
            {"id": "claude", "name": "Claude", "status": "fixture", "version": "not probed", "reason": "No provider process was started."},
            {"id": "codex", "name": "Codex / GPT", "status": "fixture", "version": "not probed", "reason": "No provider process was started."},
            {"id": "ao", "name": "Agent Orchestrator", "status": "fixture", "version": "not probed", "reason": "No local binary was invoked."},
        ],
        "evidence": _evidence(now, "fixture:cli-status"),
    }


def build_sessions(now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    return {
        "fixture_only": True,
        "items": [{"id": FIXTURE_SESSION_ID, "displayName": "HIVE / runtime fixture", "status": "working", "activity": "fixture", "harness": "fixture"}],
        "evidence": _evidence(now, "fixture:ao-sessions"),
    }


def build_history(now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    return {
        "fixture_only": True,
        "session_id": FIXTURE_SESSION_ID,
        "items": [
            {"role": "assistant", "text": "Runtime fixture loaded. No provider message was sent.", "timestamp": _observed(now, 42)},
            {"role": "user", "text": "Show active agents, WONG, and ULTRON state.", "timestamp": _observed(now, 36)},
            {"role": "assistant", "text": "Claude and ULTRON are working; WONG is ready. This is synthetic evidence only.", "timestamp": _observed(now, 30)},
        ],
        "evidence": _evidence(now, "fixture:ao-history"),
    }


def build_memory(now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    return [
        {"id": "wong/dashboard-authority", "project_id": "hive-dashboard", "title": "WONG authority boundary", "text": "WONG is the canonical memory and decision authority. The dashboard is a projection.", "updated_at": _observed(now, 55), "source": "fixture:obsidian-wong"},
        {"id": "wong/ultron-boundary", "project_id": "hive-dashboard", "title": "ULTRON boundary", "text": "ULTRON monitors access and connection policy; unavailable telemetry is shown as unknown.", "updated_at": _observed(now, 95), "source": "fixture:obsidian-wong"},
        {"id": "wong/evolve-policy", "project_id": "hive-dashboard", "title": "EVOLVE proposal only", "text": "EVOLVE may prepare isolated proposals and evidence but never silently promotes changes.", "updated_at": _observed(now, 140), "source": "fixture:obsidian-wong"},
    ]


def fixture_metadata(now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    return {
        "fixture": True,
        "fixture_version": FIXTURE_VERSION,
        "environment": "LOCAL / RUNTIME FIXTURE",
        "read_only": True,
        "loopback_only": True,
        "credentials_loaded": False,
        "external_connections": False,
        "write_routes": False,
        "observed_at": _observed(now),
        "purpose": "Exercise the dashboard's same-origin API contract without HIVE Core or provider side effects.",
    }


def _limit(query: dict[str, list[str]], default: int = 20, maximum: int = 50) -> int:
    try:
        return max(1, min(maximum, int((query.get("limit") or [default])[0])))
    except (TypeError, ValueError):
        return default


def api_payload(path: str, query: dict[str, list[str]], now: datetime | None = None) -> tuple[dict, int]:
    now = now or datetime.now(timezone.utc)
    if path == "/api/fixture/metadata":
        return fixture_metadata(now), 200
    if path == "/api/dashboard/snapshot":
        return build_snapshot(now), 200
    if path == "/api/control/worker-policy":
        return build_worker_policy(now), 200
    if path == "/api/control/capabilities":
        return build_capabilities(), 200
    if path == "/api/local-workers/cli-status":
        return build_cli_status(now), 200
    if path == "/api/ao/sessions":
        return build_sessions(now), 200
    if path.startswith("/api/ao/sessions/") and path.endswith("/history"):
        session_id = unquote(path[len("/api/ao/sessions/") : -len("/history")].strip("/"))
        if session_id != FIXTURE_SESSION_ID:
            return {"detail": "Unknown fixture session"}, 404
        return build_history(now), 200
    if path == "/api/memory/status":
        records = build_memory(now)
        return {"status": "ready", "project_count": 1, "record_count": len(records), "evidence": _evidence(now, "fixture:memory-status")}, 200
    if path == "/api/memory/search":
        records = build_memory(now)
        needle = (query.get("q") or [""])[0].strip().lower()
        project_id = (query.get("project_id") or [""])[0].strip()
        items = [item for item in records if (not project_id or item["project_id"] == project_id) and (not needle or needle in (item["title"] + " " + item["text"]).lower())]
        return {"items": items[: _limit(query)], "evidence": _evidence(now, "fixture:memory-search")}, 200
    if path == "/api/memory/get":
        record_id = (query.get("record_id") or [""])[0]
        item = next((item for item in build_memory(now) if item["id"] == record_id), None)
        if item is None:
            return {"detail": "Unknown fixture memory record"}, 404
        return {"item": item, "evidence": _evidence(now, "fixture:memory-get")}, 200
    if path == "/api/memory/build_context":
        records = build_memory(now)
        record_ids = set(query.get("record_id") or [])
        if record_ids:
            records = [item for item in records if item["id"] in record_ids]
        return {"project_id": (query.get("project_id") or ["hive-dashboard"])[0], "items": records[: _limit(query)], "text": "\n\n".join(item["title"] + ": " + item["text"] for item in records), "evidence": _evidence(now, "fixture:memory-context")}, 200
    return {"detail": "Unknown fixture endpoint"}, 404


def fixture_event_batch():
    """Deterministic, clearly synthetic events in the section 9 contract (never live data)."""
    now = datetime.now(timezone.utc)
    prov = {"source": "fixture:events", "validity": "fixture", "observed_at": now.isoformat()}
    raw = [
        {"event_id": "fx-1", "timestamp": _observed(now, 5), "role_id": "FURY", "provider": "claude", "event_type": "TASK_ROUTED", "state": "working", "task_id": "fx-task-1", "correlation_id": "fx-corr-1", "source": "fixture event bus", "title": "Task routed (fixture)"},
        {"event_id": "fx-2", "timestamp": _observed(now, 42), "role_id": "UATU", "provider": "local", "event_type": "WONG_READ", "state": "working", "task_id": "fx-task-2", "correlation_id": "fx-corr-2", "target_node": "obsidian", "source": "fixture memory bridge", "title": "WONG projection read (fixture)"},
    ]
    events = [hive_events.contract_event(r, prov) for r in raw]
    status = {"schema_version": hive_events.SCHEMA_VERSION, "validity": "fixture", "source": "fixture:events", "observed_at": now.isoformat(), "reason": "Synthetic fixture stream; not live telemetry", "event_count": len(events)}
    return events, status


class FixtureHandler(BaseHTTPRequestHandler):
    server_version = "HIVE-Dashboard-Runtime-Fixture/1.0"

    def log_message(self, format: str, *args) -> None:
        # Never log query strings, headers, or request bodies.
        path = urlsplit(self.path).path
        super().log_message("%s", self.command + " " + path)

    def json_response(self, payload: dict, status: int = 200, allow: str | None = None) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        if allow:
            self.send_header("Allow", allow)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        query = parse_qs(urlsplit(self.path).query)
        if path == "/api/events/stream":
            return self.stream_events(query)
        if path.startswith("/api/"):
            payload, status = api_payload(path, query)
            payload = dict(payload)
            payload.setdefault("fixture_only", True)
            return self.json_response(payload, status)
        return self.serve_static(path)

    def stream_events(self, query) -> None:
        """Read-only SSE of synthetic fixture events. `cycles=N` bounds it (tests)."""
        try:
            cycles = max(1, min(100000, int(query["cycles"][0]))) if query.get("cycles") else None
        except ValueError:
            cycles = None
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        try:
            for frame in hive_events.stream_frames(fixture_event_batch, 15.0, cycles, time.sleep):
                self.wfile.write(frame)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return

    def do_HEAD(self) -> None:
        # The dashboard does not need HEAD, but returning the same route shape
        # makes health checks safe without adding a write-capable surface.
        path = urlsplit(self.path).path
        if path.startswith("/api/"):
            payload, status = api_payload(path, parse_qs(urlsplit(self.path).query))
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            return
        self.serve_static(path, head_only=True)

    def _reject_write(self) -> None:
        self.close_connection = True
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if 0 < length <= MAX_BODY_TO_DRAIN:
            self.rfile.read(length)
        return self.json_response(
            {
                "detail": "Runtime fixture is read-only; no write or provider execution route exists.",
                "fixture": True,
                "read_only": True,
            },
            405,
            allow="GET, HEAD",
        )

    do_POST = _reject_write
    do_PUT = _reject_write
    do_PATCH = _reject_write
    do_DELETE = _reject_write

    def serve_static(self, path: str, head_only: bool = False) -> None:
        relative_path = unquote(path.lstrip("/")) if path != "/" else "index.html"
        candidate = (ROOT / relative_path).resolve()
        try:
            candidate.relative_to(ROOT)
        except ValueError:
            return self.json_response({"detail": "Invalid path"}, 400)
        if not candidate.is_file():
            return self.json_response({"detail": "Not found"}, 404)
        body = candidate.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(candidate.name)[0] or "application/octet-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if not head_only:
            self.wfile.write(body)


class LoopbackFixtureServer(ThreadingHTTPServer):
    allow_reuse_address = True


def main() -> None:
    parser = argparse.ArgumentParser(description="Loopback-only read-only HIVE dashboard runtime fixture")
    parser.add_argument("--port", type=int, default=4174)
    parser.add_argument("--bind", default="127.0.0.1")
    args = parser.parse_args()
    if not validate_bind(args.bind):
        parser.error("--bind must be a literal IPv4 loopback address, normally 127.0.0.1")
    server = LoopbackFixtureServer((args.bind, args.port), FixtureHandler)
    print(f"HIVE dashboard runtime fixture listening on http://{args.bind}:{args.port}/", flush=True)
    print("Read-only: no HIVE Core, AO, provider, credential, subprocess, or write access.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
