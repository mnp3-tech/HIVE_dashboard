"""Tests for the standalone, read-only dashboard runtime fixture."""

from __future__ import annotations

import datetime as dt
import http.client
import json
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fixture_server  # noqa: E402


class FixtureShapeTests(unittest.TestCase):
    def test_bind_validation_accepts_only_literal_ipv4_loopback(self):
        self.assertTrue(fixture_server.validate_bind("127.0.0.1"))
        self.assertFalse(fixture_server.validate_bind("0.0.0.0"))
        self.assertFalse(fixture_server.validate_bind("localhost"))
        self.assertFalse(fixture_server.validate_bind("::1"))

    def test_snapshot_is_deterministic_for_a_supplied_clock(self):
        moment = dt.datetime(2026, 11, 5, 12, 0, tzinfo=dt.timezone.utc)
        snapshot = fixture_server.build_snapshot(moment)
        self.assertEqual(snapshot["environment"], "LOCAL / RUNTIME FIXTURE")
        self.assertEqual(snapshot["received_at"], "2026-11-05T12:00:00Z")
        self.assertEqual(snapshot["core"]["status"], "working")
        self.assertEqual(snapshot["workers"]["evidence"]["validity"], "valid")
        self.assertTrue(any(item["id"] == "ultron" for item in snapshot["workers"]["items"]))


class FixtureHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = fixture_server.LoopbackFixtureServer(("127.0.0.1", 0), fixture_server.FixtureHandler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=2)

    def request(self, method: str, path: str, body: bytes | None = None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            connection.request(method, path, body=body, headers={"Content-Type": "application/json"} if body else {})
            response = connection.getresponse()
            raw = response.read()
            payload = json.loads(raw) if response.getheader("Content-Type", "").startswith("application/json") else raw
            return response.status, payload
        finally:
            connection.close()

    def test_metadata_declares_all_safety_properties(self):
        status, payload = self.request("GET", "/api/fixture/metadata")
        self.assertEqual(status, 200)
        self.assertTrue(payload["fixture"])
        self.assertTrue(payload["read_only"])
        self.assertTrue(payload["loopback_only"])
        self.assertFalse(payload["credentials_loaded"])
        self.assertFalse(payload["external_connections"])
        self.assertFalse(payload["write_routes"])

    def test_current_dashboard_reads_are_available(self):
        for path in (
            "/api/dashboard/snapshot",
            "/api/control/worker-policy",
            "/api/control/capabilities",
            "/api/local-workers/cli-status",
            "/api/ao/sessions",
        ):
            status, payload = self.request("GET", path)
            self.assertEqual(status, 200, path)
            self.assertTrue(payload.get("fixture_only", True), path)

    def test_snapshot_contains_orbit_workers_tasks_events(self):
        status, payload = self.request("GET", "/api/dashboard/snapshot")
        self.assertEqual(status, 200)
        self.assertEqual(len(payload["workers"]["items"]), 4)
        self.assertGreaterEqual(len(payload["tasks"]["items"]), 2)
        self.assertGreaterEqual(len(payload["events"]["items"]), 2)

    def test_chat_history_is_read_only_fixture_data(self):
        status, sessions = self.request("GET", "/api/ao/sessions")
        self.assertEqual(status, 200)
        self.assertEqual(sessions["items"][0]["id"], fixture_server.FIXTURE_SESSION_ID)
        status, history = self.request("GET", "/api/ao/sessions/fixture-hive/history")
        self.assertEqual(status, 200)
        self.assertTrue(history["items"])
        self.assertIn("No provider message was sent", history["items"][0]["text"])

    def test_memory_projection_is_queryable_without_write_access(self):
        status, payload = self.request("GET", "/api/memory/search?project_id=hive-dashboard&q=WONG")
        self.assertEqual(status, 200)
        self.assertTrue(payload["items"])
        self.assertTrue(all(item["project_id"] == "hive-dashboard" for item in payload["items"]))

    def test_static_dashboard_is_served(self):
        status, payload = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"HIVE", payload)

    def test_unknown_api_route_is_not_fabricated(self):
        status, payload = self.request("GET", "/api/not-a-real-fixture-route")
        self.assertEqual(status, 404)
        self.assertEqual(payload["detail"], "Unknown fixture endpoint")

    def test_every_write_method_is_rejected(self):
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            status, payload = self.request(method, "/api/control/dispatch", body=b'{"goal":"must not run"}')
            self.assertEqual(status, 405, method)
            self.assertTrue(payload["read_only"], method)

    def test_unknown_session_is_not_fabricated(self):
        status, payload = self.request("GET", "/api/ao/sessions/not-real/history")
        self.assertEqual(status, 404)
        self.assertEqual(payload["detail"], "Unknown fixture session")

    def test_static_path_traversal_is_rejected(self):
        status, payload = self.request("GET", "/%2e%2e/%2e%2e/Windows/System32/drivers/etc/hosts")
        self.assertEqual(status, 400)
        self.assertEqual(payload["detail"], "Invalid path")


if __name__ == "__main__":
    unittest.main()
