"""Asset and layout-file tests for the hybrid 2.5D visual layer (docs/hive/VISUAL_SPEC.md).

Pure file checks (no browser). Pillow/numpy are dev-time tools: the reproducibility test is skipped, not failed,
on a machine without them; every other test runs with the standard library only (a JPEG header is parsed by hand).
"""
from __future__ import annotations

import hashlib
import json
import re
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WALLPAPER = ROOT / "assets/hive-wallpaper.jpg"
GENERATOR = ROOT / "tools/make_wallpaper.py"
SHIPPED = ["index.html", "styles.css", "stage.css", "stage-layout.css", "app.js", "hive-core.js", "hive-ops.js"]


def jpeg_size(path: Path):
    data = path.read_bytes()
    assert data[:2] == b"\xff\xd8", "not a JPEG"
    i = 2
    while i < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xC0, 0xC1, 0xC2):
            h, w = struct.unpack(">HH", data[i + 5:i + 9])
            return w, h
        i += 2 + struct.unpack(">H", data[i + 2:i + 4])[0]
    raise AssertionError("no SOF marker")


class WallpaperTests(unittest.TestCase):
    def test_wallpaper_is_a_local_16x9_jpeg_within_the_byte_budget(self):
        self.assertTrue(WALLPAPER.is_file())
        self.assertEqual(jpeg_size(WALLPAPER), (2560, 1440))
        size = WALLPAPER.stat().st_size
        self.assertGreater(size, 50_000)
        self.assertLessEqual(size, 650 * 1024, f"wallpaper is {size} bytes")

    def test_generator_never_draws_text(self):
        src = GENERATOR.read_text(encoding="utf-8")
        code = "\n".join(line for line in src.splitlines() if not line.strip().startswith(("#", '"""')))
        for forbidden in (".text(", "ImageFont", "textbbox", "textlength", "multiline_text", "putText", "truetype", "load_default"):
            self.assertNotIn(forbidden, code, f"the wallpaper generator must not use {forbidden}")
        for allowed_only in ("ImageDraw", "ImageFilter", "ImageChops"):
            self.assertIn(allowed_only, code)
        # only primitives that cannot form glyphs are used for drawing
        draw_calls = set(re.findall(r"\bd\.(\w+)\(", code))
        self.assertTrue(draw_calls <= {"line", "ellipse"}, draw_calls)

    def test_wallpaper_is_reproducible_from_the_committed_generator(self):
        try:
            import numpy  # noqa: F401
            import PIL  # noqa: F401
        except ImportError:
            self.skipTest("Pillow/numpy not installed (dev-time tools)")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "w.jpg"
            subprocess.run([sys.executable, str(GENERATOR), "--out", str(out)], check=True, capture_output=True, timeout=120)
            # same bytes on the same platform; JPEG encoders can differ across Pillow builds, so compare decoded size and a
            # coarse content hash if the bytes differ
            if out.read_bytes() != WALLPAPER.read_bytes():
                from PIL import Image
                a, b = Image.open(out).convert("L").resize((64, 36)), Image.open(WALLPAPER).convert("L").resize((64, 36))
                diff = sum(abs(x - y) for x, y in zip(a.getdata(), b.getdata())) / (64 * 36)
                self.assertLess(diff, 2.0, "generated wallpaper differs from the committed one")

    def test_wallpaper_is_dark_in_the_middle_where_live_art_sits(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not installed")
        im = Image.open(WALLPAPER).convert("L")
        w, h = im.size
        centre = im.crop((int(w * .35), int(h * .30), int(w * .65), int(h * .60)))
        edge = im.crop((0, 0, int(w * .25), int(h * .25)))
        mean = lambda i: sum(i.tobytes()) / (i.size[0] * i.size[1])
        self.assertLess(mean(centre), 40, "the centre must stay dark so the CORE and labels stay readable")
        self.assertLess(mean(centre), mean(edge) + 5)


class LocalOnlyTests(unittest.TestCase):
    ALLOWED = re.compile(r"^(http://www\.w3\.org/2000/svg|http://127\.0\.0\.1[:/].*|http://localhost[:/].*)$")

    def test_no_external_urls_or_runtimes_in_shipped_files(self):
        for name in SHIPPED:
            text = (ROOT / name).read_text(encoding="utf-8")
            for url in re.findall(r"https?://[^\s'\"<>)]+", text):
                self.assertRegex(url, self.ALLOWED, f"{name} references {url}")
            for banned in ("unpkg.com", "cdn.jsdelivr", "cdnjs", "googleapis", "spline", "rive.app", "@import"):
                self.assertNotIn(banned, text.lower(), f"{name} mentions {banned}")

    def test_wallpaper_is_referenced_relatively(self):
        css = (ROOT / "stage.css").read_text(encoding="utf-8")
        self.assertIn('url("assets/hive-wallpaper.jpg")', css)
        self.assertNotRegex(css, r"url\(\s*[\"']?(https?:)?//")

    def test_no_baked_text_assets_other_than_the_wallpaper_and_reference_images(self):
        images = sorted(p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*") if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif"} and ".git" not in p.parts
                        and not p.as_posix().startswith(str(ROOT / "docs/hive/screenshots")) and "node_modules" not in p.parts)
        self.assertEqual(images, ["assets/hive-wallpaper.jpg", "docs/assets/hive-core-reference.png", "docs/assets/hive-dashboard-target.png"])


class LayoutFileTests(unittest.TestCase):
    def setUp(self):
        self.final = json.loads((ROOT / "docs/hive/measurements/stage-layout-final.json").read_text())
        self.plan = json.loads((ROOT / "docs/hive/measurements/layout-spec.json").read_text())
        self.css = (ROOT / "stage-layout.css").read_text()

    def test_stage_css_equals_the_final_layout_json(self):
        ids = {"topbar": "#topbar", "chats": "#panel-chats", "projects": "#panel-projects", "agents": "#panel-agents", "card_current": "#card-current",
               "card_next": "#card-next", "card_context": "#card-context", "card_external": "#card-external", "card_layout": "#card-layout",
               "activity": "#panel-activity", "approvals": "#panel-approvals", "resources": "#panel-resources", "limits": "#panel-limits", "composer": "#chat-draft-form"}
        for key, sel in ids.items():
            m = re.search(re.escape(sel) + r"\{left:([\d.]+)px;top:([\d.]+)px;width:([\d.]+)px;height:([\d.]+)px\}", self.css)
            self.assertIsNotNone(m, sel)
            f = self.final["panels_px"][key]
            for got, want in zip(map(float, m.groups()), (f["x0"], f["y0"], f["w"], f["h"])):
                self.assertAlmostEqual(got, want, delta=0.06, msg=sel)

    def test_only_documented_deviations_differ_from_the_plan(self):
        documented = {d["panel"] for d in self.final["deviations_from_plan"]}
        for key, plan in self.plan["panels_px"].items():
            fin = self.final["panels_px"][key]
            moved = any(abs(fin[k] - plan[k]) > 0.15 for k in ("x0", "y0", "w", "h"))
            if moved:
                self.assertIn(key, documented, f"{key} differs from the plan without a documented reason")
        for d in self.final["deviations_from_plan"]:
            self.assertTrue(d["reason"].strip())

    def test_minimum_gutters_hold_at_the_three_desktop_sizes(self):
        k = {w: min(w / 1671, h / 941) for w, h in ((1280, 720), (1920, 1080), (2560, 1440))}
        need = {1280: 10, 1920: 16, 2560: 20}
        smallest = min(self.final["gutters_px"][g] for g in ("chats_projects", "projects_agents", "activity_approvals", "resources_limits", "cards_1_2", "cards_2_3", "cards_3_4", "cards_4_5", "resources_composer"))
        for w, scale in k.items():
            self.assertGreaterEqual(smallest * scale, need[w] - 0.01, f"{w}: smallest gutter {smallest * scale:.2f}px")

    def test_core_is_centred_in_the_reference_stage(self):
        self.assertAlmostEqual(self.plan["core_centre_px"]["x"], 1671 / 2, places=3)

    def test_panels_stay_inside_the_stage_with_a_margin(self):
        for key, p in self.final["panels_px"].items():
            self.assertGreaterEqual(p["x0"], 14.0, key)
            self.assertLessEqual(p["x1"], 1671 - 14.0, key)
            self.assertGreaterEqual(p["y0"], 8.0, key)
            self.assertLessEqual(p["y1"], 941 - 14.0, key)


if __name__ == "__main__":
    unittest.main()
