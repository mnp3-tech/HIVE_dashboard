"""Loopback-only unified dashboard adapter.

Serves the static dashboard and exposes a deliberately narrow, bounded MVP
adapter surface: read-only project catalog, task queue, and adapter health,
plus a proposal-only submission route through the authenticated HIVE Core
API. Credentials stay in the server process environment and never reach the
browser or logs. Topology visualization is explicitly deferred: this adapter
does not compute or expose graph/topology data.

A second, independent adapter bridges a small, fixed slice of the AO (Agent
Orchestrator) CLI contract -- `ao session ls --all --json`, `ao session
history`, and `ao send` -- via subprocess.run() with shell=False and a fixed
argv allowlist. It never shells out with arbitrary arguments, never guesses
at AO's internal HTTP/IPC transport, and never reads AO's own SQLite store.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import hive_events
import hive_registry
import hive_system
import ipaddress
import json
import mimetypes
import os
import re
import secrets
import sqlite3
import subprocess
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PureWindowsPath
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
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
# Worker routing policy read-model: capability, execution_mode, cost_mode,
# network_requirement, fallback_policy, and endpoint for every worker id this
# adapter will ever accept as `preferred_worker` in a proposal. This is a static,
# purely declarative, in-memory table -- it never calls out to any service, probes
# any port, or starts one (no LM Studio autostart, no network I/O). cost_mode is
# only ever "free" or "subscription" when there is a documented, non-speculative
# basis for it; anything genuinely uncertain is "unknown" rather than guessed, and
# evaluate_worker_policy() blocks "unknown" exactly like "metered" -- fail closed,
# never fail open, for a worker this adapter cannot vouch for.
#
# Canonical ids ("lmstudio-local", "codex-subscription") align with the names
# evidenced from the Orchestrator registry; the previously used bare ids
# ("lmstudio", "codex") are preserved as aliases below so existing callers and
# stored proposals keep working. Any id that resolves to neither a canonical key
# nor an alias is unknown and fails closed exactly like a metered worker -- it is
# never guessed into an existing entry.
WORKER_ID_ALIASES = {
    "lmstudio": "lmstudio-local",
    "codex": "codex-subscription",
    "ollama": "ollama-local",
    "cline": "cline-local",
    "kilo": "vscode-kilo",
    "opencode": "opencode-local",
    "freebuff": "freebuff-local",
    "openclaw": "openclaw-local",
    "claude": "claude-subscription",
}

# Codex can authenticate either via a ChatGPT subscription login or a metered,
# pay-per-token API key; `ao agent ls` reporting it "authorized" on this machine
# does not by itself distinguish the two. cost_mode therefore stays "unknown"
# (blocked) unless the operator explicitly confirms the credential in use is a
# subscription plan -- mirroring HIVE_HEALTH_REQUIRES_AUTH's pattern of never
# fabricating a safety-relevant claim from ambiguous evidence.
CODEX_SUBSCRIPTION_CONFIRMED = os.environ.get("CODEX_SUBSCRIPTION_CONFIRMED", "").strip().lower() in {"1", "true", "yes"}

# LM Studio's own documentation states its local server listens on this loopback
# address by default when started; this is a static, documented default -- never
# probed, dialed, or auto-started by this adapter. An operator whose install uses a
# different port may override it via LMSTUDIO_ENDPOINT, but the override is only
# ever accepted when it is itself a loopback address (see _lmstudio_endpoint());
# remote workers never get an endpoint here at all, invented or otherwise.
LMSTUDIO_DEFAULT_ENDPOINT = "http://127.0.0.1:1234"
LMSTUDIO_ENDPOINT_ENV = os.environ.get("LMSTUDIO_ENDPOINT", "").strip()
OLLAMA_DEFAULT_ENDPOINT = "http://127.0.0.1:11434"

WORKER_POLICY = {
    "deterministic": {
        "capability": "deterministic_arithmetic_evaluator",
        "execution_mode": "local",
        "cost_mode": "free",
        "network_requirement": "none",
        "fallback_policy": "none_required",
        "endpoint": None,
        "endpoint_basis": "not_applicable",  # runs in-process inside HIVE Core; not a separately dialable service
    },
    "lmstudio-local": {
        "capability": "local_llm_inference",
        "execution_mode": "local",
        "cost_mode": "free",
        "network_requirement": "loopback",
        "fallback_policy": "none_required",
        "endpoint": None,  # resolved dynamically in worker_policy_record() via _lmstudio_endpoint()
        "endpoint_basis": None,
    },
    "ollama-local": {
        "capability": "local_llm_inference",
        "execution_mode": "local",
        "cost_mode": "free",
        "network_requirement": "loopback",
        "fallback_policy": "none_required",
        "endpoint": OLLAMA_DEFAULT_ENDPOINT,
        "endpoint_basis": "documented_default",
    },
    "cline-local": {
        "capability": "coding_assistant",
        "execution_mode": "local",
        "cost_mode": "unknown",
        "network_requirement": "opt_in",
        "fallback_policy": "local_preferred",
        "endpoint": None,
        "endpoint_basis": "runtime_unverified",
    },
    "vscode-kilo": {
        "capability": "editor_coding",
        "execution_mode": "local",
        "cost_mode": "unknown",
        "network_requirement": "opt_in",
        "fallback_policy": "local_preferred",
        "endpoint": None,
        "endpoint_basis": "extension_adapter_required",
    },
    "opencode-local": {
        "capability": "code_generation",
        "execution_mode": "local",
        "cost_mode": "unknown",
        "network_requirement": "opt_in",
        "fallback_policy": "local_preferred",
        "endpoint": None,
        "endpoint_basis": "wsl_cli_adapter_required",
    },
    "freebuff-local": {
        "capability": "code_generation",
        "execution_mode": "local",
        "cost_mode": "unknown",
        "network_requirement": "opt_in",
        "fallback_policy": "local_preferred",
        "endpoint": None,
        "endpoint_basis": "wsl_cli_adapter_required",
    },
    "openclaw-local": {
        "capability": "agent_orchestration",
        "execution_mode": "local",
        "cost_mode": "unknown",
        "network_requirement": "opt_in",
        "fallback_policy": "local_preferred",
        "endpoint": None,
        "endpoint_basis": "runtime_unverified",
    },
    "openrouter_free": {
        "capability": "remote_llm_inference",
        "execution_mode": "remote",
        "cost_mode": "free",
        "network_requirement": "internet",
        "fallback_policy": "local_preferred",
        "endpoint": None,
        "endpoint_basis": "not_applicable",  # remote/cloud-routed; this adapter never declares a remote worker's endpoint
    },
    "antigravity": {
        "capability": "remote_llm_inference",
        "execution_mode": "remote",
        "cost_mode": "unknown",
        "network_requirement": "internet",
        "fallback_policy": "local_preferred",
        "endpoint": None,
        "endpoint_basis": "not_applicable",
    },
    "codex-subscription": {
        "capability": "remote_llm_inference",
        "execution_mode": "remote",
        "cost_mode": "subscription" if CODEX_SUBSCRIPTION_CONFIRMED else "unknown",
        "network_requirement": "internet",
        "fallback_policy": "local_preferred",
        "endpoint": None,
        "endpoint_basis": "not_applicable",
    },
    "claude-subscription": {
        "capability": "remote_llm_inference",
        "execution_mode": "remote",
        "cost_mode": "unknown",
        "network_requirement": "internet",
        "fallback_policy": "local_preferred",
        "endpoint": None,
        "endpoint_basis": "not_applicable",
    },
}
ACCEPTED_COST_MODES = {"free", "subscription"}


def canonical_worker_id(worker_id):
    return WORKER_ID_ALIASES.get(worker_id, worker_id)


def _lmstudio_endpoint() -> tuple[str | None, str]:
    """Static endpoint metadata for lmstudio-local. Never probes or dials the
    address -- only validates that whatever value would be declared (the
    documented default, or an operator override) is itself a loopback address. A
    non-loopback override is rejected outright (endpoint reported as None) rather
    than exposed, surfacing the rejection in endpoint_basis."""
    candidate = LMSTUDIO_ENDPOINT_ENV or LMSTUDIO_DEFAULT_ENDPOINT
    if not _is_loopback_hostname(urlparse(candidate).hostname):
        return None, "invalid_non_loopback_override_rejected"
    basis = "operator_override" if LMSTUDIO_ENDPOINT_ENV else "documented_default"
    return candidate, basis
ALLOWED_TASK_TYPES = {"EVOLUTION_TASK", "GENERAL", "ANALYSIS", "PROJECT_TASK", "RESEARCH"}
MAX_BODY = 12_000
# A successful /health response does not, by itself, prove the bearer token was
# checked: /health may be a public endpoint with no auth requirement at all. Operators
# must explicitly document (and set) this flag only if they have verified that this
# specific HIVE Core deployment's /health route requires and validates the bearer
# token. Left unset, authentication is reported as unknown rather than fabricated true.
HIVE_HEALTH_REQUIRES_AUTH = os.environ.get("HIVE_HEALTH_REQUIRES_AUTH", "").strip().lower() in {"1", "true", "yes"}

# Recognized /health and /ready status vocabularies. Anything outside these sets is
# reported as unknown rather than guessed into "healthy" or "degraded".
HEALTH_OK_STATUSES = {"ok", "healthy", "ready", "online", "alive"}
HEALTH_DEGRADED_STATUSES = {"degraded", "warning"}
READY_OK_STATUSES = {"ready", "ok", "true", "online"}
READY_NOT_READY_STATUSES = {"not_ready", "false", "unready"}

STATUS_BUCKETS = {
    "queued": {"queued", "pending", "new", "submitted", "waiting"},
    "active": {"active", "running", "in_progress", "in-progress", "started", "working"},
    "completed": {"completed", "done", "success", "succeeded", "finished"},
    "blocked": {"blocked", "failed", "error", "cancelled", "canceled", "rejected"},
}

# Read-only CREATOR OPS status adapter. The adapter never reads or writes anything
# outside this single local SQLite file, and only ever executes fixed, hardcoded
# COUNT(*) queries against a small allowlist of tables below -- no row content
# (captions, handles, notes, URLs, credentials) is ever read or exposed.
# Explicit configuration only: no user-specific default path is committed. Unset => Creator Ops reports "not configured".
CREATOR_OPS_DB_PATH = os.environ.get("CREATOR_OPS_DB_PATH", "").strip()
CREATOR_OPS_TABLES = (
    "accounts",
    "posts",
    "media_assets",
    "media_asset_tags",
    "local_tasks",
    "local_notifications",
    "ai_sessions",
    "ai_messages",
    "creative_tools",
)

# Shared Orchestrator.inc read-model sources. These are local, curated registry
# artifacts only; they never become a second task database or an execution authority.
def _configured_dir(env_name: str):
    """An absolute directory from an environment variable, or None. No user-specific default is ever used."""
    raw = os.environ.get(env_name, "").strip()
    if not raw:
        return None
    path = Path(raw)
    return path if path.is_absolute() and ".." not in path.parts else None


# The Orchestrator.inc folder of the Obsidian vault, from ORCHESTRATOR_VAULT_ROOT only. Unset => the project-registry,
# self-evolution checkpoint and context-source projections report "not configured" instead of guessing a path.
ORCHESTRATOR_VAULT_ROOT = _configured_dir("ORCHESTRATOR_VAULT_ROOT")
ORCHESTRATOR_PROJECT_REGISTRY_PATH = ORCHESTRATOR_VAULT_ROOT / "Registry" / "projects.json" if ORCHESTRATOR_VAULT_ROOT else None
ORCHESTRATOR_SELF_EVOLUTION_TASK_PATH = (ORCHESTRATOR_VAULT_ROOT / "Tasks" / "self-evolution" / "P-013-proposal-only-control-plane.ukol.md"
                                         if ORCHESTRATOR_VAULT_ROOT else None)
_CONTEXT_SOURCES_RELATIVE = {
    "orchestrator-inc": (
        "Tasks/orchestrator-inc/P-008-worker-adapters.ukol.md",
        "Tasks/orchestrator-inc/P-015-local-model-and-jarvis-discovery.ukol.md",
        "Tasks/orchestrator-inc/P-016-jarvis-stt-tts-runtime.ukol.md",
        "Tasks/orchestrator-inc/P-019-worker-inventory-and-coordination.ukol.md",
        "Tasks/orchestrator-inc/P-020-disposable-cli-worker-adapters.ukol.md",
        "Tasks/orchestrator-inc/P-021-obsidian-memory-contract.ukol.md",
        "Tasks/orchestrator-inc/P-022-session-attestation-and-routing-decision.ukol.md",
        "Operations/Memory-flow.md",
    ),
    "unified-dashboard": ("Tasks/unified-dashboard/P-018-hive-operations-cockpit.ukol.md",),
    "self-evolution": ("Tasks/self-evolution/P-013-proposal-only-control-plane.ukol.md",),
    "creator-ops": ("Tasks/orchestrator-inc/P-011-creator-ops-instagram-story-skill.ukol.md",),
    "jarvis": ("Tasks/orchestrator-inc/P-016-jarvis-stt-tts-runtime.ukol.md",),
}
ORCHESTRATOR_CONTEXT_SOURCES = ({pid: tuple(ORCHESTRATOR_VAULT_ROOT / rel for rel in rels) for pid, rels in _CONTEXT_SOURCES_RELATIVE.items()}
                                if ORCHESTRATOR_VAULT_ROOT else {})
CONTEXT_MAX_QUERY = 160
CONTEXT_MAX_RECORDS = 20
CONTEXT_MAX_CHARS = 6_000
MEMORY_SCHEMA_VERSION = "1.0"
LOCAL_INFERENCE_MAX_INSTRUCTION = 2_000
LOCAL_INFERENCE_MAX_TOKENS = 256

# AO (Agent Orchestrator) CLI bridge. AO's own documented interface is a local CLI
# (`ao`) over its daemon -- it does not publish an HTTP API contract for session,
# worker, or chat data, and this adapter never guesses at or probes the daemon's
# internal transport, and never reads AO's own internal data files directly. Instead,
# a narrow, fixed slice of the documented `ao` CLI contract is bridged via
# subprocess.run() with shell=False and a hardcoded argv-prefix allowlist:
#   - `ao session ls --all --json`              (session listing)
#   - `ao session history <id> --limit --offset` (session history, best-effort redacted)
#   - `ao send --session <id> --message <text>`  (controlled send)
# No other subcommand, flag, or dynamically-assembled shell string is ever executed.
# The bridge is disabled unless AO_CLI_PATH names an absolute, existing file; when
# disabled or when the CLI invocation fails, routes report unavailable evidence
# instead of fabricating success or falling back to any other transport.
AO_CLI_PATH = os.environ.get("AO_CLI_PATH", "")
AO_CLI_TIMEOUT_SECONDS = 8
AO_CLI_MAX_OUTPUT_CHARS = 200_000
AO_SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,99}$")
AO_CLIENT_MESSAGE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
AO_SEND_MESSAGE_MAX_LEN = 4000
AO_HISTORY_MIN_LIMIT = 1
AO_HISTORY_MAX_LIMIT = 50  # ao session history itself caps --limit at 50
AO_HISTORY_MAX_OFFSET = 100_000

# Caller-authentication gate for the two routes that actually act on a live AO
# session (send, send/recover). This is independent of AO_CLI_PATH: even when the
# CLI bridge is fully configured, a request to send/recover must present a valid
# bearer token before its body is ever read or AO is ever invoked. Unset (the
# default) is fail-closed -- every send/recover request is rejected, not silently
# allowed -- since there would be no server-held value to authenticate against.
AO_SEND_CALLER_TOKEN = os.environ.get("AO_SEND_CALLER_TOKEN", "")

# Server-controlled authorization scope for ao_send(): the single AO session this
# adapter instance is permitted to deliver a message to. Set by the operator (e.g.
# to the session selected in the dashboard UI) -- never inferred from the request
# body, so a request can never grant itself a session to send to. Empty/unset or a
# value that fails AO_SESSION_ID_PATTERN means no session is authorized, and send
# fails closed for every request, regardless of what session_id is asked for. This
# is a separate concern from AO_SEND_CALLER_TOKEN above: that answers "is this HTTP
# caller allowed to use the route at all", this answers "which single session may
# actually receive a message". send/recover is intentionally out of scope here --
# recover only retrieves the daemon's already-recorded outcome for a prior send's
# delivery handle and never delivers new message content.
AO_SEND_SESSION_ID = os.environ.get("AO_SEND_SESSION_ID", "").strip()

# Best-effort redaction of credential-shaped substrings (bearer tokens, key=value
# secrets, provider API key prefixes, AWS access key IDs, JWT-shaped strings) from
# raw `ao` CLI text before it ever reaches a response. This is a defensive, imperfect
# filter -- not a guarantee that every possible pasted secret is caught -- so callers
# must still treat AO_CLI_PATH / the ao daemon's own session content as semi-trusted.
_SECRET_PATTERNS = (
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9\-_.=]{8,}"),
    re.compile(r"(?i)\b(api[_-]?key|token|access[_-]?token|auth[_-]?token|secret|password|passwd|client[_-]?secret|private[_-]?key)\b\s*[:=]\s*[\"']?[^\s\"',}]{4,}"),
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\b[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),  # JWT-shaped
)


def redact_secrets(text: str) -> str:
    if not text:
        return text
    redacted = text
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def ao_cli_configured() -> bool:
    if not AO_CLI_PATH:
        return False
    try:
        path = Path(AO_CLI_PATH)
        return path.is_absolute() and path.is_file()
    except OSError:
        return False


def ao_send_caller_auth_configured() -> bool:
    return bool(AO_SEND_CALLER_TOKEN)


def ao_send_session_authorized() -> bool:
    return bool(AO_SEND_SESSION_ID) and bool(AO_SESSION_ID_PATTERN.match(AO_SEND_SESSION_ID))


def require_ao_send_caller_auth(headers) -> None:
    """Fail-closed caller-authentication gate for the send/recover routes only.

    Independent of AO_CLI_PATH: this must be checked, and must reject, before the
    request body is read or ao_send()/ao_recover_send() are ever called. If
    AO_SEND_CALLER_TOKEN is not configured there is no server-held value to
    authenticate against, so every request is rejected rather than treated as
    "no auth required". Comparison uses hmac.compare_digest (constant-time) against
    the server-configured token; the value a client presents is only ever the
    candidate being checked, never the expected value.
    """
    if not AO_SEND_CALLER_TOKEN:
        raise AdapterError("AO send/recover caller authentication is not configured; refusing all requests", 503)
    header = headers.get("Authorization", "") or ""
    if not header.startswith("Bearer ") or len(header) <= len("Bearer "):
        raise AdapterError("Missing or malformed Authorization header", 401)
    provided = header[len("Bearer "):]
    if not hmac.compare_digest(provided.encode("utf-8"), AO_SEND_CALLER_TOKEN.encode("utf-8")):
        raise AdapterError("Invalid caller token", 401)


def ao_capabilities() -> dict:
    """Capability declaration for the AO CLI bridge.

    session_list/history are verified, documented `ao` CLI subcommands, confirmed
    whenever AO_CLI_PATH is configured. send additionally requires the caller-auth
    gate (AO_SEND_CALLER_TOKEN) and the session-scoping gate (AO_SEND_SESSION_ID) to
    both be configured, since the route cannot actually deliver a message to any
    session otherwise -- confirmed must reflect whether the route can really be used
    end to end, not just whether the CLI binary exists. This must never diverge from
    what ao_send() itself enforces. send_recover only requires caller-auth: it never
    delivers new message content, only recovers a prior send's recorded outcome, so
    it is not scoped to AO_SEND_SESSION_ID. worker_api and realtime chat remain
    unconfirmed: no public HTTP/worker-registry contract is documented for AO, and
    this adapter never guesses at one.
    """
    configured = ao_cli_configured()
    caller_auth_configured = ao_send_caller_auth_configured()
    session_authorized = ao_send_session_authorized()
    send_usable = configured and caller_auth_configured and session_authorized
    recover_usable = configured and caller_auth_configured
    return {
        "session_list_confirmed": configured,
        "session_history_confirmed": configured,
        "send_confirmed": send_usable,
        "send_recover_confirmed": recover_usable,
        "caller_auth_configured": caller_auth_configured,
        "send_session_authorized": session_authorized,
        "authorized_send_session_id": AO_SEND_SESSION_ID or None,
        "worker_api_confirmed": False,
        "chat_realtime_api_confirmed": False,
        "transport": "cli_subprocess" if configured else "cli_disabled",
        "cli_path_configured": configured,
        "reason": (
            "Session listing (`ao session ls --all --json`), history "
            "(`ao session history <id>`), and controlled send are verified, "
            "documented `ao` CLI subcommands, bridged via subprocess.run(shell=False) "
            "with a fixed argv allowlist, bounded timeout/output, and best-effort "
            "secret redaction -- only when AO_CLI_PATH names an absolute, existing ao "
            "binary. Send always uses the atomic `ao send --steer` transport with a "
            "`--client-message-id`, per send.md the only AO send mode with a "
            "documented idempotent round-trip; a failed/uncertain send preserves that "
            "id so the outcome can be recovered via `--recover-only` instead of "
            "resent. send/send-recover additionally require AO_SEND_CALLER_TOKEN: "
            "the caller must present a matching `Authorization: Bearer <token>` "
            "header, checked with a constant-time comparison before the request "
            "body is read or AO is invoked, and rejected outright if the token is "
            "not configured. send is further scoped to AO_SEND_SESSION_ID, the one "
            "operator-authorized session id a message may ever be delivered to; "
            "unset or malformed AO_SEND_SESSION_ID fails every send closed, and a "
            "live, non-terminated match in `ao session ls` is re-verified on every "
            "send as defense in depth. No other AO HTTP endpoint, worker registry, "
            "or internal SQLite store is read, and the bridge reports unavailable "
            "rather than fabricating success when unconfigured or when a call fails."
        ),
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


def run_ao_cli(args: list[str], allow_prefix: tuple[str, ...]) -> str:
    """Execute the local `ao` CLI with a fixed, allowlisted subcommand prefix.

    shell=False and an argv list (never a shell string) are used throughout, so no
    session id or message content can be interpreted as shell syntax. allow_prefix is
    an explicit, hardcoded defense-in-depth check: even if a future code change built
    `args` incorrectly, a call whose first tokens are not one of the three allowlisted
    subcommand prefixes is refused before any process is spawned.
    """
    if not ao_cli_configured():
        raise AdapterError(
            "AO CLI bridge is not configured; set AO_CLI_PATH to an absolute path to the ao binary to enable it",
            503,
        )
    if tuple(args[: len(allow_prefix)]) != allow_prefix:
        raise AdapterError("AO CLI subcommand is not in the allowlist", 403)
    try:
        result = subprocess.run(
            [AO_CLI_PATH, *args],
            shell=False,
            capture_output=True,
            text=True,
            timeout=AO_CLI_TIMEOUT_SECONDS,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        raise AdapterError(f"AO CLI timed out after {AO_CLI_TIMEOUT_SECONDS}s", 504) from None
    except OSError as error:
        raise AdapterError(f"AO CLI could not be executed: {error}", 502) from None
    stdout = (result.stdout or "")[:AO_CLI_MAX_OUTPUT_CHARS]
    if result.returncode != 0:
        detail = redact_secrets((result.stderr or result.stdout or "").strip())[:500]
        raise AdapterError(f"AO CLI exited with status {result.returncode}: {detail}", 502)
    return stdout


def validate_ao_session_id(session_id) -> str:
    if not isinstance(session_id, str) or not AO_SESSION_ID_PATTERN.match(session_id):
        raise AdapterError("Invalid session id", 400)
    return session_id


def parse_bounded_int(raw: str, name: str, minimum: int, maximum: int, default: int) -> int:
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise AdapterError(f"{name} must be an integer", 400) from None
    if not (minimum <= value <= maximum):
        raise AdapterError(f"{name} must be between {minimum} and {maximum}", 400)
    return value


def ao_sessions() -> tuple[list, dict]:
    """Normalize `ao session ls --all --json` into a safe, fixed field set.

    Unavailable (bridge disabled, CLI error, timeout) and unknown (non-JSON or
    unexpected shape) are reported distinctly, never collapsed into a fabricated
    empty-but-valid list."""
    source = "ao-cli:session ls --all --json"
    try:
        raw = run_ao_cli(["session", "ls", "--all", "--json"], ("session", "ls"))
    except AdapterError as error:
        return [], evidence(source, None, "unavailable", str(error))
    try:
        parsed = json.loads(raw) if raw.strip() else {}
    except (ValueError, UnicodeError) as error:
        return [], evidence(source, None, "unknown", f"AO CLI returned invalid JSON: {error}")
    items = parsed.get("data") if isinstance(parsed, dict) else parsed
    items = items if isinstance(items, list) else []
    sessions = []
    for item in items:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        sessions.append({
            "id": item["id"],
            "project_id": item.get("projectId"),
            "role": item.get("role"),
            "display_name": redact_secrets(str(item.get("displayName") or "")),
            "status": item.get("status", "unknown"),
            "activity": item.get("activity"),
            "harness": item.get("harness"),
            "branch": redact_secrets(str(item.get("branch") or "")) or None,
            "is_terminated": bool(item.get("isTerminated", False)),
            "last_activity_at": item.get("lastActivityAt"),
            "created_at": item.get("createdAt"),
            "updated_at": item.get("updatedAt"),
        })
    return sessions, evidence(source, utc_now(), "valid")


def ao_session_history(session_id: str, limit: int, offset: int) -> tuple[str, dict]:
    """Fetch `ao session history <id> --limit --offset` text verbatim (bounded,
    best-effort secret-redacted), with explicit provenance. Never fabricated when the
    CLI is unavailable or fails -- an empty string with unavailable evidence instead."""
    source = f"ao-cli:session history {session_id} --limit {limit} --offset {offset}"
    try:
        raw = run_ao_cli(
            ["session", "history", session_id, "--limit", str(limit), "--offset", str(offset)],
            ("session", "history"),
        )
    except AdapterError as error:
        return "", evidence(source, None, "unavailable", str(error))
    return redact_secrets(raw), evidence(source, utc_now(), "valid")


def validate_client_message_id(client_message_id) -> str:
    if not isinstance(client_message_id, str) or not AO_CLIENT_MESSAGE_ID_PATTERN.match(client_message_id):
        raise AdapterError("Invalid client_message_id", 400)
    return client_message_id


def require_authorized_ao_send_session(session_id: str) -> None:
    """Fail-closed authorization gate scoping ao_send() to the single
    operator-configured AO_SEND_SESSION_ID. A syntactically valid session id in the
    request is never, by itself, sufficient to authorize a send -- it must equal
    the server-configured target. Unset or malformed AO_SEND_SESSION_ID refuses
    every send, with no exceptions.

    As defense in depth beyond that equality check, the authorized session id must
    additionally appear, and not be terminated, in this call's own live
    `ao session ls` result: an unavailable session list fails the send closed
    rather than trusting a stale authorization or the caller's claim.
    """
    if not ao_send_session_authorized():
        raise AdapterError(
            "Send is not authorized: AO_SEND_SESSION_ID is not configured, or is configured with an invalid "
            "format; refusing to send to any session with no server-authorized target.",
            403,
        )
    if session_id != AO_SEND_SESSION_ID:
        raise AdapterError("Session id is not the server-authorized send target", 403)
    sessions, sessions_evidence = ao_sessions()
    if sessions_evidence.get("validity") != "valid":
        raise AdapterError(
            f"Cannot verify the authorized session is live: {sessions_evidence.get('reason') or 'no evidence'}",
            503,
        )
    live_session = next((item for item in sessions if item.get("id") == session_id), None)
    if live_session is None:
        raise AdapterError("Authorized session id was not found in the live AO session list", 403)
    if live_session.get("is_terminated"):
        raise AdapterError("Authorized session is terminated and cannot receive messages", 403)


def ao_send(session_id, message, confirm, client_message_id=None) -> dict:
    """Controlled, fail-closed bridge to AO's documented atomic steering transport:
    `ao send --session <id> --steer --message <text> --client-message-id <id>`.

    --steer is always used (never the plain, non-atomic send) because it is the only
    AO send mode with a documented, idempotent round-trip: per send.md, "--steer uses
    one atomic daemon operation" and every steering request carries a client message
    id that "lets the daemon return the durable steering receipt or normal turn
    without delivering the message twice" on retry. A caller-supplied
    client_message_id is validated and reused (never silently replaced) so a client
    retrying after an uncertain result reuses the same handle instead of risking a
    duplicate delivery; when omitted, a fresh one is generated here.

    Mirrors dispatch()'s confirmation gate: an explicit confirm=true is required, the
    session id and message are validated before any process is spawned. On failure
    (bridge disabled, CLI error, timeout) the client_message_id is preserved in the
    raised error so the caller can recover the delivery outcome via ao_recover_send()
    -- per send.md, "do not invent a new client message id after an uncertain
    result" -- rather than blindly resending.

    Scoped to the single operator-authorized AO_SEND_SESSION_ID (see
    require_authorized_ao_send_session()): the request's session_id is never
    trusted by itself, even once it passes format validation."""
    if confirm is not True:
        raise AdapterError("Explicit confirmation is required", 400)
    validate_ao_session_id(session_id)
    text = str(message or "").strip()
    if not (1 <= len(text) <= AO_SEND_MESSAGE_MAX_LEN):
        raise AdapterError(f"message must be between 1 and {AO_SEND_MESSAGE_MAX_LEN} characters", 400)
    client_message_id = validate_client_message_id(client_message_id) if client_message_id is not None else secrets.token_urlsafe(18)
    if not ao_cli_configured():
        raise AdapterError(
            "AO CLI bridge is not configured; set AO_CLI_PATH to an absolute path to the ao binary to enable it",
            503,
        )
    require_authorized_ao_send_session(session_id)
    args = ["send", "--session", session_id, "--steer", "--message", text, "--client-message-id", client_message_id]
    try:
        raw = run_ao_cli(args, ("send",))
    except AdapterError as error:
        raise AdapterError(
            f"{error} -- delivery is uncertain; recover with client_message_id={client_message_id} via "
            "POST /api/ao/sessions/<id>/send/recover once the transport issue clears, do not resend",
            error.status,
        ) from None
    return {
        "session_id": session_id,
        "client_message_id": client_message_id,
        "output": redact_secrets(raw.strip())[:2000],
        "evidence": evidence(
            f"ao-cli:send --session {session_id} --steer --client-message-id {client_message_id}", utc_now(), "valid"
        ),
    }


def ao_recover_send(session_id, client_message_id, confirm) -> dict:
    """Bridge to `ao send --session <id> --steer --recover-only --client-message-id
    <id>`. Recovers the daemon's recorded outcome for a prior send's delivery handle
    without contacting the provider again and without resending the original
    message, so it can never double-deliver. Used after ao_send() reports an
    uncertain/failed result for the same client_message_id."""
    if confirm is not True:
        raise AdapterError("Explicit confirmation is required", 400)
    validate_ao_session_id(session_id)
    validate_client_message_id(client_message_id)
    args = ["send", "--session", session_id, "--steer", "--recover-only", "--client-message-id", client_message_id]
    raw = run_ao_cli(args, ("send",))
    return {
        "session_id": session_id,
        "client_message_id": client_message_id,
        "output": redact_secrets(raw.strip())[:2000],
        "evidence": evidence(
            f"ao-cli:send --session {session_id} --steer --recover-only --client-message-id {client_message_id}",
            utc_now(),
            "valid",
        ),
    }


# Snapshot-scoped preflight gate (GAP-9). Inside snapshot() the FIRST Core call is a bounded preflight; if it fails at the
# connection level (refused / no response in time), every remaining GET to Core in that snapshot is skipped and reports the same
# unavailable state with a reason instead of waiting for its own timeout (on Windows a refused loopback connect can take ~2 s each).
# HTTP errors (401/403/404/500...) prove Core is reachable and never trip the gate. Nothing is cached across snapshots.
CORE_PREFLIGHT_TIMEOUT_S = 1.5
CORE_CALL_TIMEOUT_S = 4
_core_gate = threading.local()


@contextmanager
def core_snapshot_scope():
    _core_gate.state = {"first": True, "down": None}
    try:
        yield
    finally:
        _core_gate.state = None


def core_json(path: str, method: str = "GET", body: dict | None = None, idempotency_key: str | None = None):
    if not CORE_URL_IS_LOOPBACK:
        raise AdapterError("HIVE_CORE_URL does not resolve to a loopback address; refusing to contact a non-loopback Core", 503)
    allowed_routes = {"/health", "/ready", "/projects", "/workers", "/system", "/events", "/evolution", "/engineering/architecture", "/tasks", "/missions"}
    if urlparse(path).path not in allowed_routes:
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
    gate = getattr(_core_gate, "state", None) if method == "GET" else None
    timeout = CORE_CALL_TIMEOUT_S
    if gate is not None:
        if gate["down"]:
            raise AdapterError(gate["down"], 503)
        if gate["first"]:
            timeout, gate["first"] = CORE_PREFLIGHT_TIMEOUT_S, False
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read(512_000)
            return json.loads(raw.decode("utf-8")) if raw else {}
    except HTTPError as error:
        detail = error.read(4_000).decode("utf-8", "replace")
        if error.code in (401, 403):
            raise AdapterError("HIVE Core rejected authentication or authorization", error.code) from None
        raise AdapterError(f"HIVE Core returned HTTP {error.code}: {detail[:240]}", error.code) from None
    except (URLError, TimeoutError, OSError) as error:
        reason = f"HIVE Core is unavailable: {error.reason if hasattr(error, 'reason') else error}"
        # connection-level only: a refused/unreachable/timed-out socket (an OSError or timeout), not any URLError
        transport = isinstance(error, (TimeoutError, OSError)) and not isinstance(error, URLError) or isinstance(getattr(error, "reason", None), (OSError, TimeoutError))
        if gate is not None and gate["down"] is None and transport:
            gate["down"] = reason + " (preflight failed; the remaining HIVE Core probes were skipped in this snapshot)"
        raise AdapterError(reason, 503) from None
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
    """Map a failed Core call to a validity distinct from plain unreachability.

    A 401/403 proves the endpoint is reachable but rejected the request as
    unauthenticated/unauthorized -- that is "auth_required", never collapsed into
    the same "unavailable" bucket as a connection failure or timeout.
    """
    if error.status in (401, 403):
        return "auth_required"
    return "unknown" if error.status == 404 else "unavailable"


def worker_policy_record(worker_id: str) -> dict:
    """Read-model lookup for one worker id. Pure table lookup -- no I/O, no
    process/service start. worker_id is resolved through WORKER_ID_ALIASES first
    (e.g. the old bare "lmstudio"/"codex" ids still resolve to their canonical
    "lmstudio-local"/"codex-subscription" entries). A worker id that resolves to
    neither a canonical key nor an alias is reported with every field "unknown"
    (never guessed), which evaluate_worker_policy() then blocks exactly like a
    documented "metered"/"unknown" cost_mode."""
    canonical = canonical_worker_id(worker_id)
    policy = WORKER_POLICY.get(canonical)
    if policy is None:
        return {
            "worker_id": worker_id,
            "canonical_worker_id": canonical,
            "capability": None,
            "execution_mode": "unknown",
            "cost_mode": "unknown",
            "network_requirement": "unknown",
            "fallback_policy": "unknown",
            "endpoint": None,
            "endpoint_basis": "unknown",
            "cost_mode_allowed": False,
        }
    record = {"worker_id": worker_id, "canonical_worker_id": canonical, **policy}
    if canonical == "lmstudio-local":
        record["endpoint"], record["endpoint_basis"] = _lmstudio_endpoint()
    record["cost_mode_allowed"] = policy["cost_mode"] in ACCEPTED_COST_MODES
    # Defense in depth: never expose a non-loopback endpoint for any worker, even if
    # a future edit to WORKER_POLICY or an operator override introduced one, and
    # never expose one at all for a remote worker -- this is purely a read-model
    # assertion, not a probe, and never influences cost_mode/execution_mode.
    endpoint = record.get("endpoint")
    if endpoint is not None and (record["execution_mode"] != "local" or not _is_loopback_hostname(urlparse(endpoint).hostname)):
        record["endpoint"] = None
        record["endpoint_basis"] = "invalid_rejected"
    return record


def worker_policy_catalog() -> dict:
    """Full, static worker-policy read-model for every known worker id. Purely
    declarative: never probes a port, never starts a local service (e.g. LM
    Studio) as a side effect of being read."""
    return {
        "local_first_enforced": True,
        "accepted_cost_modes": sorted(ACCEPTED_COST_MODES),
        "workers": [worker_policy_record(worker_id) for worker_id in sorted(WORKER_POLICY)],
    }


def evaluate_worker_policy(worker_id, local_only: bool) -> dict:
    """Request-time admission check for a candidate `preferred_worker`.

    Enforces, in order:
    1. A fail-closed cost-mode allowlist -- only "free" and "subscription" are
       accepted; "metered" and "unknown" (including any worker id not present in
       WORKER_POLICY) are always blocked, never allowed through by default.
    2. Local-first routing -- when the caller requests `local_only`, only a worker
       with execution_mode "local" is permitted; a remote worker is blocked
       regardless of its cost_mode.

    Pure function: no network I/O, no subprocess, no service start. Returns a
    read-model record describing the decision; never raises -- callers (e.g.
    dispatch()) decide whether `allowed: false` should fail the request.
    """
    record = worker_policy_record(worker_id)
    if not record["cost_mode_allowed"]:
        return {
            **record,
            "allowed": False,
            "blocked_reason": (
                f"cost_mode '{record['cost_mode']}' is not in the accepted allowlist "
                f"{sorted(ACCEPTED_COST_MODES)}"
            ),
        }
    if local_only and record["execution_mode"] != "local":
        return {
            **record,
            "allowed": False,
            "blocked_reason": (
                f"execution_mode '{record['execution_mode']}' is not local; local-first "
                "routing requires a local worker when local_only is set"
            ),
        }
    return {**record, "allowed": True, "blocked_reason": None}


def validate_session_attestation(attestation: dict) -> bool:
    """Validate shape only; this never proves provider identity or billing."""
    if not isinstance(attestation, dict) or any(key in attestation for key in ("token", "access_token", "cookie", "raw_session", "transcript")):
        return False
    required = {"worker_id", "provider", "execution_mode", "cost_mode", "session_ref_hash", "session_identity", "execution_ready", "network", "sandbox", "observed_at"}
    if not required.issubset(attestation):
        return False
    return (
        bool(str(attestation.get("worker_id") or ""))
        and bool(str(attestation.get("provider") or ""))
        and attestation.get("execution_mode") in {"local", "remote"}
        and attestation.get("cost_mode") in {"free", "subscription", "metered", "unknown"}
        and bool(ATTESTATION_HASH_PATTERN.fullmatch(str(attestation.get("session_ref_hash") or "")))
        and attestation.get("session_identity") in {"verified", "unverified"}
        and isinstance(attestation.get("execution_ready"), bool)
        and bool(str(attestation.get("network") or ""))
        and bool(str(attestation.get("sandbox") or ""))
        and bool(str(attestation.get("observed_at") or ""))
    )


def routing_decision(payload: dict) -> dict:
    """Return a proposal-only routing decision; never launches or persists a task."""
    if not isinstance(payload, dict) or payload.get("confirm") is not True:
        raise AdapterError("Explicit confirmation is required for a routing proposal", 400)
    task_id = str(payload.get("task_id") or "")
    project_id = str(payload.get("project_id") or "")
    capability = str(payload.get("capability") or "")
    if not ROUTING_TASK_ID_PATTERN.fullmatch(task_id) or not (1 <= len(project_id) <= 120) or not (1 <= len(capability) <= 120):
        raise AdapterError("task_id, project_id and capability are required and bounded", 400)
    context_hash = str(payload.get("context_hash") or "")
    if context_hash and not ATTESTATION_HASH_PATTERN.fullmatch(context_hash):
        raise AdapterError("context_hash must use sha256:<64 lowercase hex> when supplied", 400)
    local_only = bool(payload.get("local_only"))
    preferred = canonical_worker_id(payload.get("preferred_worker")) if payload.get("preferred_worker") else None
    raw_attestations = payload.get("attestations") or []
    if not isinstance(raw_attestations, list) or len(raw_attestations) > 20:
        raise AdapterError("attestations must be a bounded list", 400)
    attestations = {}
    for attestation in raw_attestations:
        if not validate_session_attestation(attestation):
            raise AdapterError("Invalid session attestation shape; raw sessions and credentials are not accepted", 400)
        attestations[canonical_worker_id(attestation["worker_id"])] = attestation
    order = [preferred] if preferred else []
    order.extend(worker_id for worker_id in ("deterministic", "lmstudio-local", "opencode-local", "freebuff-local", "codex-subscription", "claude-subscription") if worker_id not in order)
    candidates = []
    for worker_id in order:
        if not worker_id:
            continue
        policy = evaluate_worker_policy(worker_id, local_only)
        if capability not in {"any", "general"} and policy["capability"] != capability:
            continue
        attestation = attestations.get(policy["canonical_worker_id"])
        candidate = {
            "worker_id": policy["canonical_worker_id"],
            "capability": policy["capability"],
            "policy_allowed": policy["allowed"],
            "attestation_valid": bool(attestation),
            "execution_ready": False,
            "blocked_reason": policy["blocked_reason"],
        }
        if candidate["policy_allowed"] and not attestation:
            candidate["blocked_reason"] = "No session attestation was supplied"
        elif candidate["policy_allowed"] and attestation:
            candidate["blocked_reason"] = "Attestation shape is valid but provider identity is not independently verified by this adapter"
        candidates.append(candidate)
    return {
        "kind": "routing_decision",
        "status": "blocked",
        "task_id": task_id,
        "project_id": project_id,
        "capability": capability,
        "selected_worker": None,
        "candidates": candidates,
        "execution": "none",
        "proposal_only": True,
        "evidence": evidence("orchestrator:routing-decision", utc_now(), "valid", "Proposal-only decision; no worker, provider session, HIVE task, file or canonical state was changed."),
    }


def handoff_proposal(payload: dict) -> dict:
    """Return bounded resume/handoff evidence without delivering or persisting it."""
    if not isinstance(payload, dict) or payload.get("confirm") is not True:
        raise AdapterError("Explicit confirmation is required for a handoff proposal", 400)
    task_id = str(payload.get("task_id") or "")
    project_id = str(payload.get("project_id") or "")
    attempt_id = str(payload.get("attempt_id") or "")
    idempotency_key = str(payload.get("idempotency_key") or "")
    if not ROUTING_TASK_ID_PATTERN.fullmatch(task_id) or not (1 <= len(project_id) <= 120):
        raise AdapterError("task_id and project_id are required and bounded", 400)
    if not HANDOFF_REFERENCE_PATTERN.fullmatch(attempt_id):
        raise AdapterError("attempt_id must be a bounded reference", 400)
    if not HANDOFF_REFERENCE_PATTERN.fullmatch(idempotency_key):
        raise AdapterError("idempotency_key must be a bounded reference", 400)
    attempt_number = payload.get("attempt_number", 1)
    if not isinstance(attempt_number, int) or isinstance(attempt_number, bool) or not 1 <= attempt_number <= 1000:
        raise AdapterError("attempt_number must be between 1 and 1000", 400)
    reason = str(payload.get("reason") or "")
    if reason not in HANDOFF_REASONS:
        raise AdapterError("reason is not in the handoff allowlist", 400)
    delivery_state = str(payload.get("delivery_state") or "not_sent")
    if delivery_state not in HANDOFF_DELIVERY_STATES:
        raise AdapterError("delivery_state is not in the handoff allowlist", 400)
    context_hash = str(payload.get("context_hash") or "")
    if context_hash and not ATTESTATION_HASH_PATTERN.fullmatch(context_hash):
        raise AdapterError("context_hash must use sha256:<64 lowercase hex> when supplied", 400)
    sender = str(payload.get("sender_worker") or "")
    recipient = str(payload.get("recipient_worker") or "")
    if sender and not HANDOFF_REFERENCE_PATTERN.fullmatch(sender):
        raise AdapterError("sender_worker must be a bounded reference", 400)
    if recipient and not HANDOFF_REFERENCE_PATTERN.fullmatch(recipient):
        raise AdapterError("recipient_worker must be a bounded reference", 400)

    if delivery_state == "delivered":
        status = "blocked"
        resume_action = "recover_delivery_outcome"
        blocked_reason = "delivery_already_confirmed; resend is forbidden"
        retry_allowed = False
    elif delivery_state == "uncertain":
        status = "blocked"
        resume_action = "recover_delivery_outcome"
        blocked_reason = "delivery_outcome_uncertain; recover the existing idempotency key before retry"
        retry_allowed = False
    else:
        status = "handoff_required"
        resume_action = "resume_from_checkpoint"
        blocked_reason = None
        retry_allowed = False if reason == "limit_reached" else True
    return {
        "kind": "handoff_proposal",
        "status": status,
        "task_id": task_id,
        "project_id": project_id,
        "attempt": {"attempt_id": attempt_id, "attempt_number": attempt_number},
        "idempotency_key": idempotency_key,
        "sender_worker": sender or None,
        "recipient_worker": recipient or None,
        "reason": reason,
        "delivery_state": delivery_state,
        "resume": {
            "required": True,
            "action": resume_action,
            "retry_allowed": retry_allowed,
            "checkpoint_hash": context_hash or None,
        },
        "blocked_reason": blocked_reason,
        "execution": "none",
        "proposal_only": True,
        "evidence": evidence("orchestrator:handoff-proposal", utc_now(), "valid", "Bounded handoff evidence only; no delivery, worker launch, retry or canonical state was changed."),
    }


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


def orchestrator_project_registry():
    """Read the curated Obsidian project registry without exposing raw payloads."""
    source = "obsidian:Registry/projects.json"
    if ORCHESTRATOR_PROJECT_REGISTRY_PATH is None:
        return [], evidence(source, None, "unavailable", "Project registry not configured: set ORCHESTRATOR_VAULT_ROOT")
    try:
        raw = json.loads(ORCHESTRATOR_PROJECT_REGISTRY_PATH.read_text(encoding="utf-8"))
        records = raw.get("projects", []) if isinstance(raw, dict) else []
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        return [], evidence(source, None, "unavailable", f"Project registry unavailable: {error}")
    items = []
    for item in records:
        if not isinstance(item, dict) or not item.get("id") or not item.get("name"):
            continue
        registration = str(item.get("registration", "unknown"))
        workspace = item.get("workspace")
        items.append({
            "id": item["id"],
            "name": item["name"],
            "status": "active" if registration == "registered" else "waiting" if registration in {"planned", "historical-implementation-found"} else "unknown",
            "registration": registration,
            "workspace": workspace,
            "workspace_present": bool(workspace and Path(workspace).is_dir()),
            "dashboard_role": item.get("dashboardRole", "scoped read-model"),
            "authority": item.get("authority", []),
        })
    return items, evidence(source, utc_now(), "valid", "Curated project registry loaded read-only; HIVE Core catalog remains separate.")


def _context_project_ids() -> set[str]:
    projects, _ = orchestrator_project_registry()
    return {str(item["id"]) for item in projects} | set(ORCHESTRATOR_CONTEXT_SOURCES)


def _context_source_paths(project_id: str) -> tuple[Path, ...]:
    if project_id not in _context_project_ids():
        raise AdapterError(f"Unknown memory project scope: {project_id}", 404)
    return ORCHESTRATOR_CONTEXT_SOURCES.get(project_id, ())


def validate_memory_envelope(envelope: dict) -> bool:
    required = {"schema_version", "entity_type", "project_id", "state", "privacy", "retention", "canonical", "source_ref", "observed_at", "source_hash", "content_hash", "redaction"}
    return isinstance(envelope, dict) and required.issubset(envelope) and envelope.get("schema_version") == MEMORY_SCHEMA_VERSION and isinstance(envelope.get("canonical"), bool) and all(isinstance(envelope.get(key), str) and envelope.get(key) for key in required - {"canonical"})


def _context_record(project_id: str, path: Path, include_content: bool = False) -> dict | None:
    if ORCHESTRATOR_VAULT_ROOT is None:
        return None
    try:
        resolved = path.resolve()
        root = ORCHESTRATOR_VAULT_ROOT.resolve()
        if root not in resolved.parents or resolved.suffix.lower() != ".md":
            return None
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    if len(raw) > 128_000:
        return None
    content = redact_secrets(raw)
    title_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    state_match = re.search(r"^state:\s*(\S+)", content, re.MULTILINE)
    updated_match = re.search(r"^updated_at:\s*(\S+)", content, re.MULTILINE)
    compact = re.sub(r"\s+", " ", content).strip()
    record = {
        "record_id": path.stem,
        "project_id": project_id,
        "title": title_match.group(1).strip() if title_match else path.stem,
        "state": state_match.group(1) if state_match else "unknown",
        "source": str(path.relative_to(ORCHESTRATOR_VAULT_ROOT)).replace("\\", "/"),
        "source_revision": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "updated_at": updated_match.group(1) if updated_match else None,
        "provenance": "LIVE_LOCAL_FILE",
        "freshness": "observed",
        "snippet": compact[:600],
    }
    relative_source = str(path.relative_to(ORCHESTRATOR_VAULT_ROOT)).replace("\\", "/")
    envelope = {
        "schema_version": MEMORY_SCHEMA_VERSION,
        "entity_type": "task_checkpoint" if ".ukol." in path.name else "memory_note",
        "project_id": project_id,
        "state": record["state"],
        "privacy": "internal",
        "retention": "durable",
        "canonical": True,
        "source_ref": relative_source,
        "observed_at": utc_now(),
        "source_hash": record["source_revision"],
        "content_hash": record["content_hash"],
        "redaction": "secrets_removed",
    }
    record["memory_envelope"] = envelope
    record["memory_envelope_valid"] = validate_memory_envelope(envelope)
    if include_content:
        record["content"] = content[:CONTEXT_MAX_CHARS]
    return record


def context_status() -> dict:
    projects, registry_evidence = orchestrator_project_registry()
    by_id = {project["id"]: project for project in projects}
    items = []
    for project_id in sorted(set(by_id) | set(ORCHESTRATOR_CONTEXT_SOURCES)):
        paths = ORCHESTRATOR_CONTEXT_SOURCES.get(project_id, ())
        records = [_context_record(project_id, path) for path in paths]
        items.append({
            "project_id": project_id,
            "name": by_id.get(project_id, {}).get("name", project_id),
            "status": "available" if any(records) else "prepared" if paths else "no_approved_sources",
            "record_count": sum(1 for record in records if record),
            "scope": "project-scoped, read-only, proposal-only writes",
        })
    return {
        "operations": ["status", "search", "get", "build_context", "propose"],
        "items": items,
        "evidence": evidence("obsidian:Registry/projects.json", utc_now(), registry_evidence["validity"], "Shared context adapter uses only explicit project-scoped allowlisted files; no canonical write was performed."),
    }


def context_search(project_id: str, query: str, limit: int = 20) -> dict:
    query = str(query or "").strip()
    if len(query) > CONTEXT_MAX_QUERY:
        raise AdapterError(f"Memory query exceeds {CONTEXT_MAX_QUERY} characters", 400)
    limit = max(1, min(int(limit), CONTEXT_MAX_RECORDS))
    records = [_context_record(project_id, path) for path in _context_source_paths(project_id)]
    records = [record for record in records if record]
    terms = [term.lower() for term in re.findall(r"[\w-]+", query)]
    if terms:
        records = [record for record in records if all(term in (record["title"] + " " + record["snippet"]).lower() for term in terms)]
    return {"items": records[:limit], "evidence": evidence(f"obsidian:context/{project_id}", utc_now(), "valid", "Bounded project-scoped search; source content and provider sessions remain local." )}


def context_get(project_id: str, record_id: str) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", str(record_id or "")):
        raise AdapterError("Invalid memory record id", 400)
    for path in _context_source_paths(project_id):
        if path.stem == record_id:
            record = _context_record(project_id, path, include_content=True)
            if record:
                return {"item": record, "evidence": evidence(record["source"], utc_now(), "valid", "Read-only bounded context record." )}
            raise AdapterError("Memory record is unavailable", 503)
    raise AdapterError("Memory record is not in the project scope", 404)


def context_build(project_id: str, record_ids: list[str], max_chars: int = CONTEXT_MAX_CHARS) -> dict:
    if not isinstance(record_ids, list) or not record_ids or len(record_ids) > 8:
        raise AdapterError("build_context requires 1 to 8 record_ids", 400)
    max_chars = max(500, min(int(max_chars), CONTEXT_MAX_CHARS))
    records = [context_get(project_id, record_id)["item"] for record_id in record_ids]
    used = 0
    bounded = []
    for record in records:
        content = record.get("content", "")
        remaining = max_chars - used
        if remaining <= 0:
            break
        record = {**record, "content": content[:remaining]}
        bounded.append(record)
        used += len(record["content"])
    pack_hash = hashlib.sha256(json.dumps(bounded, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    return {
        "project_id": project_id,
        "records": bounded,
        "content_hash": pack_hash,
        "provenance": "DERIVED_LOCAL_CONTEXT",
        "evidence": evidence(f"obsidian:context/{project_id}", utc_now(), "valid", "Bounded context pack; no memory or canonical file was changed."),
    }


def context_propose(payload: dict) -> dict:
    if not isinstance(payload, dict) or payload.get("confirm") is not True:
        raise AdapterError("Explicit confirmation is required for a context proposal", 400)
    project_id = str(payload.get("project_id") or "")
    summary = str(payload.get("summary") or "").strip()
    record_ids = payload.get("record_ids")
    if len(summary) < 8 or len(summary) > 1200:
        raise AdapterError("Proposal summary must be between 8 and 1200 characters", 400)
    context = context_build(project_id, record_ids)
    proposal_id = hashlib.sha256(f"{project_id}|{summary}|{context['content_hash']}".encode("utf-8")).hexdigest()[:20]
    return {
        "kind": "context_proposal",
        "id": f"ctx-{proposal_id}",
        "status": "proposed",
        "project_id": project_id,
        "summary": redact_secrets(summary),
        "record_ids": record_ids,
        "content_hash": context["content_hash"],
        "evidence": evidence("orchestrator:context-proposal", utc_now(), "valid", "Proposal-only; no file, memory, HIVE, WONG or provider state was changed."),
    }


def self_evolution_status():
    """Project-scoped P-013 checkpoint projection; proposal-only and read-only."""
    source = "obsidian:Tasks/self-evolution/P-013-proposal-only-control-plane.ukol.md"
    if ORCHESTRATOR_SELF_EVOLUTION_TASK_PATH is None:
        return {"item": None, "evidence": evidence(source, None, "unavailable", "Self-evolution checkpoint not configured: set ORCHESTRATOR_VAULT_ROOT")}
    try:
        text = ORCHESTRATOR_SELF_EVOLUTION_TASK_PATH.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        return {"item": None, "evidence": evidence(source, None, "unavailable", f"Self-evolution checkpoint unavailable: {error}")}
    if len(text) > 128_000:
        return {"item": None, "evidence": evidence(source, None, "unknown", "Self-evolution checkpoint exceeds bounded read size")}
    state_match = re.search(r"^state:\s*(\S+)", text, re.MULTILINE)
    next_match = re.search(r"^- next_action:\s*(.+)$", text, re.MULTILINE)
    blocker_match = re.search(r"^- blocker:\s*(.+)$", text, re.MULTILINE)
    checked = len(re.findall(r"^(?:- |\d+\. )\[x\]", text, re.MULTILINE))
    open_items = len(re.findall(r"^(?:- |\d+\. )\[ \]", text, re.MULTILINE))
    hive_raw, hive_evidence = fetch_with_evidence("/evolution")
    checkpoint_evidence = evidence(source, utc_now(), "valid", "P-013 checkpoint loaded read-only; no evolution action was executed.")
    if hive_evidence["validity"] == "valid" and not isinstance(hive_raw, list) and not (isinstance(hive_raw, dict) and isinstance(hive_raw.get("items"), list)):
        hive_evidence = evidence("hive:/evolution", hive_evidence.get("observed_at"), "unknown", "HIVE /evolution returned an unsupported response shape")
    statuses = {}
    for proposal in unwrap_items(hive_raw):
        if isinstance(proposal, dict):
            status = str(proposal.get("status", "UNKNOWN"))
            statuses[status] = statuses.get(status, 0) + 1
    return {
        "item": {
            "id": "P-013",
            "name": "Self-evolution control plane",
            "status": state_match.group(1) if state_match else "unknown",
            "completed_steps": checked,
            "open_steps": open_items,
            "next_action": next_match.group(1).strip() if next_match else None,
            "blocker": blocker_match.group(1).strip() if blocker_match else None,
            "proposal_only": True,
        },
        "hive": {
            "proposal_count": sum(statuses.values()),
            "statuses": statuses,
            "evidence": hive_evidence,
        },
        "checkpoint_evidence": checkpoint_evidence,
        "evidence": checkpoint_evidence if hive_evidence["validity"] == "valid" else evidence(
            f"{source} + hive:/evolution",
            hive_evidence.get("observed_at") or checkpoint_evidence["observed_at"],
            hive_evidence["validity"],
            f"P-013 checkpoint is valid, but HIVE /evolution is {hive_evidence['validity']}: {hive_evidence['reason']}",
        ),
    }


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
        title = item.get("title") or f"Task {item.get('id', 'unknown')}"
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


def normalize_workers(items) -> list:
    workers = []
    for item in items if isinstance(items, list) else []:
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
        lim = item.get("limits")
        if isinstance(lim, dict):  # pass through only the fields hive_system.limit_record understands
            workers[-1]["limits"] = {k: lim[k] for k in ("limit", "available", "basis", "unit") if k in lim}
    return workers


def worker_registry(ready: dict | None = None):
    """Prefer the authenticated /workers registry; if it is unavailable or
    auth_required, fall back to the public, lower-detail worker-availability list
    HIVE Core already includes in its unauthenticated /ready payload rather than
    collapsing straight to an empty list. The fallback is always evidenced as such,
    never presented as the authenticated registry."""
    raw, workers_evidence = fetch_with_evidence("/workers")
    if workers_evidence["validity"] == "valid":
        return normalize_workers(unwrap_items(raw)), workers_evidence
    ready = ready if ready is not None else ready_probe()
    fallback_workers = normalize_workers(ready.get("workers")) if ready.get("reachable") else []
    if fallback_workers:
        fallback_evidence = evidence(
            "hive:/ready (public worker-availability list)",
            utc_now(),
            "valid",
            f"Authenticated /workers registry is {workers_evidence['validity']} ({workers_evidence['reason']}); "
            "showing the public worker-availability list from /ready instead.",
        )
        return fallback_workers, fallback_evidence
    return [], workers_evidence


LOCAL_WORKER_PROBES = (
    ("lmstudio-local", "LM Studio", "http://127.0.0.1:1234/v1/models", "openai-compatible"),
    ("ollama-local", "Ollama", "http://127.0.0.1:11434/api/tags", "ollama"),
)
LOCAL_CLI_PROBES = (
    ("opencode-local", "OpenCode", ("wsl.exe", "-d", "Ubuntu-24.04", "--", "opencode", "--version")),
    ("freebuff-local", "Freebuff", ("wsl.exe", "-d", "Ubuntu-24.04", "--", "freebuff", "--version")),
)
OPENCODE_EXECUTION_CONFIRMED = os.environ.get("OPENCODE_EXECUTION_CONFIRMED", "").strip().lower() in {"1", "true", "yes"}
OPENCODE_WORKSPACE_ROOT = ROOT / "work" / "opencode-disposable"
OPENCODE_TASK_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
ATTESTATION_HASH_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
ROUTING_TASK_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$")
HANDOFF_REFERENCE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}$")
HANDOFF_REASONS = {"limit_reached", "worker_unavailable", "failed", "blocked", "manual"}
HANDOFF_DELIVERY_STATES = {"not_sent", "uncertain", "delivered"}


def local_worker_status():
    """Probe only the configured loopback worker endpoints; never auto-starts them."""
    items = []
    for worker_id, name, url, protocol in LOCAL_WORKER_PROBES:
        record = {
            "id": worker_id,
            "name": name,
            "endpoint": url,
            "protocol": protocol,
            "status": "unavailable",
            "models": [],
            "reason": None,
        }
        try:
            request = Request(url, headers={"Accept": "application/json"}, method="GET")
            with urlopen(request, timeout=2) as response:
                payload = json.loads(response.read(128_000).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("response must be a JSON object")
            raw_models = payload.get("data", []) if protocol == "openai-compatible" else payload.get("models", [])
            if not isinstance(raw_models, list):
                raise ValueError("model listing field is not a JSON array")
            record["models"] = [
                str(item.get("id") or item.get("name"))[:160]
                for item in raw_models if isinstance(item, dict) and (item.get("id") or item.get("name"))
            ][:20]
            record["status"] = "available"
            record["reason"] = "Loopback endpoint responded with a valid model listing"
        except HTTPError as error:
            record["reason"] = f"Loopback endpoint returned HTTP {error.code}"
        except (URLError, TimeoutError, OSError) as error:
            record["reason"] = f"Loopback endpoint unavailable: {getattr(error, 'reason', error)}"
        except (ValueError, UnicodeError) as error:
            record["status"] = "unknown"
            record["reason"] = f"Loopback endpoint returned invalid JSON: {error}"
        items.append(record)
    statuses = {item["status"] for item in items}
    validity = "valid" if statuses == {"available"} else "degraded" if "available" in statuses else "unknown" if "unknown" in statuses else "unavailable"
    return items, evidence("local:worker-probe", utc_now(), validity, "Only allowlisted loopback endpoints were probed; no worker was started.")


CLI_STATUS_TTL_S = 60.0
_cli_cache = {"t": None, "value": None}
_cli_lock = threading.Lock()


def local_cli_worker_status() -> tuple[list, dict]:
    """Cached for 60 s: the fixed version probes start external processes (wsl.exe), so they must not run on every dashboard
    refresh. A cached answer keeps its original observation time and states its age; it is never re-labelled as fresh."""
    with _cli_lock:
        if _cli_cache["value"] is not None and time.monotonic() - _cli_cache["t"] < CLI_STATUS_TTL_S:
            items, ev = _cli_cache["value"]
            age = round(time.monotonic() - _cli_cache["t"], 1)
            return [dict(i) for i in items], dict(ev, cached=True, age_s=age, reason=f"{ev['reason']} (cached answer, {age} s old; re-probed every {int(CLI_STATUS_TTL_S)} s)")
        items, ev = _probe_local_cli_workers()
        _cli_cache.update(t=time.monotonic(), value=([dict(i) for i in items], dict(ev)))
        return items, dict(ev, cached=False, age_s=0.0)


def _probe_local_cli_workers() -> tuple[list, dict]:
    """Probe installed CLI workers with fixed argv and no task execution."""
    items = []
    for worker_id, name, argv in LOCAL_CLI_PROBES:
        record = {"id": worker_id, "name": name, "protocol": "fixed-argv-version", "status": "unavailable", "version": None, "reason": None}
        try:
            result = subprocess.run(
                list(argv), shell=False, capture_output=True, text=True, timeout=4,
                encoding="utf-8", errors="replace",
            )
            output = redact_secrets((result.stdout or result.stderr or "").strip()).splitlines()
            if result.returncode == 0 and output:
                record["status"] = "available"
                record["version"] = output[0][:160]
                record["reason"] = "Fixed version probe succeeded; no model or task was launched"
            else:
                record["reason"] = f"Fixed version probe exited with status {result.returncode}"
        except subprocess.TimeoutExpired:
            record["reason"] = "Fixed version probe timed out"
        except (FileNotFoundError, OSError) as error:
            record["reason"] = f"Fixed version probe unavailable: {error}"
        items.append(record)
    statuses = {item["status"] for item in items}
    validity = "valid" if statuses == {"available"} else "degraded" if "available" in statuses else "unavailable"
    return items, evidence("local:cli-worker-probe", utc_now(), validity, "Only fixed --version argv was executed; no provider, model, task, or workspace action was launched.")


def _wsl_workspace_path(path: Path) -> str:
    drive = path.drive.rstrip(":").lower()
    if not drive:
        raise AdapterError("OpenCode workspace must be on a Windows drive", 400)
    return f"/mnt/{drive}{path.as_posix()[2:]}"


def opencode_run(payload: dict) -> dict:
    """Run only an explicitly enabled OpenCode task in a disposable workspace."""
    if not isinstance(payload, dict) or payload.get("confirm") is not True:
        raise AdapterError("Explicit confirmation is required for OpenCode execution", 400)
    if not OPENCODE_EXECUTION_CONFIRMED:
        raise AdapterError("OpenCode execution is disabled until its provider session is explicitly verified", 503)
    if payload.get("provider_session_confirmed") is not True or payload.get("network_confirmed") is not True:
        raise AdapterError("Provider-session and network confirmation are required for OpenCode execution", 400)
    task_id = str(payload.get("task_id") or "")
    if not OPENCODE_TASK_ID_PATTERN.fullmatch(task_id):
        raise AdapterError("Invalid OpenCode task_id", 400)
    workspace_raw = str(payload.get("workspace") or "")
    try:
        workspace = Path(workspace_raw).resolve()
        root = Path(OPENCODE_WORKSPACE_ROOT).resolve()
    except OSError as error:
        raise AdapterError(f"OpenCode workspace is invalid: {error}", 400) from None
    if not workspace.is_dir() or root not in workspace.parents:
        raise AdapterError("OpenCode workspace must be an existing directory inside the disposable root", 400)
    project_id = str(payload.get("project_id") or "")
    instruction = redact_secrets(str(payload.get("instruction") or "").strip())
    if not project_id or not (1 <= len(instruction) <= LOCAL_INFERENCE_MAX_INSTRUCTION):
        raise AdapterError("project_id and bounded instruction are required", 400)
    context = context_build(project_id, payload.get("record_ids"), CONTEXT_MAX_CHARS)
    context_text = "\n\n".join(f"[{record['record_id']}]\n{record.get('content', '')}" for record in context["records"])
    prompt = f"{instruction}\n\nBounded context:\n{context_text}"
    argv = [
        "wsl.exe", "-d", "Ubuntu-24.04", "--cd", _wsl_workspace_path(workspace), "--",
        "/usr/local/bin/opencode", "run", "--format", "json", "--log-level", "error",
        "--title", task_id, prompt,
    ]
    try:
        result = subprocess.run(argv, shell=False, capture_output=True, text=True, timeout=120, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        raise AdapterError("OpenCode execution timed out after 120s", 504) from None
    except (FileNotFoundError, OSError) as error:
        raise AdapterError(f"OpenCode execution unavailable: {error}", 503) from None
    stdout = redact_secrets((result.stdout or "").strip())[:65_536]
    stderr = redact_secrets((result.stderr or "").strip())[:8_000]
    if result.returncode != 0:
        status, validity, reason = "failed", "degraded", f"OpenCode exited with status {result.returncode}"
    else:
        try:
            parsed = json.loads(stdout) if stdout else None
        except (ValueError, UnicodeError):
            parsed = None
        status, validity, reason = ("completed", "valid", "Bounded OpenCode JSON output received") if isinstance(parsed, dict) else ("degraded", "degraded", "OpenCode returned empty or invalid JSON output")
    return {
        "worker_id": "opencode-local", "task_id": task_id, "status": status,
        "exit_code": result.returncode, "stdout": stdout, "stderr": stderr,
        "workspace": str(workspace), "context_hash": context["content_hash"],
        "evidence": evidence("local:opencode/run", utc_now(), validity, reason),
    }


def lmstudio_infer(payload: dict) -> dict:
    """Run one explicit, bounded inference against the loopback LM Studio adapter.

    The adapter validates the requested model against the live local model listing,
    sends only a redacted project-scoped context pack, and never starts a process,
    sends credentials, falls back to a remote worker, or writes canonical state.
    Empty content is degraded evidence rather than fabricated success.
    """
    if not isinstance(payload, dict) or payload.get("confirm") is not True:
        raise AdapterError("Explicit confirmation is required for local inference", 400)
    worker_id = canonical_worker_id(payload.get("worker_id") or "lmstudio-local")
    if worker_id != "lmstudio-local":
        raise AdapterError("Only lmstudio-local is supported by this adapter", 400)
    policy = evaluate_worker_policy(worker_id, local_only=True)
    if not policy["allowed"]:
        raise AdapterError(f"Worker preference is blocked by policy: {policy['blocked_reason']}", 400)
    project_id = str(payload.get("project_id") or "")
    model = str(payload.get("model") or "").strip()
    instruction = redact_secrets(str(payload.get("instruction") or "").strip())
    if not project_id or not model:
        raise AdapterError("project_id and model are required", 400)
    if not (1 <= len(instruction) <= LOCAL_INFERENCE_MAX_INSTRUCTION):
        raise AdapterError(f"instruction must be between 1 and {LOCAL_INFERENCE_MAX_INSTRUCTION} characters", 400)
    record_ids = payload.get("record_ids")
    context = context_build(project_id, record_ids, parse_bounded_int(payload.get("max_chars"), "max_chars", 500, CONTEXT_MAX_CHARS, 4_000))
    endpoint, endpoint_basis = _lmstudio_endpoint()
    if not endpoint:
        raise AdapterError("LM Studio endpoint is not a valid loopback address", 503)
    endpoint = endpoint.rstrip("/")
    try:
        models_request = Request(f"{endpoint}/v1/models", headers={"Accept": "application/json"}, method="GET")
        with urlopen(models_request, timeout=2) as response:
            models_payload = json.loads(response.read(128_000).decode("utf-8"))
        raw_models = models_payload.get("data", []) if isinstance(models_payload, dict) else None
        available_models = [str(item.get("id")) for item in raw_models if isinstance(item, dict) and item.get("id")] if isinstance(raw_models, list) else []
        if model not in available_models:
            raise AdapterError("Requested LM Studio model is not in the live model listing", 400)
        prompt_context = "\n\n".join(
            f"[{record['record_id']}]\n{record.get('content', '')}" for record in context["records"]
        )
        request_body = {
            "model": model,
            "messages": [
                {"role": "system", "content": "Use only the bounded context below. Do not claim actions or facts absent from it. Return a concise answer."},
                {"role": "user", "content": f"Instruction:\n{instruction}\n\nBounded context:\n{prompt_context}"},
            ],
            "temperature": 0,
            "max_tokens": parse_bounded_int(payload.get("max_tokens"), "max_tokens", 1, LOCAL_INFERENCE_MAX_TOKENS, 96),
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        completion_request = Request(
            f"{endpoint}/v1/chat/completions",
            data=json.dumps(request_body).encode("utf-8"),
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(completion_request, timeout=30) as response:
            completion_payload = json.loads(response.read(128_000).decode("utf-8"))
    except HTTPError as error:
        raise AdapterError(f"LM Studio returned HTTP {error.code}", 502) from None
    except (URLError, TimeoutError, OSError) as error:
        raise AdapterError(f"LM Studio inference unavailable: {getattr(error, 'reason', error)}", 503) from None
    except (ValueError, UnicodeError) as error:
        raise AdapterError(f"LM Studio returned invalid JSON: {error}", 502) from None
    choices = completion_payload.get("choices") if isinstance(completion_payload, dict) else None
    choice = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
    message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
    content = message.get("content") if isinstance(message.get("content"), str) else ""
    content = redact_secrets(content).strip()[:8_000]
    finish_reason = choice.get("finish_reason")
    valid = bool(content)
    return {
        "worker_id": worker_id,
        "model": model,
        "status": "completed" if valid else "degraded",
        "response": content,
        "finish_reason": finish_reason,
        "usage": completion_payload.get("usage") if isinstance(completion_payload, dict) and isinstance(completion_payload.get("usage"), dict) else None,
        "context_hash": context["content_hash"],
        "evidence": evidence(
            f"lmstudio:{endpoint}/v1/chat/completions",
            utc_now(),
            "valid" if valid else "degraded",
            "Bounded local inference completed" if valid else f"LM Studio returned no message content (finish_reason={finish_reason})",
        ),
        "endpoint_basis": endpoint_basis,
    }


def _call_probe(path: str):
    try:
        raw = core_json(path)
        return (raw if isinstance(raw, dict) else {}), None
    except AdapterError as error:
        return {}, error


def health_probe() -> dict:
    """Server-side provenance record for HIVE Core's public /health endpoint."""
    raw, error = _call_probe("/health")
    observed = utc_now()
    if error is not None:
        # A 401/403 is itself proof Core is up and reachable -- it processed the
        # request and explicitly rejected it on auth grounds, which is a different
        # fact from a connection failure/timeout where no response was ever received.
        reachable = error.status in (401, 403)
        return {
            "status": "unknown", "reachable": reachable, "observed_at": observed if reachable else None,
            "validity": unavailability_validity(error), "reason": str(error), "error_status": error.status,
        }
    status_text = str(raw.get("status", "unknown")).lower()
    if status_text in HEALTH_OK_STATUSES:
        return {"status": status_text, "reachable": True, "observed_at": observed, "validity": "valid", "reason": "HIVE Core /health responded", "error_status": None}
    if status_text in HEALTH_DEGRADED_STATUSES:
        return {"status": status_text, "reachable": True, "observed_at": observed, "validity": "valid", "reason": "HIVE Core /health reported degradation", "error_status": None}
    return {"status": "unknown", "reachable": True, "observed_at": observed, "validity": "unknown", "reason": "HIVE Core /health payload missing expected status field", "error_status": None}


def ready_probe() -> dict:
    """Server-side provenance record for HIVE Core's public /ready endpoint,
    including the public worker-availability list it already embeds (evidence only
    for readiness, never treated as authorization for protected worker detail)."""
    raw, error = _call_probe("/ready")
    observed = utc_now()
    if error is not None:
        # See health_probe(): a 401/403 proves Core is reachable and simply rejected
        # the request on auth grounds, unlike a connection failure/timeout.
        reachable = error.status in (401, 403)
        return {
            "status": "unknown", "database": "unknown", "queue": "unknown", "workers": [],
            "reachable": reachable, "observed_at": observed if reachable else None,
            "validity": unavailability_validity(error), "reason": str(error), "error_status": error.status,
        }
    status_text = str(raw.get("status", "unknown")).lower()
    database = str(raw.get("database", "unknown")).lower()
    queue = str(raw.get("queue", "unknown")).lower()
    workers = raw.get("workers") if isinstance(raw.get("workers"), list) else []
    if status_text in READY_OK_STATUSES:
        return {"status": status_text, "database": database, "queue": queue, "workers": workers, "reachable": True, "observed_at": observed, "validity": "valid", "reason": "HIVE Core /ready responded", "error_status": None}
    if status_text in READY_NOT_READY_STATUSES:
        return {"status": status_text, "database": database, "queue": queue, "workers": workers, "reachable": True, "observed_at": observed, "validity": "valid", "reason": "HIVE Core /ready reported not-ready", "error_status": None}
    return {"status": "unknown", "database": database, "queue": queue, "workers": workers, "reachable": True, "observed_at": observed, "validity": "unknown", "reason": "HIVE Core /ready payload missing expected status field", "error_status": None}


def creator_ops_status() -> dict:
    """Read-only, privacy-safe CREATOR OPS status adapter.

    Opens the local SQLite file in URI mode=ro (refuses to write) and only ever runs
    fixed SELECT COUNT(*) queries against the hardcoded CREATOR_OPS_TABLES allowlist
    above -- table names are never taken from request input or from the database's
    own catalog, and no column data (captions, handles, notes, URLs, credentials) is
    ever read. Failure to open or query the file is reported as unavailable with a
    real reason, never fabricated as empty/zero counts.
    """
    base_cfg = {"configured": bool(CREATOR_OPS_DB_PATH)}
    if not CREATOR_OPS_DB_PATH:
        return {**base_cfg, "token_configured": False, "authenticated": False, "authentication_validity": "unavailable",
                "authentication_reason": "No credentials are used; this is a local, read-only file adapter.", "reachable": False,
                "last_observed_at": None, "last_seen": None, "validity": "unavailable",
                "reason": "CREATOR OPS database not configured: set CREATOR_OPS_DB_PATH", "counts": {}}
    db_path = Path(CREATOR_OPS_DB_PATH)
    base = {"configured": True, "token_configured": False, "authenticated": False,
            "authentication_validity": "unavailable", "authentication_reason": "No credentials are used; this is a local, read-only file adapter."}
    if not db_path.is_file():
        return {**base, "reachable": False, "last_observed_at": None, "last_seen": None,
                "validity": "unavailable", "reason": f"CREATOR OPS database not found at {db_path}", "counts": {}}
    try:
        uri = f"file:{db_path.as_posix()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=2)
        try:
            cursor = connection.cursor()
            existing = {row[0] for row in cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            counts = {}
            for table in CREATOR_OPS_TABLES:
                if table not in existing:
                    continue
                cursor.execute(f'SELECT COUNT(*) FROM "{table}"')
                counts[table] = cursor.fetchone()[0]
        finally:
            connection.close()
    except sqlite3.Error as error:
        return {**base, "reachable": False, "last_observed_at": None, "last_seen": None,
                "validity": "unavailable", "reason": f"CREATOR OPS database read failed: {error}", "counts": {}}
    observed = utc_now()
    return {**base, "reachable": True, "last_observed_at": observed, "last_seen": observed,
            "validity": "valid", "reason": "Aggregate row counts only; no account, content, or credential fields are read.",
            "counts": counts}


def adapter_health(health: dict, ready: dict) -> dict:
    """health/ready are the provenance records from health_probe()/ready_probe().

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
    hive_validity = health["validity"]
    hive_reachable = health["reachable"]
    error_status = health.get("error_status")

    if not token_configured:
        authenticated, auth_validity, auth_reason = False, "unavailable", "No bearer token is configured; nothing to authenticate."
    elif error_status in (401, 403):
        authenticated, auth_validity, auth_reason = False, "unavailable", "HIVE Core explicitly rejected the configured bearer token."
    elif not hive_reachable:
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
            "last_observed_at": health["observed_at"] if hive_reachable else None,
            "last_seen": health["observed_at"] if hive_reachable else None,
            "validity": hive_validity,
            "reason": health["reason"],
            "health": health,
            "ready": ready,
        },
        "beszel": {
            "configured": bool(beszel_url),
            "token_configured": False,
            "authenticated": False,
            "authentication_validity": "unavailable",
            "authentication_reason": "Beszel integration is not implemented in this MVP; deferred",
            "reachable": False,
            "last_observed_at": None,
            "last_seen": None,
            "validity": "unknown",
            "reason": "Beszel integration is not implemented in this MVP; deferred",
        },
    }


REGISTRY_CACHE = hive_registry.RegistryCache()


def registry_snapshot(parts=None) -> dict:
    """Read-only registry (hive_registry.py). Loaded only when the Registry view asks for it; each source runs isolated with its
    own timeout and cache TTL; the HIVE Core part runs inside the snapshot preflight scope in its own thread. Paths come only from
    environment variables (see docs/hive/DATA_CONTRACTS.md); nothing is executed and nothing is written."""
    return hive_registry.build_registry(fetch_with_evidence, hive_registry.config_from_env(), bucket=bucket_for, parts=parts,
                                        cache=REGISTRY_CACHE, core_scope=core_snapshot_scope, creator_ops_counts=creator_ops_status)


def snapshot():
    with core_snapshot_scope():
        return _snapshot_impl()


def _snapshot_impl():
    health = health_probe()
    ready = ready_probe()
    if health["status"] in HEALTH_OK_STATUSES:
        core_status = "running"
    elif health["status"] in HEALTH_DEGRADED_STATUSES:
        core_status = "degraded"
    else:
        core_status = "unknown"

    adapters = adapter_health(health, ready)

    system_raw, system_evidence = fetch_with_evidence("/system")
    host = (system_raw.get("host", {}) if isinstance(system_raw, dict) else {}) or {}
    metrics_reason = None if system_evidence["validity"] == "valid" else system_evidence["reason"]

    projects, projects_evidence = project_catalog()
    registry_projects, registry_evidence = orchestrator_project_registry()
    evolution = self_evolution_status()
    tasks, tasks_evidence = task_queue()
    workers, workers_evidence = worker_registry(ready)
    local_workers, local_workers_evidence = local_worker_status()
    creator_ops = creator_ops_status()
    events_raw, events_evidence = fetch_with_evidence("/events?limit=50")
    normalized_events = []
    for event in unwrap_items(events_raw):
        if not isinstance(event, dict):
            continue
        raw_timestamp = event.get("timestamp") or event.get("created_at")
        normalized_events.append({
            "event_id": (hive_events.contract_event(event) or {}).get("event_id"),
            "timestamp": raw_timestamp,
            "timestamp_validity": "valid" if raw_timestamp else "unknown",
            "kind": event.get("event_type", "OBSERVED_EVENT"),
            "title": event.get("event_type", "Observed HIVE event"),
            "source": event.get("source", "HIVE Core"),
            "component_id": event.get("worker_id") or event.get("project_id") or "hive-core",
            "severity": str(event.get("severity", "info")).lower(),
        })

    def readiness_item(component, item_evidence, next_safe_action, forced_status=None):
        validity = item_evidence.get("validity", "unknown") if isinstance(item_evidence, dict) else "unknown"
        status = forced_status or ("ready" if validity == "valid" else validity)
        return {
            "component": component,
            "status": status,
            "validity": validity,
            "source": item_evidence.get("source", "unknown") if isinstance(item_evidence, dict) else "unknown",
            "observed_at": item_evidence.get("observed_at") if isinstance(item_evidence, dict) else None,
            "reason": item_evidence.get("reason") if isinstance(item_evidence, dict) else "No evidence received",
            "next_safe_action": next_safe_action,
        }

    ao_info = ao_capabilities()
    ao_read_only = ao_info["session_list_confirmed"] and ao_info["session_history_confirmed"]
    ao_evidence = evidence(
        "ao:capabilities",
        utc_now(),
        "valid" if ao_read_only else "unavailable",
        "AO session listing/history are read-only and verified; native worker/realtime transport and controlled send remain unconfirmed.",
    )
    readiness_items = [
        readiness_item("hive_core", evidence("hive:/health", health["observed_at"], health["validity"], health["reason"]), "Provide a scoped server-observed HIVE identity before protected reads.", "degraded" if core_status == "degraded" else None),
        readiness_item("projects", projects_evidence, "Provide HIVE authorization for /projects; keep the state AUTH_REQUIRED until then."),
        readiness_item("tasks", tasks_evidence, "Provide HIVE authorization for /tasks; do not interpret an empty list as proof of no tasks."),
        readiness_item("events", events_evidence, "Provide HIVE authorization for /events; retain UNKNOWN/UNAVAILABLE evidence."),
        readiness_item("obsidian", registry_evidence, "Repair or explicitly register the shared Obsidian source if unavailable."),
        readiness_item("creator_ops", evidence("creator-ops:local-db", creator_ops.get("last_observed_at"), creator_ops.get("validity", "unknown"), creator_ops.get("reason")), "Keep the local adapter read-only and inspect its evidence before enabling writes."),
        readiness_item("local_workers", local_workers_evidence, "Use only bounded loopback probes; do not auto-start unavailable workers."),
        readiness_item("ao_chat", ao_evidence, "Configure the approved native AO transport and caller authorization; keep chat read-only until then.", "degraded" if ao_read_only else None),
        readiness_item("provider_execution", evidence("control:capabilities", utc_now(), "blocked", "Provider execution is disabled until server-observed identity and protected routes are verified."), "Obtain verified provider identity; never bypass the attestation gate.", "blocked"),
    ]
    readiness_statuses = {item["status"] for item in readiness_items}
    readiness_aggregate = "blocked" if readiness_statuses & {"blocked", "auth_required"} else "degraded" if readiness_statuses - {"ready"} else "ready"
    readiness = {
        "aggregate": readiness_aggregate,
        "items": readiness_items,
        "evidence": evidence("orchestrator:readiness", utc_now(), "valid", "Derived read-only availability model; no credentials, sessions, provider state or canonical state were changed."),
    }

    return {
        "received_at": utc_now(),
        "environment": "LOCAL / HIVE CORE",
        "core": {
            "status": core_status,
            "observed_at": health["observed_at"],
            "reason": health["reason"],
            "ready": {
                "status": ready["status"],
                "database": ready["database"],
                "queue": ready["queue"],
                "observed_at": ready["observed_at"],
                "validity": ready["validity"],
                "reason": ready["reason"],
            },
        },
        "metrics": {
            "cpu": metric(host.get("cpu_percent"), source="hive", reason=metrics_reason),
            "memory": metric(host.get("ram_percent", host.get("memory_percent")), source="hive", reason=metrics_reason),
            "disk": metric(host.get("disk_percent"), source="hive", reason=metrics_reason),
        },
        "adapters": {**adapters, "creator_ops": creator_ops},
        "projects": {"items": projects, "evidence": projects_evidence},
        "project_registry": {"items": registry_projects, "evidence": registry_evidence},
        "self_evolution": evolution,
        "tasks": {"items": tasks, "evidence": tasks_evidence},
        "workers": {"items": workers, "evidence": workers_evidence},
        "model_limits": {"items": hive_system.model_limits(workers), "evidence": workers_evidence},
        "local_workers": {"items": local_workers, "evidence": local_workers_evidence},
        "events": {"items": normalized_events[:50], "evidence": events_evidence},
        "readiness": readiness,
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
    local_only = bool(payload.get("local_only"))
    if worker is not None:
        policy_result = evaluate_worker_policy(worker, local_only)
        if not policy_result["allowed"]:
            raise AdapterError(f"Worker preference is blocked by policy: {policy_result['blocked_reason']}", 400)
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


AO_SESSION_HISTORY_PATH = re.compile(r"^/api/ao/sessions/([^/]+)/history$")
AO_SESSION_SEND_PATH = re.compile(r"^/api/ao/sessions/([^/]+)/send$")
AO_SESSION_SEND_RECOVER_PATH = re.compile(r"^/api/ao/sessions/([^/]+)/send/recover$")



def live_event_batch():
    """(contract events, status) from HIVE Core /events with its evidence; never fabricated."""
    raw, ev = fetch_with_evidence("/events?limit=50")
    prov = {"source": ev.get("source"), "validity": ev.get("validity"), "observed_at": ev.get("observed_at")}
    events = [e for e in (hive_events.contract_event(item, prov) for item in unwrap_items(raw)) if e]
    status = {"schema_version": hive_events.SCHEMA_VERSION, "validity": ev.get("validity"), "source": ev.get("source"),
              "observed_at": ev.get("observed_at"), "reason": ev.get("reason"), "event_count": len(events)}
    return events, status


EVENT_STREAM_INTERVAL = 5.0


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

    def stream_events(self, query):
        """Server-Sent Events. `cycles=N` bounds the stream (tests); default is until disconnect."""
        try:
            cycles = parse_bounded_int(query["cycles"][0], "cycles", 1, 100000, 1) if query.get("cycles") else None
        except AdapterError:
            cycles = None
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        try:
            for frame in hive_events.stream_frames(live_event_batch, EVENT_STREAM_INTERVAL, cycles, time.sleep):
                self.wfile.write(frame)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return

    def drain_request_body(self) -> None:
        """Discard any pending request body bytes without parsing or using them.

        Called only after a rejection decision (e.g. a failed caller-auth check) has
        already been made from headers alone -- this never influences that decision.
        It exists purely so closing the connection with unread bytes still sitting in
        the socket doesn't reset the connection before the client can read the error
        response.
        """
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length > 0:
            self.rfile.read(min(length, MAX_BODY))

    def do_GET(self):
        path = urlparse(self.path).path
        try:
            if path == "/api/system/resources":
                # Non-blocking: answers from the latest fast/slow observations; probes refresh in the background.
                return self.json_response(hive_system.SYSTEM.snapshot())
            if path == "/api/events/stream":
                return self.stream_events(parse_qs(urlparse(self.path).query))
            if path == "/api/dashboard/snapshot":
                return self.json_response(snapshot())
            if path == "/api/registry":
                requested = [p for p in ",".join(parse_qs(urlparse(self.path).query).get("part", [])).split(",") if p]
                if any(p not in hive_registry.PARTS for p in requested):
                    return self.json_response({"error": f"unknown registry part; allowed: {', '.join(hive_registry.PARTS)}"}, 400)
                return self.json_response(registry_snapshot(requested or None))
            if path == "/api/control/capabilities":
                return self.json_response({
                    "delegation": {"proposal": True, "task": False, "mission": False, "self_upgrade_apply": False},
                    "provider": {"route": "HIVE Core worker registry", "direct_browser_provider_calls": False},
                    "memory": {"operations": ["status", "search", "get", "build_context", "propose"], "canonical_write": False, "project_scoped": True},
                    "local_inference": {"route": "/api/local-workers/lmstudio/infer", "confirm_required": True, "canonical_write": False, "loopback_only": True},
                    "cli_worker_probe": {"route": "/api/local-workers/cli-status", "fixed_argv_only": True, "execution": "version-only", "canonical_write": False},
                    "opencode_execution": {"route": "/api/local-workers/opencode/run", "enabled_by_default": False, "disposable_workspace_only": True, "fixed_argv": True},
                    "routing": {"route": "/api/control/routing-decision", "proposal_only": True, "provider_execution": False, "attestation_shape_only": True},
                    "handoff": {"route": "/api/control/handoff-proposal", "proposal_only": True, "delivery": False, "retry": False},
                    "core_endpoint": CORE_URL,
                    "security": {"loopback_only": True, "core_endpoint_is_loopback": CORE_URL_IS_LOOPBACK},
                    "ao": ao_capabilities(),
                })
            if path == "/api/control/worker-policy":
                return self.json_response(worker_policy_catalog())
            if path == "/api/memory/status":
                return self.json_response(context_status())
            if path == "/api/memory/search":
                query = parse_qs(urlparse(self.path).query)
                project_id = (query.get("project_id") or [""])[0]
                return self.json_response(context_search(project_id, (query.get("q") or [""])[0], parse_bounded_int((query.get("limit") or [None])[0], "limit", 1, CONTEXT_MAX_RECORDS, 20)))
            if path == "/api/memory/get":
                query = parse_qs(urlparse(self.path).query)
                return self.json_response(context_get((query.get("project_id") or [""])[0], (query.get("record_id") or [""])[0]))
            if path == "/api/memory/build_context":
                query = parse_qs(urlparse(self.path).query)
                project_id = (query.get("project_id") or [""])[0]
                record_ids = [value for value in (query.get("record_id") or []) if value]
                return self.json_response(context_build(project_id, record_ids, parse_bounded_int((query.get("max_chars") or [None])[0], "max_chars", 500, CONTEXT_MAX_CHARS, CONTEXT_MAX_CHARS)))
            if path == "/api/local-workers/cli-status":
                items, ev = local_cli_worker_status()
                return self.json_response({"items": items, "evidence": ev})
            if path == "/api/ao/sessions":
                sessions, ev = ao_sessions()
                return self.json_response({"items": sessions, "evidence": ev})
            history_match = AO_SESSION_HISTORY_PATH.match(path)
            if history_match:
                session_id = validate_ao_session_id(history_match.group(1))
                query = parse_qs(urlparse(self.path).query)
                limit = parse_bounded_int(
                    (query.get("limit") or [None])[0], "limit", AO_HISTORY_MIN_LIMIT, AO_HISTORY_MAX_LIMIT, 10
                )
                offset = parse_bounded_int((query.get("offset") or [None])[0], "offset", 0, AO_HISTORY_MAX_OFFSET, 0)
                text, ev = ao_session_history(session_id, limit, offset)
                return self.json_response({"session_id": session_id, "text": text, "evidence": ev})
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
            if path == "/api/control/dispatch":
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > MAX_BODY:
                    raise AdapterError("Request body is missing or too large", 413)
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                result = dispatch(body, self.headers.get("Idempotency-Key"))
                return self.json_response(result, 202)
            if path == "/api/memory/propose":
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > MAX_BODY:
                    raise AdapterError("Request body is missing or too large", 413)
                result = context_propose(json.loads(self.rfile.read(length).decode("utf-8")))
                return self.json_response(result, 202)
            if path == "/api/local-workers/lmstudio/infer":
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > MAX_BODY:
                    raise AdapterError("Request body is missing or too large", 413)
                result = lmstudio_infer(json.loads(self.rfile.read(length).decode("utf-8")))
                return self.json_response(result, 200)
            if path == "/api/local-workers/opencode/run":
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > MAX_BODY:
                    raise AdapterError("Request body is missing or too large", 413)
                result = opencode_run(json.loads(self.rfile.read(length).decode("utf-8")))
                return self.json_response(result, 200)
            if path == "/api/control/routing-decision":
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > MAX_BODY:
                    raise AdapterError("Request body is missing or too large", 413)
                result = routing_decision(json.loads(self.rfile.read(length).decode("utf-8")))
                return self.json_response(result, 200)
            if path == "/api/control/handoff-proposal":
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > MAX_BODY:
                    raise AdapterError("Request body is missing or too large", 413)
                result = handoff_proposal(json.loads(self.rfile.read(length).decode("utf-8")))
                return self.json_response(result, 200)
            recover_match = AO_SESSION_SEND_RECOVER_PATH.match(path)
            if recover_match:
                try:
                    require_ao_send_caller_auth(self.headers)
                except AdapterError:
                    self.drain_request_body()
                    raise
                session_id = recover_match.group(1)
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > MAX_BODY:
                    raise AdapterError("Request body is missing or too large", 413)
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                result = ao_recover_send(session_id, body.get("client_message_id"), body.get("confirm"))
                return self.json_response(result, 200)
            send_match = AO_SESSION_SEND_PATH.match(path)
            if send_match:
                try:
                    require_ao_send_caller_auth(self.headers)
                except AdapterError:
                    self.drain_request_body()
                    raise
                session_id = send_match.group(1)
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > MAX_BODY:
                    raise AdapterError("Request body is missing or too large", 413)
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                result = ao_send(session_id, body.get("message"), body.get("confirm"), body.get("client_message_id"))
                return self.json_response(result, 202)
            return self.json_response({"detail": "Unknown adapter endpoint"}, 404)
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
    hive_system.SYSTEM.snapshot(source="warmup")  # starts the first fast probe in the background (returns immediately)
    print(f"Unified dashboard adapter listening on http://{args.bind}:{args.port}/", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
