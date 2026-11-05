"""Read-only registry v2 (hive_registry.py, GET /api/registry): contract, configuration, failure modes, isolation and safety.

All HIVE Core access is injected/mocked; filesystem and database sources use temporary directories, temporary SQLite files or
tests/fixtures. Nothing contacts a real external system, and every test checks a property of the read-only registry.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import fixture_server
import hive_registry as hr
import server

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures"
NOW = datetime(2026, 11, 5, 12, 0, 0, tzinfo=timezone.utc)


def iso(seconds_ago):
    return (NOW - timedelta(seconds=seconds_ago)).isoformat().replace("+00:00", "Z")


def core_fetch(routes, unavailable=()):
    calls = []

    def fetch(path):
        calls.append(path)
        key = path.split("?")[0]
        if key in routes and key not in unavailable:
            return routes[key], {"source": f"hive:{path}", "observed_at": iso(0), "validity": "valid", "reason": None}
        return None, {"source": f"hive:{path}", "observed_at": None, "validity": "unavailable", "reason": "HIVE Core is unavailable: refused"}
    fetch.calls = calls
    return fetch


def cfg(**kw):
    base = dict(skill_roots=[], prompt_roots=[], bot_roots=[], vault_root=None, creator_ops_db=None, tool_manifest_dir=None)
    base.update(kw)
    return hr.RegistryConfig(**base)


def build(routes=None, unavailable=(), config=None, mode="live", **kw):
    return hr.build_registry(core_fetch(routes or {}, unavailable), config or cfg(), now=lambda: NOW, mode=mode, **kw)


class TempDir(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


# ------------------------------------------------------------------ schema and envelope
class SchemaTests(unittest.TestCase):
    def test_committed_schema_equals_the_generated_one(self):
        committed = json.loads(hr.SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(committed, json.loads(json.dumps(hr.build_schema())), "run: python hive_registry.py --write-schema")

    def test_every_record_kind_requires_the_full_envelope(self):
        for kind, d in hr.build_schema()["$defs"].items():
            if kind == "section_evidence":
                continue
            for f in ("id", "source", "source_id", "observed_at", "validity", "reason", "correlation_id", "schema_version", "display"):
                self.assertIn(f, d["required"], f"{kind}.{f}")
            self.assertFalse(d["additionalProperties"])

    def test_validator_rejects_bad_records_and_unknown_validity_degrades(self):
        rec = hr.envelope("worker", "worker:x", "hive:/workers", None, "valid", status="idle", capabilities=[], freshness="unknown")
        schema = hr.build_schema()
        self.assertEqual(hr.validate(rec, {"$ref": "#/$defs/worker"}, schema), [])
        for bad in (dict(rec, validity="green"), dict(rec, extra=1), {k: v for k, v in rec.items() if k != "correlation_id"}):
            self.assertTrue(hr.validate(bad, {"$ref": "#/$defs/worker"}, schema))
        self.assertEqual(hr.envelope("connector", "c", "s", None, "ok-ish")["display"], "UNKNOWN")

    def test_full_fixture_and_live_registries_validate(self):
        self.assertEqual(hr.validate_registry(fixture_server.fixture_registry(NOW)), [])
        self.assertEqual(hr.validate_registry(build()), [])


# ------------------------------------------------------------------ configuration and paths
class ConfigTests(TempDir):
    def test_missing_environment_paths_use_only_the_two_allowlisted_home_defaults(self):
        with patch.dict(os.environ, {}, clear=True):
            c = hr.config_from_env()
        self.assertEqual([Path(p) for _, p in c.skill_roots], [Path.home() / ".codex" / "skills", Path.home() / ".agents" / "skills"])
        self.assertEqual((c.prompt_roots, c.bot_roots, c.vault_root, c.creator_ops_db), ([], [], None, None))
        self.assertEqual(Path(c.tool_manifest_dir), hr.DEFAULT_TOOL_MANIFEST_DIR)

    def test_explicit_environment_overrides_and_empty_disables_defaults(self):
        with patch.dict(os.environ, {"HIVE_SKILLS_ROOTS": "", "HIVE_PROMPTS_ROOTS": str(self.tmp), "CREATOR_OPS_DB_PATH": "/x.db"}, clear=True):
            c = hr.config_from_env()
        self.assertEqual(c.skill_roots, []); self.assertEqual([p for _, p in c.prompt_roots], [str(self.tmp)]); self.assertEqual(c.creator_ops_db, "/x.db")
        with patch.dict(os.environ, {"HIVE_SKILL_ROOTS": str(self.tmp)}, clear=True):  # legacy alias still honoured
            self.assertEqual([p for _, p in hr.config_from_env().skill_roots], [str(self.tmp)])

    def test_invalid_roots_are_rejected_never_replaced(self):
        link = self.tmp / "link"
        try:
            os.symlink(self.tmp, link)
        except (OSError, NotImplementedError):
            link = None
        cases = {"relative/skills": "not an absolute path", str(self.tmp / ".." / "x"): "'..'", str(Path(Path.cwd().anchor)): "too broad",
                 str(Path.home()): "too broad", str(self.tmp / "missing"): "missing"}
        if link:
            cases[str(link)] = "symbolic link"
        for raw, why in cases.items():
            p, problem = hr.check_root(raw)
            self.assertIsNone(p, raw); self.assertIn(why, problem[1], raw)
        self.assertEqual(hr.check_root(str(self.tmp / "missing"))[1][0], "inaccessible")
        self.assertEqual(hr.check_root("relative")[1][0], "not_verified")
        self.assertEqual(hr.check_root(None)[1][0], "not_configured")

    def test_no_user_specific_absolute_path_in_shipped_code(self):
        for name in ("server.py", "hive_registry.py", "fixture_server.py", "hive_system.py", "app.js", "index.html", "tools/registry_summary.py"):
            text = (ROOT / name).read_text(encoding="utf-8")
            for marker in ("C:\\Users\\", "C:/Users/", "/Users/", "/home/"):
                self.assertNotIn(marker, text, f"{name} contains {marker}")

    def test_server_vault_and_creator_ops_paths_come_only_from_the_environment(self):
        if not os.environ.get("ORCHESTRATOR_VAULT_ROOT"):
            self.assertIsNone(server.ORCHESTRATOR_VAULT_ROOT)
            self.assertIsNone(server.ORCHESTRATOR_PROJECT_REGISTRY_PATH)
            self.assertEqual(server.ORCHESTRATOR_CONTEXT_SOURCES, {})
            items, ev = server.orchestrator_project_registry()
            self.assertEqual(items, []); self.assertIn("ORCHESTRATOR_VAULT_ROOT", ev["reason"])
        with patch.object(server, "CREATOR_OPS_DB_PATH", ""):
            st = server.creator_ops_status()
        self.assertEqual((st["validity"], st["configured"]), ("unavailable", False)); self.assertIn("CREATOR_OPS_DB_PATH", st["reason"])


# ------------------------------------------------------------------ HIVE Core, agents, ULTRON
class CoreTests(unittest.TestCase):
    ROUTES = {
        "/health": {"status": "ok"},
        "/workers": {"items": [
            {"id": "w1", "provider": "claude", "model": "m", "status": "running", "capabilities": ["code.review"], "last_seen": iso(5), "current_task": "t1"},
            {"id": "w2", "name": "claude-like name", "provider": "unknown", "status": "idle"},
            {"id": "w3", "provider": "claude-enterprise", "status": "idle"},
            {"id": "w1", "provider": "gpt"}, "garbage", {"no_id": True}]},
        "/tasks": {"items": [{"id": "t1", "title": "x", "status": "running", "worker_id": "w1", "correlation_id": "c-9"}, {"id": "t2", "status": "queued"}]},
        "/events": {"items": [{"event_id": "a", "role_id": "FURY", "state": "working", "timestamp": iso(1), "provider": "claude"}]},
    }

    def test_core_down_is_offline_and_invents_nothing(self):
        reg = build()
        self.assertEqual(next(c for c in reg["connectors"] if c["id"] == "connector:hive-core")["display"], "OFFLINE")
        self.assertEqual((reg["ultron"]["display"], reg["ultron"]["state"]), ("OFFLINE", "OFFLINE"))
        for key in ("agents", "workers", "capabilities"):
            self.assertEqual(reg[key]["items"], [], key)
        self.assertEqual(reg["tasks"]["instances"]["items"], [])

    def test_workers_tasks_providers_and_agents_keep_only_explicit_evidence(self):
        reg = build(self.ROUTES)
        w = {x["source_id"]: x for x in reg["workers"]["items"]}
        self.assertEqual(sorted(w), ["w1", "w2", "w3"]); self.assertEqual(w["w1"]["validity"], "conflict")
        self.assertIsNone(w["w2"]["provider"]); self.assertIn("provider", w["w2"]["not_provided"])
        self.assertIsNone(w["w2"]["correlation_id"]); self.assertIn("correlation_id", w["w2"]["not_provided"])
        p = {x["source_id"]: x for x in reg["providers"]["items"]}
        self.assertEqual(p["claude"]["observed_workers"], ["w1"]); self.assertEqual(p["gpt"]["observed_workers"], [])
        t = {x["source_id"]: x for x in reg["tasks"]["instances"]["items"]}
        self.assertEqual((t["t1"]["assigned_worker"], t["t1"]["correlation_id"]), ("w1", "c-9"))
        self.assertIsNone(t["t2"]["correlation_id"]); self.assertIn("correlation_id", t["t2"]["not_provided"])
        self.assertEqual([a["role_id"] for a in reg["agents"]["items"]], ["FURY"], "no agent from the role catalog")
        self.assertTrue(all(a["classification"] == "UNKNOWN" for a in reg["agents"]["items"]))
        self.assertTrue(all(r["classification"] == "UNKNOWN" and r["provider"] is None for r in reg["roles"]["items"]))

    def test_agents_section_documents_the_no_agents_route_limitation(self):
        reg = build({"/health": {"status": "ok"}, "/events": {"items": []}})
        self.assertEqual(reg["agents"]["items"], [])
        self.assertIn("no agents route", reg["agents"]["evidence"]["reason"])

    def test_auth_required_workers_fall_back_to_the_labelled_public_ready_list(self):
        routes = dict(self.ROUTES, **{"/ready": {"workers": [{"id": "pub-1", "status": "available"}]}})
        reg = build(routes, unavailable=("/workers",))
        self.assertEqual([x["source_id"] for x in reg["workers"]["items"]], ["pub-1"]); self.assertIn("public", reg["workers"]["evidence"]["reason"])

    def test_live_registry_with_core_down_costs_one_bounded_core_call(self):
        from tests.test_snapshot_latency import make, refused
        fake = make(refused)
        with patch.object(server, "urlopen", fake), patch.dict(os.environ, {"HIVE_SKILLS_ROOTS": "", "ORCHESTRATOR_VAULT_ROOT": "", "CREATOR_OPS_DB_PATH": ""}):
            reg = hr.build_registry(server.fetch_with_evidence, hr.config_from_env(), bucket=server.bucket_for, core_scope=server.core_snapshot_scope)
        self.assertEqual(len(fake.calls), 1, fake.calls); self.assertEqual(fake.calls[0][1], server.CORE_PREFLIGHT_TIMEOUT_S)
        self.assertEqual(hr.validate_registry(reg), [])


class UltronTests(unittest.TestCase):
    def u(self, events, health=True, events_ok=True):
        routes = {"/health": {"status": "ok"}, "/events": {"items": events}}
        unavailable = () if health else ("/health", "/events")
        if not events_ok:
            unavailable = ("/events",)
        return build(routes, unavailable=unavailable)["ultron"]

    def test_fresh_trusted_event_is_active_with_evidence_and_recent_observations(self):
        u = self.u([{"event_id": "e1", "role_id": "ULTRON", "state": "working", "timestamp": iso(10), "correlation_id": "c-1"},
                    {"event_id": "e0", "role_id": "ULTRON", "state": "idle", "timestamp": iso(400)}])
        self.assertEqual((u["display"], u["state"], u["last_event_id"], u["correlation_id"], u["observed_at"]), ("ACTIVE", "WORKING", "e1", "c-1", iso(10)))
        self.assertEqual([r["event_id"] for r in u["recent"]], ["e1", "e0"])

    def test_expiry_silence_untrusted_and_offline(self):
        self.assertEqual(self.u([{"event_id": "e", "role_id": "ULTRON", "state": "working", "timestamp": iso(hr.ULTRON_FRESH_S + 1)}])["display"], "STALE")
        self.assertEqual(self.u([{"event_id": "f", "role_id": "FURY", "state": "working", "timestamp": iso(1)}])["display"], "UNKNOWN")
        for ts in (iso(-3600), None, "not-a-time"):
            self.assertEqual(self.u([{"event_id": "e", "role_id": "ULTRON", "state": "working", "timestamp": ts}])["display"], "UNVERIFIED", ts)
        self.assertEqual(self.u([], health=False)["display"], "OFFLINE")
        self.assertEqual(self.u([], events_ok=False)["display"], "UNKNOWN")
        stale = self.u([{"event_id": "e", "role_id": "ULTRON", "state": "working", "timestamp": iso(500)}])
        self.assertEqual((stale["state"], stale["last_state"]), ("UNKNOWN", "WORKING"))


# ------------------------------------------------------------------ Creator Ops
class CreatorOpsTests(TempDir):
    def db(self, create="CREATE TABLE task_definitions (id TEXT, name TEXT, version TEXT, input_schema TEXT, required_capabilities TEXT, risk_class TEXT)", rows=()):
        path = self.tmp / "co.sqlite3"
        con = sqlite3.connect(path)
        con.execute(create)
        con.execute("CREATE TABLE accounts (id TEXT, secret TEXT)")
        con.execute("INSERT INTO accounts VALUES ('a', 'ACCOUNT-SECRET-XYZ')")
        if rows:
            con.executemany(f"INSERT INTO task_definitions VALUES ({','.join('?' * len(rows[0]))})", rows)
        con.commit(); con.close()
        return path

    def read(self, path):
        return hr.read_creator_ops(str(path) if path else None, iso(0))

    def test_not_configured_rejected_missing_and_corrupt(self):
        self.assertEqual(self.read(None)["connectors"][0]["display"], "NOT_CONNECTED")
        self.assertEqual(self.read("relative.db")["connectors"][0]["display"], "NOT_VERIFIED")
        self.assertEqual(self.read(self.tmp / "missing.db")["connectors"][0]["display"], "UNAVAILABLE")
        bad = self.tmp / "corrupt.db"; bad.write_bytes(b"not a database at all")
        self.assertEqual(self.read(bad)["connectors"][0]["display"], "UNAVAILABLE")

    def test_unknown_schema_is_not_verified_and_no_other_table_is_read(self):
        res = self.read(self.db("CREATE TABLE other_tasks (id TEXT, name TEXT)"))
        self.assertEqual(res["connectors"][0]["display"], "NOT_VERIFIED"); self.assertIn("schema unknown", res["connectors"][0]["reason"])
        path2 = self.tmp / "nocols.sqlite3"; con = sqlite3.connect(path2); con.execute("CREATE TABLE task_definitions (id TEXT)"); con.commit(); con.close()
        self.assertEqual(self.read(path2)["connectors"][0]["display"], "NOT_VERIFIED")

    def test_catalog_reads_only_allowlisted_columns_and_never_executes(self):
        path = self.db(rows=[("t1", "Draft", "1.0", '{"type":"object","properties":{"topic":{},"tone":{}}}', '["content.draft"]', "medium"),
                             ("t2", "<img src=x onerror=alert(1)>", None, "nope", "a, b", "weird"), ("t1", "dup", None, None, None, None)])
        statements = []
        real_connect = sqlite3.connect

        def traced(*a, **k):
            con = real_connect(*a, **k)
            con.set_trace_callback(statements.append)
            return con
        with patch.object(hr.sqlite3, "connect", side_effect=traced):
            res = self.read(path)
        items = {i["source_id"]: i for i in res["catalogs"]["creator_ops"]["items"]}
        self.assertEqual(sorted(items), ["t1", "t2"]); self.assertEqual(items["t1"]["validity"], "conflict")
        self.assertEqual(items["t1"]["input_schema_summary"], "fields: topic, tone"); self.assertEqual(items["t2"]["input_schema_summary"], "unparseable (not shown)")
        self.assertEqual(items["t2"]["declared_capabilities"], ["a", "b"]); self.assertEqual(items["t2"]["risk_class"], "unclassified")
        self.assertTrue(all(i["enabled"] is False and i["activation"] == "cataloged_not_executable" for i in items.values()))
        self.assertNotIn("ACCOUNT-SECRET-XYZ", json.dumps(res))
        joined = " | ".join(statements)
        self.assertNotIn("accounts", joined); self.assertNotRegex(joined, r"(?i)\b(insert|update|delete|drop|attach|create)\b")
        self.assertIn('FROM "task_definitions"', joined)

    def test_query_is_bounded(self):
        path = self.db(rows=[(f"t{i:03d}", f"n{i}", None, None, None, None) for i in range(12)])
        with patch.object(hr, "CREATOR_TASKS_MAX", 5):
            res = self.read(path)
        self.assertEqual(len(res["catalogs"]["creator_ops"]["items"]), 5); self.assertIn("truncated", res["connectors"][0]["reason"])


# ------------------------------------------------------------------ skills, prompts, bots
class CatalogTests(TempDir):
    def copy(self, name):
        shutil.copytree(FIX / name, self.tmp / name)
        return self.tmp / name

    def test_empty_root_is_observed_with_no_items(self):
        empty = self.tmp / "empty"; empty.mkdir()
        conns, items = hr.CatalogRootAdapter("skill", [("e", str(empty))], lambda: NOW).read()
        self.assertEqual((conns[0]["display"], items), ("OBSERVED", []))

    def test_discovery_is_not_activation_and_nothing_executes(self):
        root = self.copy("skills")
        with patch.object(subprocess, "run", side_effect=AssertionError("executed")), patch.object(subprocess, "Popen", side_effect=AssertionError("executed")), \
                patch.object(os, "system", side_effect=AssertionError("executed")):
            _, items = hr.CatalogRootAdapter("skill", [("t", str(root))], lambda: NOW).read()
        self.assertFalse((root / "hostile-metadata" / "EXECUTED_MARKER").exists())
        self.assertEqual(sorted(i["source_id"] for i in items), ["alpha-reviewer", "hostile-metadata"])
        self.assertTrue(all(i["enabled"] is False and i["activation"] == "discovered_not_activated" for i in items))
        self.assertTrue(all(not Path(i["source_path"]).is_absolute() for i in items), "source paths are relative to the root")

    def test_hostile_text_is_data_secrets_redacted_and_risk_basis_is_explicit(self):
        _, skills = hr.CatalogRootAdapter("skill", [("t", str(FIX / "skills"))], lambda: NOW).read()
        hostile = next(i for i in skills if i["source_id"] == "hostile-metadata")
        self.assertIn("<img src=x onerror=alert(1)>", hostile["description"]); self.assertNotIn("FIXTUREFAKEKEY1234567890", json.dumps(skills))
        self.assertEqual((hostile["risk_class"], hostile["risk_basis"]), ("unclassified", "none")); self.assertIn("risk_class", hostile["not_provided"])
        alpha = next(i for i in skills if i["source_id"] == "alpha-reviewer")
        self.assertEqual((alpha["risk_class"], alpha["risk_basis"], alpha["version"]), ("low", "derived_from_declared_tools", "0.1.0"))
        _, prompts = hr.CatalogRootAdapter("prompt", [("t", str(FIX / "prompts"))], lambda: NOW).read()
        rc = next(i for i in prompts if i["name"] == "review-checklist")
        self.assertIn("<script>alert(1)</script>", rc["description"]); self.assertEqual((rc["risk_class"], rc["risk_basis"]), ("low", "declared"))
        self.assertNotIn("Prompt body", json.dumps(prompts), "prompt content is never returned")
        _, bots = hr.CatalogRootAdapter("bot", [("t", str(FIX / "bots"))], lambda: NOW).read()
        bot = next(i for i in bots if i["source_id"] == "helper-bot/bot.json")
        self.assertEqual((bot["risk_class"], bot["enabled"]), ("high", False)); self.assertIn("ignored", bot["reason"])
        self.assertEqual(next(i for i in bots if i["source_id"] == "broken.bot.json")["display"], "NOT_VERIFIED")

    def test_duplicate_names_across_roots_are_conflicts(self):
        a, b = self.tmp / "a", self.tmp / "b"
        shutil.copytree(FIX / "skills" / "alpha-reviewer", a / "alpha-reviewer"); shutil.copytree(FIX / "skills" / "alpha-reviewer", b / "alpha-reviewer")
        _, items = hr.CatalogRootAdapter("skill", [("a", str(a)), ("b", str(b))], lambda: NOW).read()
        self.assertEqual([i["display"] for i in items], ["CONFLICT", "CONFLICT"]); self.assertIn("duplicate name", items[0]["reason"])

    def test_hashes_are_stable_and_change_with_content(self):
        root = self.copy("skills")

        def hashes():
            return {i["source_id"]: (i["content_hash"], i["tree_hash"]) for i in hr.CatalogRootAdapter("skill", [("t", str(root))], lambda: NOW).read()[1]}
        h1, h2 = hashes(), hashes()
        self.assertEqual(h1, h2)
        p = root / "alpha-reviewer" / "SKILL.md"; p.write_text(p.read_text(encoding="utf-8").replace("0.1.0", "0.2.0"), encoding="utf-8")
        h3 = hashes()
        self.assertNotEqual(h1["alpha-reviewer"], h3["alpha-reviewer"]); self.assertEqual(h1["hostile-metadata"], h3["hostile-metadata"])

    def test_symlink_escape_oversize_and_item_cap(self):
        root = self.copy("skills")
        outside = self.tmp / "outside"; outside.mkdir(); (outside / "SKILL.md").write_text("---\nname: escaped\n---\n", encoding="utf-8")
        try:
            os.symlink(outside, root / "linked")
        except (OSError, NotImplementedError):
            self.skipTest("symlinks not available")
        big = root / "big"; big.mkdir(); (big / "SKILL.md").write_text("---\nname: big\n---\n" + "x" * (hr.FILE_MAX + 1), encoding="utf-8")
        items = {i["source_id"]: i for i in hr.CatalogRootAdapter("skill", [("t", str(root))], lambda: NOW).read()[1]}
        self.assertNotIn("linked", items); self.assertEqual(items["big"]["display"], "NOT_VERIFIED")
        with patch.object(hr, "MAX_ITEMS_PER_ROOT", 1):
            self.assertEqual(len([i for i in hr.CatalogRootAdapter("skill", [("t", str(root))], lambda: NOW).read()[1] if i["validity"] == "valid"]), 1)


# ------------------------------------------------------------------ Obsidian
class ObsidianTests(TempDir):
    def setUp(self):
        super().setUp()
        shutil.copytree(FIX / "vault", self.tmp / "vault")
        self.vault = self.tmp / "vault"

    def test_not_configured_rejected_and_inaccessible(self):
        self.assertEqual(hr.ObsidianAdapter(None).read()[0]["display"], "NOT_CONNECTED")
        self.assertEqual(hr.ObsidianAdapter("relative/vault").read()[0]["display"], "NOT_VERIFIED")
        self.assertEqual(hr.ObsidianAdapter(str(self.tmp / ".." / "vault")).read()[0]["display"], "NOT_VERIFIED")
        self.assertEqual(hr.ObsidianAdapter(str(self.tmp / "missing")).read()[0]["display"], "UNAVAILABLE")

    def test_metadata_only_backlinks_tasks_and_no_writes(self):
        (self.vault / "Projects" / "Roadmap.md").write_text("# Roadmap\n- [ ] open one\n- [x] done one\n[[HIVE]]\n", encoding="utf-8")
        before = {p: p.stat().st_mtime for p in self.vault.rglob("*")}
        conn, notes = hr.ObsidianAdapter(str(self.vault), lambda: NOW).read()
        self.assertEqual(before, {p: p.stat().st_mtime for p in self.vault.rglob("*")})
        blob = json.dumps(notes)
        self.assertNotIn("Body text", blob); self.assertNotIn("Private daily", blob)
        n = {x["source_id"]: x for x in notes}
        self.assertEqual(n["Projects/Roadmap.md"]["backlinks"], 1, "HIVE.md links [[Roadmap]]"); self.assertEqual(n["Projects/HIVE.md"]["backlinks"], 1)
        self.assertEqual((n["Projects/Roadmap.md"]["open_tasks"], n["Projects/Roadmap.md"]["done_tasks"]), (1, 1))
        self.assertEqual((conn["display"], conn["identity_verified"], conn["vault_name"]), ("OBSERVED", True, "vault"))

    def test_subfolder_without_obsidian_folder_has_unverified_identity_and_parents_are_not_read(self):
        conn, notes = hr.ObsidianAdapter(str(self.vault / "Projects"), lambda: NOW).read()
        self.assertEqual((conn["display"], conn["identity_verified"]), ("UNVERIFIED", False)); self.assertIn("NOT_VERIFIED", conn["reason"])
        self.assertEqual([x["source_id"] for x in notes], ["HIVE.md"], "only notes under the configured root")

    def test_symlinked_note_outside_the_vault_is_skipped(self):
        secret = self.tmp / "secret.md"; secret.write_text("#outside secret body", encoding="utf-8")
        try:
            os.symlink(secret, self.vault / "Projects" / "link.md")
        except (OSError, NotImplementedError):
            self.skipTest("symlinks not available")
        _, notes = hr.ObsidianAdapter(str(self.vault), lambda: NOW).read()
        self.assertNotIn("Projects/link.md", [x["source_id"] for x in notes])

    def test_scan_is_bounded_by_count_and_time(self):
        for i in range(12):
            (self.vault / f"n{i:02d}.md").write_text(f"# n{i}\n", encoding="utf-8")
        with patch.object(hr, "NOTES_SCANNED_MAX", 5):
            conn, _ = hr.ObsidianAdapter(str(self.vault), lambda: NOW).read()
        self.assertEqual(conn["notes_scanned"], 5); self.assertIn("partial", conn["reason"]); self.assertEqual(conn["display"], "UNVERIFIED")
        ticks = iter(range(0, 100000, 10))
        conn, _ = hr.ObsidianAdapter(str(self.vault), lambda: NOW, clock=lambda: next(ticks)).read()
        self.assertIn("time budget", conn["reason"])


# ------------------------------------------------------------------ tool manifests
class ToolManifestTests(TempDir):
    def test_repository_manifests_are_valid_and_disabled(self):
        items = hr.read_tool_manifests(str(hr.DEFAULT_TOOL_MANIFEST_DIR), iso(0))["catalogs"]["tools"]["items"]
        self.assertGreaterEqual(len(items), 6)
        self.assertTrue(all(i["display"] == "OBSERVED" and i["enabled"] is False and i["activation"] == "manifest_only" for i in items), [i["reason"] for i in items])

    def test_invalid_duplicate_shell_remote_broken_and_enable_requests(self):
        items = {i["source_path"]: i for i in hr.read_tool_manifests(str(FIX / "tools"), iso(0))["catalogs"]["tools"]["items"]}
        self.assertEqual(items["a-valid.json"]["display"], "CONFLICT"); self.assertEqual(items["b-duplicate.json"]["display"], "CONFLICT")
        self.assertIn("shell metacharacters", items["c-shell.json"]["reason"]); self.assertIn("loopback", items["d-remote.json"]["reason"])
        self.assertEqual(items["e-broken.json"]["display"], "NOT_VERIFIED")
        self.assertTrue(all(i["enabled"] is False for i in items.values()))

    def test_manifest_dir_must_be_explicit_and_valid(self):
        self.assertEqual(hr.read_tool_manifests("relative/dir", iso(0))["connectors"][0]["display"], "NOT_VERIFIED")
        self.assertEqual(hr.read_tool_manifests(None, iso(0))["connectors"][0]["display"], "NOT_CONNECTED")
        big = self.tmp / "t"; big.mkdir(); (big / "x.json").write_text(json.dumps({"id": "x", "pad": "y" * hr.MANIFEST_MAX_BYTES}), encoding="utf-8")
        self.assertEqual(hr.read_tool_manifests(str(big), iso(0))["catalogs"]["tools"]["items"][0]["display"], "NOT_VERIFIED")


# ------------------------------------------------------------------ proposals
class ProposalTests(TempDir):
    def test_statuses_follow_the_reviewed_file_unless_stale_or_expired(self):
        items = hr.proposal_records(now=NOW)["items"]
        self.assertEqual(len(items), 3)
        self.assertTrue(all(p["status"] == "PENDING_HUMAN_REVIEW" and p["correlation_id"] == "prop:" + p["proposal_id"] and p["evidence_row_sha256"] for p in items))
        data = json.loads(hr.PROPOSALS_PATH.read_text(encoding="utf-8"))
        data[0]["status"], data[1]["status"], data[2]["status"] = "APPROVED_FOR_PROTOTYPE", "REJECTED", "MERGE_NOW"
        log = self.tmp / "p.json"; log.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual([p["status"] for p in hr.proposal_records(path=log, now=NOW)["items"]], ["APPROVED_FOR_PROTOTYPE", "REJECTED", "PENDING_HUMAN_REVIEW"])
        acc = self.tmp / "A.md"; acc.write_text(hr.ACCEPTANCE_PATH.read_text(encoding="utf-8").replace("| GAP-1 |", "| GAP-1 | edited", 1), encoding="utf-8")
        self.assertEqual(hr.proposal_records(acceptance=acc, now=NOW)["items"][0]["status"], "STALE")
        self.assertTrue(all(p["status"] == "EXPIRED" for p in hr.proposal_records(now=NOW + timedelta(days=400))["items"]))

    def test_no_server_code_path_acts_on_a_proposal_status(self):
        self.assertNotIn("APPROVED_FOR_PROTOTYPE", (ROOT / "server.py").read_text(encoding="utf-8"))
        uses = [line for line in (ROOT / "hive_registry.py").read_text(encoding="utf-8").splitlines() if "APPROVED_FOR_PROTOTYPE" in line]
        self.assertFalse([line for line in uses if "==" in line or line.strip().startswith(("if ", "elif ", "while "))], uses)  # vocabulary only, never a branch


# ------------------------------------------------------------------ isolation, cache, fixture/live separation, aggregates
class IsolationTests(TempDir):
    def test_a_slow_source_times_out_without_blocking_the_others(self):
        gate = threading.Event()

        def slow_fetch(path):
            gate.wait(3)
            return None, {"source": "hive:/x", "observed_at": None, "validity": "unavailable", "reason": "slow"}
        with patch.dict(hr.PART_LIMITS, {"core": (0.3, 0.0)}):
            t0 = time.monotonic()
            reg = hr.build_registry(slow_fetch, cfg(tool_manifest_dir=str(hr.DEFAULT_TOOL_MANIFEST_DIR)), now=lambda: NOW)
            took = time.monotonic() - t0
        gate.set()
        self.assertLess(took, 2.0)
        self.assertTrue(reg["parts"]["core"]["timed_out"])
        part = next(c for c in reg["connectors"] if c["id"] == "connector:part:core")
        self.assertEqual(part["display"], "OFFLINE"); self.assertIn("did not answer", part["reason"])
        self.assertTrue(reg["catalogs"]["tools"]["items"], "other sources still answered")
        self.assertNotIn("ultron", reg)

    def test_an_adapter_error_is_contained(self):
        with patch.object(hr, "read_tool_manifests", side_effect=RuntimeError("boom")):
            reg = build(config=cfg())
        self.assertIn("boom", next(c for c in reg["connectors"] if c["id"] == "connector:part:tools")["reason"])
        self.assertIn("ultron", reg)

    def test_parts_are_lazy_and_cached(self):
        fetch = core_fetch({"/health": {"status": "ok"}})
        cache = hr.RegistryCache()
        r1 = hr.build_registry(fetch, cfg(), parts=["proposals"], cache=cache, now=lambda: NOW)
        self.assertEqual(list(r1["parts"]), ["proposals"]); self.assertEqual(fetch.calls, [], "HIVE Core is not contacted for other parts")
        self.assertTrue(hr.build_registry(fetch, cfg(), parts=["proposals"], cache=cache, now=lambda: NOW)["parts"]["proposals"]["cached"])
        self.assertFalse(hr.build_registry(fetch, cfg(vault_root=str(self.tmp)), parts=["proposals"], cache=cache, now=lambda: NOW)["parts"]["proposals"]["cached"])

    def test_fixture_never_reads_as_live_and_logs_never_mix(self):
        build()
        fx = fixture_server.fixture_registry(NOW)
        recs = list(hr.iter_records(fx))
        self.assertFalse([r["id"] for r in recs if r["validity"] == "valid" or r["display"] in ("OBSERVED", "ACTIVE")])
        self.assertFalse([r["id"] for r in recs if not r["source"].startswith("fixture")])
        self.assertTrue(all(e["source"].startswith("fixture") for e in fx["evidence_log"]))
        self.assertFalse([e for e in build()["evidence_log"] if e["source"].startswith("fixture")])
        self.assertNotIn("FIXTURE-SECRET", json.dumps(fx)); self.assertNotIn("fixture_handle", json.dumps(fx))

    def test_no_aggregate_observed_chip_without_aggregate_evidence(self):
        reg = build(config=cfg(skill_roots=[("t", str(FIX / "skills"))]))
        self.assertIsNone(reg["catalogs"]["skills"]["evidence"]["display"])
        self.assertIsNone(reg["capabilities"]["evidence"]["display"])
        self.assertEqual(reg["catalogs"]["prompts"]["evidence"]["display"], "NOT_CONNECTED")

    def test_evidence_log_is_bounded(self):
        for _ in range(250):
            hr.record_evidence([hr.envelope("connector", "c", "s", None, "unknown")], iso(0))
        self.assertLessEqual(len(hr._LOGS["live"]), 200)
        self.assertLessEqual(len(build()["evidence_log"]), 50)


# ------------------------------------------------------------------ HTTP route and safety
class RouteAndSafetyTests(unittest.TestCase):
    def test_route_validates_parts_and_is_get_only(self):
        with patch.dict(os.environ, {"HIVE_SKILLS_ROOTS": "", "ORCHESTRATOR_VAULT_ROOT": "", "CREATOR_OPS_DB_PATH": ""}):
            httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
            th = threading.Thread(target=httpd.serve_forever, daemon=True); th.start()
            base = f"http://127.0.0.1:{httpd.server_address[1]}"
            try:
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(base + "/api/registry?part=bogus", timeout=5)
                self.assertEqual(ctx.exception.code, 400)
                with urllib.request.urlopen(base + "/api/registry?part=proposals,tools", timeout=10) as r:
                    data = json.loads(r.read())
                self.assertEqual(sorted(data["parts"]), ["proposals", "tools"]); self.assertEqual(hr.validate_registry(data), [])
            finally:
                httpd.shutdown(); httpd.server_close()
        src = (ROOT / "server.py").read_text(encoding="utf-8")
        self.assertNotIn("/api/registry", src[src.index("def do_POST"):])
        self.assertEqual(fixture_server.api_payload("/api/registry", {"part": ["bogus"]})[1], 400)

    def test_snapshot_never_builds_the_registry(self):
        src = (ROOT / "server.py").read_text(encoding="utf-8")
        start = src.index("def _snapshot_impl():")
        snap = src[start:src.index("\ndef ", start + 10)]
        self.assertNotIn("registry_snapshot", snap); self.assertNotIn("build_registry", snap)

    def test_registry_module_cannot_execute_reach_the_network_or_write(self):
        src = (ROOT / "hive_registry.py").read_text(encoding="utf-8")
        for banned in ("import subprocess", "Popen", "os.system", "exec(", "eval(", "urlopen", "import socket", "requests", "shell=True", "importlib", "__import__"):
            self.assertNotIn(banned, src, banned)
        body = src.partition('if __name__ == "__main__":')[0]
        for banned in ("write_text", "write_bytes", ".unlink(", ".rename(", "rmtree", "open(", "mode=rw"):
            self.assertNotIn(banned, body, banned)
        for word in ("PROD", "WONG", "ROCKET", "HIVE_API_TOKEN", "Authorization"):
            self.assertNotIn(word, src, word)

    def test_summary_tool_passes_on_this_host_without_printing_descriptions(self):
        env = dict(os.environ, HIVE_API_TOKEN="", HIVE_SKILLS_ROOTS=str(FIX / "skills"), ORCHESTRATOR_VAULT_ROOT="", CREATOR_OPS_DB_PATH="")
        r = subprocess.run([sys.executable, str(ROOT / "tools" / "registry_summary.py")], capture_output=True, text=True, timeout=60, env=env, cwd=ROOT)
        self.assertEqual(r.returncode, 0, r.stdout[-500:] + r.stderr[-500:]); self.assertTrue(r.stdout.strip().endswith("PASS"))
        self.assertNotIn("onerror", r.stdout)


if __name__ == "__main__":
    unittest.main()
