#!/usr/bin/env python3
"""Read-only registry check on the real host (intended for the Windows PC).

Builds the same registry GET /api/registry serves (all parts), validates every record against schemas/hive-readonly-v1.schema.json and
prints a summary: connector states, ULTRON status, counts, and for skills only name, version, hash prefix and declared
capabilities (no descriptions, no note content, no paths beyond the configured roots). Executes nothing, writes nothing.
Exit 0 = schema valid and read-only invariants hold; 1 = a check failed (the summary still prints).
Usage: python tools/registry_summary.py [--uncatalogued]
  --uncatalogued  also list every catalog file that was NOT catalogued (or is in conflict): id, path relative to its root,
                  state and the reason. File content, descriptions and absolute paths are never printed.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("HIVE_API_TOKEN", "")
import hive_registry as hr  # noqa: E402
import server  # noqa: E402


_QUOTED_PATH = re.compile(r"'[^']*[\\/][^']*'")
_DRIVE_PATH = re.compile(r"\b[A-Za-z]:\\[^\s;,']+")


def mask_paths(text):
    """Reasons can carry an absolute path from an OS error; mask it so only the root-relative path is shown."""
    return _DRIVE_PATH.sub("<path>", _QUOTED_PATH.sub("'<path>'", str(text or "")))


def main(argv=()):
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
    u = reg.get("ultron") or {"display": "PART NOT LOADED", "state": "UNKNOWN", "source": "-", "observed_at": None, "reason": "core part did not answer"}
    print(f"  ULTRON {u['display']} state={u['state']} source={u['source']} observed_at={u['observed_at']} reason={u['reason']}"[:240])
    for key in ("agents", "workers", "capabilities"):
        sec = reg.get(key) or {"items": [], "evidence": {"display": "PART NOT LOADED"}}
        print(f"  {key:<12} {len(sec['items']):>4}  section={sec['evidence'].get('display') or 'list (no state of its own)'}")
    prov = (reg.get("providers") or {"items": []})["items"]
    named = [p for p in prov if p.get("observed_workers")]
    print(f"  providers    {len(prov):>4}  catalog entries; runtime: {len(named)} named by a worker record, {len(prov) - len(named)} UNKNOWN "
          "(a catalog entry is not evidence of connectivity)")
    inst = (reg.get("tasks") or {}).get("instances") or {"items": []}
    print(f"  tasks        {len(inst['items']):>4}  (HIVE Core task instances)")
    for key, sec in (reg.get("catalogs") or {}).items():
        print(f"  catalog {key:<11} {len(sec['items']):>4}  section={sec['evidence'].get('display') or 'aggregate (per-root connectors above)'}")
    for part, meta in reg.get("parts", {}).items():
        if meta.get("error"):
            print(f"  part {part}: {meta['error']}")
    for s in ((reg.get("catalogs") or {}).get("skills") or {"items": []})["items"]:
        print(f"    skill {s['source']}/{s['source_id']}: {s.get('name')} v={s.get('version') or 'NOT_PROVIDED'} {str(s.get('content_hash'))[:19]} "
              f"caps={','.join(s.get('declared_capabilities') or []) or 'NOT_PROVIDED'} enabled={s['enabled']}"[:220])
    odd = [r for key in ("skills", "prompts", "bots", "tools") for r in ((reg.get("catalogs") or {}).get(key) or {"items": []})["items"]
           if r.get("display") not in ("OBSERVED", "FIXTURE")]
    print(f"  catalog files not catalogued or in conflict: {len(odd)}" + ("" if not odd or "--uncatalogued" in argv else "  (run with --uncatalogued to list them)"))
    if "--uncatalogued" in argv:
        for r in odd:
            print(f"    {r['display']:<13} {r['id']}  path={r.get('source_path') or '?'}  reason={mask_paths(r.get('reason'))}"[:300])
    props = (reg.get("proposals") or {"items": []})["items"]
    print(f"  proposals    {len(props):>4}  " + ", ".join(f"{p['proposal_id']}={p['status']}" for p in props))
    print("PASS" if not problems else "FAIL: " + "; ".join(problems[:10]))
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
