"""P1.3 control plane (read-only): agent registry, lifecycle, ULTRON observations, Internet probes, self-evolution v1.

HIVE Core is mocked through an injected fetch; Internet probes use a fake opener (no network); experiments run on the committed
synthetic datasets. Every test checks an honesty or safety property of the observation-and-proposal phase.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError

import fixture_server
import hive_control as hc
import hive_evolution as ev
import hive_probes as hp
import hive_registry as hr

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 5, 12, 0, 0, tzinfo=timezone.utc)


def iso(seconds_ago):
    return (NOW - timedelta(seconds=seconds_ago)).isoformat().replace("+00:00", "Z")


def fetch_for(routes, unavailable=()):
    def fetch(path):
        key = path.split("?")[0]
        if key in routes and key not in unavailable:
            return routes[key], {"source": f"hive:{path}", "observed_at": iso(0), "validity": "valid", "reason": None}
        return None, {"source": f"hive:{path}", "observed_at": None, "validity": "unavailable", "reason": "HIVE Core is unavailable: refused"}
    return fetch


def core(events=(), workers=(), tasks=(), down=False, agents_config=None):
    routes = {"/health": {"status": "ok"}, "/events": {"items": list(events)}, "/workers": {"items": list(workers)}, "/tasks": {"items": list(tasks)}}
    return hr.read_core(fetch_for(routes, ("/health", "/events", "/workers", "/tasks") if down else ()), lambda s: str(s).lower(), lambda: NOW, None, agents_config)


def profiles(result):
    return {p["agent_id"]: p for p in result["agent_registry"]["items"]}


class AgentRegistryTests(unittest.TestCase):
    def test_documented_only_agent_is_never_active(self):
        p = profiles(core())
        evolve = p["EVOLVE"]
        self.assertEqual((evolve["status"], evolve["lifecycle"], evolve["display"]), ("CONFIGURED", "CONFIGURED", "NOT_VERIFIED"))
        self.assertIn("Not active", evolve["reason"])
        for aid in ("FURY", "SHURI", "THOR", "VISION", "FALCON", "UATU", "ULTRON", "EVOLVE"):
            self.assertNotIn(p[aid]["lifecycle"], ("HEALTHY", "DEGRADED"), aid)

    def test_disabled_and_proposed_agents_stay_inert_with_nothing_invented(self):
        p = profiles(core())
        self.assertEqual((p["JARVIS"]["status"], p["JARVIS"]["lifecycle"]), ("DISABLED", "DISABLED"))
        bw = p["BLACK_WIDOW"]
        self.assertEqual((bw["status"], bw["lifecycle"], bw["display"]), ("PROPOSED", "PROPOSED", "NOT_VERIFIED"))
        for f in hc.LIST_FIELDS:
            self.assertEqual(bw[f], [], f); self.assertIn(f, bw["not_provided"])
        self.assertIsNone(bw["role"])

    def test_observed_agent_is_healthy_only_on_fresh_trusted_evidence(self):
        p = profiles(core([{"event_id": "e", "role_id": "FURY", "state": "working", "timestamp": iso(5), "task_id": "t1", "correlation_id": "c1"}]))
        fury = p["FURY"]
        self.assertEqual((fury["status"], fury["lifecycle"], fury["display"], fury["task_id"], fury["correlation_id"]), ("OBSERVED", "HEALTHY", "OBSERVED", "t1", "c1"))
        self.assertEqual(fury["observed_at"], iso(5))

    def test_stale_and_untrusted_observations(self):
        p = profiles(core([{"event_id": "a", "role_id": "THOR", "state": "working", "timestamp": iso(500)},
                           {"event_id": "b", "role_id": "VISION", "state": "working", "timestamp": iso(-3600)}]))
        self.assertEqual((p["THOR"]["lifecycle"], p["THOR"]["display"], p["THOR"]["status"]), ("UNKNOWN", "STALE", "CONFIGURED"))
        self.assertEqual((p["VISION"]["lifecycle"], p["VISION"]["display"]), ("UNKNOWN", "UNVERIFIED"))

    def test_conflicting_role_is_flagged(self):
        p = profiles(core([{"event_id": "a", "role_id": "FALCON", "state": "idle", "timestamp": iso(5), "role": "Research"}]))
        self.assertEqual(p["FALCON"]["display"], "CONFLICT"); self.assertIn("role conflict", p["FALCON"]["reason"])
        same = profiles(core([{"event_id": "a", "role_id": "FURY", "state": "idle", "timestamp": iso(5), "role": "planning"}]))
        self.assertEqual(same["FURY"]["display"], "OBSERVED", "matching role (case-insensitive) is not a conflict")

    def test_undocumented_observed_identity_is_discovered(self):
        p = profiles(core([{"event_id": "a", "role_id": "WATCHER_X", "state": "idle", "timestamp": iso(5)}]))
        w = p["WATCHER_X"]
        self.assertEqual((w["status"], w["lifecycle"], w["role"], w["classification"]), ("OBSERVED", "DISCOVERED", None, "UNKNOWN"))

    def test_primary_secondary_is_always_unknown(self):
        res = core([{"event_id": "a", "role_id": "FURY", "state": "idle", "timestamp": iso(5)}])
        self.assertTrue(all(p["classification"] == "UNKNOWN" for p in res["agent_registry"]["items"]))
        cfg = json.loads(hc.AGENTS_CONFIG_PATH.read_text(encoding="utf-8"))
        self.assertTrue(all(a["classification"] == "UNKNOWN" for a in cfg["agents"]))

    def test_missing_and_duplicate_agent_sources(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            res = core([{"event_id": "a", "role_id": "FURY", "state": "idle", "timestamp": iso(5)}], agents_config=str(tmp / "missing.json"))
            self.assertEqual(res["agent_registry"]["evidence"]["display"], "UNAVAILABLE")
            self.assertEqual([p["lifecycle"] for p in res["agent_registry"]["items"]], ["DISCOVERED"], "observed identities still listed")
            dup = tmp / "dup.json"
            dup.write_text(json.dumps({"agents": [{"agent_id": "FURY", "configured_status": "CONFIGURED"}, {"agent_id": "fury", "configured_status": "CONFIGURED"}]}), encoding="utf-8")
            items = core(agents_config=str(dup))["agent_registry"]["items"]
            self.assertEqual([p["display"] for p in items], ["CONFLICT", "CONFLICT"]); self.assertEqual(len({p["id"] for p in items}), 2)
            bad = tmp / "bad.json"; bad.write_text("{nope", encoding="utf-8")
            self.assertEqual(core(agents_config=str(bad))["agent_registry"]["evidence"]["display"], "NOT_VERIFIED")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_core_down_makes_configured_agents_unknown_not_offline(self):
        p = profiles(core(down=True))
        self.assertEqual((p["FURY"]["lifecycle"], p["FURY"]["display"]), ("UNKNOWN", "OFFLINE"))
        self.assertIn("cannot be observed", p["FURY"]["reason"])

    def test_no_invented_agent_task_or_worker_relationships(self):
        res = core([{"event_id": "a", "role_id": "FURY", "state": "working", "timestamp": iso(5)}],
                   workers=[{"id": "w1", "provider": "claude", "status": "running", "last_seen": iso(1)}],
                   tasks=[{"id": "t9", "status": "running", "worker_id": "w1"}])
        fury = profiles(res)["FURY"]
        self.assertIsNone(fury["task_id"], "an agent gets a task only from its own event")
        self.assertNotIn("worker", " ".join(k for k in fury if k not in ("worker_requirements",)), "profiles carry no worker link")


class UltronObservationTests(unittest.TestCase):
    def obs(self, res):
        return [(o["category"], o["severity"], o["subject"]) for o in res["ultron_observations"]["items"]]

    def test_transport_failure_is_a_single_critical_connector_observation(self):
        res = core(down=True)
        self.assertEqual(self.obs(res), [("connector_health", "critical", "HIVE Core")])
        self.assertEqual(res["ultron"]["display"], "OFFLINE")

    def test_silence_is_not_active_and_quiet_is_reported_as_no_anomaly(self):
        res = core()
        self.assertEqual(res["ultron"]["display"], "UNKNOWN")
        self.assertEqual(self.obs(res), [("system_stability", "info", "HIVE Core events")])
        self.assertIn("not an ACTIVE claim", res["ultron_observations"]["items"][0]["reason"])

    def test_ultron_expiry(self):
        self.assertEqual(core([{"event_id": "u", "role_id": "ULTRON", "state": "working", "timestamp": iso(10)}])["ultron"]["display"], "ACTIVE")
        self.assertEqual(core([{"event_id": "u", "role_id": "ULTRON", "state": "working", "timestamp": iso(hr.ULTRON_FRESH_S + 5)}])["ultron"]["display"], "STALE")

    def test_blocked_permission_repeated_failure_worker_and_routing(self):
        events = [{"event_id": "b", "role_id": "SHURI", "state": "security_blocked", "event_type": "TOOL_PERMISSION_DENIED", "timestamp": iso(3)}] + \
                 [{"event_id": f"f{i}", "role_id": "UATU", "state": "failed", "task_id": "t2", "timestamp": iso(10 + i)} for i in range(3)]
        workers = [{"id": "w-off", "status": "idle", "last_seen": iso(500)}, {"id": "w-none", "status": "idle"}]
        tasks = [{"id": "t1", "status": "queued"}, {"id": "t3", "status": "queued", "worker_id": "ghost"}, {"id": "t4", "status": "running", "worker_id": "w-off"},
                 {"id": "t5", "status": "done"}]
        got = self.obs(core(events, workers, tasks))
        for expected in [("blocked_agent", "critical", "SHURI"), ("permission_failure", "critical", "SHURI"), ("repeated_failure", "warning", "t2"),
                         ("worker_health", "warning", "w-off"), ("worker_health", "info", "w-none"), ("task_routing", "info", "t1"),
                         ("task_routing", "warning", "t3"), ("task_routing", "warning", "t4")]:
            self.assertIn(expected, got)
        self.assertFalse([o for o in got if o[2] == "t5"], "finished tasks are not routing problems")

    def test_observations_never_act(self):
        res = core([{"event_id": "b", "role_id": "SHURI", "state": "security_blocked", "timestamp": iso(3)}])
        self.assertTrue(all(o["action"] == "none (observation only)" for o in res["ultron_observations"]["items"]))
        src = (ROOT / "hive_control.py").read_text(encoding="utf-8")
        for banned in ("write_text", "write_bytes", "open(", "subprocess", "urlopen", "requests", "os.system", "exec(", "eval("):
            self.assertNotIn(banned, src, banned)


class PermissionTests(unittest.TestCase):
    def test_no_permission_self_expansion(self):
        cfg = json.loads(hc.AGENTS_CONFIG_PATH.read_text(encoding="utf-8"))
        ultron = next(a for a in cfg["agents"] if a["agent_id"] == "ULTRON")
        self.assertIn("granting itself permissions", ultron["excluded"])
        self.assertTrue(all("read" in p.lower() for p in ultron["required_permissions"]), "ULTRON's configured permissions are read-only")
        p = profiles(core([{"event_id": "u", "role_id": "ULTRON", "state": "working", "timestamp": iso(1), "permissions": ["admin"], "capabilities": ["deploy"]}]))
        self.assertEqual(p["ULTRON"]["required_permissions"], ultron["required_permissions"], "an event cannot add permissions")
        self.assertEqual(p["ULTRON"]["capabilities"], [], "an event cannot add capabilities")
        evolve = next(a for a in cfg["agents"] if a["agent_id"] == "EVOLVE")
        self.assertTrue(any("isolated branch" in x for x in evolve["excluded"]) and any("patch" in x for x in evolve["excluded"]))

    def test_no_external_execution_paths_in_the_new_modules(self):
        for name in ("hive_control.py", "hive_evolution.py", "hive_probes.py"):
            src = (ROOT / name).read_text(encoding="utf-8")
            for banned in ("subprocess", "os.system", "Popen", "exec(", "eval(", "shell=True", "importlib", "write_text", "write_bytes", ".unlink(", "rmtree"):
                self.assertNotIn(banned, src, f"{name}: {banned}")
        probes = (ROOT / "hive_probes.py").read_text(encoding="utf-8")
        self.assertIn('method="HEAD"', probes); self.assertNotIn("data=", probes); self.assertNotIn("POST", probes)


class _Resp:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeOpener:
    def __init__(self, behaviour=None):
        self.requests, self.behaviour = [], behaviour or {}

    def open(self, req, timeout=None):
        self.requests.append((req.full_url, req.get_method(), req.data, dict(req.header_items()), timeout))
        b = self.behaviour.get(req.full_url)
        if isinstance(b, Exception):
            raise b
        return b or _Resp()


class InternetProbeTests(unittest.TestCase):
    def test_not_configured_makes_no_request(self):
        op = FakeOpener()
        res = hp.read_internet(None, iso(0), op)
        self.assertEqual(res["connectors"][0]["display"], "NOT_CONNECTED"); self.assertEqual(op.requests, [])

    def test_only_listed_https_public_hosts_are_contacted_with_head_and_no_body(self):
        raw = "https://ok.example/health http://plain.example https://user:pw@cred.example https://10.1.2.3/ https://127.0.0.1/ https://box.local/ https://down.example/"
        op = FakeOpener({"https://down.example/": URLError("refused")})
        res = hp.read_internet(raw, iso(0), op)
        contacted = sorted(r[0] for r in op.requests)
        self.assertEqual(contacted, ["https://down.example/", "https://ok.example/health"])
        self.assertTrue(all(r[1] == "HEAD" and r[2] is None and r[4] == hp.PROBE_TIMEOUT_S for r in op.requests))
        self.assertTrue(all("Authorization" not in r[3] and "Cookie" not in r[3] for r in op.requests))
        by = {c["reason"].split(":")[0]: c for c in res["connectors"]}
        displays = sorted(c["display"] for c in res["connectors"])
        self.assertEqual(displays.count("NOT_VERIFIED"), 5); self.assertIn("OBSERVED", displays); self.assertIn("OFFLINE", displays)
        self.assertIsNone(res["internet"]["evidence"]["display"], "the probe list is an aggregate without a state of its own")

    def test_redirects_are_not_followed_and_http_errors_count_as_answers(self):
        op = FakeOpener({"https://r.example/": HTTPError("https://r.example/", 301, "moved", {}, None), "https://e.example/": HTTPError("https://e.example/", 503, "x", {}, None)})
        res = {c["target_host"]: c for c in hp.read_internet("https://r.example/ https://e.example/", iso(0), op)["connectors"]}
        self.assertIn("redirect not followed", res["r.example"]["reason"]); self.assertEqual(res["e.example"]["status_code"], 503)
        handler = hp._NoRedirect()
        self.assertIsNone(handler.redirect_request(None, None, 302, "x", {}, "https://elsewhere.example/"))

    def test_probe_count_is_bounded(self):
        raw = " ".join(f"https://h{i}.example/" for i in range(hp.MAX_PROBES + 3))
        acc, rej = hp.parse_probe_config(raw)
        self.assertEqual(len(acc), hp.MAX_PROBES); self.assertEqual(len(rej), 3)


class EvolutionTests(unittest.TestCase):
    def test_experiments_are_deterministic_fixture_only_and_never_adopted(self):
        a, b = ev.run_experiments(observed=iso(0)), ev.run_experiments(observed=iso(0))
        self.assertEqual(a, b)
        self.assertEqual([e["experiment_id"] for e in a], ["EXP-ROUTING-1", "EXP-CONNECTOR-1", "EXP-STALENESS-1"])
        self.assertTrue(all(e["display"] == "FIXTURE" and e["fixture_only"] is True and e["adopted"] is False for e in a))
        routing = {e["experiment_id"]: e for e in a}["EXP-ROUTING-1"]
        self.assertEqual(routing["baseline"]["metrics"]["bad_assignments"], 3); self.assertEqual(routing["candidates"][0]["metrics"]["bad_assignments"], 0)

    def test_every_domain_listed_and_no_evidence_means_no_proposal(self):
        r = ev.read_evolution(now=NOW)
        rows = {x["domain"]: x for x in r["evolution"]["domains"]}
        self.assertEqual(set(rows), set(ev.DOMAINS))
        empty = [d for d, x in rows.items() if not x["proposals"] and not x["experiments"]]
        self.assertTrue(empty and all("insufficient evidence" in rows[d]["note"] for d in empty))
        for d in ("agent_routing", "connector_reliability", "ultron_policies"):
            self.assertTrue(rows[d]["experiments"], d)

    def test_proposal_fields_stage_and_rollback_reference(self):
        items = {p["proposal_id"]: p for p in ev.read_evolution(now=NOW)["proposals"]["items"]}
        self.assertEqual(len(items), 6)
        evo = items["EVO-0001"]
        for f in ("domain", "baseline", "candidate", "evidence", "hypothesis", "expected_benefit", "success_metrics", "risk", "required_permissions", "test_plan",
                  "rollback_plan", "expires_at", "correlation_id", "status"):
            self.assertTrue(evo[f], f)
        self.assertEqual((evo["status"], evo["stage"], evo["applied"], evo["rollback_ref"]), ("PENDING_HUMAN_REVIEW", "HUMAN_REVIEW", False, "backup/pre-control-plane"))
        self.assertEqual(items["PROP-0001"]["stage"], "PROPOSE", "no experiment => not past PROPOSE")
        self.assertEqual(sum(m["met"] for m in evo["success_met"]), 3)

    def _log(self, mutate):
        tmp = Path(tempfile.mkdtemp())
        doc = json.loads(ev.PROPOSALS_PATH.read_text(encoding="utf-8"))
        mutate(doc)
        (tmp / "p.json").write_text(json.dumps(doc), encoding="utf-8")
        return tmp

    def test_proposal_creation_rejection_expiry_and_stale_dataset(self):
        def add(doc):
            new = dict(doc["proposals"][3], proposal_id="EVO-9999", status="REJECTED", correlation_id="prop:EVO-9999")
            doc["proposals"].append(new)
            doc["proposals"][4]["status"] = "APPROVED_FOR_PROTOTYPE"
            doc["proposals"][5]["evidence"][0]["sha256"] = "sha256:" + "0" * 64
            doc["proposals"][0]["expires_at"] = "2026-01-01T00:00:00Z"
        tmp = self._log(add)
        try:
            items = {p["proposal_id"]: p for p in ev.proposal_records(path=tmp / "p.json", now=NOW)["items"]}
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual(items["EVO-9999"]["status"], "REJECTED"); self.assertEqual(items["EVO-9999"]["applied"], False)
        self.assertEqual(items["EVO-0002"]["status"], "APPROVED_FOR_PROTOTYPE"); self.assertEqual(items["EVO-0002"]["applied"], False, "approval applies nothing")
        self.assertEqual(items["EVO-0003"]["status"], "STALE"); self.assertIn("dataset changed", items["EVO-0003"]["reason"])
        self.assertEqual(items["PROP-0001"]["status"], "EXPIRED")

    def test_changed_dataset_makes_experiment_proposal_stale(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            shutil.copytree(ev.DATASETS, tmp / "d")
            p = tmp / "d" / "routing.json"; data = json.loads(p.read_text()); data["tasks"].pop(); p.write_text(json.dumps(data))
            items = {x["proposal_id"]: x for x in ev.read_evolution(now=NOW, datasets=tmp / "d")["proposals"]["items"]}
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual(items["EVO-0001"]["status"], "STALE"); self.assertEqual(items["EVO-0002"]["status"], "PENDING_HUMAN_REVIEW")

    def test_no_code_path_acts_on_a_status(self):
        for name in ("hive_evolution.py", "hive_registry.py", "server.py", "app.js"):
            src = (ROOT / name).read_text(encoding="utf-8")
            self.assertFalse([l for l in src.splitlines() if "APPROVED_FOR_PROTOTYPE" in l and ("==" in l or l.strip().startswith(("if ", "elif ")))], name)


class IsolationTests(unittest.TestCase):
    def test_fixture_control_plane_never_reads_as_live(self):
        fx = fixture_server.fixture_registry(NOW)
        self.assertEqual(hr.validate_registry(fx), [])
        recs = list(hr.iter_records(fx))
        self.assertFalse([r["id"] for r in recs if r["validity"] == "valid" or r["display"] in ("OBSERVED", "ACTIVE")])
        self.assertFalse([r["id"] for r in recs if not r["source"].startswith("fixture")])
        kinds = {r["kind"] for r in recs}
        self.assertTrue({"agent_profile", "ultron_observation", "experiment", "proposal"} <= kinds)

    def test_live_registry_with_core_down_validates_and_runs_no_probe(self):
        op = FakeOpener()
        reg = hr.build_registry(fetch_for({}), hr.RegistryConfig(tool_manifest_dir=str(hr.DEFAULT_TOOL_MANIFEST_DIR)), now=lambda: NOW, probe_opener=op)
        self.assertEqual(hr.validate_registry(reg), [])
        self.assertEqual(op.requests, [])
        self.assertEqual(next(c for c in reg["connectors"] if c["id"] == "connector:internet")["display"], "NOT_CONNECTED")


if __name__ == "__main__":
    unittest.main()
