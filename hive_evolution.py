"""Self-evolution v1 (EVOLVE): proposals and sandbox/fixture experiments only.

Pipeline: OBSERVE -> MEASURE -> DETECT -> HYPOTHESIZE -> PROPOSE -> SANDBOX_FIXTURE_TEST -> COMPARE_WITH_BASELINE -> HUMAN_REVIEW
          -> VERSION -> MONITOR -> ROLLBACK.
In this phase nothing reaches VERSION: no branch, patch, deployment, permission change, external write or autonomous execution.
A proposal's status changes only through a reviewed commit to docs/hive/proposals/proposals.json. Experiments are pure functions
over committed synthetic datasets (experiments/datasets/*.json); their results describe the dataset, not production.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import hive_registry as hr

PROPOSALS_PATH = hr.ROOT / "docs" / "hive" / "proposals" / "proposals.json"
DATASETS = hr.ROOT / "experiments" / "datasets"
DOMAINS = ("agent_routing", "worker_assignment", "task_decomposition", "prompts", "skills", "tools", "connector_reliability", "system_latency",
           "system_stability", "cost", "error_rate", "human_intervention", "ultron_policies")
STAGES = ("OBSERVE", "MEASURE", "DETECT", "HYPOTHESIZE", "PROPOSE", "SANDBOX_FIXTURE_TEST", "COMPARE_WITH_BASELINE", "HUMAN_REVIEW",
          "VERSION", "MONITOR", "ROLLBACK")
STATUSES = hr.PROPOSAL_STATUSES
HUMAN = hr.HUMAN_STATUSES
LOG_MAX = 512 * 1024


# ------------------------------------------------------------------ experiments (pure functions)
def _good(worker, task):
    return worker is not None and worker["heartbeat"] == "live" and set(task["required_capabilities"]) <= set(worker["capabilities"])


def routing_metrics(data, policy):
    workers = {w["id"]: w for w in data["workers"]}
    good = bad = unassigned = changed = 0
    for t in data["tasks"]:
        explicit = t.get("preferred_worker")
        pick = explicit
        if policy == "capability_freshness_match" and not _good(workers.get(explicit), t):
            pick = next((w["id"] for w in sorted(data["workers"], key=lambda w: w["id"]) if _good(w, t)), None)
        changed += pick != explicit
        if pick is None:
            unassigned += 1
        elif _good(workers.get(pick), t):
            good += 1
        else:
            bad += 1
    n = len(data["tasks"])
    return {"good_assignment_rate": round(good / n, 3), "bad_assignments": bad, "unassigned": unassigned, "assignments_changed": changed}


def _connector_states(probe_ok, policy):
    """Displayed up/down per tick and the number of probe calls. 'two_failures_with_backoff' needs 2 consecutive failures to
    show OFFLINE and, while OFFLINE, probes only every second tick (a skipped tick keeps the last state)."""
    states, probes, fails, up, skip = [], 0, 0, True, False
    for ok in probe_ok:
        if policy == "two_failures_with_backoff" and not up and skip:
            skip = False
        else:
            probes += 1
            fails = 0 if ok else fails + 1
            up = ok if policy == "single_failure" else (ok or fails < 2)
            skip = not up
        states.append(up)
    return states, probes


def connector_metrics(data, policy):
    false_off = missed = probes = 0
    delays, undetected = [], 0
    for c in data["connectors"]:
        states, calls = _connector_states(c["probe_ok"], policy)
        probes += calls
        truth = c["truly_up"]
        false_off += sum(1 for s, t in zip(states, truth) if not s and t)
        missed += sum(1 for s, t in zip(states, truth) if s and not t)
        i = 0
        while i < len(truth):  # one detection delay per real outage
            if truth[i]:
                i += 1
                continue
            start = i
            while i < len(truth) and not truth[i]:
                i += 1
            hit = next((k for k in range(start, i) if not states[k]), None)
            if hit is None:
                undetected += 1
            else:
                delays.append(hit - start)
    return {"false_offline_ticks": false_off, "missed_outage_ticks": missed,
            "mean_detection_delay_ticks": round(sum(delays) / len(delays), 2) if delays else None, "undetected_outages": undetected, "probe_calls": probes}


def staleness_metrics(data, threshold_s):
    events = sorted(data["ultron_event_times_s"])
    active = [False] * data["horizon_s"]
    for a, b in data["truly_active_intervals_s"]:
        for t in range(a, min(b, data["horizon_s"])):
            active[t] = True
    false_active = false_stale = 0
    j, last = 0, None
    for t in range(data["horizon_s"]):
        while j < len(events) and events[j] <= t:
            last = events[j]
            j += 1
        shown = last is not None and t - last <= threshold_s
        false_active += shown and not active[t]
        false_stale += (not shown) and active[t]
    return {"false_active_s": false_active, "false_stale_s": false_stale}


EXPERIMENTS = {
    "EXP-ROUTING-1": {"domain": "agent_routing", "dataset": "routing.json", "fn": routing_metrics,
                      "baseline": ("explicit_assignment_only", "explicit_assignment_only"),
                      "candidates": [("capability_freshness_match", "capability_freshness_match")],
                      "directions": {"good_assignment_rate": "higher", "bad_assignments": "lower", "unassigned": "lower", "assignments_changed": "lower"}},
    "EXP-CONNECTOR-1": {"domain": "connector_reliability", "dataset": "connector.json", "fn": connector_metrics,
                        "baseline": ("single_failure", "single_failure"), "candidates": [("two_failures_with_backoff", "two_failures_with_backoff")],
                        "directions": {"false_offline_ticks": "lower", "missed_outage_ticks": "lower", "mean_detection_delay_ticks": "lower",
                                       "undetected_outages": "lower", "probe_calls": "lower"}},
    "EXP-STALENESS-1": {"domain": "ultron_policies", "dataset": "staleness.json", "fn": staleness_metrics,
                        "baseline": ("threshold_120s", 120), "candidates": [("threshold_60s", 60), ("threshold_180s", 180)],
                        "directions": {"false_active_s": "lower", "false_stale_s": "lower"}},
}


def _compare(base, cand, directions):
    rows = []
    for metric, direction in directions.items():
        b, c = base.get(metric), cand.get(metric)
        if b is None or c is None:
            better = None
        else:
            better = (c > b) if direction == "higher" else (c < b) if c != b else None
        rows.append({"metric": metric, "direction": direction, "baseline": b, "candidate": c, "delta": None if b is None or c is None else round(c - b, 3),
                     "better": better})
    return rows


def run_experiments(datasets=DATASETS, observed=None, source="experiment:fixture-dataset"):
    """Deterministic baseline-vs-candidate runs on committed synthetic datasets. Nothing is adopted."""
    observed = observed or hr.utc_iso(datetime.now(timezone.utc))
    out = []
    for exp_id, spec in EXPERIMENTS.items():
        path = Path(datasets) / spec["dataset"]
        try:
            raw = path.read_bytes()
            if len(raw) > LOG_MAX:
                raise ValueError("dataset too large")
            data = json.loads(raw.decode("utf-8"))
            base_name, base_param = spec["baseline"]
            base = spec["fn"](data, base_param)
            cands = [{"name": n, "params": p if not callable(p) else None, "metrics": spec["fn"](data, p),
                      "comparison": None} for n, p in spec["candidates"]]
            for c in cands:
                c["comparison"] = _compare(base, c["metrics"], spec["directions"])
        except (OSError, ValueError, KeyError, TypeError) as error:
            out.append(hr.envelope("experiment", f"experiment:{exp_id}", source, None, "not_verified", f"experiment could not run: {error}", source_id=exp_id,
                                   experiment_id=exp_id, domain=spec["domain"], dataset_path=f"experiments/datasets/{spec['dataset']}", dataset_sha256=None,
                                   baseline=None, candidates=[], fixture_only=True, adopted=False))
            continue
        first = cands[0]["comparison"]
        wins = sum(1 for r in first if r["better"] is True)
        losses = sum(1 for r in first if r["better"] is False)
        out.append(hr.envelope("experiment", f"experiment:{exp_id}", source, observed, "fixture",
                               f"Fixture experiment on {data.get('dataset_id')}: first candidate better on {wins}, worse on {losses} of {len(first)} metric(s). "
                               "Describes the synthetic dataset only; nothing is adopted.", source_id=exp_id, experiment_id=exp_id, domain=spec["domain"],
                               dataset_path=f"experiments/datasets/{spec['dataset']}", dataset_sha256=hr.sha256_bytes(raw),
                               baseline={"name": base_name, "params": base_param, "metrics": base}, candidates=cands, fixture_only=True, adopted=False))
    return out


# ------------------------------------------------------------------ proposals v2
def _stage(status, experiment):
    if status in ("STALE", "EXPIRED"):
        return "HUMAN_REVIEW" if experiment else "PROPOSE"
    if experiment is not None and experiment.get("validity") in ("valid", "fixture"):
        return "HUMAN_REVIEW"  # sandbox test and baseline comparison done; waiting for (or after) human review
    return "PROPOSE"


def proposal_records(path=PROPOSALS_PATH, acceptance=hr.ACCEPTANCE_PATH, experiments=None, now=None):
    """Proposals with evidence checks: a GAP row (exact sha256) or an experiment dataset (exact sha256). Display only."""
    now = now or datetime.now(timezone.utc)
    observed = hr.utc_iso(now)
    experiments = experiments if experiments is not None else run_experiments(observed=observed)
    by_exp = {e["experiment_id"]: e for e in experiments}
    try:
        if Path(path).stat().st_size > LOG_MAX:
            raise ValueError("proposal log larger than 512 KB")
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        rows = {}
        for line in Path(acceptance).read_text(encoding="utf-8").splitlines():
            m = re.match(r"^\| (GAP-\d+) \|", line)
            if m:
                rows[m.group(1)] = line
    except (OSError, ValueError) as error:
        return hr.section([], "local:proposal-log", None, "inaccessible", f"Proposal log unreadable: {error}")
    items = []
    for p in (doc.get("proposals") if isinstance(doc, dict) else None) or []:
        if not isinstance(p, dict) or not p.get("proposal_id"):
            continue
        evidence = [e for e in p.get("evidence") or [] if isinstance(e, dict)]
        exp = by_exp.get(p.get("experiment_id")) if p.get("experiment_id") else None
        status, validity, reason = (p.get("status") if p.get("status") in HUMAN else "PENDING_HUMAN_REVIEW"), "valid", "Evidence matches. Display only: no status triggers any change."
        for ev in evidence:
            if ev.get("type") == "gap_row":
                row = rows.get(ev.get("ref"))
                if row is None or hr.sha256_text(row) != ev.get("sha256"):
                    status, validity, reason = "STALE", "stale", f"{ev.get('ref')} row missing or changed since the proposal was written; re-review required"
            elif ev.get("type") == "experiment":
                if exp is None or exp.get("dataset_sha256") != ev.get("sha256"):
                    status, validity, reason = "STALE", "stale", f"experiment {ev.get('ref')} dataset changed or did not run; re-run and re-review"
        expires = hr.parse_ts(p.get("expires_at"))
        if validity == "valid" and (expires is None or expires < now):
            status, validity, reason = "EXPIRED", "stale", "proposal expired"
        rollback = p.get("rollback") if isinstance(p.get("rollback"), dict) else {}
        metrics = [m for m in p.get("success_metrics") or [] if isinstance(m, dict) and m.get("metric")]
        met = None
        if exp is not None and exp.get("candidates"):
            comp = {r["metric"]: r for r in exp["candidates"][0]["comparison"]}
            met = [{"metric": m["metric"], "met": comp.get(m["metric"], {}).get("better") is True} for m in metrics]
        domain = p.get("domain") if p.get("domain") in DOMAINS else None
        items.append(hr.envelope("proposal", f"proposal:{p['proposal_id']}", "local:proposal-log (docs/hive/proposals/proposals.json)", observed, validity, reason,
                                 source_id=str(p["proposal_id"])[:80], correlation_id=p.get("correlation_id") if isinstance(p.get("correlation_id"), str) else None,
                                 proposal_id=str(p["proposal_id"])[:80], domain=domain or "unclassified", gap_id=next((e.get("ref") for e in evidence if e.get("type") == "gap_row"), None),
                                 baseline=hr.safe_text(p.get("baseline"), 300), candidate=hr.safe_text(p.get("candidate"), 300),
                                 evidence=[{"type": hr.safe_text(e.get("type"), 20), "ref": hr.safe_text(e.get("ref"), 120), "sha256": e.get("sha256") if isinstance(e.get("sha256"), str) else None}
                                           for e in evidence][:10],
                                 hypothesis=hr.safe_text(p.get("hypothesis"), 400), problem=hr.safe_text(p.get("problem"), 400), expected_benefit=hr.safe_text(p.get("expected_benefit"), 300),
                                 success_metrics=[{"metric": hr.safe_text(m.get("metric"), 60), "direction": m.get("direction") if m.get("direction") in ("higher", "lower") else None,
                                                   "target": hr.safe_text(m.get("target"), 60)} for m in metrics][:10],
                                 success_met=met, experiment_id=p.get("experiment_id") if isinstance(p.get("experiment_id"), str) else None,
                                 affected_area=hr.safe_text(p.get("affected_area"), 120), affected_files=hr._str_list(p.get("affected_files")) or [],
                                 risk=p.get("risk") if p.get("risk") in hr.RISKS else "unclassified", required_permissions=hr._str_list(p.get("required_permissions")) or [],
                                 test_plan=hr._str_list(p.get("test_plan")) or [], rollback_plan=hr.safe_text(rollback.get("plan"), 300), rollback_ref=hr.safe_text(rollback.get("ref"), 80),
                                 status=status, stage=_stage(status, exp), proposal_only=True, applied=False,
                                 created_at=p.get("created_at") if isinstance(p.get("created_at"), str) else None,
                                 expires_at=p.get("expires_at") if isinstance(p.get("expires_at"), str) else None))
    return hr.section(items, "local:proposal-log", observed, "valid", f"{len(items)} proposal(s); status changes only through a reviewed commit to the log.")


def domain_coverage(proposals, experiments):
    """Every domain is listed. A domain without evidence has no proposal: insufficient evidence means no-op, not an invented proposal."""
    rows = []
    for d in DOMAINS:
        p = [x["proposal_id"] for x in proposals if x.get("domain") == d]
        e = [x["experiment_id"] for x in experiments if x.get("domain") == d]
        rows.append({"domain": d, "proposals": p, "experiments": e, "note": None if p or e else "no proposal: insufficient evidence (no-op)"})
    return rows


def read_evolution(path=PROPOSALS_PATH, acceptance=hr.ACCEPTANCE_PATH, now=None, datasets=DATASETS):
    now = now or datetime.now(timezone.utc)
    observed = hr.utc_iso(now)
    experiments = run_experiments(datasets, observed)
    proposals = proposal_records(path, acceptance, experiments, now)
    return {"proposals": proposals,
            "experiments": hr.section(experiments, "experiment:fixture-dataset", observed, "fixture",
                                      "Sandbox/fixture experiments on synthetic datasets; results are not production evidence and nothing is adopted."),
            "evolution": {"domains": domain_coverage(proposals["items"], experiments), "stages": list(STAGES),
                          "rules": ["no automatic branch, patch, deployment, permission change, external write or execution",
                                    "status changes only through a reviewed commit to the proposal log",
                                    "VERSION / MONITOR / ROLLBACK stages are not reached in this phase"]}}
