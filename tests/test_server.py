"""Unit tests for the unified dashboard adapter contract (server.py).

Runs with the stdlib unittest runner only; no extra dependencies required.
All HIVE Core network access is mocked via server.urlopen.
"""

from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

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


if __name__ == "__main__":
    unittest.main()
