#!/usr/bin/env python3
"""Prints what fonts Qt can actually see — run in CI alongside the UI smoke.

A headless runner may expose no usable font at all, and the difference matters:
the same screenshot full of tofu means "the runner has no fonts" or "our font
stack resolves to nothing on this platform", and only this tells them apart.
"""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFont, QFontDatabase, QFontInfo, QFontMetrics

from claude_dongle.utils import UI_FONT

app = QApplication(sys.argv[:1])
families = QFontDatabase.families()
print(f"platform: {sys.platform}  ·  font families visible to Qt: {len(families)}")
print("first families:", ", ".join(families[:8]) or "(none)")
info = QFontInfo(QFont(UI_FONT, 10))
print(f"requested {UI_FONT!r} -> resolved {info.family()!r} (exactMatch={info.exactMatch()})")
w = QFontMetrics(QFont(UI_FONT, 10)).horizontalAdvance("5h session 46%")
print(f"width of a sample string: {w}px")
if not families or w <= 0:
    print("NO USABLE FONT — screenshots from this environment are not "
          "representative of a real desktop", flush=True)
