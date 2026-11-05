#!/usr/bin/env python3
"""Measure docs/assets/hive-dashboard-target.png and write docs/hive/measurements/target.json.

Reproducible geometry/colour/typography extraction used by docs/hive/VISUAL_SPEC.md.
Dev tool only (needs Pillow + numpy). The target image is visual direction only: nothing
measured here (numbers, names, statuses) is ever used as data by the dashboard.

Method (tolerance about +-2 px at 1671x941):
  * panel edges: start from an approximate bbox, then move each side to the strongest
    luminance gradient within +-10 px, averaged over the middle 80% of that side;
  * circles (rings, planet, nodes): least-squares fit to mask pixels in an annulus window;
  * text height: tight bbox of bright pixels inside a hand-placed window (UPPERCASE samples
    only, so the height is the cap height);
  * colours: median of masked pixels inside a small window.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "docs/assets/hive-dashboard-target.png"
OUT = ROOT / "docs/hive/measurements/target.json"

im = np.array(Image.open(SRC).convert("RGB")).astype(float)
H, W, _ = im.shape
lum = im @ np.array([0.2126, 0.7152, 0.0722])

# approximate boxes read from the image (x0, y0, x1, y1) at 1671x941; refined below
APPROX = {
    "chats": (35, 80, 293, 353), "projects": (35, 372, 296, 545), "agents": (35, 565, 296, 790),
    "card_current": (331, 76, 562, 142), "card_next": (585, 76, 748, 142), "card_context": (759, 76, 948, 142),
    "card_external": (964, 76, 1153, 142), "card_layout": (1170, 76, 1278, 142),
    "activity": (1313, 80, 1643, 355), "approvals": (1313, 379, 1645, 611),
    "resources": (331, 636, 828, 778), "limits": (853, 636, 1311, 778), "composer": (309, 806, 1425, 880),
}


def refine_edge(axis: str, pos: int, lo: int, hi: int, rng: int = 10) -> int:
    """axis 'x': a vertical edge at column `pos` spanning rows lo..hi; 'y': horizontal edge."""
    span = hi - lo
    a, b = lo + int(span * 0.1), hi - int(span * 0.1)
    best, best_score = pos, -1.0
    for p in range(pos - rng, pos + rng + 1):
        if axis == "x":
            if p < 2 or p >= W - 2:
                continue
            score = np.abs(lum[a:b, p + 1] - lum[a:b, p - 1]).mean()
        else:
            if p < 2 or p >= H - 2:
                continue
            score = np.abs(lum[p + 1, a:b] - lum[p - 1, a:b]).mean()
        if score > best_score:
            best, best_score = p, score
    return best


panels = {}
for name, (x0, y0, x1, y1) in APPROX.items():
    rx0 = refine_edge("x", x0, y0, y1); rx1 = refine_edge("x", x1, y0, y1)
    ry0 = refine_edge("y", y0, x0, x1); ry1 = refine_edge("y", y1, x0, x1)
    panels[name] = {"x0": rx0, "y0": ry0, "x1": rx1, "y1": ry1, "w": rx1 - rx0, "h": ry1 - ry0,
                    "approx_shift_px": [rx0 - x0, ry0 - y0, rx1 - x1, ry1 - y1]}


# the first card's bottom edge locks onto its progress bar; the five cards share one row, so pin it
panels["card_current"]["y1"] = panels["card_next"]["y1"]
panels["card_current"]["h"] = panels["card_current"]["y1"] - panels["card_current"]["y0"]
panels["card_current"]["note"] = "bottom edge pinned to the card row (edge detector locked onto the progress bar)"


def fit_circle(xs, ys):
    A = np.c_[2 * xs, 2 * ys, np.ones_like(xs)]
    b = xs ** 2 + ys ** 2
    sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    cx, cy = sol[0], sol[1]
    r = float(np.sqrt(sol[2] + cx ** 2 + cy ** 2))
    return float(cx), float(cy), r


def ring_fit(cx, cy, r_lo, r_hi, mask_fn):
    ys, xs = np.mgrid[0:H, 0:W]
    d = np.hypot(xs - cx, ys - cy)
    sel = (d >= r_lo) & (d <= r_hi)
    m = mask_fn(im[..., 0], im[..., 1], im[..., 2]) & sel
    if m.sum() < 200:
        return None
    fx, fy, fr = fit_circle(xs[m].astype(float), ys[m].astype(float))
    return {"cx": round(fx, 1), "cy": round(fy, 1), "r": round(fr, 1), "pixels": int(m.sum())}


# outer neon ring (green/cyan, bright and saturated) around the CORE; first guess centre
guess = (823.0, 398.0)
neon = lambda r, g, b: (g > 150) & (b > 90) & (r < 150) & (g > r + 50)
core_ring = ring_fit(*guess, 225, 275, neon)
if core_ring:  # refit with the refined centre to tighten
    core_ring = ring_fit(core_ring["cx"], core_ring["cy"], core_ring["r"] - 14, core_ring["r"] + 14, neon) or core_ring

# black hole horizon: darkest blob near the centre
cx0, cy0 = (core_ring["cx"], core_ring["cy"]) if core_ring else guess
ys, xs = np.mgrid[0:H, 0:W]
dark = (lum < 14) & (np.hypot(xs - cx0, ys - cy0) < 70)
horizon = None
if dark.sum() > 200:
    hx, hy = xs[dark].mean(), ys[dark].mean()
    horizon = {"cx": round(float(hx), 1), "cy": round(float(hy), 1), "r_equiv": round(float(np.sqrt(dark.sum() / np.pi)), 1)}


def centroid(box, mask_fn):
    x0, y0, x1, y1 = box
    sub = im[y0:y1, x0:x1]
    m = mask_fn(sub[..., 0], sub[..., 1], sub[..., 2])
    if m.sum() < 30:
        return None
    yy, xx = np.nonzero(m)
    return {"cx": round(float(xx.mean() + x0), 1), "cy": round(float(yy.mean() + y0), 1), "pixels": int(m.sum())}


sat = lambda r, g, b: (np.maximum(np.maximum(r, g), b) - np.minimum(np.minimum(r, g), b) > 90) & (np.maximum(np.maximum(r, g), b) > 150)
# planet: bright blue/white disc upper right
planet = centroid((1110, 150, 1220, 250), lambda r, g, b: (b > 120) & (b > r + 25))
nodes_win = {  # approximate windows around each agent node (rings + icons are saturated)
    "FURY": (780, 195, 862, 270), "SHURI": (648, 232, 730, 310), "THOR": (908, 232, 990, 310),
    "VISION": (628, 425, 710, 505), "FALCON": (922, 428, 1004, 508), "UATU": (775, 500, 857, 578), "ULTRON": (785, 148, 862, 190),
}
nodes = {k: centroid(v, sat) for k, v in nodes_win.items()}


def text_box(box, thr=150):
    x0, y0, x1, y1 = box
    sub = lum[y0:y1, x0:x1]
    m = sub > thr
    if m.sum() < 8:
        return None
    yy, xx = np.nonzero(m)
    return {"x0": int(xx.min() + x0), "x1": int(xx.max() + x0), "y0": int(yy.min() + y0), "y1": int(yy.max() + y0),
            "height_px": int(yy.max() - yy.min() + 1), "width_px": int(xx.max() - xx.min() + 1)}


def rows_in_window(box, thr=140, min_gap=3):
    """Row centres/left edge/height of bright text rows inside a window (label groups)."""
    x0, y0, x1, y1 = box
    sub = lum[y0:y1, x0:x1] > thr
    ys = np.nonzero(sub.any(axis=1))[0]
    rows, start, prev = [], None, None
    for y in ys:
        if start is None:
            start = prev = y
        elif y - prev > min_gap:
            rows.append((start, prev)); start = prev = y
        else:
            prev = y
    if start is not None:
        rows.append((start, prev))
    out = []
    for a, b in rows:
        band = sub[a:b + 1]
        xs = np.nonzero(band.any(axis=0))[0]
        out.append({"y_centre": int((a + b) / 2 + y0), "height_px": int(b - a + 1), "x_left": int(xs.min() + x0), "x_right": int(xs.max() + x0)})
    return out


LABEL_GROUPS = {
    "files_github_development": (472, 204, 565, 282), "data_documents_models": (482, 470, 560, 545),
    "internet_categories": (1150, 270, 1215, 405), "system_security_performance_uptime": (1155, 468, 1240, 568),
    "logs_patterns_anomalies_NOT_IMPLEMENTED_spec_forbids_logs": (940, 568, 1015, 625),
}
label_groups = {k: rows_in_window(v) for k, v in LABEL_GROUPS.items()}
for g in label_groups.values():
    if len(g) > 1:
        pitches = [g[i + 1]["y_centre"] - g[i]["y_centre"] for i in range(len(g) - 1)]
        g.append({"row_pitch_px_median": int(np.median(pitches))})

# UPPERCASE samples -> cap height; windows chosen tight around the text
TEXT = {
    "panel_title_CHATS": (86, 92, 140, 112), "panel_title_PROJECTS": (86, 382, 170, 400), "panel_title_AGENTS": (86, 574, 150, 592),
    "panel_title_ACTIVITY": (1350, 92, 1440, 112), "panel_title_APPROVALS": (1350, 391, 1470, 409),
    "node_name_FURY": (800, 262, 842, 278), "node_name_THOR": (930, 305, 972, 320), "node_name_ULTRON": (795, 185, 852, 200),
    "approval_label_GPT": (1358, 452, 1392, 470), "approval_label_CLAUDE": (1358, 557, 1415, 574),
    "gauge_label_CPU": (368, 748, 405, 764), "internet_label": (1128, 246, 1208, 262),
    "voice_label": (1352, 832, 1400, 850), "top_HIVE": (86, 18, 148, 38),
}
text = {k: text_box(v) for k, v in TEXT.items()}


def median_colour(box, mask_fn=None):
    x0, y0, x1, y1 = box
    sub = im[y0:y1, x0:x1].reshape(-1, 3)
    if mask_fn is not None:
        m = mask_fn(sub[:, 0], sub[:, 1], sub[:, 2])
        if m.sum() < 5:
            return None
        sub = sub[m]
    return [int(v) for v in np.median(sub, axis=0)]


COLOURS = {
    "panel_interior_chats": median_colour((60, 200, 270, 330)),
    "panel_interior_activity": median_colour((1330, 280, 1630, 345)),
    "panel_border_left_chats": [int(v) for v in im[200, panels["chats"]["x0"]]],
    "panel_border_top_chats": [int(v) for v in im[panels["chats"]["y0"], 150]],
    "approve_button": median_colour((1423, 452, 1500, 472), lambda r, g, b: (g > r + 30) & (g > 60)),
    "edit_button": median_colour((1507, 452, 1565, 472), lambda r, g, b: (b > r + 40) & (b > 90)),
    "reject_button": median_colour((1573, 452, 1632, 472), lambda r, g, b: (r > g + 50) & (r > 90)),
    "chip_gpt": median_colour((415, 17, 470, 36), lambda r, g, b: (g > r + 20) & (g > 80)),
    "chip_codex": median_colour((492, 17, 560, 36), lambda r, g, b: (b > g + 20) & (b > 90)),
    "chip_claude": median_colour((580, 17, 650, 36), lambda r, g, b: (r > b + 40) & (r > 120)),
    "ultron_badge_green": median_colour((970, 12, 1010, 42), lambda r, g, b: (g > r + 40) & (g > 120)),
    "gauge_cpu": median_colour((352, 685, 420, 745), lambda r, g, b: (g > 150) & (b > 120) & (g > r + 40)),
    "gauge_ram": median_colour((432, 685, 496, 745), lambda r, g, b: (b > 150) & (b > r + 50)),
    "gauge_gpu": median_colour((660, 685, 722, 745), lambda r, g, b: (b > 120) & (r > 90) & (g < 100)),
    "bar_gpt": median_colour((985, 680, 1075, 692), lambda r, g, b: (g > 150) & (g > r + 40)),
    "bar_codex": median_colour((985, 728, 1050, 740), lambda r, g, b: (b > 120) & (r > 80) & (g < 120)),
    "orbit_ring_neon_sample": median_colour((int(core_ring["cx"] - core_ring["r"]) - 4, int(core_ring["cy"]) - 6, int(core_ring["cx"] - core_ring["r"]) + 6, int(core_ring["cy"]) + 6), lambda r, g, b: (np.maximum(np.maximum(r, g), b) > 120)) if core_ring else None,
    "background_nebula_violet": median_colour((10, 860, 120, 930)),
    "background_nebula_blue": median_colour((1440, 760, 1560, 830)),
    "background_dark_space": median_colour((300, 380, 360, 440)),
    "text_primary_sample": [int(v) for v in im[panels['chats']['y0'] + 25:panels['chats']['y0'] + 31, 90:140].reshape(-1, 3).max(axis=0)],
}

# gutters between panels (px at 1671x941)
def gap_x(a, b): return panels[b]["x0"] - panels[a]["x1"]
def gap_y(a, b): return panels[b]["y0"] - panels[a]["y1"]
gutters = {
    "chats_to_projects_y": gap_y("chats", "projects"), "projects_to_agents_y": gap_y("projects", "agents"),
    "activity_to_approvals_y": gap_y("activity", "approvals"), "resources_to_limits_x": gap_x("resources", "limits"),
    "card_current_to_next_x": gap_x("card_current", "card_next"), "card_next_to_context_x": gap_x("card_next", "card_context"),
    "card_context_to_external_x": gap_x("card_context", "card_external"), "card_external_to_layout_x": gap_x("card_external", "card_layout"),
    "left_rail_to_center_x": panels["card_current"]["x0"] - panels["chats"]["x1"], "center_to_right_rail_x": panels["activity"]["x0"] - panels["card_layout"]["x1"],
    "cards_to_core_note": "no panel; the CORE art starts directly below the card row",
    "resources_to_composer_y": gap_y("resources", "composer"),
}

# polar coordinates of the nodes relative to the neon ring centre, radius in units of the ring radius
polar = {}
if core_ring:
    for k, n in nodes.items():
        if n:
            dx, dy = n["cx"] - core_ring["cx"], n["cy"] - core_ring["cy"]
            polar[k] = {"angle_deg": round(float(np.degrees(np.arctan2(dy, dx))), 1), "r_over_ring": round(float(np.hypot(dx, dy) / core_ring["r"]), 3)}
    if planet:
        dx, dy = planet["cx"] - core_ring["cx"], planet["cy"] - core_ring["cy"]
        polar["INTERNET_planet"] = {"angle_deg": round(float(np.degrees(np.arctan2(dy, dx))), 1), "r_over_ring": round(float(np.hypot(dx, dy) / core_ring["r"]), 3)}

out = {
    "source": str(SRC.relative_to(ROOT)), "image_px": {"w": W, "h": H}, "aspect": round(W / H, 4),
    "tolerance_px": 2, "panels": panels, "gutters_px": gutters,
    "core": {"neon_ring": core_ring, "horizon": horizon, "planet": planet, "nodes": nodes, "polar": polar,
             "planet_radius_px_estimate": 42, "node_radius_px_estimate": 33, "estimate_note": "radii of the planet and nodes read from the image (+-3 px); centres are measured"},
    "text_cap_heights_px": text, "label_groups": label_groups, "colours_rgb": COLOURS,
}
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(out, indent=1))
print(json.dumps({"panels": {k: [v["x0"], v["y0"], v["w"], v["h"]] for k, v in panels.items()},
                  "core": out["core"], "gutters": gutters}, indent=0)[:2600])
