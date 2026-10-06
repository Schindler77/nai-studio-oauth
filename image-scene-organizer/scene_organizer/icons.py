"""Lucide line icons (ISC licence, assets/icons) tinted at load time."""
from __future__ import annotations

import os

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from .theme import ASSETS

_cache: dict[tuple[str, str, int, int], QIcon] = {}


def icon(name: str, color: str, size: int = 20, gap: int = 0) -> QIcon:
    """``gap`` adds transparent space on the right (space before a toolbar label)."""
    key = (name, color, size, gap)
    if key in _cache:
        return _cache[key]
    path = os.path.join(ASSETS, "icons", name + ".svg")
    ic = QIcon()
    try:
        with open(path, encoding="utf-8") as f:
            svg = f.read().replace("currentColor", color[:7])
    except OSError:
        _cache[key] = ic
        return ic
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    for scale in (1, 2):  # crisp on high-DPI screens
        pm = QPixmap((size + gap) * scale, size * scale)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        renderer.render(p, QRectF(0, 0, size * scale, size * scale))
        p.end()
        pm.setDevicePixelRatio(scale)
        ic.addPixmap(pm)
    _cache[key] = ic
    return ic
