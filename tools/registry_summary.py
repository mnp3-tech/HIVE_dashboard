#!/usr/bin/env python3
"""Read-only registry check on the real host (intended for the Windows PC).

Builds the same registry GET /api/registry serves, validates every record against schemas/hive-readonly-v1.schema.json and
prints a summary: connector states, ULTRON status, counts, and for skills only name, version, hash prefix and declared
capabilities (no descriptions, no note content, no paths beyond the configured roots). Executes nothing, writes nothing.
Exit 0 = schema valid and read-only invariants hold; 1 = a check failed (the summary still prints).
Usage: python tools/registry_summary.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("HIVE_API_TOKEN", "")
import hive_registry as hr  # noqa: E402
import server  # noqa: E402


def main():
    reg = server.registry_snapshot()
    problems = hr.validate_registry(reg)
    recs = list(hr.iter_records(reg))
    if not (reg.get("read_only") and reg.get("executes_nothing")):
        problems.append("read_only/executes_nothing flags missing")
    problems += [f"{r['id']}: enabled" for r in recs if r.get("kind") == "catalog_item" and r.get("enabled") is not False]
    problems += [f"{r['id']}: fixture source in live mode" for r in recs if str(r.get("source", "")).startswith("fixture")]
    print(f"registry {reg['schema_version']} generated {reg['generated_at']} mode={reg['mode']}")
    for c in reg["connectors"]:
        print(f"  connector {c['id']:<28} {c['display']:<14} {c.get('reason') or ''}"[:200])
    u = reg["ultron"]
    print(f"  ULTRON {u['display']} state={u['state']} source={u['source']} observed_at={u['observed_at']} reason={u['reason']}"[:240])
    for key in ("agents", "workers", "providers", "capabilities"):
        print(f"  {key:<12} {len(reg[key]['items']):>4}  section={reg[key]['evidence']['display']}")
    print(f"  tasks        {len(reg['tasks']['instances']['items']):>4}  definitions={reg['tasks']['definitions']['evidence']['display']}")
    for key, sec in reg["catalogs"].items():
        print(f"  catalog {key:<10} {len(sec['items']):>4}  section={sec['evidence']['display']}")
    for s in reg["catalogs"]["skills"]["items"]:
        print(f"    skill {s['source']}/{s['source_id']}: {s.get('name')} v={s.get('version') or 'NOT_PROVIDED'} {str(s.get('content_hash'))[:19]} "
              f"caps={','.join(s.get('declared_capabilities') or []) or 'NOT_PROVIDED'} enabled={s['enabled']}"[:220])
    print(f"  proposals    {len(reg['proposals']['items']):>4}  " + ", ".join(f"{p['proposal_id']}={p['display']}" for p in reg["proposals"]["items"]))
    print("PASS" if not problems else "FAIL: " + "; ".join(problems[:10]))
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
