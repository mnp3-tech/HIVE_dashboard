"""Read-only registry (hive_registry.py, GET /api/registry): contract, failure modes and safety properties.

All HIVE Core access is injected/mocked; filesystem catalogs use temporary directories or tests/fixtures. Nothing contacts a
real external system, and every test checks a property of the read-only foundation (no execution, no writes, no invention).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import fixture_server
import hive_registry as hr
import server

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 5, 12, 0, 0, tzinfo=timezone.utc)


def iso(seconds_ago):
    return (NOW - timedelta(seconds=seconds_ago)).isoformat().replace("+00:00", "Z")


def core_fetch(routes, unavailable=()):
    """routes: path-without-query -> raw payload. Paths in `unavailable` (or missing) answer like an unreachable Core."""
    calls = []

    def fetch(path):
        calls.append(path)
        key = path.split("?")[0]
        if key in routes and key not in unavailable:
            return routes[key], {"source": f"hive:{path}", "observed_at": iso(0), "validity": "valid", "reason": None}
        return None, {"source": f"hive:{path}", "observed_at": None, "validity": "unavailable", "reason": "HIVE Core is unavailable: refused"}
    fetch.calls = calls
    return fetch


def build(routes=None, unavailable=(), skills=None, vault=None, creator=None, mode="live", **kw):
    return hr.build_registry(core_fetch(routes or {}, unavailable), creator or (lambda: {"validity": "unavailable", "reason": "not on this host", "counts": {}}),
                             [], skill_roots=skills if skills is not None else [], vault_root=vault, now=lambda: NOW, mode=mode, **kw)


class SchemaTests(unittest.TestCase):
    def test_committed_schema_equals_the_generated_one(self):
        committed = json.loads(hr.SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(committed, json.loads(json.dumps(hr.build_schema())), "run: python hive_registry.py --write-schema")

    def test_every_record_kind_requires_the_full_envelope(self):
        for kind, d in hr.build_schema()["$defs"].items():
            if kind == "section_evidence":
                continue
            for field in ("id", "source", "source_id", "observed_at", "validity", "reason", "correlation_id", "schema_version", "display"):
                self.assertIn(field, d["required"], f"{kind}.{field}")
            self.assertFalse(d["additionalProperties"])

    def test_validator_rejects_bad_records(self):
        rec = hr.envelope("worker", "worker:x", "hive:/workers", None, "valid", status="idle", capabilities=[], freshness="unknown")
        self.assertEqual(hr.validate(rec, {"$ref": "#/$defs/worker"}, hr.build_schema()), [])
        for bad in (dict(rec, validity="green"), dict(rec, extra=1), {k: v for k, v in rec.items() if k != "correlation_id"}, dict(rec, freshness="fine")):
            self.assertTrue(hr.validate(bad, {"$ref": "#/$defs/worker"}, hr.build_schema()), bad)

    def test_unknown_validity_from_a_source_degrades_to_unknown(self):
        rec = hr.envelope("connector", "c", "s", None, "ok-ish")
        self.assertEqual((rec["validity"], rec["display"]), ("unknown", "UNKNOWN"))


class CoreDownTests(unittest.TestCase):
    def test_unreachable_core_is_offline_everywhere_and_invents_nothing(self):
        reg = build()
        self.assertEqual(hr.validate_registry(reg), [])
        core = next(c for c in reg["connectors"] if c["id"] == "connector:hive-core")
        self.assertEqual(core["display"], "OFFLINE")
        self.assertEqual((reg["ultron"]["display"], reg["ultron"]["state"]), ("OFFLINE", "OFFLINE"))
        for key in ("agents", "workers", "capabilities"):
            self.assertEqual(reg[key]["items"], [], key)
        self.assertEqual(reg["tasks"]["instances"]["items"], [])
        self.assertTrue(all(p["observed_workers"] == [] and p["display"] == "UNKNOWN" for p in reg["providers"]["items"]))

    def test_live_endpoint_with_core_down_costs_one_bounded_core_call_and_validates(self):
        from tests.test_snapshot_latency import make, refused  # same mock transport as the GAP-9 tests
        fake = make(refused)
        with patch.object(server, "urlopen", fake), patch.object(server, "creator_ops_status", return_value={"validity": "unavailable", "reason": "x", "counts": {}}), \
                patch.dict(os.environ, {"HIVE_SKILL_ROOTS": "", "ORCHESTRATOR_VAULT_ROOT": ""}):
            reg = server.registry_snapshot()
        self.assertEqual(len(fake.calls), 1, fake.calls)
        self.assertEqual(fake.calls[0][1], server.CORE_PREFLIGHT_TIMEOUT_S)
        self.assertEqual(hr.validate_registry(reg), [])
        self.assertTrue(reg["read_only"] and reg["executes_nothing"])


class UltronTests(unittest.TestCase):
    def reg(self, events, health=True, events_ok=True):
        routes = {"/health": {"status": "ok"}, "/events": {"items": events}}
        return build(routes, unavailable=() if health else ("/health", "/events")) if events_ok else build(routes, unavailable=("/events",))

    def test_fresh_trusted_ultron_event_is_active_with_its_evidence(self):
        u = self.reg([{"event_id": "e1", "role_id": "ULTRON", "state": "working", "timestamp": iso(10), "correlation_id": "c-1"}])["ultron"]
        self.assertEqual((u["display"], u["state"], u["validity"], u["last_event_id"], u["correlation_id"]), ("ACTIVE", "WORKING", "valid", "e1", "c-1"))
        self.assertEqual(u["observed_at"], iso(10))

    def test_old_ultron_event_expires_to_stale_and_state_unknown(self):
        u = self.reg([{"event_id": "e1", "role_id": "ULTRON", "state": "working", "timestamp": iso(hr.ULTRON_FRESH_S + 1)}])["ultron"]
        self.assertEqual((u["display"], u["state"], u["last_state"]), ("STALE", "UNKNOWN", "WORKING"))

    def test_silence_is_never_active(self):
        u = self.reg([{"event_id": "f1", "role_id": "FURY", "state": "working", "timestamp": iso(5)}])["ultron"]
        self.assertEqual((u["display"], u["state"]), ("UNKNOWN", "UNKNOWN"))
        self.assertIn("silence is not ACTIVE", u["reason"])

    def test_future_or_missing_timestamps_are_unverified_not_active(self):
        for ts in (iso(-3600), None, "not-a-time"):
            u = self.reg([{"event_id": "e1", "role_id": "ULTRON", "state": "working", "timestamp": ts}])["ultron"]
            self.assertEqual(u["display"], "UNVERIFIED", ts)

    def test_events_unavailable_while_core_health_is_ok_is_unknown(self):
        u = self.reg([], events_ok=False)["ultron"]
        self.assertEqual(u["display"], "UNKNOWN")

    def test_offline_transport_is_offline(self):
        self.assertEqual(self.reg([], health=False)["ultron"]["display"], "OFFLINE")

    def test_newest_trusted_event_wins(self):
        u = self.reg([{"event_id": "old", "role_id": "ULTRON", "state": "idle", "timestamp": iso(500)},
                      {"event_id": "new", "role_id": "ultron", "state": "review", "timestamp": iso(3)}])["ultron"]
        self.assertEqual((u["last_event_id"], u["state"]), ("new", "REVIEW"))


class RegistryRecordTests(unittest.TestCase):
    ROUTES = {
        "/health": {"status": "ok"},
        "/workers": {"items": [
            {"id": "w1", "provider": "claude", "model": "m", "status": "running", "capabilities": ["code.review"], "last_seen": iso(5), "current_task": "t1"},
            {"id": "w2", "name": "claude-like name", "provider": "unknown", "status": "idle"},
            {"id": "w3", "provider": "claude-enterprise", "status": "idle"},
            {"id": "w1", "provider": "gpt"}, "garbage", {"no_id": True}]},
        "/tasks": {"items": [{"id": "t1", "title": "x", "status": "running", "worker_id": "w1", "correlation_id": "c-9"}, {"id": "t2", "status": "queued"}, {"title": "no id"}]},
        "/events": {"items": [{"event_id": "a", "role_id": "FURY", "state": "working", "timestamp": iso(1), "provider": "claude"}]},
    }

    def setUp(self):
        self.reg = build(self.ROUTES)

    def test_schema_valid(self):
        self.assertEqual(hr.validate_registry(self.reg), [])

    def test_workers_keep_only_explicit_fields_and_flag_duplicates_and_skip_malformed(self):
        w = {x["source_id"]: x for x in self.reg["workers"]["items"]}
        self.assertEqual(sorted(w), ["w1", "w2", "w3"])
        self.assertEqual(w["w1"]["validity"], "conflict")  # duplicate id in one response
        self.assertIsNone(w["w2"]["provider"]); self.assertIn("provider", w["w2"]["not_provided"])
        self.assertEqual(w["w1"]["freshness"], "live"); self.assertEqual(w["w2"]["freshness"], "unknown")

    def test_providers_link_only_on_exact_explicit_provider_field(self):
        p = {x["source_id"]: x for x in self.reg["providers"]["items"]}
        self.assertEqual(p["claude"]["observed_workers"], ["w1"], "no substring or name-based inference (w2 name, w3 'claude-enterprise')")
        self.assertEqual(p["gpt"]["observed_workers"], [], "the duplicate w1 record naming gpt was dropped, not merged")

    def test_tasks_keep_explicit_assignment_and_correlation_only(self):
        t = {x["source_id"]: x for x in self.reg["tasks"]["instances"]["items"]}
        self.assertEqual((t["t1"]["assigned_worker"], t["t1"]["correlation_id"]), ("w1", "c-9"))
        self.assertIsNone(t["t2"]["assigned_worker"]); self.assertIsNone(t["t2"]["correlation_id"])
        self.assertIn("assigned_worker", t["t2"]["not_provided"])
        self.assertEqual(self.reg["tasks"]["definitions"]["items"], [])
        self.assertEqual(self.reg["tasks"]["definitions"]["evidence"]["display"], "NOT_CONNECTED")

    def test_agents_come_only_from_events_and_classification_is_always_unknown(self):
        agents = self.reg["agents"]["items"]
        self.assertEqual([a["role_id"] for a in agents], ["FURY"], "no agent is created from the role catalog")
        self.assertTrue(all(a["classification"] == "UNKNOWN" for a in agents))
        roles = self.reg["roles"]["items"]
        self.assertTrue(all(r["classification"] == "UNKNOWN" and r["provider"] is None for r in roles))

    def test_capabilities_are_declarations_not_permissions(self):
        caps = {c["name"]: c for c in self.reg["capabilities"]["items"]}
        self.assertEqual(list(caps), ["code.review"])
        self.assertIn("not a permission", caps["code.review"]["reason"])

    def test_auth_required_workers_fall_back_to_public_ready_list_and_say_so(self):
        routes = dict(self.ROUTES, **{"/ready": {"workers": [{"id": "pub-1", "status": "available"}]}})
        reg = hr.build_registry(lambda p: core_fetch(routes, unavailable=("/workers",))(p), lambda: {}, [], skill_roots=[], now=lambda: NOW)
        self.assertEqual([w["source_id"] for w in reg["workers"]["items"]], ["pub-1"])
        self.assertIn("/ready", reg["workers"]["evidence"]["source"]); self.assertIn("public", reg["workers"]["evidence"]["reason"])


class FixtureModeTests(unittest.TestCase):
    def test_fixture_registry_never_reads_as_live(self):
        reg = fixture_server.fixture_registry(NOW)
        self.assertEqual(hr.validate_registry(reg), [])
        recs = list(hr.iter_records(reg))
        self.assertTrue(recs)
        self.assertFalse([r["id"] for r in recs if r["validity"] == "valid" or r["display"] in ("OBSERVED", "ACTIVE")])
        self.assertFalse([r["id"] for r in recs if not r["source"].startswith("fixture")])
        self.assertEqual(reg["mode"], "fixture")

    def test_live_and_fixture_evidence_logs_never_mix(self):
        build()  # a live read
        fx = fixture_server.fixture_registry(NOW)
        self.assertTrue(fx["evidence_log"])
        self.assertTrue(all(e["source"].startswith("fixture") for e in fx["evidence_log"]))
        live = build()
        self.assertFalse([e for e in live["evidence_log"] if e["source"].startswith("fixture")])


class SkillCatalogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        shutil.copytree(ROOT / "tests" / "fixtures" / "skills", self.tmp / "skills")
        self.root = self.tmp / "skills"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def read(self):
        return hr.SkillCatalogAdapter([("t", str(self.root))], lambda: NOW).read()

    def test_discovery_is_not_activation_and_nothing_is_executed(self):
        with patch.object(subprocess, "run", side_effect=AssertionError("executed")), patch.object(subprocess, "Popen", side_effect=AssertionError("executed")), \
                patch.object(os, "system", side_effect=AssertionError("executed")):
            conns, items = self.read()
        self.assertFalse((self.root / "hostile-metadata" / "EXECUTED_MARKER").exists())
        self.assertEqual(sorted(i["source_id"] for i in items), ["alpha-reviewer", "hostile-metadata"], "hidden directory skipped")
        self.assertTrue(all(i["enabled"] is False and i["activation"] == "discovered_not_activated" for i in items))
        self.assertEqual(conns[0]["display"], "OBSERVED")

    def test_metadata_is_data_secrets_redacted_and_hashes_are_real(self):
        _, items = self.read()
        hostile = next(i for i in items if i["source_id"] == "hostile-metadata")
        self.assertIn("<img src=x onerror=alert(1)>", hostile["description"])  # stored as text; the UI escapes it
        self.assertNotIn("FIXTUREFAKEKEY1234567890", json.dumps(items))
        self.assertIsNone(hostile["version"]); self.assertIn("version", hostile["not_provided"]); self.assertIn("risk_class", hostile["not_provided"])
        alpha = next(i for i in items if i["source_id"] == "alpha-reviewer")
        text = (self.root / "alpha-reviewer" / "SKILL.md").read_text(encoding="utf-8")
        self.assertEqual(alpha["content_hash"], "sha256:" + hashlib.sha256(text.encode()).hexdigest())
        self.assertEqual(alpha["declared_capabilities"], ["Read", "Grep"]); self.assertEqual(alpha["version"], "0.1.0")

    def test_version_change_changes_the_hash(self):
        _, a = self.read()
        p = self.root / "alpha-reviewer" / "SKILL.md"
        p.write_text(p.read_text(encoding="utf-8").replace("0.1.0", "0.2.0"), encoding="utf-8")
        _, b = self.read()
        ha, hb = ({i["source_id"]: i["content_hash"] for i in x}["alpha-reviewer"] for x in (a, b))
        self.assertNotEqual(ha, hb)

    def test_symlink_escape_and_oversize_files_are_not_followed_or_read(self):
        outside = self.tmp / "outside"; outside.mkdir()
        (outside / "SKILL.md").write_text("---\nname: escaped\n---\n", encoding="utf-8")
        try:
            os.symlink(outside, self.root / "linked-skill")
        except (OSError, NotImplementedError):
            self.skipTest("symlinks not available")
        big = self.root / "big"; big.mkdir()
        (big / "SKILL.md").write_text("---\nname: big\n---\n" + "x" * (hr.SKILL_MD_MAX + 10), encoding="utf-8")
        _, items = self.read()
        ids = {i["source_id"]: i for i in items}
        self.assertNotIn("linked-skill", ids)
        self.assertEqual(ids["big"]["validity"], "unknown"); self.assertIn("larger than", ids["big"]["reason"])

    def test_missing_root_is_not_connected(self):
        conns, items = hr.SkillCatalogAdapter([("x", str(self.tmp / "nope"))], lambda: NOW).read()
        self.assertEqual((conns[0]["display"], items), ("NOT_CONNECTED", []))

    def test_default_roots_are_exactly_the_two_allowlisted_home_roots(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("HIVE_SKILL_ROOTS", None)
            roots = hr.default_skill_roots()
        self.assertEqual([Path(p) for _, p in roots], [Path.home() / ".codex" / "skills", Path.home() / ".agents" / "skills"])


class ObsidianTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        shutil.copytree(ROOT / "tests" / "fixtures" / "vault", self.tmp / "vault")
        self.vault = self.tmp / "vault"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_not_configured_and_not_a_vault(self):
        self.assertEqual(hr.ObsidianAdapter(None).read()[0]["display"], "NOT_CONNECTED")
        plain = self.tmp / "plain"; plain.mkdir()
        self.assertEqual(hr.ObsidianAdapter(str(plain)).read()[0]["display"], "OFFLINE")

    def test_metadata_only_no_content_and_no_writes(self):
        before = {p: p.stat().st_mtime for p in self.vault.rglob("*")}
        conn, notes = hr.ObsidianAdapter(str(self.vault), lambda: NOW).read()
        after = {p: p.stat().st_mtime for p in self.vault.rglob("*")}
        self.assertEqual(before, after, "the adapter must not write, rename or delete anything")
        blob = json.dumps(notes)
        self.assertNotIn("Body text", blob); self.assertNotIn("Private daily", blob)
        hive = next(n for n in notes if n["source_id"] == "Projects/HIVE.md")
        self.assertEqual((sorted(hive["tags"]), hive["outgoing_links"], hive["activation"]), (["hive/dashboard", "project"], 2, "metadata_only"))
        self.assertEqual(conn["display"], "OBSERVED")

    def test_symlinked_note_outside_the_vault_is_skipped(self):
        secret = self.tmp / "secret.md"; secret.write_text("#outside secret body", encoding="utf-8")
        try:
            os.symlink(secret, self.vault / "Projects" / "link.md")
        except (OSError, NotImplementedError):
            self.skipTest("symlinks not available")
        _, notes = hr.ObsidianAdapter(str(self.vault), lambda: NOW).read()
        self.assertNotIn("Projects/link.md", [n["source_id"] for n in notes])

    def test_server_uses_only_the_environment_variable_not_the_hardcoded_constant(self):
        from tests.test_snapshot_latency import make, refused
        with patch.object(server, "urlopen", make(refused)), patch.object(server, "creator_ops_status", return_value={}), \
                patch.dict(os.environ, {"ORCHESTRATOR_VAULT_ROOT": "", "HIVE_SKILL_ROOTS": ""}):
            reg = server.registry_snapshot()
        obs = next(c for c in reg["connectors"] if c["id"] == "connector:obsidian")
        self.assertEqual(obs["display"], "NOT_CONNECTED"); self.assertIn("ORCHESTRATOR_VAULT_ROOT", obs["reason"])


class CatalogAndProposalTests(unittest.TestCase):
    def test_creator_ops_counts_only_and_task_catalog_not_verified(self):
        reg = build(creator=lambda: {"validity": "valid", "reason": "counts", "last_observed_at": iso(1), "counts": {"local_tasks": 4}})
        co = next(c for c in reg["connectors"] if c["id"] == "connector:creator-ops")
        self.assertEqual(co["table_counts"], {"local_tasks": 4})
        cat = reg["catalogs"]["creator_ops"]
        self.assertEqual((cat["items"], cat["evidence"]["display"]), ([], "NOT_CONNECTED"))
        self.assertIn("NOT_VERIFIED", cat["evidence"]["reason"])

    def test_prompts_and_bots_are_not_connected_and_tools_are_never_run(self):
        reg = hr.build_registry(core_fetch({}), lambda: {}, [{"id": "t", "name": "T", "transport": "cli", "target": "x"}], skill_roots=[], now=lambda: NOW)
        for key in ("prompts", "bots"):
            self.assertEqual(reg["catalogs"][key]["evidence"]["display"], "NOT_CONNECTED")
        tool = reg["catalogs"]["tools"]["items"][0]
        self.assertEqual((tool["activation"], tool["enabled"], tool["display"]), ("configured_not_run", False, "UNKNOWN"))

    def test_proposals_are_valid_only_while_their_gap_row_matches_and_never_change_review_status(self):
        items = hr.proposal_records(now=NOW)["items"]
        self.assertEqual(len(items), 3)
        self.assertTrue(all(p["validity"] == "valid" and p["review_status"] == "PENDING_HUMAN_REVIEW" and p["proposal_only"] for p in items))
        with tempfile.TemporaryDirectory() as tmp:
            acc = Path(tmp) / "ACCEPTANCE.md"
            acc.write_text(hr.ACCEPTANCE_PATH.read_text(encoding="utf-8").replace("| GAP-1 |", "| GAP-1 | edited", 1), encoding="utf-8")
            changed = {p["gap_id"]: p for p in hr.proposal_records(acceptance=acc, now=NOW)["items"]}
        self.assertEqual(changed["GAP-1"]["validity"], "stale"); self.assertEqual(changed["GAP-3"]["validity"], "valid")
        expired = hr.proposal_records(now=NOW + timedelta(days=400))["items"]
        self.assertTrue(all(p["validity"] == "stale" and "expired" in p["reason"] for p in expired))

    def test_evidence_log_is_bounded(self):
        for _ in range(250):
            hr.record_evidence([hr.envelope("connector", "c", "s", None, "unknown")], iso(0))
        self.assertLessEqual(len(hr._LOG), 200)
        self.assertLessEqual(len(build()["evidence_log"]), 50)


class SummaryToolTests(unittest.TestCase):
    def test_summary_tool_validates_and_passes_on_this_host(self):
        env = dict(os.environ, HIVE_API_TOKEN="", HIVE_SKILL_ROOTS=str(ROOT / "tests" / "fixtures" / "skills"), ORCHESTRATOR_VAULT_ROOT="")
        r = subprocess.run([__import__("sys").executable, str(ROOT / "tools" / "registry_summary.py")], capture_output=True, text=True, timeout=60, env=env, cwd=ROOT)
        self.assertEqual(r.returncode, 0, r.stdout[-400:] + r.stderr[-400:])
        self.assertTrue(r.stdout.strip().endswith("PASS"))
        self.assertIn("enabled=False", r.stdout); self.assertNotIn("onerror", r.stdout, "descriptions are not printed")


class SafetyTests(unittest.TestCase):
    SRC = (ROOT / "hive_registry.py").read_text(encoding="utf-8")

    def test_registry_module_cannot_execute_or_reach_the_network(self):
        for banned in ("import subprocess", "Popen", "os.system", "exec(", "eval(", "urlopen", "import socket", "requests", "shell=True"):
            self.assertNotIn(banned, self.SRC, banned)

    def test_registry_module_writes_only_its_schema_file_from_the_cli_entry_point(self):
        body, _, main = self.SRC.partition('if __name__ == "__main__":')
        for banned in ("write_text", "write_bytes", ".unlink(", ".rename(", "rmtree", "open("):
            self.assertNotIn(banned, body, banned)
        self.assertIn("write_text", main)

    def test_no_prod_wong_rocket_or_token_handling(self):
        for word in ("PROD", "WONG", "ROCKET", "HIVE_API_TOKEN", "Authorization"):
            self.assertNotIn(word, self.SRC, word)

    def test_endpoint_is_get_only(self):
        handler_src = (ROOT / "server.py").read_text(encoding="utf-8")
        post = handler_src[handler_src.index("def do_POST"):]
        self.assertNotIn("/api/registry", post)


if __name__ == "__main__":
    unittest.main()
