"""GAP-9 regression: with HIVE Core unreachable, snapshot() must pay for ONE bounded preflight, not one timeout per Core probe.

Windows measurement (owner-reported): ~9 Core probes at ~2 s each made /api/dashboard/snapshot take ~18 s. All Core network access here is
mocked through server.urlopen; nothing contacts a real Core. No Core data is invented: skipped probes report unavailable with a reason.
"""
from __future__ import annotations

import io
import json
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import server


class Resp:
    def __init__(self, obj):
        self.b = json.dumps(obj).encode()

    def read(self, n=-1):
        return self.b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def core_path(req):
    full = req.full_url
    return full[len(server.CORE_URL):] if full.startswith(server.CORE_URL) else None


def make(core_behaviour, delay=0.0):
    """core_behaviour(path) -> object (JSON), or an exception instance to raise. Non-Core URLs (LM Studio/Ollama) fail instantly."""
    calls = []

    def fake(req, timeout=None):
        path = core_path(req)
        if path is None:
            raise URLError(ConnectionRefusedError(111, "refused"))
        calls.append((path, timeout))
        if delay:
            time.sleep(delay)
        out = core_behaviour(path)
        if isinstance(out, BaseException):
            raise out
        return Resp(out)
    fake.calls = calls
    return fake


def refused(path):
    return URLError(ConnectionRefusedError(10061, "No connection could be made because the target machine actively refused it"))


def walk(o):
    if isinstance(o, dict):
        yield o
        for v in o.values():
            yield from walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from walk(v)


class CoreDownTests(unittest.TestCase):
    def snap(self, fake):
        with patch.object(server, "urlopen", fake), patch.object(server, "ao_cli_configured", return_value=False):
            return server.snapshot()

    def test_unreachable_core_costs_one_bounded_preflight_call(self):
        fake = make(refused)
        self.snap(fake)
        self.assertEqual(len(fake.calls), 1, fake.calls)
        self.assertEqual(fake.calls[0], ("/health", server.CORE_PREFLIGHT_TIMEOUT_S))
        self.assertLess(server.CORE_PREFLIGHT_TIMEOUT_S, server.CORE_CALL_TIMEOUT_S)

    def test_snapshot_time_is_bounded_by_one_slow_failure_not_by_the_number_of_probes(self):
        fake = make(refused, delay=0.25)  # each failing Core call would cost 0.25 s; ~9 of them used to cost >2 s
        t0 = time.monotonic()
        self.snap(fake)
        elapsed = time.monotonic() - t0
        self.assertEqual(len(fake.calls), 1)
        self.assertLess(elapsed, 1.0, f"snapshot took {elapsed:.2f} s with Core down")

    def test_skipped_probes_report_unavailable_with_a_reason_and_no_invented_data(self):
        snap = self.snap(make(refused))
        hive = [d for d in walk(snap) if isinstance(d.get("source"), str) and d["source"].startswith("hive:")]
        self.assertTrue(hive, "expected Core-backed evidence items")
        for d in hive:
            self.assertNotEqual(d.get("validity"), "valid", d)
            self.assertTrue(d.get("reason"), d)
        reasons = " ".join(str(d.get("reason")) for d in hive)
        self.assertIn("HIVE Core is unavailable", reasons); self.assertIn("preflight failed", reasons); self.assertIn("skipped", reasons)
        self.assertEqual(snap["adapters"]["hive"]["validity"], "unavailable"); self.assertFalse(snap["adapters"]["hive"]["reachable"])
        for k in ("cpu", "memory", "disk"):
            self.assertIsNone(snap["metrics"][k]["value"], k)
        self.assertEqual(snap["tasks"]["items"], [])

    def test_timeout_at_connection_level_also_trips_the_gate(self):
        fake = make(lambda path: TimeoutError("timed out"))
        self.snap(fake)
        self.assertEqual(len(fake.calls), 1)


class CoreUpTests(unittest.TestCase):
    def snap(self, fake):
        with patch.object(server, "urlopen", fake), patch.object(server, "ao_cli_configured", return_value=False):
            return server.snapshot()

    def test_reachable_core_is_probed_normally(self):
        fake = make(lambda path: {"status": "ok"} if path == "/health" else {})
        self.snap(fake)
        paths = [p for p, _ in fake.calls]
        self.assertGreaterEqual(len(paths), 5, paths); self.assertEqual(paths[0], "/health")
        self.assertEqual(fake.calls[0][1], server.CORE_PREFLIGHT_TIMEOUT_S)
        self.assertTrue(all(t == server.CORE_CALL_TIMEOUT_S for _, t in fake.calls[1:]))

    def test_http_errors_prove_reachability_and_never_trip_the_gate(self):
        for code in (401, 403, 404, 500):
            fake = make(lambda path, c=code: HTTPError(server.CORE_URL + path, c, "x", {}, io.BytesIO(b"{}")))
            self.snap(fake)
            self.assertGreaterEqual(len(fake.calls), 5, f"HTTP {code} must not skip the other probes: {fake.calls}")

    def test_generic_url_error_without_a_socket_error_does_not_trip_the_gate(self):
        fake = make(lambda path: URLError("route not mocked"))
        self.snap(fake)
        self.assertGreaterEqual(len(fake.calls), 5)

    def test_gate_does_not_leak_into_the_next_snapshot_or_into_control_calls(self):
        self.snap(make(refused))
        self.assertIsNone(getattr(server._core_gate, "state", None))
        fake = make(lambda path: {"status": "ok"} if path == "/health" else {})
        self.snap(fake)
        self.assertGreaterEqual(len(fake.calls), 5, "a Core that came back must be probed again on the next snapshot")
        with patch.object(server, "urlopen", fake):  # outside a snapshot: the default timeout, never the preflight one
            fake.calls.clear(); server.core_json("/health")
        self.assertEqual(fake.calls, [("/health", server.CORE_CALL_TIMEOUT_S)])

    def test_posts_are_never_gated(self):
        with server.core_snapshot_scope():
            server._core_gate.state["down"] = "HIVE Core is unavailable: simulated"
            fake = make(lambda path: {"ok": True})
            with patch.object(server, "urlopen", fake):
                server.core_json("/tasks", "POST", {"x": 1}, "key")
        self.assertEqual(len(fake.calls), 1)


if __name__ == "__main__":
    unittest.main()
