#!/usr/bin/env python3
"""Windows diagnostic: WHY does the system probe finish in the smoke test but time out inside server.py?

Read-only. Runs the same fixed PowerShell probe four ways, 3 runs each, with a LONG diagnostic-only timeout (60 s) so the real
duration is visible. The production timeout (hive_system.PROBE_TIMEOUT_S) is never changed by this tool.
  A  legacy runner      stdin inherited, no flags            (how the probe ran before)
  B  stdin closed       stdin=DEVNULL
  C  current runner     hive_system.default_runner           (stdin closed + no console window)
  D  live server path   server.py started with stdin/stdout NUL (like the Node checker does) and GET /api/system/resources
For every run it prints total time and, from the script's own markers, the cumulative ms at the end of each section
(cpu, memory, gpu, disks, usb), so the slow section is named. Prints no tokens/environment.
Usage: python tools/diagnose_system_probe.py [--runs 3] [--skip-server]
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import hive_system as hs  # noqa: E402

DIAG_TIMEOUT_S = 60


def deltas(cum):
    prev, out = 0, []
    for name in hs.SECTION_ORDER:
        if name in cum:
            out.append(f"{name}={cum[name] - prev}ms")
            prev = cum[name]
    return " ".join(out) or "(no section finished)"


def run_direct(label, **kw):
    t0 = time.monotonic()
    try:
        p = subprocess.run(hs.POWERSHELL_ARGV, shell=False, capture_output=True, text=True, timeout=DIAG_TIMEOUT_S, encoding="utf-8", errors="replace", **kw)
        dt = time.monotonic() - t0
        cum = hs.parse_progress(p.stderr)
        ok = p.returncode == 0 and p.stdout.strip().startswith("{")
        print(f"  {label}: {dt:6.2f} s  exit={p.returncode} json={'yes' if ok else 'NO'}  [{deltas(cum)}]")
        return dt
    except subprocess.TimeoutExpired as e:
        print(f"  {label}: >{DIAG_TIMEOUT_S} s TIMEOUT  [{deltas(hs.parse_progress(e.stderr))}]")
        return None


def run_current():
    t0 = time.monotonic()
    try:
        code, out = hs.default_runner(hs.POWERSHELL_ARGV, timeout=DIAG_TIMEOUT_S)
        dt = time.monotonic() - t0
        cum = (json.loads(out).get("timings_ms") or {}) if out.strip().startswith("{") else {}
        print(f"  C current runner: {dt:6.2f} s  exit={code}  [{deltas(cum)}]")
    except subprocess.TimeoutExpired as e:
        print(f"  C current runner: >{DIAG_TIMEOUT_S} s TIMEOUT  [{deltas(hs.parse_progress(e.stderr))}]")


def run_server(port, runs):
    srv = subprocess.Popen([sys.executable, "server.py", "--port", str(port)], cwd=str(ROOT), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           env={**os.environ, "HIVE_API_TOKEN": ""})
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2).read(1)
                break
            except OSError:
                time.sleep(0.15)
        for i in range(runs):
            t0 = time.monotonic()
            try:
                with urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}/api/system/resources", headers={"Connection": "close"}), timeout=40) as r:
                    j = json.loads(r.read(2_000_000))
                dt = time.monotonic() - t0
                ev = j["evidence"]
                print(f"  D live server #{i + 1}: {dt:6.2f} s  evidence={ev['validity']} probe_ms={ev.get('probe_ms')} timings={ev.get('probe_timings_ms')} completed={ev.get('probe_completed')} stalled_in={ev.get('probe_stalled_in')}")
            except Exception as e:  # report, never crash
                print(f"  D live server #{i + 1}: request failed after {time.monotonic() - t0:.1f} s: {type(e).__name__}: {str(e)[:100]}")
            time.sleep(hs.CACHE_TTL_S + 1)  # let the 5 s cache expire so every request re-probes
    finally:
        srv.kill()


def main(argv):
    if os.name != "nt":
        print("FAIL: run this on the Windows PC (it needs powershell.exe).")
        return 2
    runs = int(argv[argv.index("--runs") + 1]) if "--runs" in argv else 3
    print(f"production probe timeout = {hs.PROBE_TIMEOUT_S} s (unchanged); diagnostic timeout = {DIAG_TIMEOUT_S} s")
    print("A legacy runner (stdin inherited, no flags)"); [run_direct("A legacy", stdin=None) for _ in range(runs)]
    print("B stdin closed"); [run_direct("B devnull", stdin=subprocess.DEVNULL) for _ in range(runs)]
    print("C current runner"); [run_current() for _ in range(runs)]
    if "--skip-server" not in argv:
        print("D live server path (server.py with stdin/stdout NUL)"); run_server(4196, runs)
    print("DONE (diagnostic only; nothing here is a PASS/FAIL of the dashboard)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
