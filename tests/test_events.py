"""P0.2 server-side tests: section 9 event contract and SSE endpoints (mocked upstream)."""
from __future__ import annotations

import http.client
import json
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fixture_server  # noqa: E402
import hive_events  # noqa: E402
import server  # noqa: E402

CONTRACT_KEYS = {"schema_version", "event_id", "timestamp", "source", "role_id", "provider", "model", "task_id", "run_id",
                 "correlation_id", "event_type", "state", "severity", "provenance", "redacted_summary"}


class ContractTests(unittest.TestCase):
    def test_contract_has_all_section9_fields_and_never_invents(self):
        ev = hive_events.contract_event({"timestamp": "2026-11-05T12:00:00Z", "kind": "TASK_ROUTED", "component_id": "FURY"}, {"source": "x"})
        self.assertTrue(CONTRACT_KEYS <= set(ev))
        self.assertIsNone(ev["provider"]); self.assertIsNone(ev["model"]); self.assertIsNone(ev["task_id"])
        self.assertEqual(ev["state"], "UNKNOWN")  # no state supplied -> UNKNOWN, never WORKING
        self.assertEqual(ev["provenance"], {"source": "x"})

    def test_state_mapping_and_unknown_fallback(self):
        for raw, want in [("running", "WORKING"), ("Completed", "IDLE"), ("waiting approval", "WAITING_APPROVAL"), ("in_review", "REVIEW"),
                          ("error", "FAILED"), ("sandbox_violation", "SECURITY_BLOCKED"), ("offline", "OFFLINE"), ("???", "UNKNOWN"), (None, "UNKNOWN"), (5, "UNKNOWN")]:
            self.assertEqual(hive_events.normalize_state(raw), want, raw)

    def test_non_dicts_rejected_and_ids_deterministic(self):
        self.assertIsNone(hive_events.contract_event("x")); self.assertIsNone(hive_events.contract_event(None))
        raw = {"timestamp": "t", "kind": "K", "component_id": "R", "title": "T"}
        self.assertEqual(hive_events.contract_event(raw)["event_id"], hive_events.contract_event(dict(raw))["event_id"])

    def test_summary_redacts_secrets_and_is_bounded(self):
        ev = hive_events.contract_event({"event_id": "1", "title": "Bearer abcdef1234567890 token=hunter2 sk-abcdefghijklmnop " + "x" * 500})
        for leaked in ("abcdef1234567890", "hunter2", "sk-abcdefghijklmnop"):
            self.assertNotIn(leaked, ev["redacted_summary"])
        self.assertLessEqual(len(ev["redacted_summary"]), 160)

    def test_prompt_like_events_withhold_summary_and_extra_redactions(self):
        for t in ("PROMPT_SENT", "LLM_COMPLETION", "CHAIN_OF_THOUGHT", "REASONING_TRACE", "TRANSCRIPT_UPDATE"):
            ev = hive_events.contract_event({"event_id": t, "event_type": t, "title": "private tax return"})
            self.assertIsNone(ev["redacted_summary"], t)
        text = "-----BEGIN RSA PRIVATE KEY-----\nMIIEabc\n-----END RSA PRIVATE KEY----- cookie: sid=abc123 ghp_abcdefghijklmnop xoxb-1234567890-abcdef " + "A" * 48
        out = hive_events.redact_summary(text, 400)
        for leaked in ("MIIEabc", "abc123", "ghp_abcdefghijklmnop", "xoxb-1234567890", "A" * 40):
            self.assertNotIn(leaked, out)

    def test_raw_prompt_fields_are_never_copied_into_the_contract(self):
        ev = hive_events.contract_event({"event_id": "1", "event_type": "X", "prompt": "RAW PROMPT", "chain_of_thought": "THOUGHT", "messages": [{"content": "m"}]})
        self.assertNotIn("RAW PROMPT", json.dumps(ev)); self.assertNotIn("THOUGHT", json.dumps(ev))

    def test_movement_hints_only_when_supplied(self):
        self.assertNotIn("target_node", hive_events.contract_event({"event_id": "1"}))
        self.assertEqual(hive_events.contract_event({"event_id": "1", "target_node": "obsidian"})["target_node"], "obsidian")


class RedactionParityTests(unittest.TestCase):
    """The JS twin (hive-core.js) is checked against the same fixture list in tests/core.test.mjs."""

    def test_shared_cases_match_the_recorded_js_output(self):
        cases = json.loads((Path(__file__).parent / "redaction_cases.json").read_text(encoding="utf-8"))["cases"]
        self.assertGreaterEqual(len(cases), 20)
        for c in cases:
            self.assertEqual(hive_events.redact_summary(c["input"], 160), c["expected"], c["input"][:40])

    def test_display_fields_are_redacted_but_identity_fields_are_not(self):
        ev = hive_events.contract_event({"event_id": "x" * 100, "role_id": "token=abc123", "provider": "secret=zzz", "model": "password=pw", "source": "cookie: sid=1",
                                         "task_id": "123e4567-e89b-12d3-a456-426614174000", "redacted_summary": "secret=abc123"})
        dump = json.dumps(ev)
        for leaked in ("abc123", "zzz", "password=pw", "sid=1"):
            self.assertNotIn(leaked, dump)
        self.assertEqual(ev["task_id"], "123e4567-e89b-12d3-a456-426614174000"); self.assertEqual(len(ev["event_id"]), 80)

    def test_withhold_is_case_insensitive(self):
        for t in ("prompt_sent", "LLMPrompt", "user_message_body", "Chain-Of-Thought", "llm_completion"):
            self.assertIsNone(hive_events.contract_event({"event_id": t, "event_type": t, "title": "private"})["redacted_summary"], t)


class FramingTests(unittest.TestCase):
    def test_frames_status_first_then_each_event_once(self):
        evs = [hive_events.contract_event({"event_id": "b"}), hive_events.contract_event({"event_id": "a"})]  # newest first
        frames = list(hive_events.stream_frames(lambda: (evs, {"validity": "valid"}), 0, 3, lambda _s: None))
        text = b"".join(frames).decode()
        self.assertTrue(text.startswith("event: status"))
        self.assertEqual(text.count("event: hive"), 2)  # 3 cycles, still only 2 events (dedupe)
        self.assertEqual(text.count("event: status"), 3)
        self.assertLess(text.index("id: a"), text.index("id: b"))  # oldest first

    def test_frame_injection_is_neutralised(self):
        frame = hive_events.sse_frame({"x": "a\nb"}, "hive", "id1\nevent: evil").decode()
        self.assertEqual(frame.count("\nevent:"), 1)
        self.assertNotIn("\nevent: evil", frame)
        self.assertEqual(frame.count("\n\n"), 1)


def _serve(handler):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def _get(httpd, path):
    conn = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=5)
    conn.request("GET", path)
    resp = conn.getresponse()
    return resp.status, resp.getheader("Content-Type"), resp.read().decode()


class EndpointTests(unittest.TestCase):
    def test_fixture_stream_is_sse_labelled_fixture_and_bounded(self):
        httpd = _serve(fixture_server.FixtureHandler)
        try:
            status, ctype, body = _get(httpd, "/api/events/stream?cycles=1")
        finally:
            httpd.shutdown(); httpd.server_close()
        self.assertEqual(status, 200); self.assertIn("text/event-stream", ctype)
        data = [json.loads(l[6:]) for l in body.splitlines() if l.startswith("data: ")]
        self.assertEqual(data[0]["validity"], "fixture")
        self.assertTrue(all(d["provenance"]["validity"] == "fixture" for d in data[1:]))
        self.assertTrue(CONTRACT_KEYS <= set(data[1]))

    def test_live_stream_reports_unavailable_core_without_fabricating_events(self):
        fake = ({"items": []}, {"source": "hive:/events", "validity": "unavailable", "observed_at": "2026-11-05T12:00:00Z", "reason": "connection refused"})
        with patch.object(server, "fetch_with_evidence", return_value=fake):
            httpd = _serve(server.Handler)
            try:
                status, ctype, body = _get(httpd, "/api/events/stream?cycles=1")
            finally:
                httpd.shutdown(); httpd.server_close()
        self.assertEqual(status, 200); self.assertIn("text/event-stream", ctype)
        self.assertEqual(body.count("event: hive"), 0)
        status_frame = json.loads([l for l in body.splitlines() if l.startswith("data: ")][0][6:])
        self.assertEqual(status_frame["validity"], "unavailable"); self.assertEqual(status_frame["event_count"], 0)

    def test_live_stream_never_reports_valid_for_untrusted_upstream(self):
        for validity in ("auth_required", "unknown", "stale"):
            fake = ({"items": []}, {"source": "hive:/events", "validity": validity, "observed_at": "2026-11-05T12:00:00Z", "reason": "r"})
            with patch.object(server, "fetch_with_evidence", return_value=fake):
                httpd = _serve(server.Handler)
                try:
                    _s, _c, body = _get(httpd, "/api/events/stream?cycles=1")
                finally:
                    httpd.shutdown(); httpd.server_close()
            status = json.loads([l for l in body.splitlines() if l.startswith("data: ")][0][6:])
            self.assertEqual(status["validity"], validity); self.assertEqual(status["event_count"], 0)

    def test_stream_and_polling_ids_agree_for_the_same_upstream_event(self):
        raw = {"timestamp": "2026-11-05T12:00:00Z", "event_type": "TASK_STARTED", "component_id": "FURY", "title": "t", "source": "bus"}
        self.assertEqual(hive_events.contract_event(raw, {"validity": "valid"})["event_id"], hive_events.contract_event(dict(raw))["event_id"])

    def test_live_stream_normalises_core_events_with_provenance(self):
        fake = ({"items": [{"id": "ev-1", "timestamp": "2026-11-05T12:00:00Z", "event_type": "TASK_STARTED", "status": "running", "component_id": "FURY", "title": "secret=abc123def go"}]},
                {"source": "hive:/events", "validity": "valid", "observed_at": "2026-11-05T12:00:01Z", "reason": None})
        with patch.object(server, "fetch_with_evidence", return_value=fake):
            httpd = _serve(server.Handler)
            try:
                _s, _c, body = _get(httpd, "/api/events/stream?cycles=1")
            finally:
                httpd.shutdown(); httpd.server_close()
        ev = json.loads([l for l in body.splitlines() if l.startswith("data: ")][1][6:])
        self.assertEqual(ev["event_id"], "ev-1"); self.assertEqual(ev["state"], "WORKING")
        self.assertEqual(ev["provenance"]["validity"], "valid"); self.assertNotIn("abc123def", ev["redacted_summary"])


if __name__ == "__main__":
    unittest.main()
