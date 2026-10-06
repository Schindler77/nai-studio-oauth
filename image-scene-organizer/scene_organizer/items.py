"""Graphics items drawn on the canvas. They only mirror model data; all
mouse interaction is handled centrally by the Canvas view."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetrics, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsItem, QStyleOptionGraphicsItem

from .model import LABEL_H, TITLE_H

ACCENT = QColor("#4fc3f7")
TEXT = QColor("#e6e6e6")


CANVAS_BG = QColor("#1b1c1f")


def _readable_on(c: QColor) -> QColor:
    """Text colour for a (possibly translucent) bar drawn over the canvas."""
    a = c.alphaF()
    r, g, b = (getattr(c, k)() * a + getattr(CANVAS_BG, k)() * (1 - a) for k in ("red", "green", "blue"))
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    return QColor("#111") if lum > 150 else QColor("#fff")


def draw_lock(p, x: float, y: float, s: float) -> None:
    """Small padlock badge with its top-left corner at (x, y), size s."""
    p.save()
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(255, 193, 7, 235))
    p.drawRoundedRect(QRectF(x, y, s, s), s * 0.2, s * 0.2)
    pen = QPen(QColor("#222"), max(1.0, s * 0.09))
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawArc(QRectF(x + s * 0.32, y + s * 0.14, s * 0.36, s * 0.42), 0, 180 * 16)
    p.setBrush(QColor("#222"))
    p.drawRect(QRectF(x + s * 0.24, y + s * 0.42, s * 0.52, s * 0.38))
    p.restore()


class ThumbItem(QGraphicsItem):
    def __init__(self, canvas, ref_id: str):
        super().__init__()
        self.canvas = canvas
        self.ref_id = ref_id
        self.path = ""
        self.name = ""
        self.locked = False
        self.index = 0
        self.cut = False
        self.cw = self.ch = 100
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setAcceptedMouseButtons(Qt.NoButton)  # Canvas handles the mouse

    def set_cell(self, cw: float, ch: float) -> None:
        if (cw, ch) != (self.cw, self.ch):
            self.prepareGeometryChange()
            self.cw, self.ch = cw, ch

    def set_data(self, ref, index: int, cut: bool) -> None:
        state = (ref.path, ref.display_name, ref.locked, index, cut)
        if state != (self.path, self.name, self.locked, self.index, self.cut):
            self.path, self.name, self.locked, self.index, self.cut = state
            self.setToolTip(f"{ref.display_name}\n{ref.path}")
            self.update()

    def boundingRect(self) -> QRectF:
        return QRectF(-3, -3, self.cw + 6, self.ch + 6)

    def paint(self, p, opt: QStyleOptionGraphicsItem, widget=None):
        lod = QStyleOptionGraphicsItem.levelOfDetailFromTransform(p.worldTransform())
        cache = self.canvas.thumbs
        s = self.cw
        box = QRectF(0, 0, s, s)
        p.fillRect(box, QColor(24, 25, 28))
        pix = cache.get(self.path)
        if pix is not None and not pix.isNull():
            pw, ph = pix.width(), pix.height()
            k = min(s / pw, s / ph)
            tw, th = pw * k, ph * k
            p.drawPixmap(QRectF((s - tw) / 2, (s - th) / 2, tw, th), pix, QRectF(pix.rect()))
        elif cache.is_missing(self.path):
            p.setPen(QPen(QColor("#e05252"), 2))
            p.drawLine(box.topLeft() + QPointF(8, 8), box.bottomRight() - QPointF(8, 8))
            p.drawLine(box.topRight() + QPointF(-8, 8), box.bottomLeft() + QPointF(8, -8))
            if lod > 0.3:
                p.drawText(box, Qt.AlignCenter, "missing")
        elif lod > 0.3:
            p.setPen(QColor(120, 120, 120))
            p.drawText(box, Qt.AlignCenter, "…")
        if self.cut:
            p.fillRect(box, QColor(0, 0, 0, 150))
        if self.isSelected():
            p.setPen(QPen(ACCENT, 3))
            p.setBrush(Qt.NoBrush)
            p.drawRect(box.adjusted(-1.5, -1.5, 1.5, 1.5))
        else:
            p.setPen(QPen(QColor(255, 255, 255, 40), 1))
            p.setBrush(Qt.NoBrush)
            p.drawRect(box)
        if self.locked:
            ls = max(14.0, s * 0.16)
            draw_lock(p, s - ls - 4, 4, ls)
        if lod < 0.3:
            return
        show_num, show_label = self.canvas.show_numbers(), self.canvas.show_labels()
        if show_num:
            f = QFont(p.font())
            f.setPixelSize(max(10, int(s * 0.09)))
            f.setBold(True)
            p.setFont(f)
            txt = str(self.index + 1)
            fm = QFontMetrics(f)
            r = QRectF(4, 4, fm.horizontalAdvance(txt) + 10, fm.height() + 2)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 170))
            p.drawRoundedRect(r, 4, 4)
            p.setPen(QColor("#fff"))
            p.drawText(r, Qt.AlignCenter, txt)
        if show_label:
            f = QFont(p.font())
            f.setPixelSize(12)
            f.setBold(False)
            p.setFont(f)
            fm = QFontMetrics(f)
            p.setPen(TEXT if not self.cut else QColor(130, 130, 130))
            p.drawText(QRectF(0, s + 2, s, LABEL_H - 2), Qt.AlignHCenter | Qt.AlignVCenter,
                       fm.elidedText(self.name, Qt.ElideMiddle, int(s)))


class RegionItem(QGraphicsItem):
    ARROW_W = 26
    GRIP = 16

    def __init__(self, canvas, region_id: str):
        super().__init__()
        self.canvas = canvas
        self.region_id = region_id
        self.w = self.h = 100.0
        self.name = ""
        self.color = QColor("#4a86e8")
        self.count = 0
        self.locked_count = 0
        self.auto = True
        self.collapsed = False
        self.active = False
        self.multi_selected = False
        self.drop_hint = False
        self.setAcceptedMouseButtons(Qt.NoButton)

    def set_geometry(self, w: float, h: float) -> None:
        if (w, h) != (self.w, self.h):
            self.prepareGeometryChange()
            self.w, self.h = w, h

    def set_data(self, reg, active: bool, multi_selected: bool) -> None:
        self.name, self.color = reg.name, QColor(reg.color)
        self.count = len(reg.images)
        self.locked_count = sum(1 for r in reg.images if r.locked)
        self.auto, self.collapsed = reg.auto_arrange, reg.collapsed
        self.active, self.multi_selected = active, multi_selected
        self.update()

    def set_drop_hint(self, on: bool) -> None:
        if on != self.drop_hint:
            self.drop_hint = on
            self.update()

    def zone(self, local: QPointF) -> str:
        if local.y() <= TITLE_H:
            return "arrow" if local.x() <= self.ARROW_W else "title"
        if not self.collapsed and local.x() >= self.w - self.GRIP and local.y() >= self.h - self.GRIP:
            return "grip"
        return "body"

    def boundingRect(self) -> QRectF:
        return QRectF(-3, -3, self.w + 6, self.h + 6)

    def paint(self, p, opt, widget=None):
        lod = QStyleOptionGraphicsItem.levelOfDetailFromTransform(p.worldTransform())
        rect = QRectF(0, 0, self.w, self.h)
        c = self.color
        tint = QColor(c)
        tint.setAlpha(34 if not self.drop_hint else 70)
        p.setPen(Qt.NoPen)
        p.setBrush(tint)
        p.drawRoundedRect(rect, 6, 6)
        # title bar
        title = QRectF(0, 0, self.w, TITLE_H)
        path = QPainterPath()
        path.addRoundedRect(title, 6, 6)
        if not self.collapsed:
            path.addRect(QRectF(0, TITLE_H / 2, self.w, TITLE_H / 2))
        bar = QColor(c)
        bar.setAlpha(230 if self.active else 175)
        p.fillPath(path.simplified(), QBrush(bar))
        # border
        border = QColor(c).lighter(135) if self.active else QColor(c)
        p.setPen(QPen(border, 3 if self.active or self.drop_hint else 1.6))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(rect, 6, 6)
        if self.multi_selected:
            p.setPen(QPen(QColor("#ffffff"), 1.5, Qt.DashLine))
            p.drawRoundedRect(rect.adjusted(-4, -4, 4, 4), 8, 8)
        if lod < 0.12:
            return
        fg = _readable_on(bar)
        f = QFont(p.font())
        f.setPixelSize(14)
        f.setBold(True)
        p.setFont(f)
        p.setPen(fg)
        p.drawText(QRectF(6, 0, self.ARROW_W, TITLE_H), Qt.AlignVCenter | Qt.AlignLeft,
                   "▶" if self.collapsed else "▼")
        badges = ("AUTO" if self.auto else "FREE")
        if self.locked_count:
            badges = f"{self.locked_count}      " + badges
        f2 = QFont(f)
        f2.setPixelSize(11)
        f2.setBold(True)
        fm2 = QFontMetrics(f2)
        bw = fm2.horizontalAdvance(badges) + 12
        name = f"{self.name}  ({self.count} images)" if self.canvas.show_region_names() \
            else f"({self.count} images)"
        fm = QFontMetrics(f)
        avail = int(self.w - self.ARROW_W - bw - 12)
        p.drawText(QRectF(self.ARROW_W, 0, max(avail, 10), TITLE_H), Qt.AlignVCenter | Qt.AlignLeft,
                   fm.elidedText(name, Qt.ElideRight, max(avail, 10)))
        p.setFont(f2)
        p.drawText(QRectF(self.w - bw - 6, 0, bw, TITLE_H), Qt.AlignVCenter | Qt.AlignRight, badges)
        if self.locked_count:
            lx = self.w - 6 - fm2.horizontalAdvance(badges) + fm2.horizontalAdvance(f"{self.locked_count} ")
            draw_lock(p, lx, (TITLE_H - 14) / 2, 14)
        if not self.collapsed:
            p.setPen(QPen(QColor(c).lighter(120), 1.4))
            for d in (4, 8, 12):
                p.drawLine(QPointF(self.w - d, self.h - 3), QPointF(self.w - 3, self.h - d))
            if self.count == 0 and lod > 0.3:
                p.setPen(QColor(180, 180, 180, 150))
                f3 = QFont(f)
                f3.setPixelSize(13)
                f3.setBold(False)
                p.setFont(f3)
                p.drawText(rect.adjusted(0, TITLE_H, 0, 0), Qt.AlignCenter,
                           "Drop images here, or select this region and use Import")
