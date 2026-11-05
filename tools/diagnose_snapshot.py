#!/usr/bin/env python3
"""Time each read-only probe that /api/dashboard/snapshot runs in sequence, plus a refused loopback connect, and the whole snapshot().

Why: on Windows the snapshot exceeded 10 s although the System Resources probe takes ~4.5 s. This names the slow call(s).
Works on any OS (values differ); read-only; contacts only the loopback endpoints server.py already probes; no tokens printed.
Usage: python tools/diagnose_snapshot.py
"""
from __future__ import annotations

import os
import socket
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("HIVE_API_TOKEN", "")
import server  # noqa: E402


def timed(label, fn, *a):
    t0 = time.monotonic()
    try:
        out = fn(*a)
        err = ""
    except Exception as e:  # report, never crash
        out, err = None, f"  raised {type(e).__name__}: {str(e)[:80]}"
    ms = round((time.monotonic() - t0) * 1000)
    print(f"  {ms:7d} ms  {label}{err}")
    return ms, out


def main():
    rows = []
    core = urlparse(server.CORE_URL)
    t0 = time.monotonic()
    try:
        socket.create_connection((core.hostname, core.port or 80), timeout=10).close(); res = "connected"
    except OSError as e:
        res = f"{type(e).__name__}"
    print(f"  {round((time.monotonic() - t0) * 1000):7d} ms  one raw TCP connect to HIVE Core {core.hostname}:{core.port} -> {res}")
    ms, health = timed("health_probe()", server.health_probe); rows.append(ms)
    ms, ready = timed("ready_probe()", server.ready_probe); rows.append(ms)
    steps = [("fetch_with_evidence('/system')", server.fetch_with_evidence, "/system"), ("project_catalog()", server.project_catalog),
             ("orchestrator_project_registry()", server.orchestrator_project_registry), ("self_evolution_status()", server.self_evolution_status),
             ("task_queue()", server.task_queue), ("worker_registry(ready)", server.worker_registry, ready), ("local_worker_status()", server.local_worker_status),
             ("creator_ops_status()", server.creator_ops_status), ("fetch_with_evidence('/events?limit=50')", server.fetch_with_evidence, "/events?limit=50"),
             ("ao_capabilities()", server.ao_capabilities)]
    for label, fn, *args in steps:
        rows.append(timed(label, fn, *args)[0])
    print(f"  {sum(rows):7d} ms  sum of the individual probes above")
    total, _ = timed("whole snapshot() as the endpoint runs it", server.snapshot)
    print("DONE (diagnostic only). The largest line above is the slow call; slow = most of the total, not the sum of many small ones.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
