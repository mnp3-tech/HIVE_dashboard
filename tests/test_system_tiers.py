"""Non-blocking, tiered system resources (hive_system.TieredSystem): fast gauges never wait for the slow device inventory,
cached values carry observed_at and freshness, stale values are never presented as fresh, and failures stay honest.
All PowerShell output is mocked; a synchronous executor or real threads with gates make the timing deterministic."""
from __future__ import annotations

import json
import subprocess
import threading
import time
import unittest

import hive_system as hs
from tests.test_system import RAW


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class SyncExecutor:
    def submit(self, fn, *a):
        fn(*a)


def runner_for(fast=None, slow=None, nvidia=None):
    """fast/slow: raw dict, an exception instance, or a callable(argv) returning (code, out)."""
    calls = []

    def run(argv, timeout=hs.PROBE_TIMEOUT_S):
        calls.append(argv[-1] if argv[0] != "nvidia-smi" else "nvidia")
        if argv[0] == "nvidia-smi":
            if nvidia is None:
                raise FileNotFoundError("nvidia-smi")
            return 0, nvidia
        spec = fast if argv == hs.FAST_ARGV else slow
        if isinstance(spec, BaseException):
            raise spec
        if callable(spec):
            return spec(argv)
        return 0, json.dumps(RAW if spec is None else spec)
    run.calls = calls
    return run


def tiered(run, clock=None, executor=None):
    return hs.TieredSystem(runner=run, platform_name="nt", clock=clock or Clock(), now=lambda: "2026-11-05T12:00:00+00:00", executor=executor or SyncExecutor())


class ScriptSplitTests(unittest.TestCase):
    def test_fast_script_keeps_gauge_sources_and_drops_slow_inventory(self):
        for slow_only in ("Get-Partition", "Get-Disk", "Get-PnpDevice", "Win32_VideoController"):
            self.assertNotIn(slow_only, hs.FAST_SCRIPT); self.assertIn(slow_only, hs.SLOW_SCRIPT)
        for gauge_source in ("Win32_PerfFormattedData_PerfOS_Processor", "Win32_OperatingSystem", "Get-Volume"):
            self.assertIn(gauge_source, hs.FAST_SCRIPT)
        self.assertNotIn("Win32_LogicalDisk", hs.FAST_SCRIPT + hs.SLOW_SCRIPT, "disk telemetry meaning is unchanged (Get-Volume)")
        for marker in ("{0}", "%s", "$env:", "$args", "Invoke-Expression", "iex ", "DownloadString", "Start-Process"):
            self.assertNotIn(marker, hs.FAST_SCRIPT + hs.SLOW_SCRIPT)
        self.assertEqual(hs.FAST_ARGV[:6], hs.POWERSHELL_ARGV[:6]); self.assertEqual(hs.PROBE_TIMEOUT_S, 8, "the timeout was not raised")

    def test_disk_gauge_meaning_is_identical_to_the_full_probe(self):
        full = hs.parse_powershell(RAW, "t")
        sysm = tiered(runner_for()).snapshot()
        for k in ("value", "unit", "source", "drive", "free_bytes", "total_bytes"):
            self.assertEqual(sysm["items"]["disk"].get(k), full["disk"].get(k), k)


class TierTests(unittest.TestCase):
    def test_cold_start_answers_at_once_with_unknown_and_never_blocks(self):
        gate = threading.Event()

        def slow_fast(argv):
            gate.wait(5)
            return 0, json.dumps(RAW)
        s = hs.TieredSystem(runner=runner_for(fast=slow_fast, slow=slow_fast), platform_name="nt")
        t0 = time.monotonic()
        first = s.snapshot()
        self.assertLess(time.monotonic() - t0, 0.5, "the first answer must not wait for any probe")
        self.assertEqual(first["tiers"]["fast"]["state"], "pending"); self.assertEqual(first["evidence"]["validity"], "unknown")
        for k in ("cpu", "memory", "disk"):
            self.assertIsNone(first["items"][k]["value"]); self.assertEqual(first["items"][k]["validity"], "unknown")
            self.assertIn("first fast probe in progress", first["items"][k]["reason"])
        gate.set()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and s.snapshot()["tiers"]["fast"]["state"] != "fresh":
            time.sleep(0.02)
        self.assertEqual(s.snapshot()["items"]["cpu"]["value"], 23.0)

    def test_fast_gauges_do_not_wait_for_slow_inventory(self):
        gate = threading.Event()

        def stuck(argv):
            gate.wait(5)
            return 0, json.dumps(RAW)
        s = hs.TieredSystem(runner=runner_for(slow=stuck), platform_name="nt")
        s.snapshot()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and s.snapshot()["tiers"]["fast"]["state"] != "fresh":
            time.sleep(0.02)
        snap = s.snapshot()
        gate.set()
        self.assertEqual(snap["tiers"]["slow"]["state"], "pending")
        self.assertEqual([snap["items"][k]["validity"] for k in ("cpu", "memory", "disk")], ["valid"] * 3)
        self.assertEqual((snap["items"]["disks_known"], snap["items"]["usb_known"], snap["items"]["disks"]), (False, False, []))
        self.assertIn("first slow probe in progress", snap["items"]["inventory_reason"])
        self.assertIsNone(snap["items"]["gpu"]["value"])

    def test_slow_inventory_failure_keeps_fast_gauges_valid(self):
        snap = tiered(runner_for(slow=OSError("Get-PnpDevice exploded"))).snapshot()
        self.assertEqual([snap["items"][k]["validity"] for k in ("cpu", "memory", "disk")], ["valid"] * 3)
        self.assertEqual(snap["tiers"]["slow"]["state"], "failed"); self.assertIn("exploded", snap["tiers"]["slow"]["last_error"])
        self.assertFalse(snap["items"]["disks_known"]); self.assertIn("no slow observation yet", snap["items"]["inventory_reason"])
        self.assertEqual(snap["items"]["gpu"]["validity"], "unavailable")

    def test_fast_timeout_without_history_is_unavailable_with_the_stalled_section(self):
        err = subprocess.TimeoutExpired("powershell", 8, stderr="HIVE_T cpu 300\n")
        snap = tiered(runner_for(fast=err)).snapshot()
        cpu = snap["items"]["cpu"]
        self.assertEqual((cpu["value"], cpu["validity"]), (None, "unavailable"))
        self.assertIn("timed out after 8 s", cpu["reason"]); self.assertIn("stalled in: memory", cpu["reason"])
        self.assertEqual(snap["evidence"]["validity"], "unavailable")

    def test_stale_cache_is_never_presented_as_fresh(self):
        clock = Clock()
        results = [json.dumps(RAW)]

        def flaky(argv):
            if results:
                return 0, results.pop()
            raise subprocess.TimeoutExpired("powershell", 8)
        s = tiered(runner_for(fast=flaky, slow=flaky), clock=clock)
        fresh = s.snapshot()
        self.assertEqual((fresh["items"]["cpu"]["validity"], fresh["items"]["cpu"]["freshness"]), ("valid", "fresh"))
        observed = fresh["items"]["cpu"]["observed_at"]
        clock.t += hs.FAST_REFRESH_S + 1          # refresh due; it fails, the previous observation is kept and still fresh
        mid = s.snapshot()
        self.assertEqual(mid["items"]["cpu"]["validity"], "valid"); self.assertIn("latest attempt failed", mid["tiers"]["fast"]["reason"])
        clock.t += hs.FAST_FRESH_S                # past the fresh window
        old = s.snapshot()
        cpu = old["items"]["cpu"]
        self.assertEqual((cpu["validity"], cpu["freshness"], cpu["observed_at"]), ("stale", "stale", observed))
        self.assertIn("fresh window", cpu["reason"]); self.assertEqual(old["evidence"]["validity"], "stale")
        self.assertEqual(old["tiers"]["fast"]["state"], "stale")

    def test_partial_fast_result_marks_only_the_missing_metric(self):
        snap = tiered(runner_for(fast=dict(RAW, cpu_percent=None, errors={"cpu": "Access denied"}))).snapshot()
        self.assertEqual(snap["items"]["cpu"]["validity"], "unavailable"); self.assertEqual(snap["items"]["cpu"]["reason"], "Access denied")
        self.assertEqual([snap["items"][k]["validity"] for k in ("memory", "disk")], ["valid", "valid"])
        self.assertEqual(snap["evidence"]["validity"], "degraded")

    def test_refreshes_are_single_flight_and_respect_the_interval(self):
        gate = threading.Event()
        counter = {"n": 0}

        def counted(argv):
            counter["n"] += 1
            gate.wait(5)
            return 0, json.dumps(RAW)
        s = hs.TieredSystem(runner=runner_for(fast=counted, slow=counted), platform_name="nt")
        for _ in range(25):
            snap = s.snapshot()
        time.sleep(0.1)
        self.assertEqual(counter["n"], 1, "one fast probe in flight, however many requests arrive; the slow probe waits for it")
        self.assertEqual(snap["tiers"]["slow"]["state"], "not_started"); self.assertIn("starts after the first fast probe", snap["tiers"]["slow"]["reason"])
        gate.set()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and s.snapshot()["tiers"]["slow"]["state"] != "fresh":
            time.sleep(0.02)
        self.assertEqual(counter["n"], 2, "after the first fast result exactly one slow probe ran")
        clock = Clock()
        run = runner_for()
        t = tiered(run, clock=clock)
        t.snapshot(); t.snapshot(); t.snapshot()
        self.assertEqual(run.calls.count(hs.FAST_SCRIPT), 1, "no re-probe inside the refresh interval")
        clock.t += hs.FAST_REFRESH_S + 0.1
        t.snapshot()
        self.assertEqual(run.calls.count(hs.FAST_SCRIPT), 2); self.assertEqual(run.calls.count(hs.SLOW_SCRIPT), 1)

    def test_failed_refresh_backs_off_instead_of_hammering(self):
        clock = Clock()
        run = runner_for(fast=OSError("boom"), slow=OSError("boom"))
        s = tiered(run, clock=clock)
        for _ in range(5):
            s.snapshot()
        self.assertEqual(run.calls.count(hs.FAST_SCRIPT), 1)
        clock.t += hs.FAST_REFRESH_S + 0.1
        s.snapshot()
        self.assertEqual(run.calls.count(hs.FAST_SCRIPT), 2)

    def test_nvidia_is_part_of_the_slow_tier_only(self):
        run = runner_for(nvidia="Mock RTX, 12, 40")
        snap = tiered(run).snapshot()
        self.assertEqual((snap["items"]["gpu"]["value"], snap["items"]["temperature"]["value"]), (12.0, 40.0))
        self.assertEqual(run.calls, [hs.FAST_SCRIPT, hs.SLOW_SCRIPT, "nvidia"])

    def test_compatible_response_shape(self):
        snap = tiered(runner_for()).snapshot()
        self.assertTrue({"cpu", "memory", "disk", "gpu", "temperature", "disks", "usb", "disks_known", "usb_known"} <= set(snap["items"]))
        self.assertTrue({"source", "validity", "observed_at", "reason"} <= set(snap["evidence"]))
        for k in ("cpu", "memory", "disk", "gpu", "temperature"):
            self.assertTrue({"value", "unit", "validity", "source", "observed_at", "reason"} <= set(snap["items"][k]), k)
        self.assertEqual(set(snap["tiers"]), {"fast", "slow"})

    def test_non_windows_runs_nothing_and_answers_immediately(self):
        run = runner_for()
        s = hs.TieredSystem(runner=run, platform_name="posix")
        snap = s.snapshot()
        self.assertEqual(run.calls, []); self.assertEqual(snap["evidence"]["validity"], "unavailable")


if __name__ == "__main__":
    unittest.main()
