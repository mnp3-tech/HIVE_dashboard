#!/usr/bin/env python3
"""Windows smoke test for the REAL PowerShellAdapter (read-only; starts only the fixed PowerShell script and nvidia-smi).

  python tools/smoke_system_windows.py            # real adapter, Windows only
  python tools/smoke_system_windows.py --full     # also print disks/USB names (may contain personal labels: do not share unredacted)
  python tools/smoke_system_windows.py --selftest # checker logic against MockAdapter (any OS; proves nothing about Windows)

Prints one line per metric and PASS/FAIL. Exit code 0 only if every rule holds. Never prints tokens or environment.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import hive_system as hs  # noqa: E402


def check(result):
    """Return a list of rule violations (empty = PASS)."""
    bad, items, ev = [], result["items"], result["evidence"]
    for k in ("cpu", "memory", "disk", "gpu", "temperature"):
        m = items[k]
        for f in ("source", "observed_at", "validity", "reason", "value"):
            if f not in m:
                bad.append(f"{k}: missing field {f}")
        if m.get("validity") == "valid":
            if not m.get("source"): bad.append(f"{k}: valid without source")
            if not m.get("observed_at"): bad.append(f"{k}: valid without observed_at")
            if not isinstance(m.get("value"), (int, float)) or isinstance(m.get("value"), bool): bad.append(f"{k}: valid without a numeric value")
        else:
            if m.get("value") is not None: bad.append(f"{k}: value present although not valid")
            if not m.get("reason"): bad.append(f"{k}: unavailable without a reason")
    for k in ("cpu", "memory", "disk"):
        v = items[k].get("value")
        if items[k].get("validity") == "valid" and not (isinstance(v, (int, float)) and 0 <= v <= 100): bad.append(f"{k}: out of 0-100")
    for k in ("gpu", "temperature"):  # only nvidia-smi may make these valid; hardware_present is never telemetry
        if items[k].get("validity") == "valid" and items[k].get("source") != "nvidia-smi": bad.append(f"{k}: valid from a source other than nvidia-smi ({items[k].get('source')})")
    if items["cpu"].get("validity") == "valid" and "PerfOS_Processor" not in str(items["cpu"].get("source")): bad.append("cpu: unexpected source")
    if not ev.get("observed_at") or not ev.get("source"): bad.append("evidence: missing source/observed_at")
    return bad


def main(argv):
    full, selftest = "--full" in argv, "--selftest" in argv
    if selftest:
        raw = {"cpu_percent": 12.0, "mem_total_kb": 1000, "mem_free_kb": 400, "gpus": ["Mock GPU"], "volumes": [{"letter": "C", "drive_type": "Fixed", "size": 100, "free": 40, "bus": "NVMe", "readonly": False}], "pnp": [], "errors": {}}
        os.environ["SystemDrive"] = "C:"
        result = hs.collect_system(adapter=hs.MockAdapter(raw))
    else:
        if os.name != "nt":
            print("FAIL: this smoke test must run on Windows (real adapter). Use --selftest for the checker only.")
            return 2
        result = hs.collect_system(adapter=hs.PowerShellAdapter())
    items = result["items"]
    print(f"adapter: {'MOCK (selftest)' if selftest else 'PowerShellAdapter (real)'}   evidence: {result['evidence']['validity']} @ {result['evidence']['observed_at']} ({result['evidence']['source']})")
    for k in ("cpu", "memory", "disk", "gpu", "temperature"):
        m = items[k]
        print(f"{k:<12} validity={m['validity']:<11} value={m['value']!s:<8} unit={m['unit']}  source={m['source']}  observed_at={m['observed_at']}  reason={m['reason']}")
    print(f"gpu.hardware_present (capability, NOT telemetry): {items['gpu'].get('hardware_present')}")
    print(f"disks_known={items['disks_known']} ({len(items['disks'])} volumes)  usb_known={items['usb_known']} ({len(items['usb'])} devices)")
    if full:
        print(json.dumps({"disks": items["disks"], "usb": items["usb"]}, indent=2))
    bad = check(result)
    print("PASS" if not bad else "FAIL: " + "; ".join(bad))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
