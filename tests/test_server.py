"""Unit tests for the unified dashboard adapter contract (server.py).

Runs with the stdlib unittest runner only; no extra dependencies required.
All HIVE Core network access is mocked via server.urlopen.
"""

from __future__ import annotations

import http.client
import io
import json
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server  # noqa: E402


class FakeResponse:
    def __init__(self, payload):
        self._raw = json.dumps(payload).encode("utf-8")

    def read(self, n=-1):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def path_of(request) -> str:
    full = request.full_url
    return full[len(server.CORE_URL):] or "/"


def fake_urlopen(routes):
    """routes: dict exact-or-prefix-path -> payload dict, or an Exception instance to raise."""

    def _fake(request, timeout=4):
        path = path_of(request)
        for key, value in routes.items():
            if path == key or path.startswith(key):
                if isinstance(value, Exception):
                    raise value
                return FakeResponse(value)
        raise URLError(f"no fake route configured for {path}")

    return _fake


def http_error(code: int, detail: bytes = b"error") -> HTTPError:
    return HTTPError("http://core", code, "error", {}, io.BytesIO(detail))


class MetricTests(unittest.TestCase):
    def test_metric_valid_value(self):
        result = server.metric(42)
        self.assertEqual(result["value"], 42.0)
        self.assertEqual(result["validity"], "valid")

    def test_metric_none_is_unavailable_not_zero(self):
        result = server.metric(None)
        self.assertIsNone(result["value"])
        self.assertEqual(result["validity"], "unavailable")

    def test_metric_non_numeric_is_unknown(self):
        result = server.metric("not-a-number")
        self.assertIsNone(result["value"])
        self.assertEqual(result["validity"], "unknown")


class BucketForTests(unittest.TestCase):
    def test_known_statuses_map_to_buckets(self):
        self.assertEqual(server.bucket_for("pending"), "queued")
        self.assertEqual(server.bucket_for("RUNNING"), "active")
        self.assertEqual(server.bucket_for("done"), "completed")
        self.assertEqual(server.bucket_for("failed"), "blocked")

    def test_unrecognized_status_is_unknown_not_fabricated(self):
        self.assertEqual(server.bucket_for("some-upstream-only-status"), "unknown")
        self.assertEqual(server.bucket_for(None), "unknown")


class ProjectCatalogTests(unittest.TestCase):
    def test_success_normalizes_items_and_marks_valid(self):
        routes = {"/projects": {"items": [{"id": "seed", "name": "SEED", "status": "active"}]}}
        with patch.object(server, "urlopen", fake_urlopen(routes)):
            projects, evidence = server.project_catalog()
        self.assertEqual(len(projects), 1)
        self.assertEqual(projects[0]["id"], "seed")
        self.assertEqual(evidence["validity"], "valid")
        self.assertIsNotNone(evidence["observed_at"])

    def test_items_missing_id_are_dropped_not_fabricated(self):
        routes = {"/projects": {"items": [{"name": "no id"}, {"id": "ok", "name": "OK"}]}}
        with patch.object(server, "urlopen", fake_urlopen(routes)):
            projects, _ = server.project_catalog()
        self.assertEqual([p["id"] for p in projects], ["ok"])

    def test_404_from_core_is_unknown_not_unavailable(self):
        routes = {"/projects": http_error(404)}
        with patch.object(server, "urlopen", fake_urlopen(routes)):
            projects, evidence = server.project_catalog()
        self.assertEqual(projects, [])
        self.assertEqual(evidence["validity"], "unknown")

    def test_connection_failure_is_unavailable(self):
        routes = {"/projects": URLError("refused")}
        with patch.object(server, "urlopen", fake_urlopen(routes)):
            projects, evidence = server.project_catalog()
        self.assertEqual(projects, [])
        self.assertEqual(evidence["validity"], "unavailable")
        self.assertIsNone(evidence["observed_at"])


class OrchestratorRegistryTests(unittest.TestCase):
    def test_project_registry_is_read_only_and_preserves_registration_state(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "projects.json"
            path.write_text(json.dumps({"projects": [
                {"id": "hive-core-seed", "name": "HIVE / seed core", "registration": "registered", "workspace": root},
                {"id": "self-evolution", "name": "Self-evolution", "registration": "historical-implementation-found", "workspace": None},
            ]}), encoding="utf-8")
            with patch.object(server, "ORCHESTRATOR_PROJECT_REGISTRY_PATH", path):
                items, evidence = server.orchestrator_project_registry()
        self.assertEqual([item["id"] for item in items], ["hive-core-seed", "self-evolution"])
        self.assertTrue(items[0]["workspace_present"])
        self.assertFalse(items[1]["workspace_present"])
        self.assertEqual(evidence["validity"], "valid")

    def test_self_evolution_checkpoint_supports_numbered_checklists(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "P-013.ukol.md"
            path.write_text("""---\nstate: in-progress\n---\n\n## Plan\n1. [x] inspect\n2. [ ] map\n\n## Checkpoint\n- next_action: map evidence\n- blocker: review required\n""", encoding="utf-8")
            evolution_fixture = ({}, {"source": "hive:/evolution", "observed_at": None, "validity": "auth_required", "reason": "fixture auth boundary"})
            with patch.object(server, "ORCHESTRATOR_SELF_EVOLUTION_TASK_PATH", path), patch.object(server, "fetch_with_evidence", return_value=evolution_fixture):
                result = server.self_evolution_status()
        self.assertEqual(result["item"]["completed_steps"], 1)
        self.assertEqual(result["item"]["open_steps"], 1)
        self.assertEqual(result["item"]["next_action"], "map evidence")
        self.assertEqual(result["checkpoint_evidence"]["validity"], "valid")
        self.assertEqual(result["evidence"]["validity"], "auth_required")


class LocalWorkerStatusTests(unittest.TestCase):
    def test_allowlisted_loopback_probes_report_models_and_unavailability(self):
        def fake(request, timeout=2):
            if request.full_url.endswith("/v1/models"):
                return FakeResponse({"data": [{"id": "qwen3.5-4b"}]})
            raise URLError("connection refused")

        with patch.object(server, "urlopen", fake):
            items, evidence = server.local_worker_status()
        self.assertEqual(items[0]["status"], "available")
        self.assertEqual(items[0]["models"], ["qwen3.5-4b"])
        self.assertEqual(items[1]["status"], "unavailable")
        self.assertIn("unavailable", items[1]["reason"])
        self.assertEqual(evidence["validity"], "degraded")

    def test_malformed_json_shape_is_unknown_and_does_not_break_snapshot(self):
        with patch.object(server, "urlopen", lambda request, timeout=2: FakeResponse(["not", "an", "object"])):
            items, evidence = server.local_worker_status()
        self.assertTrue(all(item["status"] == "unknown" for item in items))
        self.assertEqual(evidence["validity"], "unknown")


class SharedContextAdapterTests(unittest.TestCase):
    def _fixture(self):
        root = tempfile.TemporaryDirectory()
        base = Path(root.name)
        registry = base / "projects.json"
        source = base / "P-DEMO.md"
        registry.write_text(json.dumps({"projects": [{"id": "demo", "name": "Demo"}]}), encoding="utf-8")
        source.write_text("""---\nid: P-DEMO\nstate: in-progress\nupdated_at: 2026-10-29T17:00:00Z\n---\n# Demo context\n\nUse this bounded context pack. token: secret-value\n""", encoding="utf-8")
        return root, registry, source

    def test_status_search_get_and_build_context_are_scoped_and_hashed(self):
        root, registry, source = self._fixture()
        try:
            with patch.object(server, "ORCHESTRATOR_PROJECT_REGISTRY_PATH", registry), patch.object(server, "ORCHESTRATOR_VAULT_ROOT", Path(root.name)), patch.object(server, "ORCHESTRATOR_CONTEXT_SOURCES", {"demo": (source,)}):
                status = server.context_status()
                search = server.context_search("demo", "bounded")
                item = server.context_get("demo", "P-DEMO")
                pack = server.context_build("demo", ["P-DEMO"], 700)
            self.assertEqual(status["items"][0]["status"], "available")
            self.assertEqual(search["items"][0]["record_id"], "P-DEMO")
            self.assertIn("[REDACTED]", item["item"]["content"])
            self.assertNotIn("secret-value", item["item"]["content"])
            self.assertEqual(len(pack["content_hash"]), 64)
            self.assertEqual(pack["provenance"], "DERIVED_LOCAL_CONTEXT")
        finally:
            root.cleanup()

    def test_unknown_scope_and_out_of_scope_record_fail_closed(self):
        root, registry, source = self._fixture()
        try:
            with patch.object(server, "ORCHESTRATOR_PROJECT_REGISTRY_PATH", registry), patch.object(server, "ORCHESTRATOR_VAULT_ROOT", Path(root.name)), patch.object(server, "ORCHESTRATOR_CONTEXT_SOURCES", {"demo": (source,)}):
                with self.assertRaises(server.AdapterError):
                    server.context_search("unknown", "x")
                with self.assertRaises(server.AdapterError):
                    server.context_get("demo", "not-allowlisted")
        finally:
            root.cleanup()

    def test_propose_is_explicit_and_does_not_write_memory(self):
        root, registry, source = self._fixture()
        try:
            before = source.read_bytes()
            with patch.object(server, "ORCHESTRATOR_PROJECT_REGISTRY_PATH", registry), patch.object(server, "ORCHESTRATOR_VAULT_ROOT", Path(root.name)), patch.object(server, "ORCHESTRATOR_CONTEXT_SOURCES", {"demo": (source,)}):
                result = server.context_propose({"project_id": "demo", "record_ids": ["P-DEMO"], "summary": "Propose a bounded context update", "confirm": True})
            self.assertEqual(result["status"], "proposed")
            self.assertEqual(before, source.read_bytes())
            with self.assertRaises(server.AdapterError):
                server.context_propose({"project_id": "demo", "record_ids": ["P-DEMO"], "summary": "Propose a bounded context update"})
        finally:
            root.cleanup()

    def test_explicit_context_source_scope_is_allowed_without_registry_project_row(self):
        root, registry, source = self._fixture()
        try:
            with patch.object(server, "ORCHESTRATOR_PROJECT_REGISTRY_PATH", registry), patch.object(server, "ORCHESTRATOR_VAULT_ROOT", Path(root.name)), patch.object(server, "ORCHESTRATOR_CONTEXT_SOURCES", {"orchestrator-inc": (source,)}):
                result = server.context_search("orchestrator-inc", "bounded")
            self.assertEqual(result["items"][0]["project_id"], "orchestrator-inc")
        finally:
            root.cleanup()


class CoreAllowlistTests(unittest.TestCase):
    def test_route_allowlist_rejects_prefix_bypass(self):
        with self.assertRaises(server.AdapterError) as raised:
            server.core_json("/evolutionevil")
        self.assertEqual(raised.exception.status, 403)


class TaskQueueTests(unittest.TestCase):
    def test_tasks_are_bucketed_from_evidence_only(self):
        routes = {
            "/tasks": {
                "items": [
                    {"id": "t1", "status": "pending", "title": "A"},
                    {"id": "t2", "status": "running", "title": "B"},
                    {"id": "t3", "status": "done", "title": "C"},
                    {"id": "t4", "status": "failed", "title": "D"},
                    {"id": "t5", "status": "weird-status", "title": "E"},
                ]
            }
        }
        with patch.object(server, "urlopen", fake_urlopen(routes)):
            tasks, evidence = server.task_queue()
        buckets = {task["id"]: task["status"] for task in tasks}
        self.assertEqual(buckets, {"t1": "queued", "t2": "active", "t3": "completed", "t4": "blocked", "t5": "unknown"})
        self.assertEqual(evidence["validity"], "valid")

    def test_tasks_without_id_are_dropped(self):
        routes = {"/tasks": {"items": [{"status": "queued"}]}}
        with patch.object(server, "urlopen", fake_urlopen(routes)):
            tasks, _ = server.task_queue()
        self.assertEqual(tasks, [])

    def test_unavailable_when_core_unreachable(self):
        routes = {"/tasks": URLError("refused")}
        with patch.object(server, "urlopen", fake_urlopen(routes)):
            tasks, evidence = server.task_queue()
        self.assertEqual(tasks, [])
        self.assertEqual(evidence["validity"], "unavailable")


class SnapshotAdapterHealthTests(unittest.TestCase):
    def test_hive_reachable_marks_valid_with_observed_timestamp(self):
        routes = {
            "/health": {"status": "ok"},
            "/system": {},
            "/projects": {"items": []},
            "/tasks": {"items": []},
            "/workers": {"items": []},
            "/events": {"items": []},
        }
        with patch.object(server, "urlopen", fake_urlopen(routes)):
            snap = server.snapshot()
        self.assertTrue(snap["adapters"]["hive"]["reachable"])
        self.assertEqual(snap["adapters"]["hive"]["validity"], "valid")
        self.assertIsNotNone(snap["adapters"]["hive"]["last_observed_at"])
        self.assertEqual(snap["core"]["status"], "running")

    def test_hive_unreachable_is_distinct_from_stale(self):
        routes = {"/health": URLError("refused")}
        with patch.object(server, "urlopen", fake_urlopen(routes)):
            snap = server.snapshot()
        self.assertFalse(snap["adapters"]["hive"]["reachable"])
        self.assertEqual(snap["adapters"]["hive"]["validity"], "unavailable")
        self.assertIsNone(snap["adapters"]["hive"]["last_observed_at"])
        self.assertEqual(snap["core"]["status"], "unknown")

    def test_beszel_is_not_fabricated_as_reachable(self):
        routes = {"/health": {"status": "ok"}}
        with patch.object(server, "urlopen", fake_urlopen(routes)):
            snap = server.snapshot()
        beszel = snap["adapters"]["beszel"]
        self.assertFalse(beszel["configured"])
        self.assertFalse(beszel["reachable"])
        self.assertEqual(beszel["validity"], "unknown")

    def test_topology_is_explicitly_deferred(self):
        routes = {"/health": {"status": "ok"}}
        with patch.object(server, "urlopen", fake_urlopen(routes)):
            snap = server.snapshot()
        self.assertEqual(snap["topology"]["status"], "deferred")


class DispatchTests(unittest.TestCase):
    def test_fails_closed_when_token_absent(self):
        with patch.object(server, "API_TOKEN", ""):
            with self.assertRaises(server.AdapterError) as ctx:
                server.dispatch({"mode": "proposal", "goal": "a valid goal", "confirm": True}, None)
        self.assertEqual(ctx.exception.status, 503)

    def test_requires_explicit_confirmation(self):
        with patch.object(server, "API_TOKEN", "tok"):
            with self.assertRaises(server.AdapterError) as ctx:
                server.dispatch({"mode": "proposal", "goal": "a valid goal"}, None)
        self.assertEqual(ctx.exception.status, 400)

    def test_rejects_non_proposal_modes(self):
        with patch.object(server, "API_TOKEN", "tok"):
            for mode in ("task", "mission", "apply", "deploy", "promote", "rollback"):
                with self.assertRaises(server.AdapterError) as ctx:
                    server.dispatch({"mode": mode, "goal": "a valid goal", "confirm": True}, None)
                self.assertEqual(ctx.exception.status, 400)

    def test_goal_length_is_validated(self):
        with patch.object(server, "API_TOKEN", "tok"):
            with self.assertRaises(server.AdapterError):
                server.dispatch({"mode": "proposal", "goal": "short", "confirm": True}, None)

    def test_worker_must_be_allowlisted(self):
        with patch.object(server, "API_TOKEN", "tok"):
            with self.assertRaises(server.AdapterError) as ctx:
                server.dispatch({"mode": "proposal", "goal": "a valid goal", "confirm": True, "preferred_worker": "not-a-real-worker"}, None)
        self.assertEqual(ctx.exception.status, 400)

    def test_local_only_conflicts_with_external_worker(self):
        with patch.object(server, "API_TOKEN", "tok"):
            with self.assertRaises(server.AdapterError):
                server.dispatch({"mode": "proposal", "goal": "a valid goal", "confirm": True, "preferred_worker": "codex", "local_only": True}, None)

    def test_fails_closed_when_reachability_evidence_absent(self):
        routes = {"/health": URLError("refused")}
        with patch.object(server, "API_TOKEN", "tok"), patch.object(server, "urlopen", fake_urlopen(routes)):
            with self.assertRaises(server.AdapterError) as ctx:
                server.dispatch({"mode": "proposal", "goal": "a valid goal", "confirm": True}, None)
        self.assertEqual(ctx.exception.status, 503)
        self.assertIn("reachability evidence is absent", str(ctx.exception))

    def test_success_submits_proposal_without_apply(self):
        routes = {
            "/health": {"status": "ok"},
            "/tasks": {"id": "task-123", "status": "queued"},
        }
        with patch.object(server, "API_TOKEN", "tok"), patch.object(server, "urlopen", fake_urlopen(routes)):
            result = server.dispatch({"mode": "proposal", "goal": "draft a safe proposal", "confirm": True}, "idem-1")
        self.assertEqual(result["kind"], "proposal")
        self.assertEqual(result["id"], "task-123")


class LoopbackEnforcementTests(unittest.TestCase):
    """Finding 1 (HIGH): loopback-only bind and Core target must be enforced, not optional."""

    def test_is_loopback_hostname_accepts_only_loopback_forms(self):
        self.assertTrue(server._is_loopback_hostname("127.0.0.1"))
        self.assertTrue(server._is_loopback_hostname("::1"))
        self.assertTrue(server._is_loopback_hostname("localhost"))
        self.assertTrue(server._is_loopback_hostname("LOCALHOST"))
        self.assertFalse(server._is_loopback_hostname("0.0.0.0"))
        self.assertFalse(server._is_loopback_hostname("::"))
        self.assertFalse(server._is_loopback_hostname("example.com"))
        self.assertFalse(server._is_loopback_hostname("8.8.8.8"))
        self.assertFalse(server._is_loopback_hostname(None))
        self.assertFalse(server._is_loopback_hostname(""))

    def test_core_json_refuses_non_loopback_core_without_sending_request(self):
        calls = []

        def _must_not_be_called(request, timeout=4):
            calls.append(request)
            raise AssertionError("urlopen must not be called for a non-loopback Core target")

        with patch.object(server, "CORE_URL_IS_LOOPBACK", False), patch.object(server, "urlopen", _must_not_be_called):
            with self.assertRaises(server.AdapterError) as ctx:
                server.core_json("/health")
        self.assertEqual(calls, [])
        self.assertEqual(ctx.exception.status, 503)

    def test_dispatch_reachability_check_also_fails_closed_on_non_loopback_core(self):
        with patch.object(server, "API_TOKEN", "tok"), patch.object(server, "CORE_URL_IS_LOOPBACK", False):
            with self.assertRaises(server.AdapterError) as ctx:
                server.dispatch({"mode": "proposal", "goal": "a valid goal", "confirm": True}, None)
        self.assertEqual(ctx.exception.status, 503)

    def test_main_refuses_to_start_on_non_loopback_bind(self):
        with patch.object(sys, "argv", ["server.py", "--bind", "0.0.0.0"]):
            with self.assertRaises(SystemExit):
                server.main()

    def test_main_refuses_to_start_on_non_loopback_core_url(self):
        with patch.object(sys, "argv", ["server.py"]), patch.object(server, "CORE_URL_IS_LOOPBACK", False):
            with self.assertRaises(SystemExit):
                server.main()


class TaskTypeAllowlistTests(unittest.TestCase):
    """Finding 2 (HIGH): task_type must be enforced server-side, not left to client-only UI validation."""

    def test_unlisted_task_type_is_rejected(self):
        with patch.object(server, "API_TOKEN", "tok"):
            with self.assertRaises(server.AdapterError) as ctx:
                server.dispatch({"mode": "proposal", "goal": "a valid goal", "confirm": True, "task_type": "DEPLOY"}, None)
        self.assertEqual(ctx.exception.status, 400)

    def test_default_task_type_is_allowlisted_and_succeeds(self):
        routes = {"/health": {"status": "ok"}, "/tasks": {"id": "task-999"}}
        with patch.object(server, "API_TOKEN", "tok"), patch.object(server, "urlopen", fake_urlopen(routes)):
            result = server.dispatch({"mode": "proposal", "goal": "draft a safe proposal", "confirm": True}, None)
        self.assertEqual(result["id"], "task-999")


class WorkerPolicyTests(unittest.TestCase):
    """P-017: worker routing policy read-model. Enforces local-first routing and a
    fail-closed free/subscription-only cost-mode allowlist; metered/unknown cost
    modes and unrecognized worker ids are always blocked, never allowed through by
    default. Pure, in-memory, side-effect-free -- no network I/O, no service start."""

    def test_record_for_known_worker_reports_its_declared_policy(self):
        record = server.worker_policy_record("deterministic")
        self.assertEqual(record["worker_id"], "deterministic")
        self.assertEqual(record["execution_mode"], "local")
        self.assertEqual(record["cost_mode"], "free")
        self.assertEqual(record["network_requirement"], "none")
        self.assertTrue(record["cost_mode_allowed"])

    def test_record_for_unknown_worker_is_all_unknown_not_guessed(self):
        record = server.worker_policy_record("some-future-worker")
        self.assertEqual(record["capability"], None)
        self.assertEqual(record["execution_mode"], "unknown")
        self.assertEqual(record["cost_mode"], "unknown")
        self.assertEqual(record["network_requirement"], "unknown")
        self.assertFalse(record["cost_mode_allowed"])

    def test_catalog_lists_every_declared_worker_with_local_first_metadata(self):
        catalog = server.worker_policy_catalog()
        self.assertTrue(catalog["local_first_enforced"])
        self.assertEqual(catalog["accepted_cost_modes"], ["free", "subscription"])
        ids = {w["worker_id"] for w in catalog["workers"]}
        self.assertEqual(ids, set(server.WORKER_POLICY))

    def test_free_cost_mode_is_accepted(self):
        result = server.evaluate_worker_policy("deterministic", local_only=False)
        self.assertTrue(result["allowed"])
        self.assertIsNone(result["blocked_reason"])

    def test_subscription_cost_mode_is_accepted_via_synthetic_fixture(self):
        # No currently declared worker is "subscription" (none is confidently
        # documented as such), so this exercises the accept branch directly against
        # the policy table rather than relying on real worker classification.
        with patch.dict(server.WORKER_POLICY, {"fixture-subscription-worker": {
            "capability": "remote_llm_inference", "execution_mode": "remote",
            "cost_mode": "subscription", "network_requirement": "internet",
            "fallback_policy": "local_preferred",
        }}):
            result = server.evaluate_worker_policy("fixture-subscription-worker", local_only=False)
        self.assertTrue(result["allowed"])

    def test_metered_cost_mode_is_blocked(self):
        with patch.dict(server.WORKER_POLICY, {"fixture-metered-worker": {
            "capability": "remote_llm_inference", "execution_mode": "remote",
            "cost_mode": "metered", "network_requirement": "internet",
            "fallback_policy": "local_preferred",
        }}):
            result = server.evaluate_worker_policy("fixture-metered-worker", local_only=False)
        self.assertFalse(result["allowed"])
        self.assertIn("metered", result["blocked_reason"])

    def test_unknown_declared_cost_mode_is_blocked(self):
        # antigravity/codex are declared "unknown" (no documented billing basis),
        # which must be blocked exactly like "metered" -- fail closed by default.
        for worker_id in ("antigravity", "codex"):
            result = server.evaluate_worker_policy(worker_id, local_only=False)
            self.assertFalse(result["allowed"], f"{worker_id} must be blocked while cost_mode is unknown")
            self.assertIn("unknown", result["blocked_reason"])

    def test_unrecognized_worker_id_is_blocked(self):
        result = server.evaluate_worker_policy("totally-made-up-worker", local_only=False)
        self.assertFalse(result["allowed"])
        self.assertIn("unknown", result["blocked_reason"])

    def test_local_first_routing_blocks_remote_worker_when_local_only(self):
        # openrouter_free is "free" (would pass the cost gate alone) but is remote,
        # so local-first routing must still block it when local_only is requested.
        result = server.evaluate_worker_policy("openrouter_free", local_only=True)
        self.assertFalse(result["allowed"])
        self.assertIn("local", result["blocked_reason"])

    def test_local_worker_is_allowed_under_local_only(self):
        result = server.evaluate_worker_policy("lmstudio", local_only=True)
        self.assertTrue(result["allowed"])

    def test_known_local_worker_aliases_are_visible_but_unverified_workers_fail_closed(self):
        for worker_id in ("ollama", "cline", "kilo", "opencode", "freebuff", "openclaw"):
            record = server.worker_policy_record(worker_id)
            self.assertNotEqual(record["capability"], None)
            if worker_id != "ollama":
                self.assertFalse(record["cost_mode_allowed"])
        self.assertTrue(server.worker_policy_record("ollama")["cost_mode_allowed"])

    def test_remote_worker_allowed_when_local_only_not_requested(self):
        result = server.evaluate_worker_policy("openrouter_free", local_only=False)
        self.assertTrue(result["allowed"])

    def test_evaluate_worker_policy_has_no_side_effects(self):
        # Pure read-model: must never shell out, never open a socket/subprocess.
        with patch("server.subprocess.run") as mock_run, patch.object(server, "urlopen") as mock_urlopen:
            server.evaluate_worker_policy("lmstudio", local_only=True)
            server.worker_policy_catalog()
        mock_run.assert_not_called()
        mock_urlopen.assert_not_called()

    def test_dispatch_blocks_unknown_cost_mode_worker_with_policy_reason(self):
        with patch.object(server, "API_TOKEN", "tok"):
            with self.assertRaises(server.AdapterError) as ctx:
                server.dispatch({"mode": "proposal", "goal": "a valid goal", "confirm": True, "preferred_worker": "codex"}, None)
        self.assertEqual(ctx.exception.status, 400)
        self.assertIn("blocked by policy", str(ctx.exception))

    def test_dispatch_blocks_remote_worker_under_local_only(self):
        with patch.object(server, "API_TOKEN", "tok"):
            with self.assertRaises(server.AdapterError) as ctx:
                server.dispatch(
                    {"mode": "proposal", "goal": "a valid goal", "confirm": True,
                     "preferred_worker": "openrouter_free", "local_only": True},
                    None,
                )
        self.assertEqual(ctx.exception.status, 400)

    def test_dispatch_blocks_unrecognized_worker_id(self):
        with patch.object(server, "API_TOKEN", "tok"):
            with self.assertRaises(server.AdapterError) as ctx:
                server.dispatch(
                    {"mode": "proposal", "goal": "a valid goal", "confirm": True, "preferred_worker": "not-a-real-worker"},
                    None,
                )
        self.assertEqual(ctx.exception.status, 400)

    def test_dispatch_allows_free_local_worker(self):
        routes = {"/health": {"status": "ok"}, "/tasks": {"id": "task-local-1"}}
        with patch.object(server, "API_TOKEN", "tok"), patch.object(server, "urlopen", fake_urlopen(routes)):
            result = server.dispatch(
                {"mode": "proposal", "goal": "draft a safe proposal", "confirm": True,
                 "preferred_worker": "deterministic", "local_only": True},
                None,
            )
        self.assertEqual(result["id"], "task-local-1")


class WorkerPolicyEndpointTests(unittest.TestCase):
    """P-017 review follow-up, gap 1: an explicit, loopback-only endpoint field for
    local workers; remote workers never get an invented endpoint; reading the
    policy never probes a port or starts a service."""

    def test_local_in_process_worker_has_no_endpoint(self):
        # deterministic runs in-process inside HIVE Core -- it is not a separately
        # dialable service, so endpoint must stay None, not a fabricated address.
        record = server.worker_policy_record("deterministic")
        self.assertIsNone(record["endpoint"])
        self.assertEqual(record["endpoint_basis"], "not_applicable")

    def test_lmstudio_local_endpoint_defaults_to_documented_loopback_address(self):
        with patch.object(server, "LMSTUDIO_ENDPOINT_ENV", ""):
            record = server.worker_policy_record("lmstudio-local")
        self.assertEqual(record["endpoint"], server.LMSTUDIO_DEFAULT_ENDPOINT)
        self.assertEqual(record["endpoint_basis"], "documented_default")
        self.assertTrue(server._is_loopback_hostname(urlparse(record["endpoint"]).hostname))

    def test_lmstudio_local_endpoint_honors_loopback_override(self):
        with patch.object(server, "LMSTUDIO_ENDPOINT_ENV", "http://127.0.0.1:4321"):
            record = server.worker_policy_record("lmstudio-local")
        self.assertEqual(record["endpoint"], "http://127.0.0.1:4321")
        self.assertEqual(record["endpoint_basis"], "operator_override")

    def test_lmstudio_local_rejects_non_loopback_override(self):
        with patch.object(server, "LMSTUDIO_ENDPOINT_ENV", "http://evil.example.com:4321"):
            record = server.worker_policy_record("lmstudio-local")
        self.assertIsNone(record["endpoint"])
        self.assertEqual(record["endpoint_basis"], "invalid_non_loopback_override_rejected")

    def test_remote_workers_never_get_an_endpoint(self):
        for worker_id in ("openrouter_free", "antigravity", "codex-subscription"):
            record = server.worker_policy_record(worker_id)
            self.assertIsNone(record["endpoint"], f"{worker_id} must never have an invented endpoint")
            self.assertEqual(record["endpoint_basis"], "not_applicable")

    def test_unrecognized_worker_has_no_endpoint(self):
        record = server.worker_policy_record("totally-made-up-worker")
        self.assertIsNone(record["endpoint"])
        self.assertEqual(record["endpoint_basis"], "unknown")

    def test_endpoint_defense_in_depth_rejects_non_loopback_even_if_declared_local(self):
        # Even if a future table edit accidentally declared a non-loopback endpoint
        # for a local worker, worker_policy_record() must still reject it rather
        # than expose it -- a static assertion, never a live probe of the address.
        with patch.dict(server.WORKER_POLICY, {"fixture-bad-local-worker": {
            "capability": "local_llm_inference", "execution_mode": "local", "cost_mode": "free",
            "network_requirement": "loopback", "fallback_policy": "none_required",
            "endpoint": "http://0.0.0.0:9999", "endpoint_basis": "documented_default",
        }}):
            record = server.worker_policy_record("fixture-bad-local-worker")
        self.assertIsNone(record["endpoint"])
        self.assertEqual(record["endpoint_basis"], "invalid_rejected")

    def test_endpoint_defense_in_depth_rejects_endpoint_on_a_remote_worker(self):
        with patch.dict(server.WORKER_POLICY, {"fixture-bad-remote-worker": {
            "capability": "remote_llm_inference", "execution_mode": "remote", "cost_mode": "free",
            "network_requirement": "internet", "fallback_policy": "local_preferred",
            "endpoint": "http://127.0.0.1:9999", "endpoint_basis": "documented_default",
        }}):
            record = server.worker_policy_record("fixture-bad-remote-worker")
        self.assertIsNone(record["endpoint"])
        self.assertEqual(record["endpoint_basis"], "invalid_rejected")

    def test_reading_policy_never_probes_or_starts_a_service(self):
        with patch("server.subprocess.run") as mock_run, patch.object(server, "urlopen") as mock_urlopen:
            server.worker_policy_record("lmstudio-local")
            server.worker_policy_catalog()
            server.evaluate_worker_policy("lmstudio-local", local_only=True)
        mock_run.assert_not_called()
        mock_urlopen.assert_not_called()


class WorkerIdAlignmentTests(unittest.TestCase):
    """P-017 review follow-up, gap 2: canonical worker ids are aligned with the
    evidenced Orchestrator registry names (lmstudio-local, codex-subscription); old
    bare ids are preserved as an explicit, evidenced alias mapping; any id outside
    both the canonical table and the alias map fails closed."""

    def test_canonical_worker_id_resolves_known_aliases(self):
        self.assertEqual(server.canonical_worker_id("lmstudio"), "lmstudio-local")
        self.assertEqual(server.canonical_worker_id("codex"), "codex-subscription")

    def test_canonical_worker_id_passes_through_unaliased_ids(self):
        self.assertEqual(server.canonical_worker_id("openrouter_free"), "openrouter_free")
        self.assertEqual(server.canonical_worker_id("totally-unknown"), "totally-unknown")

    def test_old_bare_lmstudio_alias_resolves_to_canonical_record(self):
        record = server.worker_policy_record("lmstudio")
        self.assertEqual(record["worker_id"], "lmstudio")
        self.assertEqual(record["canonical_worker_id"], "lmstudio-local")
        self.assertEqual(record["execution_mode"], "local")
        self.assertTrue(record["cost_mode_allowed"])

    def test_old_bare_codex_alias_resolves_to_canonical_record(self):
        record = server.worker_policy_record("codex")
        self.assertEqual(record["canonical_worker_id"], "codex-subscription")

    def test_codex_subscription_defaults_to_unknown_and_blocked(self):
        # Confirms the fail-closed default: "authorized" in `ao agent ls` does not
        # by itself prove a subscription (vs. metered API key) billing plan.
        with patch.object(server, "CODEX_SUBSCRIPTION_CONFIRMED", False):
            record = server.worker_policy_record("codex-subscription")
            result = server.evaluate_worker_policy("codex-subscription", local_only=False)
        self.assertEqual(record["cost_mode"], "unknown")
        self.assertFalse(result["allowed"])

    def test_codex_subscription_confirmed_flag_is_read_at_import_not_mutable_live(self):
        # CODEX_SUBSCRIPTION_CONFIRMED (like HIVE_HEALTH_REQUIRES_AUTH) is read once
        # from the environment; WORKER_POLICY's cost_mode for codex-subscription is
        # computed from it at that time. Patching the resulting cost_mode value
        # directly is how a test (or an operator restarting the process after
        # setting the env var) actually flips this, which this test pins.
        with patch.dict(server.WORKER_POLICY, {"codex-subscription": {
            **server.WORKER_POLICY["codex-subscription"], "cost_mode": "subscription",
        }}):
            result = server.evaluate_worker_policy("codex-subscription", local_only=False)
        self.assertTrue(result["allowed"])

    def test_unaliased_unknown_id_still_fails_closed(self):
        result = server.evaluate_worker_policy("some-other-vendor-worker", local_only=False)
        self.assertFalse(result["allowed"])
        self.assertIn("unknown", result["blocked_reason"])

    def test_catalog_exposes_canonical_ids_not_old_bare_ids(self):
        catalog = server.worker_policy_catalog()
        ids = {w["worker_id"] for w in catalog["workers"]}
        self.assertIn("lmstudio-local", ids)
        self.assertIn("codex-subscription", ids)
        self.assertNotIn("lmstudio", ids)
        self.assertNotIn("codex", ids)

    def test_dispatch_still_accepts_old_bare_worker_ids_via_alias(self):
        routes = {"/health": {"status": "ok"}, "/tasks": {"id": "task-alias-1"}}
        with patch.object(server, "API_TOKEN", "tok"), patch.object(server, "urlopen", fake_urlopen(routes)):
            result = server.dispatch(
                {"mode": "proposal", "goal": "draft a safe proposal", "confirm": True,
                 "preferred_worker": "lmstudio", "local_only": True},
                None,
            )
        self.assertEqual(result["id"], "task-alias-1")


class WorkerRegistryEvidenceTests(unittest.TestCase):
    """Finding 3 (MEDIUM): optional adapter failures must preserve unknown/unavailable provenance."""

    def test_success_marks_valid(self):
        routes = {"/workers": {"items": [{"id": "w1", "name": "Worker 1"}]}}
        with patch.object(server, "urlopen", fake_urlopen(routes)):
            workers, ev = server.worker_registry()
        self.assertEqual([w["id"] for w in workers], ["w1"])
        self.assertEqual(ev["validity"], "valid")

    def test_failure_is_not_collapsed_to_silent_empty_default(self):
        routes = {"/workers": URLError("refused")}
        with patch.object(server, "urlopen", fake_urlopen(routes)):
            workers, ev = server.worker_registry()
        self.assertEqual(workers, [])
        self.assertEqual(ev["validity"], "unavailable")
        self.assertIsNotNone(ev["reason"])


class SnapshotEvidencePreservationTests(unittest.TestCase):
    """Finding 3 (MEDIUM): snapshot() must expose workers/events/metrics provenance on failure."""

    def test_workers_and_events_carry_unavailable_evidence_when_core_fails(self):
        routes = {"/health": {"status": "ok"}}
        with patch.object(server, "urlopen", fake_urlopen(routes)):
            snap = server.snapshot()
        self.assertEqual(snap["workers"]["items"], [])
        self.assertEqual(snap["workers"]["evidence"]["validity"], "unavailable")
        self.assertEqual(snap["events"]["items"], [])
        self.assertEqual(snap["events"]["evidence"]["validity"], "unavailable")

    def test_metric_reason_reflects_real_system_fetch_failure(self):
        routes = {"/health": {"status": "ok"}}
        with patch.object(server, "urlopen", fake_urlopen(routes)):
            snap = server.snapshot()
        cpu = snap["metrics"]["cpu"]
        self.assertEqual(cpu["validity"], "unavailable")
        self.assertNotEqual(cpu["reason"], "not supplied")
        self.assertIn("unavailable", cpu["reason"].lower())


class EventTimestampTests(unittest.TestCase):
    """Finding 4 (MEDIUM): missing event timestamps must not be fabricated as utc_now()."""

    def test_missing_timestamp_is_reported_unknown_not_fabricated(self):
        routes = {
            "/health": {"status": "ok"},
            "/events": {"items": [{"event_type": "NO_TIMESTAMP", "source": "test"}]},
        }
        with patch.object(server, "urlopen", fake_urlopen(routes)):
            snap = server.snapshot()
        events = snap["events"]["items"]
        self.assertEqual(len(events), 1)
        self.assertIsNone(events[0]["timestamp"])
        self.assertEqual(events[0]["timestamp_validity"], "unknown")

    def test_present_timestamp_is_preserved_verbatim(self):
        routes = {
            "/health": {"status": "ok"},
            "/events": {"items": [{"event_type": "X", "timestamp": "2026-01-01T00:00:00Z"}]},
        }
        with patch.object(server, "urlopen", fake_urlopen(routes)):
            snap = server.snapshot()
        events = snap["events"]["items"]
        self.assertEqual(events[0]["timestamp"], "2026-01-01T00:00:00Z")
        self.assertEqual(events[0]["timestamp_validity"], "valid")


class HealthValidityTests(unittest.TestCase):
    """Finding 4 (MEDIUM): a 200 response with a missing/invalid status must not be marked valid."""

    def test_successful_call_with_missing_status_is_unknown_not_valid(self):
        routes = {"/health": {}}
        with patch.object(server, "urlopen", fake_urlopen(routes)):
            snap = server.snapshot()
        self.assertEqual(snap["core"]["status"], "unknown")
        self.assertEqual(snap["adapters"]["hive"]["validity"], "unknown")
        self.assertTrue(snap["adapters"]["hive"]["reachable"])

    def test_successful_call_with_recognized_status_is_valid(self):
        routes = {"/health": {"status": "ok"}}
        with patch.object(server, "urlopen", fake_urlopen(routes)):
            snap = server.snapshot()
        self.assertEqual(snap["adapters"]["hive"]["validity"], "valid")


class AuthenticatedVsTokenConfiguredTests(unittest.TestCase):
    """Finding 4 (MEDIUM): distinguish a configured token from a verified authentication."""

    def test_token_configured_but_rejected_is_not_reported_authenticated(self):
        routes = {"/health": http_error(401)}
        with patch.object(server, "API_TOKEN", "tok"), patch.object(server, "urlopen", fake_urlopen(routes)):
            snap = server.snapshot()
        hive = snap["adapters"]["hive"]
        self.assertTrue(hive["token_configured"])
        self.assertFalse(hive["authenticated"])
        self.assertEqual(hive["authentication_validity"], "unavailable")
        # A 401 is itself proof Core is up and reachable; it is the auth check that
        # was rejected, not connectivity. See ReachabilityVsAuthRequiredTests below.
        self.assertTrue(hive["reachable"])
        self.assertEqual(hive["validity"], "auth_required")

    def test_token_configured_and_call_succeeds_is_not_fabricated_authenticated(self):
        # A successful /health call does not by itself prove the bearer token was
        # ever checked (the endpoint may require no auth at all), so authenticated
        # must stay false and be reported as a distinct "unknown" validity rather
        # than fabricated true merely because a token is configured.
        routes = {"/health": {"status": "ok"}}
        with patch.object(server, "API_TOKEN", "tok"), patch.object(server, "HIVE_HEALTH_REQUIRES_AUTH", False), patch.object(server, "urlopen", fake_urlopen(routes)):
            snap = server.snapshot()
        hive = snap["adapters"]["hive"]
        self.assertTrue(hive["token_configured"])
        self.assertFalse(hive["authenticated"])
        self.assertEqual(hive["authentication_validity"], "unknown")

    def test_documented_auth_guaranteed_endpoint_allows_authenticated_true(self):
        # Only when the operator has explicitly documented that this HIVE Core
        # deployment's /health route validates the bearer token does a successful
        # call count as proof of authentication.
        routes = {"/health": {"status": "ok"}}
        with patch.object(server, "API_TOKEN", "tok"), patch.object(server, "HIVE_HEALTH_REQUIRES_AUTH", True), patch.object(server, "urlopen", fake_urlopen(routes)):
            snap = server.snapshot()
        hive = snap["adapters"]["hive"]
        self.assertTrue(hive["authenticated"])
        self.assertEqual(hive["authentication_validity"], "valid")

    def test_no_token_is_never_reported_authenticated(self):
        routes = {"/health": {"status": "ok"}}
        with patch.object(server, "API_TOKEN", ""), patch.object(server, "HIVE_HEALTH_REQUIRES_AUTH", True), patch.object(server, "urlopen", fake_urlopen(routes)):
            snap = server.snapshot()
        hive = snap["adapters"]["hive"]
        self.assertFalse(hive["token_configured"])
        self.assertFalse(hive["authenticated"])
        self.assertEqual(hive["authentication_validity"], "unavailable")

    def test_token_configured_but_unreachable_is_not_reported_authenticated(self):
        routes = {"/health": URLError("refused")}
        with patch.object(server, "API_TOKEN", "tok"), patch.object(server, "urlopen", fake_urlopen(routes)):
            snap = server.snapshot()
        hive = snap["adapters"]["hive"]
        self.assertTrue(hive["token_configured"])
        self.assertFalse(hive["authenticated"])
        self.assertEqual(hive["authentication_validity"], "unavailable")


class AuthRequiredValidityTests(unittest.TestCase):
    """Protected endpoints that reject an absent/invalid token are distinct from a
    plain connection failure (unavailable) or a 404 (unknown)."""

    def test_401_maps_to_auth_required(self):
        self.assertEqual(server.unavailability_validity(http_error_obj(401)), "auth_required")

    def test_403_maps_to_auth_required(self):
        self.assertEqual(server.unavailability_validity(http_error_obj(403)), "auth_required")

    def test_404_still_maps_to_unknown(self):
        self.assertEqual(server.unavailability_validity(http_error_obj(404)), "unknown")

    def test_503_still_maps_to_unavailable(self):
        self.assertEqual(server.unavailability_validity(http_error_obj(503)), "unavailable")

    def test_project_catalog_reports_auth_required_on_401(self):
        routes = {"/projects": http_error(401)}
        with patch.object(server, "urlopen", fake_urlopen(routes)):
            projects, evidence = server.project_catalog()
        self.assertEqual(projects, [])
        self.assertEqual(evidence["validity"], "auth_required")

    def test_task_queue_reports_auth_required_on_403(self):
        routes = {"/tasks": http_error(403)}
        with patch.object(server, "urlopen", fake_urlopen(routes)):
            tasks, evidence = server.task_queue()
        self.assertEqual(tasks, [])
        self.assertEqual(evidence["validity"], "auth_required")


def http_error_obj(status: int) -> "server.AdapterError":
    return server.AdapterError("rejected", status)


class HealthProbeTests(unittest.TestCase):
    def test_alive_status_is_recognized_as_valid(self):
        # A live HIVE Core instance was observed returning status="alive", which
        # must be treated as healthy, not as an unrecognized/unknown payload.
        routes = {"/health": {"status": "alive", "service": "hive-core", "version": "0.3.0-alpha"}}
        with patch.object(server, "urlopen", fake_urlopen(routes)):
            probe = server.health_probe()
        self.assertEqual(probe["status"], "alive")
        self.assertEqual(probe["validity"], "valid")
        self.assertTrue(probe["reachable"])

    def test_unreachable_is_unavailable_with_no_observed_at(self):
        routes = {"/health": URLError("refused")}
        with patch.object(server, "urlopen", fake_urlopen(routes)):
            probe = server.health_probe()
        self.assertFalse(probe["reachable"])
        self.assertEqual(probe["validity"], "unavailable")
        self.assertIsNone(probe["observed_at"])

    def test_401_is_auth_required_not_unavailable(self):
        routes = {"/health": http_error(401)}
        with patch.object(server, "urlopen", fake_urlopen(routes)):
            probe = server.health_probe()
        self.assertEqual(probe["validity"], "auth_required")
        self.assertEqual(probe["error_status"], 401)
        # A 401 proves Core processed and rejected the request -- it is reachable.
        self.assertTrue(probe["reachable"])
        self.assertIsNotNone(probe["observed_at"])


class ReadyProbeTests(unittest.TestCase):
    def test_ready_status_with_workers_is_recognized_as_valid(self):
        routes = {
            "/ready": {
                "status": "ready", "database": "ok", "queue": "running",
                "workers": [{"id": "deterministic", "name": "Safe arithmetic evaluator", "provider": "builtin", "status": "available"}],
            }
        }
        with patch.object(server, "urlopen", fake_urlopen(routes)):
            probe = server.ready_probe()
        self.assertEqual(probe["status"], "ready")
        self.assertEqual(probe["database"], "ok")
        self.assertEqual(probe["queue"], "running")
        self.assertEqual(probe["validity"], "valid")
        self.assertEqual(len(probe["workers"]), 1)

    def test_unreachable_ready_is_unavailable_with_empty_workers(self):
        routes = {"/ready": URLError("refused")}
        with patch.object(server, "urlopen", fake_urlopen(routes)):
            probe = server.ready_probe()
        self.assertFalse(probe["reachable"])
        self.assertEqual(probe["validity"], "unavailable")
        self.assertEqual(probe["workers"], [])

    def test_snapshot_exposes_ready_record_under_core(self):
        routes = {
            "/health": {"status": "alive"},
            "/ready": {"status": "ready", "database": "ok", "queue": "running", "workers": []},
        }
        with patch.object(server, "urlopen", fake_urlopen(routes)):
            snap = server.snapshot()
        self.assertEqual(snap["core"]["ready"]["status"], "ready")
        self.assertEqual(snap["core"]["ready"]["database"], "ok")
        self.assertEqual(snap["core"]["ready"]["validity"], "valid")


class ReachabilityVsAuthRequiredTests(unittest.TestCase):
    """A 401/403 proves Core processed and rejected the request -- it is reachable,
    distinct from a connection failure/timeout where no response was ever received.
    unavailability_validity() already encodes this distinction (auth_required vs.
    unavailable); health_probe()/ready_probe() must agree with it instead of
    reporting reachable=false for every error uniformly."""

    def test_health_probe_401_is_reachable_with_observed_at(self):
        routes = {"/health": http_error(401)}
        with patch.object(server, "urlopen", fake_urlopen(routes)):
            probe = server.health_probe()
        self.assertTrue(probe["reachable"])
        self.assertIsNotNone(probe["observed_at"])
        self.assertEqual(probe["validity"], "auth_required")

    def test_health_probe_403_is_reachable_with_observed_at(self):
        routes = {"/health": http_error(403)}
        with patch.object(server, "urlopen", fake_urlopen(routes)):
            probe = server.health_probe()
        self.assertTrue(probe["reachable"])
        self.assertIsNotNone(probe["observed_at"])
        self.assertEqual(probe["validity"], "auth_required")

    def test_health_probe_connection_failure_stays_unreachable(self):
        routes = {"/health": URLError("refused")}
        with patch.object(server, "urlopen", fake_urlopen(routes)):
            probe = server.health_probe()
        self.assertFalse(probe["reachable"])
        self.assertIsNone(probe["observed_at"])
        self.assertEqual(probe["validity"], "unavailable")

    def test_health_probe_404_is_out_of_narrow_fix_scope_stays_unreachable(self):
        # Only 401/403 prove reachability for this fix; a 404 is left as-is
        # (reachable=false) -- this test pins that boundary so it isn't widened
        # silently in a future change.
        routes = {"/health": http_error(404)}
        with patch.object(server, "urlopen", fake_urlopen(routes)):
            probe = server.health_probe()
        self.assertFalse(probe["reachable"])
        self.assertEqual(probe["validity"], "unknown")

    def test_ready_probe_401_is_reachable_with_observed_at(self):
        routes = {"/ready": http_error(401)}
        with patch.object(server, "urlopen", fake_urlopen(routes)):
            probe = server.ready_probe()
        self.assertTrue(probe["reachable"])
        self.assertIsNotNone(probe["observed_at"])
        self.assertEqual(probe["validity"], "auth_required")
        self.assertEqual(probe["workers"], [])

    def test_ready_probe_connection_failure_stays_unreachable(self):
        routes = {"/ready": URLError("refused")}
        with patch.object(server, "urlopen", fake_urlopen(routes)):
            probe = server.ready_probe()
        self.assertFalse(probe["reachable"])
        self.assertIsNone(probe["observed_at"])
        self.assertEqual(probe["validity"], "unavailable")

    def test_snapshot_hive_adapter_reflects_reachable_auth_required(self):
        routes = {"/health": http_error(401)}
        with patch.object(server, "urlopen", fake_urlopen(routes)):
            snap = server.snapshot()
        hive = snap["adapters"]["hive"]
        self.assertTrue(hive["reachable"])
        self.assertIsNotNone(hive["last_observed_at"])
        self.assertEqual(hive["validity"], "auth_required")


class WorkerFallbackTests(unittest.TestCase):
    """When the authenticated /workers registry is unavailable or auth_required,
    fall back to the public worker-availability list already embedded in /ready
    rather than collapsing straight to an empty list."""

    def test_falls_back_to_ready_workers_on_401(self):
        routes = {
            "/workers": http_error(401),
            "/ready": {"status": "ready", "database": "ok", "queue": "running",
                       "workers": [{"id": "deterministic", "name": "Deterministic", "provider": "builtin", "status": "available"}]},
        }
        with patch.object(server, "urlopen", fake_urlopen(routes)):
            workers, ev = server.worker_registry()
        self.assertEqual([w["id"] for w in workers], ["deterministic"])
        self.assertEqual(ev["validity"], "valid")
        self.assertIn("ready", ev["source"])

    def test_no_fallback_when_ready_also_unreachable(self):
        routes = {"/workers": http_error(401), "/ready": URLError("refused")}
        with patch.object(server, "urlopen", fake_urlopen(routes)):
            workers, ev = server.worker_registry()
        self.assertEqual(workers, [])
        self.assertEqual(ev["validity"], "auth_required")

    def test_authenticated_registry_preferred_when_available(self):
        routes = {
            "/workers": {"items": [{"id": "w1", "name": "Full detail"}]},
            "/ready": {"status": "ready", "database": "ok", "queue": "running", "workers": [{"id": "deterministic"}]},
        }
        with patch.object(server, "urlopen", fake_urlopen(routes)):
            workers, ev = server.worker_registry()
        self.assertEqual([w["id"] for w in workers], ["w1"])
        self.assertEqual(ev["validity"], "valid")
        self.assertIn("/workers", ev["source"])


class CreatorOpsStatusTests(unittest.TestCase):
    def _make_db(self) -> Path:
        tmp_dir = Path(tempfile.mkdtemp(prefix="creator-ops-test-"))
        self.addCleanup(lambda: [p.unlink() for p in tmp_dir.glob("*")] and tmp_dir.rmdir())
        db_path = tmp_dir / "creator_ops.sqlite3"
        connection = sqlite3.connect(db_path)
        try:
            connection.execute("CREATE TABLE accounts (id INTEGER PRIMARY KEY, handle TEXT)")
            connection.execute("CREATE TABLE posts (id INTEGER PRIMARY KEY, caption TEXT)")
            connection.execute("INSERT INTO accounts (handle) VALUES ('a'), ('b')")
            connection.execute("INSERT INTO posts (caption) VALUES ('secret caption text')")
            connection.commit()
        finally:
            connection.close()
        return db_path

    def test_reports_aggregate_counts_only_no_row_content(self):
        db_path = self._make_db()
        with patch.object(server, "CREATOR_OPS_DB_PATH", str(db_path)):
            status = server.creator_ops_status()
        self.assertEqual(status["validity"], "valid")
        self.assertTrue(status["reachable"])
        self.assertEqual(status["counts"]["accounts"], 2)
        self.assertEqual(status["counts"]["posts"], 1)
        # No row-level content (captions, handles) ever appears anywhere in the result.
        dumped = json.dumps(status)
        self.assertNotIn("secret caption text", dumped)
        self.assertNotIn("'a'", dumped)

    def test_missing_table_is_simply_absent_from_counts(self):
        db_path = self._make_db()
        with patch.object(server, "CREATOR_OPS_DB_PATH", str(db_path)):
            status = server.creator_ops_status()
        self.assertNotIn("media_assets", status["counts"])

    def test_missing_file_is_unavailable_with_reason(self):
        missing = str(Path(tempfile.mkdtemp(prefix="creator-ops-missing-")) / "does-not-exist.sqlite3")
        with patch.object(server, "CREATOR_OPS_DB_PATH", missing):
            status = server.creator_ops_status()
        self.assertFalse(status["reachable"])
        self.assertEqual(status["validity"], "unavailable")
        self.assertIn("not found", status["reason"])
        self.assertEqual(status["counts"], {})

    def test_corrupt_file_is_unavailable_not_fabricated(self):
        tmp_dir = Path(tempfile.mkdtemp(prefix="creator-ops-corrupt-"))
        self.addCleanup(lambda: [p.unlink() for p in tmp_dir.glob("*")] and tmp_dir.rmdir())
        corrupt_path = tmp_dir / "corrupt.sqlite3"
        corrupt_path.write_bytes(b"not a real sqlite database")
        with patch.object(server, "CREATOR_OPS_DB_PATH", str(corrupt_path)):
            status = server.creator_ops_status()
        self.assertFalse(status["reachable"])
        self.assertEqual(status["validity"], "unavailable")

    def test_included_in_snapshot_adapters(self):
        db_path = self._make_db()
        routes = {"/health": {"status": "alive"}}
        with patch.object(server, "CREATOR_OPS_DB_PATH", str(db_path)), patch.object(server, "urlopen", fake_urlopen(routes)):
            snap = server.snapshot()
        self.assertIn("creator_ops", snap["adapters"])
        self.assertEqual(snap["adapters"]["creator_ops"]["validity"], "valid")


def fake_completed(stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


class AoCliConfigurationTests(unittest.TestCase):
    """The AO CLI bridge is disabled unless AO_CLI_PATH is an absolute, existing file
    -- never fabricated as available."""

    def test_unset_path_is_not_configured(self):
        with patch.object(server, "AO_CLI_PATH", ""):
            self.assertFalse(server.ao_cli_configured())

    def test_relative_path_is_not_configured(self):
        with patch.object(server, "AO_CLI_PATH", "ao"):
            self.assertFalse(server.ao_cli_configured())

    def test_absolute_nonexistent_path_is_not_configured(self):
        with patch.object(server, "AO_CLI_PATH", r"C:\definitely\not\a\real\path\ao.exe"):
            self.assertFalse(server.ao_cli_configured())

    def test_absolute_existing_file_is_configured(self):
        with patch.object(server, "AO_CLI_PATH", sys.executable):
            self.assertTrue(server.ao_cli_configured())


class AoCapabilitiesTests(unittest.TestCase):
    """ao_capabilities() must reflect the CLI bridge's actual configuration state
    rather than a fixed static declaration."""

    def test_unconfigured_reports_all_false(self):
        with patch.object(server, "AO_CLI_PATH", ""), patch.object(server, "AO_SEND_CALLER_TOKEN", ""):
            caps = server.ao_capabilities()
        self.assertFalse(caps["session_list_confirmed"])
        self.assertFalse(caps["session_history_confirmed"])
        self.assertFalse(caps["send_confirmed"])
        self.assertFalse(caps["send_recover_confirmed"])
        self.assertFalse(caps["caller_auth_configured"])
        self.assertFalse(caps["worker_api_confirmed"])
        self.assertFalse(caps["chat_realtime_api_confirmed"])
        self.assertEqual(caps["transport"], "cli_disabled")
        self.assertTrue(caps["reason"])

    def test_configured_reports_verified_subcommands_true(self):
        with patch.object(server, "AO_CLI_PATH", sys.executable), patch.object(server, "AO_SEND_CALLER_TOKEN", "secret-token"):
            caps = server.ao_capabilities()
        self.assertTrue(caps["session_list_confirmed"])
        self.assertTrue(caps["session_history_confirmed"])
        self.assertTrue(caps["send_confirmed"])
        self.assertTrue(caps["send_recover_confirmed"])
        self.assertTrue(caps["caller_auth_configured"])
        self.assertFalse(caps["worker_api_confirmed"])
        self.assertFalse(caps["chat_realtime_api_confirmed"])
        self.assertEqual(caps["transport"], "cli_subprocess")

    def test_cli_configured_but_caller_auth_missing_keeps_send_unconfirmed(self):
        # send/send_recover must reflect whether the route is actually reachable by
        # any caller, not merely whether the ao binary exists.
        with patch.object(server, "AO_CLI_PATH", sys.executable), patch.object(server, "AO_SEND_CALLER_TOKEN", ""):
            caps = server.ao_capabilities()
        self.assertTrue(caps["session_list_confirmed"])
        self.assertFalse(caps["send_confirmed"])
        self.assertFalse(caps["send_recover_confirmed"])
        self.assertFalse(caps["caller_auth_configured"])


class RunAoCliTests(unittest.TestCase):
    """run_ao_cli() must never spawn a process when the bridge is unconfigured or
    when the requested argv is outside the hardcoded allowlist, and must enforce
    shell=False, a bounded timeout, and bounded/redacted failure output."""

    def test_refuses_when_not_configured_without_spawning(self):
        with patch.object(server, "AO_CLI_PATH", ""), patch.object(server, "subprocess") as mock_subprocess:
            with self.assertRaises(server.AdapterError) as ctx:
                server.run_ao_cli(["session", "ls", "--all", "--json"], ("session", "ls"))
        self.assertEqual(ctx.exception.status, 503)
        mock_subprocess.run.assert_not_called()

    def test_refuses_disallowed_prefix_without_spawning(self):
        with patch.object(server, "AO_CLI_PATH", sys.executable), patch.object(server, "subprocess") as mock_subprocess:
            with self.assertRaises(server.AdapterError) as ctx:
                server.run_ao_cli(["session", "kill", "mer-3"], ("session", "ls"))
        self.assertEqual(ctx.exception.status, 403)
        mock_subprocess.run.assert_not_called()

    def test_success_calls_with_shell_false_and_exact_argv(self):
        with patch.object(server, "AO_CLI_PATH", r"C:\ao\ao.exe"), patch("server.subprocess.run", return_value=fake_completed(stdout="ok")) as mock_run, \
             patch.object(server, "ao_cli_configured", return_value=True):
            result = server.run_ao_cli(["session", "ls", "--all", "--json"], ("session", "ls"))
        self.assertEqual(result, "ok")
        args, kwargs = mock_run.call_args
        self.assertEqual(args[0], [r"C:\ao\ao.exe", "session", "ls", "--all", "--json"])
        self.assertFalse(kwargs["shell"])
        self.assertEqual(kwargs["timeout"], server.AO_CLI_TIMEOUT_SECONDS)

    def test_timeout_raises_504(self):
        with patch.object(server, "ao_cli_configured", return_value=True), \
             patch("server.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="ao", timeout=8)):
            with self.assertRaises(server.AdapterError) as ctx:
                server.run_ao_cli(["send", "--session", "s1", "--message", "hi"], ("send",))
        self.assertEqual(ctx.exception.status, 504)

    def test_nonzero_exit_raises_502_with_redacted_detail(self):
        with patch.object(server, "ao_cli_configured", return_value=True), \
             patch("server.subprocess.run", return_value=fake_completed(stderr="token=supersecretvalue123 failed", returncode=1)):
            with self.assertRaises(server.AdapterError) as ctx:
                server.run_ao_cli(["session", "ls", "--all", "--json"], ("session", "ls"))
        self.assertEqual(ctx.exception.status, 502)
        self.assertNotIn("supersecretvalue123", str(ctx.exception))

    def test_oserror_raises_502(self):
        with patch.object(server, "ao_cli_configured", return_value=True), \
             patch("server.subprocess.run", side_effect=OSError("no such file")):
            with self.assertRaises(server.AdapterError) as ctx:
                server.run_ao_cli(["session", "ls", "--all", "--json"], ("session", "ls"))
        self.assertEqual(ctx.exception.status, 502)

    def test_output_is_bounded(self):
        huge = "x" * (server.AO_CLI_MAX_OUTPUT_CHARS + 1000)
        with patch.object(server, "ao_cli_configured", return_value=True), \
             patch("server.subprocess.run", return_value=fake_completed(stdout=huge)):
            result = server.run_ao_cli(["session", "ls", "--all", "--json"], ("session", "ls"))
        self.assertEqual(len(result), server.AO_CLI_MAX_OUTPUT_CHARS)


class ValidateAoSessionIdTests(unittest.TestCase):
    def test_accepts_realistic_ids(self):
        for valid in ("mer-3", "unified-dashboard-8", "ao-pilot-issue-1", "a"):
            self.assertEqual(server.validate_ao_session_id(valid), valid)

    def test_rejects_non_string_and_malformed(self):
        for invalid in (None, "", "has space", "../etc/passwd", "semi;colon", "$(rm -rf)", 123, "-leading-hyphen"):
            with self.assertRaises(server.AdapterError) as ctx:
                server.validate_ao_session_id(invalid)
            self.assertEqual(ctx.exception.status, 400)


class ParseBoundedIntTests(unittest.TestCase):
    def test_none_returns_default(self):
        self.assertEqual(server.parse_bounded_int(None, "limit", 1, 50, 10), 10)

    def test_valid_value_within_bounds(self):
        self.assertEqual(server.parse_bounded_int("25", "limit", 1, 50, 10), 25)

    def test_non_integer_raises_400(self):
        with self.assertRaises(server.AdapterError) as ctx:
            server.parse_bounded_int("not-a-number", "limit", 1, 50, 10)
        self.assertEqual(ctx.exception.status, 400)

    def test_out_of_bounds_raises_400(self):
        with self.assertRaises(server.AdapterError) as ctx:
            server.parse_bounded_int("51", "limit", 1, 50, 10)
        self.assertEqual(ctx.exception.status, 400)
        with self.assertRaises(server.AdapterError):
            server.parse_bounded_int("-1", "offset", 0, 100000, 0)


class RedactSecretsTests(unittest.TestCase):
    def test_bearer_token_is_redacted(self):
        text = server.redact_secrets("Authorization: Bearer abcdef1234567890xyz")
        self.assertNotIn("abcdef1234567890xyz", text)
        self.assertIn("[REDACTED]", text)

    def test_key_value_secret_is_redacted(self):
        text = server.redact_secrets('api_key="sk-live-1234567890abcdef"')
        self.assertNotIn("sk-live-1234567890abcdef", text)

    def test_plain_text_is_unchanged(self):
        text = "Please investigate session_manager.go line 142."
        self.assertEqual(server.redact_secrets(text), text)

    def test_empty_string_passthrough(self):
        self.assertEqual(server.redact_secrets(""), "")


class AoSessionsTests(unittest.TestCase):
    """ao_sessions() normalizes `ao session ls --all --json` into a fixed, safe
    field set and preserves unavailable/unknown evidence on failure."""

    def test_success_normalizes_expected_fields_and_redacts(self):
        payload = json.dumps({
            "data": [
                {
                    "id": "unified-dashboard-8", "projectId": "unified-dashboard", "role": "worker",
                    "displayName": "token=sk-shouldnotleak1234567890 bridge work", "status": "idle",
                    "activity": "idle", "harness": "claude-code", "branch": "ao/unified-dashboard-ao-chat-bridge",
                    "isTerminated": False, "lastActivityAt": "2026-10-28T19:00:00Z",
                    "createdAt": "2026-10-28T18:00:00Z", "updatedAt": "2026-10-28T19:00:00Z",
                },
                {"name": "dropped, no id"},
            ]
        })
        with patch.object(server, "ao_cli_configured", return_value=True), \
             patch("server.subprocess.run", return_value=fake_completed(stdout=payload)):
            sessions, ev = server.ao_sessions()
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["id"], "unified-dashboard-8")
        self.assertEqual(sessions[0]["project_id"], "unified-dashboard")
        self.assertNotIn("sk-shouldnotleak1234567890", json.dumps(sessions))
        self.assertEqual(ev["validity"], "valid")
        self.assertIsNotNone(ev["observed_at"])

    def test_invalid_json_is_unknown_not_fabricated(self):
        with patch.object(server, "ao_cli_configured", return_value=True), \
             patch("server.subprocess.run", return_value=fake_completed(stdout="not json {{{")):
            sessions, ev = server.ao_sessions()
        self.assertEqual(sessions, [])
        self.assertEqual(ev["validity"], "unknown")

    def test_unavailable_when_bridge_not_configured(self):
        with patch.object(server, "AO_CLI_PATH", ""):
            sessions, ev = server.ao_sessions()
        self.assertEqual(sessions, [])
        self.assertEqual(ev["validity"], "unavailable")
        self.assertIsNone(ev["observed_at"])


class AoSessionHistoryTests(unittest.TestCase):
    def test_success_returns_redacted_text_with_valid_evidence(self):
        with patch.object(server, "ao_cli_configured", return_value=True), \
             patch.object(server, "AO_CLI_PATH", r"C:\ao\ao.exe"), \
             patch("server.subprocess.run", return_value=fake_completed(stdout="## Turn 1\npassword=hunter2hunter2 was pasted")) as mock_run:
            text, ev = server.ao_session_history("mer-3", 5, 0)
        self.assertNotIn("hunter2hunter2", text)
        self.assertEqual(ev["validity"], "valid")
        args, _ = mock_run.call_args
        self.assertEqual(args[0], [r"C:\ao\ao.exe", "session", "history", "mer-3", "--limit", "5", "--offset", "0"])

    def test_unavailable_when_bridge_not_configured_never_fabricates_history(self):
        with patch.object(server, "AO_CLI_PATH", ""):
            text, ev = server.ao_session_history("mer-3", 10, 0)
        self.assertEqual(text, "")
        self.assertEqual(ev["validity"], "unavailable")
        self.assertIsNone(ev["observed_at"])

    def test_nonzero_exit_is_unavailable_not_fabricated(self):
        with patch.object(server, "ao_cli_configured", return_value=True), \
             patch("server.subprocess.run", return_value=fake_completed(stderr="no such session", returncode=1)):
            text, ev = server.ao_session_history("no-such-session", 10, 0)
        self.assertEqual(text, "")
        self.assertEqual(ev["validity"], "unavailable")


class ValidateClientMessageIdTests(unittest.TestCase):
    def test_accepts_realistic_ids(self):
        for valid in ("correction-42", "a", "A1_b2-C3"):
            self.assertEqual(server.validate_client_message_id(valid), valid)

    def test_rejects_malformed(self):
        for invalid in (None, "", "has space", "semi;colon", 123, "$(rm -rf)"):
            with self.assertRaises(server.AdapterError) as ctx:
                server.validate_client_message_id(invalid)
            self.assertEqual(ctx.exception.status, 400)


class AoSendTests(unittest.TestCase):
    """Controlled send uses AO's documented atomic `--steer` transport with a
    `--client-message-id` for an idempotent round-trip: explicit confirmation,
    validated session id/message/client_message_id, fixed argv, fail-closed with the
    delivery handle preserved when the bridge is unavailable or the call fails."""

    def test_requires_explicit_confirmation(self):
        with self.assertRaises(server.AdapterError) as ctx:
            server.ao_send("mer-3", "hello", False)
        self.assertEqual(ctx.exception.status, 400)

    def test_rejects_invalid_session_id(self):
        with self.assertRaises(server.AdapterError) as ctx:
            server.ao_send("not a valid id", "hello", True)
        self.assertEqual(ctx.exception.status, 400)

    def test_rejects_empty_message(self):
        with self.assertRaises(server.AdapterError) as ctx:
            server.ao_send("mer-3", "   ", True)
        self.assertEqual(ctx.exception.status, 400)

    def test_rejects_overlong_message(self):
        with self.assertRaises(server.AdapterError) as ctx:
            server.ao_send("mer-3", "x" * (server.AO_SEND_MESSAGE_MAX_LEN + 1), True)
        self.assertEqual(ctx.exception.status, 400)

    def test_rejects_malformed_client_message_id(self):
        with self.assertRaises(server.AdapterError) as ctx:
            server.ao_send("mer-3", "hello", True, client_message_id="has space")
        self.assertEqual(ctx.exception.status, 400)

    def test_success_always_uses_atomic_steer_transport(self):
        with patch.object(server, "ao_cli_configured", return_value=True), \
             patch.object(server, "AO_CLI_PATH", r"C:\ao\ao.exe"), \
             patch("server.subprocess.run", return_value=fake_completed(stdout="sent")) as mock_run:
            result = server.ao_send("mer-3", "Focus on the backend.", True, client_message_id="correction-42")
        args, _ = mock_run.call_args
        self.assertEqual(
            args[0],
            [r"C:\ao\ao.exe", "send", "--session", "mer-3", "--steer", "--message", "Focus on the backend.",
             "--client-message-id", "correction-42"],
        )
        self.assertEqual(result["session_id"], "mer-3")
        self.assertEqual(result["client_message_id"], "correction-42")
        self.assertEqual(result["evidence"]["validity"], "valid")

    def test_client_message_id_is_auto_generated_when_omitted(self):
        with patch.object(server, "ao_cli_configured", return_value=True), \
             patch.object(server, "AO_CLI_PATH", r"C:\ao\ao.exe"), \
             patch("server.subprocess.run", return_value=fake_completed(stdout="sent")) as mock_run:
            result = server.ao_send("mer-3", "hello", True)
        self.assertTrue(result["client_message_id"])
        args, _ = mock_run.call_args
        self.assertIn("--client-message-id", args[0])
        self.assertIn(result["client_message_id"], args[0])

    def test_caller_supplied_client_message_id_is_reused_not_replaced(self):
        # Reusing the same id on retry is how the documented transport avoids
        # double delivery; this pins that the adapter never silently generates a
        # new one when the caller supplies one.
        with patch.object(server, "ao_cli_configured", return_value=True), \
             patch.object(server, "AO_CLI_PATH", r"C:\ao\ao.exe"), \
             patch("server.subprocess.run", return_value=fake_completed(stdout="sent")):
            result = server.ao_send("mer-3", "retry after uncertain result", True, client_message_id="retry-handle-7")
        self.assertEqual(result["client_message_id"], "retry-handle-7")

    def test_output_is_redacted(self):
        with patch.object(server, "ao_cli_configured", return_value=True), \
             patch("server.subprocess.run", return_value=fake_completed(stdout="Bearer abcdef1234567890xyz accepted")):
            result = server.ao_send("mer-3", "hello", True)
        self.assertNotIn("abcdef1234567890xyz", result["output"])

    def test_fails_closed_when_bridge_not_configured(self):
        with patch.object(server, "AO_CLI_PATH", ""):
            with self.assertRaises(server.AdapterError) as ctx:
                server.ao_send("mer-3", "hello", True)
        self.assertEqual(ctx.exception.status, 503)

    def test_failure_preserves_client_message_id_for_recovery(self):
        # Bounded failure evidence: on an uncertain/failed send, the delivery handle
        # must be surfaced to the caller so it can recover the outcome instead of
        # blindly resending (which could double-deliver).
        with patch.object(server, "ao_cli_configured", return_value=True), \
             patch("server.subprocess.run", return_value=fake_completed(stderr="transport error", returncode=1)):
            with self.assertRaises(server.AdapterError) as ctx:
                server.ao_send("mer-3", "hello", True, client_message_id="handle-99")
        self.assertIn("handle-99", str(ctx.exception))
        self.assertIn("send/recover", str(ctx.exception))

    def test_timeout_preserves_client_message_id_for_recovery(self):
        with patch.object(server, "ao_cli_configured", return_value=True), \
             patch("server.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="ao", timeout=8)):
            with self.assertRaises(server.AdapterError) as ctx:
                server.ao_send("mer-3", "hello", True, client_message_id="handle-100")
        self.assertEqual(ctx.exception.status, 504)
        self.assertIn("handle-100", str(ctx.exception))


class AoRecoverSendTests(unittest.TestCase):
    """Recovery bridges to `ao send --steer --recover-only --client-message-id` --
    it must never resend the original message, so it cannot double-deliver."""

    def test_requires_explicit_confirmation(self):
        with self.assertRaises(server.AdapterError) as ctx:
            server.ao_recover_send("mer-3", "handle-1", False)
        self.assertEqual(ctx.exception.status, 400)

    def test_rejects_invalid_session_id(self):
        with self.assertRaises(server.AdapterError) as ctx:
            server.ao_recover_send("not a valid id", "handle-1", True)
        self.assertEqual(ctx.exception.status, 400)

    def test_requires_valid_client_message_id(self):
        with self.assertRaises(server.AdapterError) as ctx:
            server.ao_recover_send("mer-3", None, True)
        self.assertEqual(ctx.exception.status, 400)
        with self.assertRaises(server.AdapterError):
            server.ao_recover_send("mer-3", "has space", True)

    def test_success_builds_recover_only_argv_without_message(self):
        with patch.object(server, "ao_cli_configured", return_value=True), \
             patch.object(server, "AO_CLI_PATH", r"C:\ao\ao.exe"), \
             patch("server.subprocess.run", return_value=fake_completed(stdout="recovered: delivered")) as mock_run:
            result = server.ao_recover_send("mer-3", "handle-1", True)
        args, _ = mock_run.call_args
        self.assertEqual(
            args[0],
            [r"C:\ao\ao.exe", "send", "--session", "mer-3", "--steer", "--recover-only", "--client-message-id", "handle-1"],
        )
        self.assertNotIn("--message", args[0])
        self.assertEqual(result["client_message_id"], "handle-1")
        self.assertEqual(result["evidence"]["validity"], "valid")

    def test_fails_closed_when_bridge_not_configured(self):
        with patch.object(server, "AO_CLI_PATH", ""):
            with self.assertRaises(server.AdapterError) as ctx:
                server.ao_recover_send("mer-3", "handle-1", True)
        self.assertEqual(ctx.exception.status, 503)


class RequireAoSendCallerAuthTests(unittest.TestCase):
    """Fail-closed caller-auth gate for send/recover (addresses the independent
    review finding that P-009 shipped send/recover with no caller-auth gate at
    all). Missing/malformed/wrong tokens are always rejected, and an unconfigured
    server token rejects every request rather than letting it through."""

    def test_unconfigured_token_rejects_even_with_a_header(self):
        with patch.object(server, "AO_SEND_CALLER_TOKEN", ""):
            with self.assertRaises(server.AdapterError) as ctx:
                server.require_ao_send_caller_auth({"Authorization": "Bearer anything"})
        self.assertEqual(ctx.exception.status, 503)

    def test_missing_header_is_rejected(self):
        with patch.object(server, "AO_SEND_CALLER_TOKEN", "secret-token"):
            with self.assertRaises(server.AdapterError) as ctx:
                server.require_ao_send_caller_auth({})
        self.assertEqual(ctx.exception.status, 401)

    def test_malformed_header_without_bearer_prefix_is_rejected(self):
        with patch.object(server, "AO_SEND_CALLER_TOKEN", "secret-token"):
            with self.assertRaises(server.AdapterError) as ctx:
                server.require_ao_send_caller_auth({"Authorization": "secret-token"})
        self.assertEqual(ctx.exception.status, 401)

    def test_empty_bearer_value_is_rejected(self):
        with patch.object(server, "AO_SEND_CALLER_TOKEN", "secret-token"):
            with self.assertRaises(server.AdapterError) as ctx:
                server.require_ao_send_caller_auth({"Authorization": "Bearer "})
        self.assertEqual(ctx.exception.status, 401)

    def test_wrong_token_is_rejected(self):
        with patch.object(server, "AO_SEND_CALLER_TOKEN", "secret-token"):
            with self.assertRaises(server.AdapterError) as ctx:
                server.require_ao_send_caller_auth({"Authorization": "Bearer wrong-token"})
        self.assertEqual(ctx.exception.status, 401)

    def test_correct_token_passes_without_raising(self):
        with patch.object(server, "AO_SEND_CALLER_TOKEN", "secret-token"):
            server.require_ao_send_caller_auth({"Authorization": "Bearer secret-token"})

    def test_client_cannot_make_its_own_value_the_expected_token(self):
        # Pins the comparison direction: the header value is always the candidate
        # being checked against the server-held AO_SEND_CALLER_TOKEN, never used as
        # the expected value itself.
        with patch.object(server, "AO_SEND_CALLER_TOKEN", "secret-token"):
            with self.assertRaises(server.AdapterError):
                server.require_ao_send_caller_auth({"Authorization": "Bearer secret-token-but-longer"})


class AoSendCallerAuthHttpTests(unittest.TestCase):
    """HTTP-level coverage for the send/recover caller-auth gate: real requests
    against a loopback-bound server.Handler (default HTTP/1.0, closes per request),
    proving rejection happens before the body is read or AO is ever invoked."""

    @classmethod
    def setUpClass(cls):
        cls.httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=2)

    def _post(self, path, body=b"", headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request("POST", path, body=body, headers=headers or {})
            resp = conn.getresponse()
            data = resp.read()
            return resp.status, (json.loads(data) if data else {})
        finally:
            conn.close()

    def test_send_missing_authorization_header_is_rejected_before_body_read(self):
        with patch.object(server, "AO_SEND_CALLER_TOKEN", "secret-token"), patch.object(server, "ao_send") as mock_send:
            status, _ = self._post("/api/ao/sessions/mer-3/send", body=b'{"message": "hi", "confirm": true}')
        self.assertEqual(status, 401)
        mock_send.assert_not_called()

    def test_send_malformed_authorization_header_is_rejected(self):
        with patch.object(server, "AO_SEND_CALLER_TOKEN", "secret-token"), patch.object(server, "ao_send") as mock_send:
            status, _ = self._post(
                "/api/ao/sessions/mer-3/send",
                body=b'{"message": "hi", "confirm": true}',
                headers={"Authorization": "Basic secret-token"},
            )
        self.assertEqual(status, 401)
        mock_send.assert_not_called()

    def test_send_wrong_token_is_rejected(self):
        with patch.object(server, "AO_SEND_CALLER_TOKEN", "secret-token"), patch.object(server, "ao_send") as mock_send:
            status, _ = self._post(
                "/api/ao/sessions/mer-3/send",
                body=b'{"message": "hi", "confirm": true}',
                headers={"Authorization": "Bearer wrong-token"},
            )
        self.assertEqual(status, 401)
        mock_send.assert_not_called()

    def test_send_unconfigured_caller_token_fails_closed(self):
        with patch.object(server, "AO_SEND_CALLER_TOKEN", ""), patch.object(server, "ao_send") as mock_send:
            status, _ = self._post(
                "/api/ao/sessions/mer-3/send",
                body=b'{"message": "hi", "confirm": true}',
                headers={"Authorization": "Bearer anything"},
            )
        self.assertEqual(status, 503)
        mock_send.assert_not_called()

    def test_send_malformed_json_body_never_reached_when_auth_missing(self):
        # Proves auth is checked strictly before the body is parsed: an
        # invalid-JSON body with no Authorization header must still fail with 401
        # (caller-auth rejection), never a 400 "Invalid JSON request".
        with patch.object(server, "AO_SEND_CALLER_TOKEN", "secret-token"), patch.object(server, "ao_send") as mock_send:
            status, _ = self._post("/api/ao/sessions/mer-3/send", body=b"not json {{{")
        self.assertEqual(status, 401)
        mock_send.assert_not_called()

    def test_recover_missing_authorization_header_is_rejected(self):
        with patch.object(server, "AO_SEND_CALLER_TOKEN", "secret-token"), patch.object(server, "ao_recover_send") as mock_recover:
            status, _ = self._post("/api/ao/sessions/mer-3/send/recover", body=b'{"client_message_id": "h1", "confirm": true}')
        self.assertEqual(status, 401)
        mock_recover.assert_not_called()

    def test_recover_wrong_token_is_rejected(self):
        with patch.object(server, "AO_SEND_CALLER_TOKEN", "secret-token"), patch.object(server, "ao_recover_send") as mock_recover:
            status, _ = self._post(
                "/api/ao/sessions/mer-3/send/recover",
                body=b'{"client_message_id": "h1", "confirm": true}',
                headers={"Authorization": "Bearer wrong"},
            )
        self.assertEqual(status, 401)
        mock_recover.assert_not_called()

    def test_recover_unconfigured_caller_token_fails_closed(self):
        with patch.object(server, "AO_SEND_CALLER_TOKEN", ""), patch.object(server, "ao_recover_send") as mock_recover:
            status, _ = self._post(
                "/api/ao/sessions/mer-3/send/recover",
                body=b'{"client_message_id": "h1", "confirm": true}',
                headers={"Authorization": "Bearer anything"},
            )
        self.assertEqual(status, 503)
        mock_recover.assert_not_called()

    def test_send_valid_token_with_mocked_cli_reaches_ao_send_and_succeeds(self):
        # Positive fixture: a correct token clears the gate and the request reaches
        # the real ao_send() code path end to end over real HTTP; the ao CLI itself
        # is fully mocked at the subprocess boundary, so no real AO send occurs.
        with patch.object(server, "AO_SEND_CALLER_TOKEN", "secret-token"), \
             patch.object(server, "ao_cli_configured", return_value=True), \
             patch.object(server, "AO_CLI_PATH", r"C:\ao\ao.exe"), \
             patch("server.subprocess.run", return_value=fake_completed(stdout="sent")):
            status, payload = self._post(
                "/api/ao/sessions/mer-3/send",
                body=b'{"message": "hello", "confirm": true}',
                headers={"Authorization": "Bearer secret-token", "Content-Type": "application/json"},
            )
        self.assertEqual(status, 202)
        self.assertEqual(payload["session_id"], "mer-3")
        self.assertTrue(payload["client_message_id"])


if __name__ == "__main__":
    unittest.main()
