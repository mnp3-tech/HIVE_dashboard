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
import hmac
import ipaddress
import json
import mimetypes
import os
import re
import secrets
import sqlite3
import subprocess
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
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
CREATOR_OPS_DB_PATH = os.environ.get(
    "CREATOR_OPS_DB_PATH",
    r"C:\Users\Martin\Documents\ChatGPT\CREATOR OPS\data\creator_ops.sqlite3",
)
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
    whenever AO_CLI_PATH is configured. send/send_recover additionally require the
    caller-auth gate (AO_SEND_CALLER_TOKEN) to be configured, since those routes
    cannot actually be reached by any caller otherwise -- confirmed must reflect
    whether the route can really be used end to end, not just whether the CLI binary
    exists. worker_api and realtime chat remain unconfirmed: no public HTTP/
    worker-registry contract is documented for AO, and this adapter never guesses at
    one.
    """
    configured = ao_cli_configured()
    caller_auth_configured = ao_send_caller_auth_configured()
    send_usable = configured and caller_auth_configured
    return {
        "session_list_confirmed": configured,
        "session_history_confirmed": configured,
        "send_confirmed": send_usable,
        "send_recover_confirmed": send_usable,
        "caller_auth_configured": caller_auth_configured,
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
            "not configured. No other AO HTTP endpoint, worker registry, or "
            "internal SQLite store is read, and the bridge reports unavailable "
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
    result" -- rather than blindly resending."""
    if confirm is not True:
        raise AdapterError("Explicit confirmation is required", 400)
    validate_ao_session_id(session_id)
    text = str(message or "").strip()
    if not (1 <= len(text) <= AO_SEND_MESSAGE_MAX_LEN):
        raise AdapterError(f"message must be between 1 and {AO_SEND_MESSAGE_MAX_LEN} characters", 400)
    client_message_id = validate_client_message_id(client_message_id) if client_message_id is not None else secrets.token_urlsafe(18)
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


def snapshot():
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
    tasks, tasks_evidence = task_queue()
    workers, workers_evidence = worker_registry(ready)
    creator_ops = creator_ops_status()
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
            if path == "/api/dashboard/snapshot":
                return self.json_response(snapshot())
            if path == "/api/control/capabilities":
                return self.json_response({
                    "delegation": {"proposal": True, "task": False, "mission": False, "self_upgrade_apply": False},
                    "provider": {"route": "HIVE Core worker registry", "direct_browser_provider_calls": False},
                    "core_endpoint": CORE_URL,
                    "security": {"loopback_only": True, "core_endpoint_is_loopback": CORE_URL_IS_LOOPBACK},
                    "ao": ao_capabilities(),
                })
            if path == "/api/control/worker-policy":
                return self.json_response(worker_policy_catalog())
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
    print(f"Unified dashboard adapter listening on http://{args.bind}:{args.port}/", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
