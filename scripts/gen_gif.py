#!/usr/bin/env python3
"""GIF of the 'Usage' card with the rings animating (0 -> values), offscreen.

Renders the frames through the app's own renderer (UsageRing) and assembles the
GIF with PIL — deterministic, no screen recording, no PII. Reproduces the same
easing (OutCubic) as the real animation.

Usage:
    python scripts/gen_gif.py            # writes docs/rings.gif
    python scripts/gen_gif.py /tmp/out   # another directory
"""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "docs"

from claude_dongle.utils import BG, SURFACE, FG2, UI_FONT
from claude_dongle.dashboard_ui import UsageRing

from PyQt6.QtWidgets import QApplication, QWidget, QLabel, QVBoxLayout, QHBoxLayout, QFrame
from PyQt6.QtGui import QFont, QImage
from PyQt6.QtCore import Qt
from PIL import Image

# fake data (same as the screenshots)
SPECS = [("5h session", 46, 0.517, "2h25  ·  on pace"),
         ("Week", 34, 0.471, "3d 16h  ·  low"),
         ("Fable", 58, 0.471, "3d 16h  ·  high")]

app = QApplication(sys.argv[:1])

W, H = 440, 208
root = QWidget()
root.setObjectName("gifRoot")
root.setFixedSize(W, H)
root.setStyleSheet(f"#gifRoot {{ background: {BG}; }}")
outer = QVBoxLayout(root)
outer.setContentsMargins(16, 14, 16, 14)
card = QFrame()
card.setStyleSheet(f"background: {SURFACE}; border-radius: 16px;")
cbox = QVBoxLayout(card)
cbox.setContentsMargins(18, 15, 18, 15)
title = QLabel("USAGE")
tf = QFont(UI_FONT, 8, QFont.Weight.Bold)
tf.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.4)
title.setFont(tf)
title.setStyleSheet(f"color: {FG2};")
cbox.addWidget(title)
cbox.addSpacing(8)
rings_row = QHBoxLayout()
rings_row.setSpacing(6)
rings = []
for label, tgt, pace, sub in SPECS:
    r = UsageRing(label)
    r._target_pct, r._stale, r._pace, r._sub = tgt, False, pace, sub
    rings.append((r, tgt))
    rings_row.addWidget(r)
cbox.addLayout(rings_row)
outer.addWidget(card)
root.show()
app.processEvents()


def _to_pil(pm):
    img = pm.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    w, h, stride = img.width(), img.height(), img.bytesPerLine()
    ptr = img.constBits(); ptr.setsize(h * stride)
    return Image.frombuffer("RGBA", (w, h), bytes(ptr), "raw", "RGBA", stride, 1)


def _eased(t):   # OutCubic, same as the app
    return 1 - (1 - t) ** 3


NA = 24
seq = [0.0] * 4 + [_eased(i / (NA - 1)) for i in range(NA)] + [1.0] * 18
frames = []
for f in seq:
    for r, tgt in rings:
        r._display_pct = tgt * f
    frames.append(_to_pil(root.grab()).convert("RGB"))

# consistent palette (from the final frame) -> no flicker between frames
ref = frames[-1].convert("P", palette=Image.Palette.ADAPTIVE, colors=128)
frames_p = [fr.quantize(palette=ref, dither=Image.Dither.NONE) for fr in frames]
OUT.mkdir(parents=True, exist_ok=True)
gif = OUT / "rings.gif"
frames_p[0].save(gif, save_all=True, append_images=frames_p[1:],
                 duration=40, loop=0, optimize=True, disposal=2)
print("OK", gif, os.path.getsize(gif) // 1024, "KB")
