"""Tips: short text in the sidebar, and a popup that shows each tip as an
animated picture (drawn in code so it follows the theme and language)."""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QKeySequence, QLinearGradient, QPainter, QPainterPath, QPen, \
    QShortcut
from PySide6.QtWidgets import (QCheckBox, QDialog, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout,
                               QWidget)

from . import theme
from .i18n import tr

TIPS = [
    {"key": "drag", "title": "Reorder with Auto-Arrange",
     "text": "Drag images into the order you want. With Auto-Arrange ON, the other images "
             "move aside and the row stays in order."},
    {"key": "lock", "title": "Protect confirmed images",
     "text": "Lock the images you have confirmed (Ctrl+L). New imports never push them around."},
    {"key": "viewer", "title": "Look at an image closely",
     "text": "Double-click a thumbnail to see it large. Wheel zooms, 100% shows real pixels."},
    {"key": "wheel", "title": "Zoom vs. thumbnail size",
     "text": "Ctrl+Wheel changes the thumbnail size; the wheel alone zooms the canvas."},
    {"key": "cancel", "title": "Cancel a drag",
     "text": "Right-click while dragging cancels the move and puts everything back."},
    {"key": "save", "title": "Reuse a region in another project",
     "text": "Save a region on its own (⋯ → Save Region) and load it into another project."},
]

PERIOD = 4.8  # seconds per animation loop
HUES = [205, 30, 140, 265, 350, 175, 50, 300, 95]


def _ease(x: float) -> float:
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)


def _phase(t: float, a: float, b: float) -> float:
    return _ease((t - a) / (b - a))


# ------------------------------------------------------------ drawing helpers
def _font(px: int, weight: QFont.Weight = QFont.Normal) -> QFont:
    f = QFont()
    f.setPixelSize(px)
    f.setWeight(weight)
    return f


def _text(p, rect: QRectF, text: str, color: QColor, px: int = 13, weight=QFont.Normal,
          align=Qt.AlignLeft | Qt.AlignVCenter) -> None:
    p.setFont(_font(px, weight))
    p.setPen(color)
    p.drawText(rect, align | Qt.TextWordWrap, text)


def _thumb(p, r: QRectF, n: int, *, locked=False, tilt=0.0, shadow=False, label=True,
           selected=False, alpha=1.0, new=False) -> None:
    t = theme.current()
    p.save()
    p.setOpacity(p.opacity() * alpha)
    if tilt:
        c = r.center()
        p.translate(c)
        p.rotate(tilt)
        p.translate(-c)
    if shadow:
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 55))
        p.drawRoundedRect(r.translated(0, 7).adjusted(2, 2, 2, 2), 6, 6)
    hue = HUES[(n - 1) % len(HUES)]
    g = QLinearGradient(r.topLeft(), r.bottomLeft())
    g.setColorAt(0, QColor.fromHsv(hue, 90 if not new else 40, 240))
    g.setColorAt(1, QColor.fromHsv((hue + 20) % 360, 150 if not new else 70, 170))
    path = QPainterPath()
    path.addRoundedRect(r, 6, 6)
    p.fillPath(path, g)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(255, 255, 255, 120))
    p.drawEllipse(QPointF(r.right() - r.width() * 0.28, r.top() + r.height() * 0.32), r.height() * 0.14,
                  r.height() * 0.14)
    p.setBrush(QColor(20, 24, 40, 150))
    p.drawRect(QRectF(r.left() + r.width() * 0.45, r.bottom() - r.height() * 0.42, r.width() * 0.08,
                      r.height() * 0.42))
    if selected:
        p.setPen(QPen(theme.c(t.accent), 3))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(r.adjusted(-1, -1, 1, 1), 7, 7)
    if locked:
        s = 16
        x, y = r.right() - s - 4, r.bottom() - s - 4
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 150))
        p.drawRoundedRect(QRectF(x, y, s, s), 4, 4)
        p.setPen(QPen(QColor("#fff"), 1.6))
        p.setBrush(Qt.NoBrush)
        p.drawArc(QRectF(x + 5, y + 2.5, 6, 7), 0, 180 * 16)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#fff"))
        p.drawRoundedRect(QRectF(x + 4, y + 7, 8, 6), 1, 1)
    if label:
        txt = f"N{n - 6}" if new else str(n).zfill(2)
        _text(p, QRectF(r.left(), r.bottom() + 2, r.width(), 16), txt, theme.c(t.label), 11, QFont.DemiBold,
              Qt.AlignHCenter | Qt.AlignTop)
    p.restore()


def _card(p, r: QRectF, color: str, title: str, switch: bool | None = True) -> None:
    t = theme.current()
    col = QColor(color)
    base = theme.c(t.card_base)
    p.setPen(QPen(theme.blend(col, base, 0.4), 1.2))
    p.setBrush(theme.blend(col, base, t.card_mix))
    p.drawRoundedRect(r, 10, 10)
    head = QPainterPath()
    head.addRoundedRect(QRectF(r.left(), r.top(), r.width(), 30), 10, 10)
    head.addRect(QRectF(r.left(), r.top() + 15, r.width(), 15))
    p.fillPath(head.simplified(), theme.blend(col, base, t.header_mix))
    p.setPen(Qt.NoPen)
    p.setBrush(col)
    p.drawEllipse(QPointF(r.left() + 16, r.top() + 15), 6, 6)
    _text(p, QRectF(r.left() + 28, r.top(), r.width() - (160 if switch is not None else 36), 30), title,
          theme.c(t.text), 14, QFont.Bold)
    if switch is not None:
        sw = QRectF(r.right() - 118, r.top() + 5, 108, 20)
        p.setPen(Qt.NoPen)
        p.setBrush(theme.c(t.accent) if switch else theme.c(t.switch_off))
        p.drawRoundedRect(sw, 10, 10)
        p.setBrush(QColor("#fff"))
        p.drawEllipse(QRectF(sw.left() + 3, sw.top() + 3, 14, 14))
        _text(p, sw.adjusted(20, 0, -6, 0), tr("Auto-Arrange ON") if switch else tr("Auto-Arrange OFF"),
              QColor("#fff"), 10, QFont.DemiBold, Qt.AlignCenter)


def _badge(p, c: QPointF, text: str, color: QColor | None = None) -> None:
    p.setPen(Qt.NoPen)
    p.setBrush(color or theme.c(theme.current().accent))
    p.drawEllipse(c, 11, 11)
    _text(p, QRectF(c.x() - 11, c.y() - 11, 22, 22), text, QColor("#fff"), 12, QFont.Bold, Qt.AlignCenter)


def _arrow(p, a: QPointF, b: QPointF, color: QColor, dashed=False, bend=0.0, width=2.2) -> None:
    path = QPainterPath(a)
    mid = (a + b) / 2 + QPointF(0, bend)
    path.quadTo(mid, b)
    p.setPen(QPen(color, width, Qt.DashLine if dashed else Qt.SolidLine, Qt.RoundCap))
    p.setBrush(Qt.NoBrush)
    p.drawPath(path)
    ang = math.atan2(b.y() - mid.y(), b.x() - mid.x())
    head = QPainterPath(b)
    for da in (2.6, -2.6):
        head.moveTo(b)
        head.lineTo(b.x() + 10 * math.cos(ang + da), b.y() + 10 * math.sin(ang + da))
    p.setPen(QPen(color, width, Qt.SolidLine, Qt.RoundCap))
    p.drawPath(head)


def _mouse(p, c: QPointF, part: str) -> None:
    """Mouse icon; part = 'left' | 'right' | 'wheel' highlighted."""
    t = theme.current()
    body = QRectF(c.x() - 14, c.y() - 22, 28, 44)
    p.setPen(QPen(theme.c(t.subtext), 1.6))
    p.setBrush(theme.c(t.base))
    p.drawRoundedRect(body, 14, 14)
    hl = QColor("#f59e0b")
    if part in ("left", "right"):
        half = QPainterPath()
        x = body.left() if part == "left" else c.x()
        clip = QRectF(x, body.top(), 14, 18)
        half.addRoundedRect(body, 14, 14)
        sub = QPainterPath()
        sub.addRect(clip)
        p.fillPath(half.intersected(sub), hl)
    p.setPen(QPen(theme.c(t.subtext), 1.4))
    p.drawLine(QPointF(c.x(), body.top()), QPointF(c.x(), body.top() + 18))
    p.drawLine(QPointF(body.left(), body.top() + 18), QPointF(body.right(), body.top() + 18))
    p.setPen(Qt.NoPen)
    p.setBrush(hl if part == "wheel" else theme.c(t.subtext))
    p.drawRoundedRect(QRectF(c.x() - 2.5, body.top() + 5, 5, 9), 2.5, 2.5)


def _keycap(p, r: QRectF, text: str) -> None:
    t = theme.current()
    p.setPen(QPen(theme.c(t.border), 1.2))
    p.setBrush(theme.c(t.base))
    p.drawRoundedRect(r, 5, 5)
    _text(p, r, text, theme.c(t.text), 12, QFont.Bold, Qt.AlignCenter)


def _cursor(p, tip: QPointF) -> None:
    path = QPainterPath(tip)
    for dx, dy in ((0, 17), (4.5, 13), (8, 20), (10.5, 19), (7, 12), (12.5, 12)):
        path.lineTo(tip.x() + dx, tip.y() + dy)
    path.closeSubpath()
    p.setPen(QPen(QColor("#111"), 1.2))
    p.setBrush(QColor("#fff"))
    p.drawPath(path)


# ----------------------------------------------------------- the pictures
def _row(left: float, top: float, w: float, h: float, gap: float, n: int) -> list[QRectF]:
    return [QRectF(left + i * (w + gap), top, w, h) for i in range(n)]


def draw_drag(p, r: QRectF, t: float) -> None:
    th = theme.current()
    w, h, gap = 74, 46, 12
    card = QRectF(r.left() + 20, r.top() + 58, 6 * w + 5 * gap + 28, h + 64)
    _card(p, card, "#4a86e8", tr("First Meeting"))
    slots = _row(card.left() + 14, card.top() + 42, w, h, gap, 6)
    a = _phase(t, 0.18, 0.62)
    lift = math.sin(math.pi * a)
    order = {1: 0 + a, 2: 1 + a, 3: 2 - 2 * a, 4: 3, 5: 4, 6: 5}
    if 0.02 < a < 0.98:
        ph = QRectF(slots[0])
        p.setPen(QPen(theme.c(th.accent), 2, Qt.DashLine))
        fill = theme.c(th.accent)
        fill.setAlpha(30)
        p.setBrush(fill)
        p.drawRoundedRect(ph, 6, 6)
    for n in (1, 2, 4, 5, 6):
        x = slots[0].left() + order[n] * (w + gap)
        _thumb(p, QRectF(x, slots[0].top(), w, h), n)
    x3 = slots[0].left() + order[3] * (w + gap)
    r3 = QRectF(x3, slots[0].top() - 16 * lift, w, h)
    _thumb(p, r3, 3, tilt=-6 * lift, shadow=lift > 0.05, selected=True, label=lift < 0.15)
    if t < 0.7:
        _cursor(p, r3.center() + QPointF(6, 4))
    _badge(p, QPointF(r.left() + 30, r.top() + 14), "1")
    _text(p, QRectF(r.left() + 48, r.top() + 2, 420, 24),
          tr("Move 03 to the front → 01 and 02 move back"), theme.c(th.text), 14, QFont.DemiBold)
    _badge(p, QPointF(card.right() + 26, card.top() + 20), "2")
    _text(p, QRectF(card.right() + 44, card.top() + 4, r.right() - card.right() - 50, 70),
          tr("Auto-Arrange ON keeps the row in order: the others shift by themselves."),
          theme.c(th.subtext), 13)
    _arrow(p, QPointF(slots[2].center().x(), card.top() - 4), QPointF(slots[0].center().x() + 6, card.top() - 4),
           theme.c(th.accent), bend=-22)
    done = _phase(t, 0.66, 0.8)
    res_top = card.bottom() + 22
    _badge(p, QPointF(r.left() + 30, res_top + 12), "✓", QColor("#10b981"))
    _text(p, QRectF(r.left() + 48, res_top, 520, 24),
          tr("Result: 03 is first and 01, 02 kept their order behind it."), theme.c(th.text), 14,
          QFont.DemiBold)
    for i, n in enumerate((3, 1, 2, 4, 5, 6)):
        rr = QRectF(card.left() + 14 + i * (w + gap), res_top + 34, w, h)
        _thumb(p, rr, n, alpha=0.25 + 0.75 * done, selected=(n == 3 and done > 0.5))


def draw_lock(p, r: QRectF, t: float) -> None:
    th = theme.current()
    w, h, gap = 74, 46, 12
    card = QRectF(r.left() + 20, r.top() + 40, 6 * w + 5 * gap + 28, h + 64)
    _card(p, card, "#e05252", tr("Battle"))
    slots = _row(card.left() + 14, card.top() + 42, w, h, gap, 6)
    for i in range(3):
        _thumb(p, slots[i], i + 1, locked=True)
    for i in range(3):
        a = _phase(t, 0.15 + i * 0.12, 0.45 + i * 0.12)
        start = QPointF(r.right() - 60, r.top() + 10 + i * 18)
        dst = slots[3 + i].topLeft()
        pos = start + (dst - start) * a
        _thumb(p, QRectF(pos.x(), pos.y(), w, h), 7 + i, new=True, alpha=0.4 + 0.6 * a, label=a > 0.95)
    folder = QRectF(r.right() - 120, r.top() + 2, 100, 30)
    p.setPen(QPen(QColor("#f59e0b"), 1.4))
    p.setBrush(QColor(245, 158, 11, 40))
    p.drawRoundedRect(folder, 6, 6)
    _text(p, folder, tr("Import"), theme.c(th.text), 12, QFont.DemiBold, Qt.AlignCenter)
    p.setPen(QPen(QColor("#f59e0b"), 2, Qt.DashLine))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(QRectF(slots[0].left() - 6, slots[0].top() - 6, 3 * w + 2 * gap + 12, h + 30), 8, 8)
    _text(p, QRectF(r.left() + 20, r.top() + 4, 520, 26),
          tr("Locked 01–03 stay exactly where they are."), theme.c(th.text), 14, QFont.DemiBold)
    _text(p, QRectF(r.left() + 20, card.bottom() + 16, r.width() - 40, 44),
          tr("New images are added after them — even if you drop them at the front."), theme.c(th.subtext), 13)


def draw_viewer(p, r: QRectF, t: float) -> None:
    th = theme.current()
    w, h, gap = 64, 40, 10
    card = QRectF(r.left() + 20, r.top() + 50, 2 * w + gap + 28, 2 * (h + 18) + 52)
    _card(p, card, "#4caf6a", tr("Flashback"), switch=None)
    cells = [QRectF(card.left() + 14 + (i % 2) * (w + gap), card.top() + 42 + (i // 2) * (h + 22), w, h)
             for i in range(4)]
    for i, c in enumerate(cells):
        _thumb(p, c, i + 1, selected=(i == 1))
    k = (t * 2) % 1.0
    for j in range(2):
        rad = 10 + 22 * ((k + j * 0.35) % 1.0)
        p.setPen(QPen(QColor(245, 158, 11, int(220 * (1 - (k + j * 0.35) % 1.0))), 2))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(cells[1].center(), rad, rad)
    _cursor(p, cells[1].center() + QPointF(4, 4))
    _text(p, QRectF(card.left(), card.bottom() + 8, card.width(), 20), tr("Double-click"), theme.c(th.text), 13,
          QFont.DemiBold, Qt.AlignHCenter)
    big = QRectF(card.right() + 70, r.top() + 10, r.right() - card.right() - 90, r.height() - 30)
    _arrow(p, QPointF(card.right() + 10, card.center().y()), QPointF(big.left() - 10, card.center().y()),
           theme.c(th.accent))
    p.setPen(QPen(theme.c(th.border), 1.2))
    p.setBrush(QColor("#0e0e10"))
    p.drawRoundedRect(big, 8, 8)
    zoom = 1.0 + 0.5 * _phase(t, 0.35, 0.7) - 0.5 * _phase(t, 0.85, 1.0)
    img = QRectF(0, 0, big.width() * 0.55 * zoom, big.height() * 0.62 * zoom)
    img.moveCenter(big.center() + QPointF(0, 12))
    p.save()
    p.setClipRect(big.adjusted(2, 34, -2, -2))
    _thumb(p, img, 2, label=False)
    p.restore()
    bar = QRectF(big.left(), big.top(), big.width(), 30)
    x = bar.left() + 10
    for label in (tr("Fit to Screen"), "100%"):
        fw = QFontMetrics(_font(11, QFont.DemiBold)).horizontalAdvance(label) + 16
        pill = QRectF(x, bar.top() + 6, fw, 18)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 40))
        p.drawRoundedRect(pill, 9, 9)
        _text(p, pill, label, QColor("#eee"), 11, QFont.DemiBold, Qt.AlignCenter)
        x += fw + 8
    _text(p, bar.adjusted(0, 0, -10, 0), f"{round(zoom * 100)}%", QColor("#eee"), 12, QFont.Bold,
          Qt.AlignRight | Qt.AlignVCenter)
    _mouse(p, QPointF(big.right() - 34, big.bottom() - 40), "wheel")
    _text(p, QRectF(big.left(), big.bottom() + 2, big.width(), 20),
          tr("Wheel = zoom · drag = move · Esc or double-click = close"), theme.c(th.subtext), 12,
          align=Qt.AlignHCenter | Qt.AlignTop)


def draw_wheel(p, r: QRectF, t: float) -> None:
    th = theme.current()
    s = 0.5 + 0.5 * math.sin(2 * math.pi * t)
    half = (r.width() - 60) / 2
    left = QRectF(r.left() + 20, r.top() + 34, half, r.height() - 80)
    right = QRectF(left.right() + 20, left.top(), half, left.height())
    for panel in (left, right):
        p.setPen(QPen(theme.c(th.border), 1.2))
        p.setBrush(theme.c(th.canvas_bg))
        p.drawRoundedRect(panel, 10, 10)
    _text(p, QRectF(left.left(), r.top() + 4, half, 24), tr("Wheel = zoom the whole canvas"), theme.c(th.text), 14,
          QFont.DemiBold, Qt.AlignHCenter)
    _text(p, QRectF(right.left(), r.top() + 4, half, 24), tr("Ctrl + Wheel = thumbnail size only"),
          theme.c(th.text), 14, QFont.DemiBold, Qt.AlignHCenter)
    p.save()
    p.setClipRect(left.adjusted(2, 2, -2, -2))
    k = 0.85 + 0.5 * s
    c = left.center() - QPointF(0, 14)
    for i, (dx, dy, col) in enumerate(((-118, -62, "#4a86e8"), (8, -62, "#e05252"), (-118, 10, "#4caf6a"),
                                         (8, 10, "#d6be3a"))):
        rr = QRectF(c.x() + dx * k, c.y() + dy * k, 110 * k, 62 * k)
        p.setPen(QPen(QColor(col), 1.2))
        p.setBrush(theme.blend(QColor(col), theme.c(th.card_base), 0.75))
        p.drawRoundedRect(rr, 6, 6)
        for j in range(3):
            _thumb(p, QRectF(rr.left() + 6 * k + j * 31 * k, rr.top() + 20 * k, 27 * k, 18 * k), i * 3 + j + 1,
                   label=False)
    p.restore()
    _mouse(p, QPointF(left.right() - 34, left.bottom() - 34), "wheel")
    card = QRectF(right.left() + 20, right.top() + 18, right.width() - 40, right.height() - 86)
    _card(p, card, "#9a6ce0", tr("Ending"))
    tw = 46 + 26 * s
    x, y = card.left() + 12, card.top() + 40
    for n in range(1, 8):
        if x + tw > card.right() - 12:
            x, y = card.left() + 12, y + tw * 0.62 + 20
        if y + tw * 0.62 > card.bottom() - 6:
            break
        _thumb(p, QRectF(x, y, tw, tw * 0.62), n)
        x += tw + 10
    _keycap(p, QRectF(right.right() - 110, right.bottom() - 46, 44, 26), "Ctrl")
    _text(p, QRectF(right.right() - 66, right.bottom() - 46, 12, 26), "+", theme.c(th.text), 14, QFont.Bold,
          Qt.AlignCenter)
    _mouse(p, QPointF(right.right() - 30, right.bottom() - 34), "wheel")


def draw_cancel(p, r: QRectF, t: float) -> None:
    th = theme.current()
    w, h, gap = 74, 46, 12
    card = QRectF(r.left() + 20, r.top() + 40, 6 * w + 5 * gap + 28, h + 64)
    _card(p, card, "#4a86e8", tr("First Meeting"))
    slots = _row(card.left() + 14, card.top() + 42, w, h, gap, 6)
    out = _phase(t, 0.1, 0.45)
    back = _phase(t, 0.62, 0.85)
    a = out * (1 - back)
    for i in (0, 1, 3, 4, 5):
        _thumb(p, slots[i], i + 1)
    src = slots[2]
    far = QPointF(src.left() + 170, src.top() + 72)
    pos = src.topLeft() + (far - src.topLeft()) * a
    p.setPen(QPen(theme.c(th.subtext), 1.4, Qt.DashLine))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(src, 6, 6)
    if 0.45 < t < 0.9:
        _arrow(p, far + QPointF(w / 2, -6), QPointF(src.center().x() + 8, src.bottom() + 8), QColor("#f59e0b"),
               dashed=True, bend=40)
    _thumb(p, QRectF(pos.x(), pos.y(), w, h), 3, tilt=-6 * a, shadow=a > 0.05, selected=True)
    _mouse(p, QPointF(card.right() + 46, card.center().y() + 10), "right" if 0.45 < t < 0.7 else "left")
    _text(p, QRectF(card.right() + 10, card.center().y() + 40, 110, 40),
          tr("Right-click") if 0.45 < t < 0.7 else tr("Dragging…"), theme.c(th.text), 12, QFont.DemiBold,
          Qt.AlignHCenter | Qt.AlignTop)
    _text(p, QRectF(r.left() + 20, r.top() + 4, 560, 26), tr("Right-click during a drag = cancel"),
          theme.c(th.text), 14, QFont.DemiBold)
    _text(p, QRectF(r.left() + 20, card.bottom() + 96, r.width() - 40, 40),
          tr("Nothing changes: the image goes back to its place and no menu opens. Esc does the same."),
          theme.c(th.subtext), 13)


def draw_save(p, r: QRectF, t: float) -> None:
    th = theme.current()
    w, h, gap = 46, 30, 8
    card = QRectF(r.left() + 20, r.top() + 60, 3 * w + 2 * gap + 24, h + 56)
    _card(p, card, "#e05252", tr("Battle"), switch=None)
    for i in range(3):
        _thumb(p, QRectF(card.left() + 12 + i * (w + gap), card.top() + 40, w, h), i + 1, locked=i == 0,
               label=False)
    file_r = QRectF(card.right() + 70, card.top() + 4, 74, 90)
    _arrow(p, QPointF(card.right() + 8, card.center().y()), QPointF(file_r.left() - 8, card.center().y()),
           theme.c(th.accent))
    a = _phase(t, 0.1, 0.35)
    p.setOpacity(0.3 + 0.7 * a)
    fold = QPainterPath()
    fold.moveTo(file_r.topLeft())
    fold.lineTo(file_r.right() - 18, file_r.top())
    fold.lineTo(file_r.right(), file_r.top() + 18)
    fold.lineTo(file_r.bottomRight())
    fold.lineTo(file_r.bottomLeft())
    fold.closeSubpath()
    p.setPen(QPen(theme.c(th.subtext), 1.4))
    p.setBrush(theme.c(th.base))
    p.drawPath(fold)
    _text(p, file_r.adjusted(4, 30, -4, 0), ".isregion", theme.c(th.accent), 12, QFont.Bold,
          Qt.AlignHCenter | Qt.AlignTop)
    p.setOpacity(1.0)
    _text(p, QRectF(file_r.left() - 40, file_r.bottom() + 6, file_r.width() + 80, 34),
          tr("Battle") + ".isregion", theme.c(th.text), 12, QFont.DemiBold, Qt.AlignHCenter | Qt.AlignTop)
    win = QRectF(file_r.right() + 70, r.top() + 64, min(card.width() + 60, r.right() - file_r.right() - 90),
                 card.height() + 44)
    _arrow(p, QPointF(file_r.right() + 8, file_r.center().y()), QPointF(win.left() - 8, file_r.center().y()),
           theme.c(th.accent))
    p.setPen(QPen(theme.c(th.border), 1.2))
    p.setBrush(theme.c(th.canvas_bg))
    p.drawRoundedRect(win, 8, 8)
    _text(p, QRectF(win.left(), win.top() - 22, win.width(), 20), tr("Another project"), theme.c(th.text), 13,
          QFont.DemiBold, Qt.AlignHCenter)
    b = _phase(t, 0.45, 0.75)
    inner = QRectF(win.left() + 20, win.top() + 20, card.width(), card.height())
    p.setOpacity(b)
    _card(p, inner, "#e05252", tr("Battle"), switch=None)
    for i in range(3):
        _thumb(p, QRectF(inner.left() + 12 + i * (w + gap), inner.top() + 40, w, h), i + 1, locked=i == 0,
               label=False)
    p.setOpacity(1.0)
    _text(p, QRectF(r.left() + 20, r.top() + 4, r.width() - 40, 26),
          tr("⋯ → Save Region, then File → Load Saved Region in any project."), theme.c(th.text), 14,
          QFont.DemiBold)
    _text(p, QRectF(r.left() + 20, card.bottom() + 52, file_r.right() - r.left(), 44),
          tr("Order, locks, colour and Auto-Arrange come along."), theme.c(th.subtext), 13)


DRAW = {"drag": draw_drag, "lock": draw_lock, "viewer": draw_viewer, "wheel": draw_wheel,
        "cancel": draw_cancel, "save": draw_save}


class TipCanvas(QWidget):
    def __init__(self, index: int = 0):
        super().__init__()
        self.index = index
        self.setMinimumSize(760, 330)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._t0 = time.monotonic()
        self.fixed_t: float | None = None  # tests / screenshots
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self.update)
        self._timer.start()

    def set_index(self, i: int) -> None:
        self.index = i
        self._t0 = time.monotonic()
        self.update()

    def phase(self) -> float:
        if self.fixed_t is not None:
            return self.fixed_t
        return ((time.monotonic() - self._t0) / PERIOD) % 1.0

    def paintEvent(self, e):
        th = theme.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.fillRect(self.rect(), theme.c(th.base))
        DRAW[TIPS[self.index]["key"]](p, QRectF(self.rect()).adjusted(10, 10, -10, -10), self.phase())


class TipDialog(QDialog):
    """Illustrated tips; ◀ ▶ (or arrow keys) browse, the checkbox controls the sidebar tips."""

    def __init__(self, parent, index: int, tips_on: bool):
        super().__init__(parent)
        self.setWindowTitle(tr("Tips"))
        self.title = QLabel()
        self.title.setObjectName("TipTitle")
        f = self.title.font()
        f.setPixelSize(20)
        f.setBold(True)
        self.title.setFont(f)
        self.canvas = TipCanvas(index)
        self.text = QLabel()
        self.text.setWordWrap(True)
        self.show_tips = QCheckBox(tr("Show tips in the sidebar"))
        self.show_tips.setChecked(tips_on)
        self.page = QLabel()
        self.prev_btn = QPushButton(tr("‹ Previous"))
        self.next_btn = QPushButton(tr("Next ›"))
        close = QPushButton(tr("Close"))
        self.prev_btn.clicked.connect(lambda: self.step(-1))
        self.next_btn.clicked.connect(lambda: self.step(1))
        close.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addWidget(self.show_tips)
        row.addStretch(1)
        row.addWidget(self.page)
        row.addSpacing(10)
        row.addWidget(self.prev_btn)
        row.addWidget(self.next_btn)
        row.addWidget(close)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.addWidget(self.title)
        lay.addWidget(self.canvas, 1)
        lay.addWidget(self.text)
        lay.addLayout(row)
        QShortcut(QKeySequence(Qt.Key_Left), self, lambda: self.step(-1))
        QShortcut(QKeySequence(Qt.Key_Right), self, lambda: self.step(1))
        self.resize(820, 560)
        self.show_index(index)

    def show_index(self, i: int) -> None:
        self.index = i % len(TIPS)
        tip = TIPS[self.index]
        self.title.setText(tr(tip["title"]))
        self.text.setText(tr(tip["text"]))
        self.page.setText(f"{self.index + 1} / {len(TIPS)}")
        self.canvas.set_index(self.index)

    def step(self, d: int) -> None:
        self.show_index(self.index + d)
