"""Render a captured terminal transcript to a PNG for the README.

Not part of the eval pipeline - a small presentation helper.
    .venv/bin/python tools/render_capture.py reports/captures/gate.txt reports/images/gate.png "evalkit golden"
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BG, FG, DIM = (24, 26, 31), (222, 226, 233), (128, 136, 150)
COLORS = {"PASS": (94, 190, 130), "FAIL": (233, 108, 108), "DISP": (226, 176, 90),
          "NOEV": (128, 136, 150), "MIX ": (226, 176, 90), "ERR ": (233, 108, 108),
          "OK": (94, 190, 130), "GATE PASSED": (94, 190, 130)}
FONT_CANDIDATES = ["/System/Library/Fonts/Menlo.ttc", "/System/Library/Fonts/Monaco.ttf",
                   "/Library/Fonts/Menlo.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"]
PAD, SIZE, LEADING = 24, 26, 1.45
TOKEN = re.compile(r"PASS|FAIL|DISP|NOEV|MIX |ERR |GATE PASSED|\bOK\b")


def load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def render(src: Path, dst: Path, title: str) -> None:
    lines = src.read_text(encoding="utf-8").rstrip("\n").split("\n")
    if title:
        lines = [f"$ {title}", ""] + lines
    font = load_font(SIZE)
    bold = load_font(SIZE)
    cw = font.getbbox("M")[2] - font.getbbox("M")[0]
    lh = int(SIZE * LEADING)
    width = PAD * 2 + cw * max((len(l) for l in lines), default=40)
    height = PAD * 2 + lh * len(lines) + 34

    img = Image.new("RGB", (width, height), BG)
    d = ImageDraw.Draw(img)
    for i, (x, c) in enumerate([(0, (255, 95, 87)), (1, (254, 188, 46)), (2, (40, 200, 64))]):
        d.ellipse([PAD + i * 20, 14, PAD + i * 20 + 11, 25], fill=c)

    y = PAD + 26
    for line in lines:
        x = PAD
        if line.startswith("$ "):
            d.text((x, y), line, font=bold, fill=(120, 190, 255))
        else:
            pos, last = x, 0
            for m in TOKEN.finditer(line):
                d.text((pos, y), line[last:m.start()], font=font, fill=FG)
                pos += cw * (m.start() - last)
                d.text((pos, y), m.group(), font=bold, fill=COLORS.get(m.group().strip(), FG))
                pos += cw * len(m.group())
                last = m.end()
            d.text((pos, y), line[last:], font=font, fill=FG if last else FG)
        y += lh

    dst.parent.mkdir(parents=True, exist_ok=True)
    img.save(dst)
    print(f"{dst}  {img.width}x{img.height}")


if __name__ == "__main__":
    render(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3] if len(sys.argv) > 3 else "")
