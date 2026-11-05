#!/usr/bin/env python3
"""Convert the supplied wallpaper source to the dashboard's served JPEG, deterministically.

Source : assets/src/hive-wallpaper-v1.png (SHA-256 pinned below; refuses to run on any other file)
Output : assets/hive-wallpaper.jpg, 2560x1440
Params : RGB, Image.LANCZOS resize straight to 2560x1440 (source is 1672x941, so this is a 1.53x upscale),
         JPEG quality 90, 4:2:0 subsampling, optimize=True, progressive=False, no EXIF/ICC.
This script draws nothing and never calls a text API. Dev-time tool (Pillow).
Usage: python tools/convert_wallpaper.py [--out assets/hive-wallpaper.jpg] [--quality 90]
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets/src/hive-wallpaper-v1.png"
SOURCE_SHA256 = "8AD50B3BA7F39462C0BD032A69BE97391388DF71FBC492023E60E48670D3A7A8".lower()
SIZE = (2560, 1440)


def convert(out: Path, quality: int) -> None:
    digest = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    if digest != SOURCE_SHA256:
        raise SystemExit(f"source SHA-256 mismatch: {digest}")
    im = Image.open(SOURCE).convert("RGB").resize(SIZE, Image.LANCZOS)
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out, "JPEG", quality=quality, subsampling=2, optimize=True, progressive=False)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "assets/hive-wallpaper.jpg"))
    ap.add_argument("--quality", type=int, default=90)
    a = ap.parse_args()
    convert(Path(a.out), a.quality)
    print("wrote", a.out)
