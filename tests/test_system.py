"""P1.1 tests: OS resource adapter and model limits. All OS/provider output is MOCKED.
Real PowerShell/nvidia-smi behaviour is NOT VERIFIED in the Linux container (and not yet on Windows)."""
from __future__ import annotations

import http.client
import json
import subprocess
import sys
import threading
import unittest
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fixture_server  # noqa: E402
import hive_system as hs  # noqa: E402
import server  # noqa: E402

GB = 10 ** 9
RAW = {
    "cpu_percent": 23, "mem_total_kb": 16 * 1024 * 1024, "mem_free_kb": 4 * 1024 * 1024, "gpus": ["Mock GPU"],
    "volumes": [
        {"letter": "C", "label": "OS", "drive_type": "Fixed", "size": 1000 * GB, "free": 400 * GB, "bus": "NVMe", "readonly": False},
        {"letter": "E", "label": "Ext", "drive_type": "Fixed", "size": 2000 * GB, "free": 1310 * GB, "bus": "USB", "readonly": False},
        {"letter": "F", "label": "Stick", "drive_type": "Removable", "size": 32 * GB, "free": 30 * GB, "bus": "USB", "readonly": True},
    ],
    "pnp": [
        {"name": "USB Root Hub (USB 3.0)", "class": "USB", "status": "OK"},
        {"name": "USB Mass Storage Device", "class": "USB", "status": "OK"},
        {"name": "Pixel 8", "class": "WPD", "status": "OK"},
        {"name": "Digital Camera", "class": "Image", "status": "OK"},
    ],
    "temp_deci_kelvin": [3231.5, 3300.0], "errors": {},
}


def run_ok(raw=None, nvidia=None):
    calls = []

    def runner(argv, timeout=hs.PROBE_TIMEOUT_S):
        calls.append(argv)
        if argv[0] == "nvidia-smi":
            if nvidia is None:
                raise FileNotFoundError("nvidia-smi")
            return 0, nvidia
        return 0, json.dumps(RAW if raw is None else raw)
    runner.calls = calls
    return runner


class ParseTests(unittest.TestCase):
    def test_valid_values_come_straight_from_the_os_output(self):
        with patch.dict("os.environ", {"SystemDrive": "C:"}):
            r = hs.parse_powershell(RAW, "2026-11-05T00:00:00+00:00")
        self.assertEqual((r["cpu"]["value"], r["cpu"]["validity"]), (23.0, "valid"))
        self.assertEqual(r["memory"]["value"], 75.0); self.assertEqual(r["memory"]["total_bytes"], 16 * 1024 ** 3)
        self.assertEqual(r["disk"]["value"], 60.0); self.assertEqual(r["disk"]["free_bytes"], 400 * GB); self.assertEqual(r["disk"]["drive"], "C:\\")
        self.assertAlmostEqual(r["temperature"]["value"], 56.85, delta=0.06)  # hottest zone: 3300.0 deci-kelvin = 56.85 C
        self.assertEqual(r["gpu"]["validity"], "unavailable"); self.assertIsNone(r["gpu"]["value"]); self.assertEqual(r["gpu"]["adapters"], ["Mock GPU"])

    def test_disk_kinds_access_and_free_space(self):
        d = {x["id"]: x for x in hs.parse_powershell(RAW)["disks"]}
        self.assertEqual(d["C:\\"]["kind"], "fixed"); self.assertEqual(d["E:\\"]["kind"], "external"); self.assertEqual(d["F:\\"]["kind"], "removable")
        self.assertEqual(d["E:\\"]["total_bytes"], 2000 * GB); self.assertEqual(d["E:\\"]["free_bytes"], 1310 * GB); self.assertEqual(d["E:\\"]["access"], "Read/Write")
        self.assertEqual(d["F:\\"]["access"], "Read-only")

    def test_mtp_ptp_phone_is_never_a_disk_and_says_storage_unavailable(self):
        r = hs.parse_powershell(RAW)
        self.assertFalse(any("Pixel" in str(x) or "Camera" in str(x) for x in r["disks"]))
        phones = [u for u in r["usb"] if u["kind"] == "phone_mtp_ptp"]
        self.assertEqual({p["name"] for p in phones}, {"Pixel 8", "Digital Camera"})
        for p in phones:
            self.assertEqual(p["storage_note"], "Storage metrics unavailable"); self.assertEqual(p["storage_metrics"], "unavailable"); self.assertEqual(p["protocol"], "MTP/PTP")
            self.assertNotIn("total_bytes", p); self.assertNotIn("free_bytes", p)
        self.assertEqual([u["name"] for u in r["usb"] if u["kind"] == "usb_device"], ["USB Mass Storage Device"])  # hub filtered
        self.assertFalse(any("Root Hub" in u["name"] for u in r["usb"]))

    def test_invalid_numbers_become_unknown_never_clamped_or_defaulted(self):
        bad = dict(RAW, cpu_percent=150, mem_total_kb=0, mem_free_kb=1, temp_deci_kelvin=[99999, "x", None, True])
        with patch.dict("os.environ", {"SystemDrive": "C:"}):
            r = hs.parse_powershell(bad)
        for k in ("cpu", "memory", "temperature"):
            self.assertIsNone(r[k]["value"], k); self.assertEqual(r[k]["validity"], "unavailable"); self.assertTrue(r[k]["reason"])
        for junk in (float("nan"), float("inf"), -1, True, "50", None):
            self.assertIsNone(hs.parse_powershell(dict(RAW, cpu_percent=junk))["cpu"]["value"], repr(junk))

    def test_inconsistent_disk_sizes_are_rejected_and_not_used_for_the_disk_gauge(self):
        vols = [{"letter": "C", "drive_type": "Fixed", "size": 100, "free": 500, "bus": "NVMe"}, {"letter": "D", "drive_type": "Fixed", "size": 0, "free": 0},
                {"letter": "", "size": 5, "free": 1}, "garbage", {"letter": "E", "drive_type": "Fixed", "size": "big", "free": 1}]
        with patch.dict("os.environ", {"SystemDrive": "C:"}):
            r = hs.parse_powershell(dict(RAW, volumes=vols))
        self.assertIsNone(r["disk"]["value"]); self.assertEqual(r["disk"]["validity"], "unavailable")
        self.assertTrue(all(d["validity"] == "unavailable" and d["total_bytes"] is None for d in r["disks"]))

    def test_known_flags_distinguish_empty_from_not_returned(self):
        ok = hs.parse_powershell(dict(RAW, volumes=[], pnp=[]))
        self.assertTrue(ok["disks_known"] and ok["usb_known"]); self.assertEqual((ok["disks"], ok["usb"]), ([], []))
        gone = hs.parse_powershell({"cpu_percent": 5, "errors": {"usb": "Access denied", "disks": "Not elevated"}})
        self.assertFalse(gone["disks_known"] or gone["usb_known"])
        self.assertFalse(hs.parse_powershell(dict(RAW, volumes="x", pnp=None))["usb_known"])
        out = hs.collect_system(platform_name="posix"); self.assertFalse(out["items"]["disks_known"] or out["items"]["usb_known"])

    def test_probe_errors_are_reported_as_reasons(self):
        r = hs.parse_powershell({"errors": {"cpu": "Access denied", "temperature": "Not supported"}})
        self.assertEqual(r["cpu"]["reason"], "Access denied"); self.assertEqual(r["temperature"]["reason"], "Not supported")
        self.assertEqual(r["disks"], []); self.assertEqual(r["usb"], [])

    def test_nvidia_fills_gpu_only_from_a_wellformed_line(self):
        r = hs.parse_powershell(RAW)
        hs.apply_nvidia(r, "Mock RTX, 41, 55\n")
        self.assertEqual((r["gpu"]["value"], r["gpu"]["source"]), (41.0, "nvidia-smi"))
        for junk in ("", "garbage", "a,b,c", "n, 101, 50", "n, -5, 50", "n, nan, 50", "only,two"):
            r2 = hs.parse_powershell(RAW); hs.apply_nvidia(r2, junk); self.assertIsNone(r2["gpu"]["value"], junk)


class CollectTests(unittest.TestCase):
    def test_non_windows_reports_unknown_for_everything_and_never_runs_a_process(self):
        called = []
        out = hs.collect_system(runner=lambda *a, **k: called.append(a), platform_name="posix")
        self.assertEqual(called, []); self.assertEqual(out["evidence"]["validity"], "unavailable"); self.assertIn("Windows", out["evidence"]["reason"])
        for k in ("cpu", "memory", "disk", "gpu", "temperature"):
            self.assertIsNone(out["items"][k]["value"]); self.assertEqual(out["items"][k]["validity"], "unavailable")
        self.assertEqual((out["items"]["disks"], out["items"]["usb"]), ([], []))

    def test_windows_path_uses_two_fixed_argvs_and_validates(self):
        runner = run_ok(nvidia="Mock RTX, 12, 40")
        with patch.dict("os.environ", {"SystemDrive": "C:"}):
            out = hs.collect_system(runner=runner, platform_name="nt")
        self.assertEqual(runner.calls[0], hs.POWERSHELL_ARGV); self.assertEqual(runner.calls[1], hs.NVIDIA_ARGV)
        self.assertEqual(out["evidence"]["validity"], "valid"); self.assertEqual(out["items"]["gpu"]["value"], 12.0)

    def test_failures_degrade_to_unavailable_with_reasons(self):
        def boom(exc):
            def r(argv, timeout=0): raise exc
            return r
        for exc, word in [(subprocess.TimeoutExpired("p", 8), "timed out"), (FileNotFoundError("powershell.exe"), "not runnable"), (PermissionError("denied"), "not runnable")]:
            out = hs.collect_system(runner=boom(exc), platform_name="nt")
            self.assertEqual(out["evidence"]["validity"], "unavailable"); self.assertIn(word, out["evidence"]["reason"]); self.assertIsNone(out["items"]["cpu"]["value"])
        for stdout, code in [("not json", 0), ("[1,2]", 0), ("", 0), (json.dumps(RAW), 1)]:
            out = hs.collect_system(runner=lambda argv, timeout=0, s=stdout, c=code: (c, s), platform_name="nt")
            self.assertEqual(out["evidence"]["validity"], "unavailable", stdout[:10]); self.assertIsNone(out["items"]["memory"]["value"])

    def test_partial_data_is_degraded_not_valid(self):
        out = hs.collect_system(runner=run_ok(dict(RAW, cpu_percent=None)), platform_name="nt")
        self.assertEqual(out["evidence"]["validity"], "degraded"); self.assertIsNone(out["items"]["cpu"]["value"]); self.assertEqual(out["items"]["memory"]["validity"], "valid")

    def test_missing_nvidia_is_silent_and_gpu_stays_unknown(self):
        out = hs.collect_system(runner=run_ok(nvidia=None), platform_name="nt")
        self.assertIsNone(out["items"]["gpu"]["value"])

    def test_default_runner_uses_shell_false_fixed_argv_timeout_and_bounded_output(self):
        with patch.object(subprocess, "run", return_value=subprocess.CompletedProcess(["x"], 0, stdout="z" * (hs.MAX_OUTPUT_CHARS + 50), stderr="")) as run:
            code, out = hs.default_runner(hs.POWERSHELL_ARGV)
        kw = run.call_args.kwargs
        self.assertIs(kw["shell"], False); self.assertEqual(kw["timeout"], hs.PROBE_TIMEOUT_S); self.assertLessEqual(len(out), hs.MAX_OUTPUT_CHARS)
        self.assertEqual(run.call_args.args[0][0], "powershell.exe")

    def test_script_text_is_a_constant_with_no_interpolation_points(self):
        for marker in ("{0}", "%s", "$env:", "$args", "Invoke-Expression", "iex ", "DownloadString", "Start-Process"):
            self.assertNotIn(marker, hs.POWERSHELL_SCRIPT)
        self.assertEqual(hs.POWERSHELL_ARGV[0:4], ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy"])

    def test_cache_ttl(self):
        hs._cache.update(at=0.0, value=None); n = []
        runner = lambda argv, timeout=0: (n.append(1), (0, json.dumps(RAW)))[1] if argv[0] != "nvidia-smi" else (_ for _ in ()).throw(FileNotFoundError())
        t = [100.0]
        hs.cached_system(runner, "nt", lambda: t[0]); hs.cached_system(runner, "nt", lambda: t[0] + 1); self.assertEqual(len(n), 1)
        hs.cached_system(runner, "nt", lambda: t[0] + hs.CACHE_TTL_S + 1); self.assertEqual(len(n), 2)
        hs._cache.update(at=0.0, value=None)


class ModelLimitTests(unittest.TestCase):
    def test_always_four_rows_in_fixed_order_unknown_without_any_record(self):
        rows = hs.model_limits([])
        self.assertEqual([r["label"] for r in rows], ["GPT", "CLAUDE", "CODEX", "LOCAL"])
        for r in rows:
            self.assertEqual(r["status"], "UNKNOWN"); self.assertIsNone(r["limit"]); self.assertIsNone(r["available"])
        self.assertEqual(len(hs.model_limits(None)), 4)

    def test_status_rules(self):
        w = [{"provider": "gpt", "model": "m1", "limits": {"limit": 200000, "available": 187000, "basis": "provider", "unit": "tokens"}},
             {"provider": "claude", "limits": {"limit": 200000, "available": 100000, "basis": "estimate"}},
             {"provider": "codex", "model": "m3"}]
        r = {x["provider"]: x for x in hs.model_limits(w)}
        self.assertEqual((r["gpt"]["status"], r["gpt"]["limit"], r["gpt"]["available"]), ("KNOWN", 200000.0, 187000.0))
        self.assertEqual(r["claude"]["status"], "ESTIMATED"); self.assertIn("not provider-confirmed", r["claude"]["reason"])
        self.assertEqual(r["codex"]["status"], "NOT_PROVIDED"); self.assertEqual(r["local"]["status"], "UNKNOWN")

    def test_malformed_limits_are_not_provided_never_known(self):
        for lim in ({"limit": "200K", "basis": "provider"}, {"limit": -1, "basis": "provider"}, {"limit": 10, "available": 20, "basis": "provider"}, {"limit": 10, "basis": "guess"},
                    {"limit": 10}, {"limit": float("nan"), "basis": "provider"}, {"limit": True, "basis": "provider"}, {}, "lots", 5):
            r = hs.model_limits([{"provider": "gpt", "limits": lim}])[0]
            self.assertEqual(r["status"], "NOT_PROVIDED", repr(lim)); self.assertIsNone(r["limit"])

    def test_no_inference_from_model_name_or_other_fields(self):
        r = hs.model_limits([{"provider": "gpt", "model": "gpt-4 200k context", "quota": 5, "limit": 5}])[0]
        self.assertEqual(r["status"], "NOT_PROVIDED"); self.assertIsNone(r["limit"])

    def test_provider_matching_is_symmetric_and_local_is_detected(self):
        w = [{"provider": "unknown", "name": "Claude worker", "limits": {"limit": 1, "basis": "provider"}}, {"id": "lmstudio-local", "provider": "local"}, {"provider": "other"}]
        r = {x["provider"]: x["status"] for x in hs.model_limits(w)}
        self.assertEqual(r, {"gpt": "UNKNOWN", "claude": "KNOWN", "codex": "UNKNOWN", "local": "NOT_PROVIDED"})
        a = hs.model_limits([{"provider": "gpt", "limits": {"limit": 9, "basis": "provider"}}])[0]
        b = hs.model_limits([{"provider": "claude", "limits": {"limit": 9, "basis": "provider"}}])[1]
        self.assertEqual({k: v for k, v in a.items() if k not in ("provider", "label")}, {k: v for k, v in b.items() if k not in ("provider", "label")})

    def test_normalize_workers_passes_only_known_limit_fields(self):
        w = server.normalize_workers([{"id": "w1", "provider": "gpt", "limits": {"limit": 5, "basis": "provider", "evil": "x", "api_key": "sk-secret"}}, {"id": "w2"}])
        self.assertEqual(w[0]["limits"], {"limit": 5, "basis": "provider"}); self.assertNotIn("limits", w[1])


def _serve(handler):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def _get(httpd, path):
    c = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=5)
    c.request("GET", path); r = c.getresponse(); return r.status, json.loads(r.read().decode())


class EndpointTests(unittest.TestCase):
    def test_live_endpoint_on_this_host_is_honest_unknown(self):
        hs._cache.update(at=0.0, value=None)
        httpd = _serve(server.Handler)
        try:
            with patch.object(hs, "os") as fake_os:
                fake_os.name = "posix"; fake_os.environ = {}
                status, body = _get(httpd, "/api/system/resources")
        finally:
            httpd.shutdown(); httpd.server_close(); hs._cache.update(at=0.0, value=None)
        self.assertEqual(status, 200); self.assertEqual(body["evidence"]["validity"], "unavailable")
        self.assertTrue(all(body["items"][k]["value"] is None for k in ("cpu", "memory", "disk", "gpu", "temperature")))

    def test_live_endpoint_serves_mocked_windows_output(self):
        hs._cache.update(at=0.0, value=None)
        httpd = _serve(server.Handler)
        try:
            with patch.object(hs, "default_runner", side_effect=run_ok()), patch.object(hs.os, "name", "nt"):
                status, body = _get(httpd, "/api/system/resources")
        finally:
            httpd.shutdown(); httpd.server_close(); hs._cache.update(at=0.0, value=None)
        self.assertEqual(body["items"]["cpu"]["value"], 23.0)

    def test_endpoint_takes_no_parameters_that_reach_the_probe(self):
        hs._cache.update(at=0.0, value=None); seen = []
        httpd = _serve(server.Handler)
        try:
            with patch.object(hs, "default_runner", side_effect=lambda argv, timeout=0: (seen.append(list(argv)), (0, json.dumps(RAW)))[1] if argv[0] != "nvidia-smi" else (_ for _ in ()).throw(FileNotFoundError())), patch.object(hs.os, "name", "nt"):
                _get(httpd, "/api/system/resources?cmd=calc.exe&path=C:/Windows&argv=x")
        finally:
            httpd.shutdown(); httpd.server_close(); hs._cache.update(at=0.0, value=None)
        self.assertEqual(seen, [hs.POWERSHELL_ARGV])

    def test_fixture_endpoint_is_labelled_fixture_and_phone_is_not_a_disk(self):
        httpd = _serve(fixture_server.FixtureHandler)
        try:
            status, body = _get(httpd, "/api/system/resources"); s2, snap = _get(httpd, "/api/dashboard/snapshot")
        finally:
            httpd.shutdown(); httpd.server_close()
        self.assertTrue(body["fixture_only"]); self.assertEqual(body["evidence"]["validity"], "fixture")
        self.assertFalse(any("Phone" in d["label"] or "Phone" in d["id"] for d in body["items"]["disks"]))
        self.assertEqual([u["storage_note"] for u in body["items"]["usb"] if u["kind"] == "phone_mtp_ptp"], ["Storage metrics unavailable"])
        self.assertEqual([r["status"] for r in snap["model_limits"]["items"]], ["KNOWN", "ESTIMATED", "NOT_PROVIDED", "UNKNOWN"])


if __name__ == "__main__":
    unittest.main()
