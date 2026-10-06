"""Light / dark appearance. The canvas items read ``current()`` when they
paint, so switching themes only needs a repaint and a new app palette."""
from __future__ import annotations

import os
from dataclasses import dataclass

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
THEMES = ("light", "dark")
DEFAULT_THEME = "light"


@dataclass(frozen=True)
class Theme:
    name: str
    canvas_bg: str
    grid: str
    window: str
    base: str
    alt: str
    text: str
    subtext: str
    border: str
    hover: str
    accent: str
    card_base: str      # region colour is blended into this for the card body
    card_mix: float     # 0..1 share of card_base in the card body
    header_mix: float   # same for the header band
    thumb_bg: str
    label: str
    shadow: str
    icon: str           # neutral icon colour
    switch_off: str


LIGHT = Theme("light", canvas_bg="#eef1f5", grid="#0000000d", window="#f7f8fa", base="#ffffff",
              alt="#f3f4f6", text="#1f2937", subtext="#64748b", border="#d9dee5", hover="#e8edf5",
              accent="#2f6fed", card_base="#ffffff", card_mix=0.88, header_mix=0.78,
              thumb_bg="#dfe3ea", label="#374151", shadow="#0f172a22", icon="#475569",
              switch_off="#cbd5e1")
DARK = Theme("dark", canvas_bg="#1b1c1f", grid="#ffffff0e", window="#2b2d31", base="#232428",
             alt="#2b2d31", text="#e6e6e6", subtext="#9aa3af", border="#3a3d43", hover="#3a3f48",
             accent="#4f8cff", card_base="#1b1c1f", card_mix=0.84, header_mix=0.70,
             thumb_bg="#141518", label="#d1d5db", shadow="#00000066", icon="#cbd5e1",
             switch_off="#4b5563")

_current = LIGHT


def current() -> Theme:
    return _current


def set_theme(name: str) -> Theme:
    global _current
    _current = DARK if name == "dark" else LIGHT
    return _current


def c(value: str) -> QColor:
    """'#rrggbb' or '#rrggbbaa' (CSS order) to QColor."""
    if len(value) == 9:
        col = QColor(value[:7])
        col.setAlpha(int(value[7:], 16))
        return col
    return QColor(value)


def blend(color: QColor, base: QColor, t: float) -> QColor:
    """Mix ``t`` of ``base`` into ``color``."""
    return QColor(round(color.red() * (1 - t) + base.red() * t),
                  round(color.green() * (1 - t) + base.green() * t),
                  round(color.blue() * (1 - t) + base.blue() * t))


def palette(t: Theme) -> QPalette:
    p = QPalette()
    p.setColor(QPalette.Window, c(t.window))
    p.setColor(QPalette.WindowText, c(t.text))
    p.setColor(QPalette.Base, c(t.base))
    p.setColor(QPalette.AlternateBase, c(t.alt))
    p.setColor(QPalette.ToolTipBase, c(t.base))
    p.setColor(QPalette.ToolTipText, c(t.text))
    p.setColor(QPalette.Text, c(t.text))
    p.setColor(QPalette.Button, c(t.base))
    p.setColor(QPalette.ButtonText, c(t.text))
    p.setColor(QPalette.Highlight, c(t.accent))
    p.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    p.setColor(QPalette.PlaceholderText, c(t.subtext))
    p.setColor(QPalette.Mid, c(t.border))
    for role in (QPalette.Text, QPalette.ButtonText, QPalette.WindowText):
        p.setColor(QPalette.Disabled, role, c(t.subtext))
    return p


def stylesheet(t: Theme) -> str:
    return f"""
    QToolBar {{ background: {t.base}; border: none; border-bottom: 1px solid {t.border};
                padding: 4px 8px; spacing: 2px; }}
    QToolBar QToolButton {{ padding: 5px 9px; border-radius: 6px; color: {t.text}; }}
    QToolBar QToolButton:hover {{ background: {t.hover}; }}
    QToolBar QToolButton:checked {{ background: {t.hover}; }}
    QToolBar::separator {{ background: {t.border}; width: 1px; margin: 6px 6px; }}
    QMenuBar {{ background: {t.window}; }}
    QStatusBar {{ background: {t.window}; border-top: 1px solid {t.border}; }}
    QDockWidget {{ titlebar-close-icon: none; }}
    """


FONT_FAMILY = "Pretendard"


def load_fonts() -> str | None:
    """Register the bundled Pretendard font; returns the family name if available."""
    family = None
    folder = os.path.join(ASSETS, "fonts")
    for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        if name.lower().endswith((".otf", ".ttf")):
            fid = QFontDatabase.addApplicationFont(os.path.join(folder, name))
            fams = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
            family = family or (fams[0] if fams else None)
    return family


def ui_font(family: str | None) -> QFont:
    f = QFont(family or "")
    f.setPointSizeF(9.5)
    return f
