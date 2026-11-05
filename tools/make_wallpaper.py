#!/usr/bin/env python3
"""Generate assets/hive-wallpaper.jpg: a purely decorative space + circuit wallpaper.

Contents: nebula clouds, stars, faint circuit traces, a vignette. NOTHING ELSE:
no text, digits, gauges, rings, panels, icons, logos or state colours. This script never calls any
text-drawing API (a test greps for that). Deterministic: same seed -> same bytes.

Dev-time tool (Pillow + numpy). The committed JPEG is what the dashboard serves, from this repository only.
Usage: python tools/make_wallpaper.py [--out assets/hive-wallpaper.jpg] [--seed 20261105] [--quality 80]
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

W, H = 2560, 1440
ROOT = Path(__file__).resolve().parents[1]


def fbm(rng: np.random.Generator, w: int, h: int, octaves: int = 6, base: int = 4, persistence: float = 0.55) -> np.ndarray:
    """Fractal value noise in [0, 1] built from smoothly upsampled random grids."""
    out = np.zeros((h, w), dtype=np.float32)
    amp, total = 1.0, 0.0
    for o in range(octaves):
        gw, gh = base * 2 ** o + 1, int(base * 2 ** o * h / w) + 2
        grid = rng.random((gh, gw)).astype(np.float32)
        layer = np.asarray(Image.fromarray((grid * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC), dtype=np.float32) / 255.0
        out += layer * amp
        total += amp
        amp *= persistence
    out /= total
    lo, hi = float(out.min()), float(out.max())
    return (out - lo) / (hi - lo + 1e-9)


def smoothstep(x: np.ndarray, a: float, b: float) -> np.ndarray:
    t = np.clip((x - a) / (b - a), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def nebula(rng: np.random.Generator) -> np.ndarray:
    ys, xs = np.mgrid[0:H, 0:W].astype(np.float32)
    nx, ny = xs / W, ys / H
    img = np.zeros((H, W, 3), dtype=np.float32)
    img[:] = (3, 8, 18)  # deep space base
    palette = [  # (colour, noise threshold, gain, strength)
        ((92, 44, 176), 0.52, 5.0, 0.36), ((34, 96, 210), 0.54, 5.0, 0.32), ((176, 52, 150), 0.60, 6.0, 0.26),
        ((24, 150, 160), 0.62, 6.0, 0.18), ((214, 112, 58), 0.68, 7.0, 0.10),
    ]
    # keep the centre (where the CORE sits) calmer so the live art stays readable: a soft dark ellipse
    centre = np.exp(-(((nx - 0.5) / 0.30) ** 2 + ((ny - 0.45) / 0.34) ** 2))
    calm = 1.0 - 0.72 * centre
    for colour, thr, gain, strength in palette:
        n = fbm(rng, W // 2, H // 2, octaves=6, base=3)
        n = np.asarray(Image.fromarray((n * 255).astype(np.uint8)).resize((W, H), Image.BICUBIC), dtype=np.float32) / 255.0
        # large-scale placement so each colour owns a region
        px, py = rng.random(), rng.random()
        region = np.exp(-(((nx - px) / 0.45) ** 2 + ((ny - py) / 0.5) ** 2))
        mask = smoothstep(n, thr - 0.18, thr - 0.18 + 1.0 / gain) * (0.25 + 0.75 * region) * calm * strength
        img += mask[..., None] * np.array(colour, dtype=np.float32)
    # dust lanes: dark streaks that eat into the clouds
    lanes = fbm(rng, W // 2, H // 2, octaves=5, base=5)
    lanes = np.asarray(Image.fromarray((lanes * 255).astype(np.uint8)).resize((W, H), Image.BICUBIC), dtype=np.float32) / 255.0
    img *= (1.0 - 0.45 * smoothstep(lanes, 0.55, 0.8))[..., None]
    return img


def stars(img: np.ndarray, rng: np.random.Generator) -> None:
    tints = np.array([(255, 255, 255), (205, 225, 255), (255, 235, 205), (190, 210, 255)], dtype=np.float32)

    def stamp(cx: int, cy: int, radius: int, colour: np.ndarray, amount: float) -> None:
        y0, y1, x0, x1 = max(0, cy - radius), min(H, cy + radius + 1), max(0, cx - radius), min(W, cx + radius + 1)
        if y0 >= y1 or x0 >= x1:
            return
        yy, xx = np.mgrid[y0:y1, x0:x1]
        g = np.exp(-(((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * (radius / 2.4) ** 2)))
        img[y0:y1, x0:x1] += g[..., None] * colour * amount

    for _ in range(3200):  # tiny: 1 px points, brightness follows a power law
        x, y = int(rng.integers(0, W)), int(rng.integers(0, H))
        b = (0.15 + 0.85 * rng.random() ** 3) * 255
        img[y, x] += tints[int(rng.integers(0, 4))] * (b / 255.0)
        if rng.random() < 0.15 and x + 1 < W:
            img[y, x + 1] += tints[int(rng.integers(0, 4))] * (b / 255.0) * 0.5
    for _ in range(340):  # medium
        stamp(int(rng.integers(0, W)), int(rng.integers(0, H)), 3, tints[int(rng.integers(0, 4))], 0.9 + 0.5 * rng.random())
    for _ in range(46):  # large soft glows
        cx, cy = int(rng.integers(0, W)), int(rng.integers(0, H))
        stamp(cx, cy, 11, np.array((150, 190, 255), dtype=np.float32), 0.30)
        stamp(cx, cy, 3, np.array((255, 255, 255), dtype=np.float32), 1.2)


def circuits(rng: np.random.Generator) -> Image.Image:
    """Faint right-angle / 45-degree traces and node rings (lines and ellipses only)."""
    layer = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(layer)
    grid = 40
    for _ in range(170):
        x, y = int(rng.integers(0, W // grid)) * grid, int(rng.integers(0, H // grid)) * grid
        # fewer traces through the middle, more toward the edges
        if abs(x / W - 0.5) < 0.18 and abs(y / H - 0.45) < 0.22 and rng.random() < 0.7:
            continue
        pts = [(x, y)]
        dx, dy = [(1, 0), (0, 1), (-1, 0), (0, -1)][int(rng.integers(0, 4))]
        for _seg in range(int(rng.integers(3, 8))):
            length = int(rng.integers(2, 7)) * grid
            x, y = x + dx * length, y + dy * length
            pts.append((x, y))
            if rng.random() < 0.5:  # 45-degree jog
                jog = int(rng.integers(1, 3)) * grid
                sx, sy = (1 if rng.random() < 0.5 else -1), (1 if rng.random() < 0.5 else -1)
                x, y = x + sx * jog, y + sy * jog
                pts.append((x, y))
            dx, dy = (dy, dx) if rng.random() < 0.5 else (-dy, -dx)
        alpha = int(26 + 44 * rng.random())
        d.line(pts, fill=alpha, width=1, joint="curve")
        for (px, py) in (pts[0], pts[-1]):
            r = int(rng.integers(3, 6))
            d.ellipse((px - r, py - r, px + r, py + r), outline=min(255, alpha + 40), width=1)
    return layer


def vignette(img: np.ndarray) -> None:
    ys, xs = np.mgrid[0:H, 0:W].astype(np.float32)
    d = np.sqrt(((xs / W - 0.5) / 0.75) ** 2 + ((ys / H - 0.5) / 0.75) ** 2)
    img *= (1.0 - 0.55 * smoothstep(d, 0.55, 1.05))[..., None]


def build(seed: int) -> Image.Image:
    rng = np.random.default_rng(seed)
    img = nebula(rng)
    stars(img, rng)
    tr = circuits(rng)
    glow = tr.filter(ImageFilter.GaussianBlur(2.2))
    tr_arr = np.asarray(ImageChops.add(tr, glow), dtype=np.float32) / 255.0
    img += tr_arr[..., None] * np.array((70, 160, 235), dtype=np.float32) * 0.42
    vignette(img)
    # a whisper of grain so gradients do not band after JPEG
    img += rng.normal(0, 1.4, size=img.shape).astype(np.float32)
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8), "RGB")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "assets/hive-wallpaper.jpg"))
    ap.add_argument("--seed", type=int, default=20261105)
    ap.add_argument("--quality", type=int, default=80)
    a = ap.parse_args()
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    build(a.seed).save(out, "JPEG", quality=a.quality, optimize=True, progressive=False, subsampling=2)
    print(f"wrote {out} ({out.stat().st_size / 1024:.0f} KB, {W}x{H}, seed {a.seed}, q{a.quality})")


if __name__ == "__main__":
    main()
