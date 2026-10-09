"""Graphics items drawn on the canvas. They only mirror model data; all
mouse interaction is handled centrally by the Canvas view."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsItem, QStyleOptionGraphicsItem

from . import theme
from .i18n import tr
from .model import LABEL_H, TITLE_H

RADIUS_THUMB = 6
RADIUS_CARD = 12


def draw_lock(p, x: float, y: float, s: float, bg: QColor | None = None, fg: QColor | None = None) -> None:
    """Padlock badge with its top-left corner at (x, y), size s."""
    p.save()
    p.setPen(Qt.NoPen)
    p.setBrush(bg if bg is not None else QColor(0, 0, 0, 150))
    p.drawRoundedRect(QRectF(x, y, s, s), s * 0.25, s * 0.25)
    fg = fg if fg is not None else QColor("#ffffff")
    p.setPen(QPen(fg, max(1.2, s * 0.1)))
    p.setBrush(Qt.NoBrush)
    p.drawArc(QRectF(x + s * 0.33, y + s * 0.16, s * 0.34, s * 0.40), 0, 180 * 16)
    p.setPen(Qt.NoPen)
    p.setBrush(fg)
    p.drawRoundedRect(QRectF(x + s * 0.24, y + s * 0.42, s * 0.52, s * 0.38), s * 0.06, s * 0.06)
    p.restore()


def _font(px: int, weight: QFont.Weight = QFont.Normal) -> QFont:
    f = QFont()  # application font (what the canvas paints with)
    f.setPixelSize(px)
    f.setWeight(weight)
    return f


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
        self.img_h = 100
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setAcceptedMouseButtons(Qt.NoButton)  # Canvas handles the mouse
        # Keep the painted thumbnail as a pixmap: dragging / panning only moves it
        # (re-rendered when the zoom, selection or picture changes).
        self.setCacheMode(QGraphicsItem.DeviceCoordinateCache)

    def set_cell(self, cw: float, ch: float, img_h: float | None = None) -> None:
        img_h = ch if img_h is None else img_h
        if (cw, ch, img_h) != (self.cw, self.ch, self.img_h):
            self.prepareGeometryChange()
            self.cw, self.ch, self.img_h = cw, ch, img_h

    def set_data(self, ref, index: int, cut: bool) -> None:
        state = (ref.path, ref.display_name, ref.locked, index, cut)
        if state != (self.path, self.name, self.locked, self.index, self.cut):
            self.path, self.name, self.locked, self.index, self.cut = state
            self.setToolTip(f"{ref.display_name}\n{ref.path}")
            self.update()

    def boundingRect(self) -> QRectF:
        return QRectF(-6, -6, self.cw + 12, self.ch + 12)

    def shape(self) -> QPainterPath:  # hit-testing: the cell, not the glow margin
        path = QPainterPath()
        path.addRect(QRectF(0, 0, self.cw, self.ch))
        return path

    def paint(self, p, opt: QStyleOptionGraphicsItem, widget=None):
        parent = self.parentItem()
        if isinstance(parent, RegionItem) and parent.scroll_on:  # stay inside the scrolling body
            p.save()
            p.setClipRect(parent.body_rect().translated(-self.pos()), Qt.IntersectClip)
            self._paint(p, opt)
            p.restore()
        else:
            self._paint(p, opt)

    def _paint(self, p, opt: QStyleOptionGraphicsItem):
        t = theme.current()
        lod = QStyleOptionGraphicsItem.levelOfDetailFromTransform(p.worldTransform())
        cache = self.canvas.thumbs
        w, h = self.cw, self.img_h
        box = QRectF(0, 0, w, h)
        detailed = lod > 0.35
        clip = QPainterPath()
        clip.addRoundedRect(box, RADIUS_THUMB, RADIUS_THUMB)
        selected = self.isSelected()
        if selected and detailed:  # soft glow behind the selection ring
            glow = theme.c(t.accent)
            glow.setAlpha(60)
            p.setPen(QPen(glow, 8))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(box.adjusted(-2, -2, 2, 2), RADIUS_THUMB + 2, RADIUS_THUMB + 2)
        p.save()
        if detailed:
            p.setClipPath(clip, Qt.IntersectClip)  # keep a scrolling region's body clip
        p.fillRect(box, theme.c(t.thumb_bg))
        pix = cache.get(self.path)
        if pix is not None and not pix.isNull():
            pw, ph = pix.width(), pix.height()
            if self.canvas.thumb_fill() == "cover":  # crop the source to the box shape
                k = max(w / pw, h / ph)
                sw, sh = w / k, h / k
                p.drawPixmap(box, pix, QRectF((pw - sw) / 2, (ph - sh) / 2, sw, sh))
            else:
                k = min(w / pw, h / ph)
                tw, th = pw * k, ph * k
                p.drawPixmap(QRectF((w - tw) / 2, (h - th) / 2, tw, th), pix, QRectF(pix.rect()))
        elif cache.is_missing(self.path):
            p.setPen(QPen(QColor("#e05252"), 2))
            p.drawLine(box.topLeft() + QPointF(8, 8), box.bottomRight() - QPointF(8, 8))
            p.drawLine(box.topRight() + QPointF(-8, 8), box.bottomLeft() + QPointF(8, -8))
            if detailed:
                p.drawText(box, Qt.AlignCenter, tr("missing file"))
        elif detailed:
            p.setPen(theme.c(t.subtext))
            p.drawText(box, Qt.AlignCenter, "…")
        if self.cut:
            veil = theme.c(t.base)
            veil.setAlpha(160)
            p.fillRect(box, veil)
        p.restore()
        if self.ref_id in self.canvas.search_hits:
            p.setPen(QPen(QColor("#f59e0b"), 3))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(box.adjusted(-4, -4, 4, 4), RADIUS_THUMB + 3, RADIUS_THUMB + 3)
        if selected:
            p.setPen(QPen(theme.c(t.accent), 3))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(box.adjusted(-1, -1, 1, 1), RADIUS_THUMB + 1, RADIUS_THUMB + 1)
        elif detailed:
            p.setPen(QPen(theme.c(t.shadow), 1))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(box, RADIUS_THUMB, RADIUS_THUMB)
        if self.locked:
            ls = max(14.0, min(w, h) * 0.2)
            draw_lock(p, w - ls - 5, h - ls - 5, ls)
        if not detailed or not self.canvas.label_shown():
            return
        num = str(self.index + 1).zfill(2)
        if self.canvas.show_labels():
            text = f"{num}  {self.name}" if self.canvas.show_numbers() else self.name
        else:
            text = num
        f = _font(12, QFont.Medium)
        p.setFont(f)
        p.setPen(theme.c(t.label) if not self.cut else theme.c(t.subtext))
        p.drawText(QRectF(0, h + 2, w, LABEL_H - 2), Qt.AlignHCenter | Qt.AlignVCenter,
                   QFontMetrics(f).elidedText(text, Qt.ElideMiddle, int(w)))


class RegionItem(QGraphicsItem):
    GRIP = 16
    SWITCH_H = 28

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
        self.r_arrow = self.r_switch = self.r_menu = QRectF()
        self.scroll_on = False
        self.scroll = 0.0
        self.content_h = 0.0
        self.setAcceptedMouseButtons(Qt.NoButton)

    def set_scroll(self, on: bool, scroll: float, content_h: float) -> None:
        if (on, scroll, content_h) != (self.scroll_on, self.scroll, self.content_h):
            self.scroll_on, self.scroll, self.content_h = on, scroll, content_h
            self.update()

    def body_rect(self) -> QRectF:
        return QRectF(0, TITLE_H, self.w, max(self.h - TITLE_H, 0))

    def scrollbar_rects(self) -> tuple[QRectF, QRectF] | None:
        """(track, thumb) when the region scrolls and its content is taller than it."""
        body = self.body_rect()
        if not self.scroll_on or self.content_h <= self.h + 0.5 or body.height() < 20:
            return None
        track = QRectF(self.w - 11, body.top() + 6, 7, body.height() - 12 - self.GRIP)
        frac = body.height() / max(self.content_h - TITLE_H, 1)
        length = max(24.0, track.height() * min(frac, 1.0))
        max_scroll = max(self.content_h - self.h, 1)
        top = track.top() + (track.height() - length) * min(self.scroll / max_scroll, 1.0)
        return track, QRectF(track.left(), top, track.width(), length)

    def set_geometry(self, w: float, h: float) -> None:
        if (w, h) != (self.w, self.h):
            self.prepareGeometryChange()
            self.w, self.h = w, h
            self._header_layout()

    def set_data(self, reg, active: bool, multi_selected: bool) -> None:
        self.name, self.color = reg.name, QColor(reg.color)
        self.count = len(reg.images)
        self.locked_count = sum(1 for r in reg.images if r.locked)
        self.auto, self.collapsed = reg.auto_arrange, reg.collapsed
        self.active, self.multi_selected = active, multi_selected
        self._header_layout()
        self.update()

    def set_drop_hint(self, on: bool) -> None:
        if on != self.drop_hint:
            self.drop_hint = on
            self.update()

    # -------------------------------------------------------------- header
    def _header_layout(self) -> None:
        """Hit areas inside the header (right to left: ⋯, count, lock, switch)."""
        y = (TITLE_H - self.SWITCH_H) / 2
        self.r_arrow = QRectF(4, 0, 24, TITLE_H)
        self.r_menu = QRectF(self.w - 36, y, 28, self.SWITCH_H)
        count_w = QFontMetrics(_font(14, QFont.DemiBold)).horizontalAdvance(self.count_text()) + 16
        lock_w = 0 if not self.locked_count else 46
        sw_w = QFontMetrics(_font(13, QFont.DemiBold)).horizontalAdvance(self.switch_text()) + 42
        x = self.r_menu.left() - count_w - lock_w - sw_w - 6
        self.r_switch = QRectF(x, y, sw_w, self.SWITCH_H)

    def count_text(self) -> str:
        return tr("{n} images", n=self.count)

    def switch_text(self) -> str:
        return tr("Auto-Arrange ON") if self.auto else tr("Auto-Arrange OFF")

    def zone(self, local: QPointF) -> str:
        if local.y() <= TITLE_H:
            if self.r_switch.contains(local):
                return "switch"
            if self.r_menu.contains(local):
                return "menu"
            return "arrow" if self.r_arrow.contains(local) else "title"
        if not self.collapsed and local.x() >= self.w - self.GRIP and local.y() >= self.h - self.GRIP:
            return "grip"
        bars = self.scrollbar_rects()
        if bars and bars[0].adjusted(-4, 0, 4, 0).contains(local):
            return "scrollbar"
        return "body"

    def boundingRect(self) -> QRectF:
        return QRectF(-8, -8, self.w + 16, self.h + 16)

    def shape(self) -> QPainterPath:  # hit-testing: the card, not the shadow margin
        path = QPainterPath()
        path.addRect(QRectF(0, 0, self.w, self.h))
        return path

    def paint(self, p, opt, widget=None):
        t = theme.current()
        lod = QStyleOptionGraphicsItem.levelOfDetailFromTransform(p.worldTransform())
        rect = QRectF(0, 0, self.w, self.h)
        col = self.color
        base = theme.c(t.card_base)
        body = theme.blend(col, base, t.card_mix if not self.drop_hint else t.card_mix - 0.12)
        header = theme.blend(col, base, t.header_mix)
        # shadow
        if lod > 0.2:
            sh = theme.c(t.shadow)
            for i, a in ((6, 0.25), (3, 0.45)):
                s2 = QColor(sh)
                s2.setAlphaF(sh.alphaF() * a)
                p.setPen(Qt.NoPen)
                p.setBrush(s2)
                p.drawRoundedRect(rect.translated(0, i / 2).adjusted(-i / 3, 0, i / 3, i / 3),
                                  RADIUS_CARD + 2, RADIUS_CARD + 2)
        p.setPen(Qt.NoPen)
        p.setBrush(body)
        p.drawRoundedRect(rect, RADIUS_CARD, RADIUS_CARD)
        hp = QPainterPath()
        hp.addRoundedRect(QRectF(0, 0, self.w, TITLE_H), RADIUS_CARD, RADIUS_CARD)
        if not self.collapsed:
            hp.addRect(QRectF(0, TITLE_H / 2, self.w, TITLE_H / 2))
        p.fillPath(hp.simplified(), header)
        border = col if (self.active or self.drop_hint) else theme.blend(col, base, 0.45)
        p.setPen(QPen(border, 2.4 if self.active or self.drop_hint else 1.2))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(rect, RADIUS_CARD, RADIUS_CARD)
        if self.multi_selected:
            p.setPen(QPen(theme.c(t.accent), 1.5, Qt.DashLine))
            p.drawRoundedRect(rect.adjusted(-5, -5, 5, 5), RADIUS_CARD + 4, RADIUS_CARD + 4)
        if self.region_id in self.canvas.search_regions:
            p.setPen(QPen(QColor("#f59e0b"), 2.5, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(rect.adjusted(-6, -6, 6, 6), RADIUS_CARD + 5, RADIUS_CARD + 5)
        bars = self.scrollbar_rects()
        if bars:
            track, knob = bars
            p.setPen(Qt.NoPen)
            p.setBrush(theme.blend(col, base, 0.75))
            p.drawRoundedRect(track, 3.5, 3.5)
            p.setBrush(theme.blend(col, base, 0.2))
            p.drawRoundedRect(knob, 3.5, 3.5)
        if lod < 0.12:
            return
        text_col = theme.c(t.text)
        sub_col = theme.c(t.subtext)
        # chevron + colour dot + title
        p.setPen(QPen(sub_col, 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        cx, cy = self.r_arrow.center().x(), TITLE_H / 2
        if self.collapsed:
            p.drawPolyline([QPointF(cx - 2, cy - 5), QPointF(cx + 3, cy), QPointF(cx - 2, cy + 5)])
        else:
            p.drawPolyline([QPointF(cx - 5, cy - 2), QPointF(cx, cy + 3), QPointF(cx + 5, cy - 2)])
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        p.drawEllipse(QPointF(self.r_arrow.right() + 10, cy), 8, 8)
        title_x = self.r_arrow.right() + 28
        avail = int(self.r_switch.left() - title_x - 10)
        if self.canvas.show_region_names() and avail > 20:
            f = _font(21, QFont.Bold)
            p.setFont(f)
            p.setPen(text_col)
            p.drawText(QRectF(title_x, 0, avail, TITLE_H), Qt.AlignVCenter | Qt.AlignLeft,
                       QFontMetrics(f).elidedText(self.name, Qt.ElideRight, avail))
        # auto-arrange switch
        r = self.r_switch
        p.setPen(Qt.NoPen)
        p.setBrush(theme.c(t.accent) if self.auto else theme.c(t.switch_off))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        knob_d = r.height() - 8
        kx = r.left() + 4 if self.auto else r.right() - 4 - knob_d
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QRectF(kx, r.top() + 4, knob_d, knob_d))
        f = _font(13, QFont.DemiBold)
        p.setFont(f)
        p.setPen(QColor("#ffffff") if self.auto else text_col)
        tr_rect = r.adjusted(knob_d + 10, 0, -8, 0) if self.auto else r.adjusted(10, 0, -knob_d - 10, 0)
        p.drawText(tr_rect, Qt.AlignCenter, self.switch_text())
        # locks, count, menu
        x = r.right() + 8
        if self.locked_count:
            draw_lock(p, x, (TITLE_H - 18) / 2, 18, bg=QColor(245, 158, 11), fg=QColor("#ffffff"))
            f = _font(13, QFont.DemiBold)
            p.setFont(f)
            p.setPen(text_col)
            p.drawText(QRectF(x + 21, 0, 24, TITLE_H), Qt.AlignVCenter | Qt.AlignLeft, str(self.locked_count))
            x += 46
        f = _font(14, QFont.DemiBold)
        p.setFont(f)
        p.setPen(sub_col)
        p.drawText(QRectF(x, 0, self.r_menu.left() - x - 4, TITLE_H), Qt.AlignVCenter | Qt.AlignRight,
                   self.count_text())
        p.setBrush(sub_col)
        m = self.r_menu.center()
        for dx in (-6, 0, 6):
            p.drawEllipse(QPointF(m.x() + dx, m.y()), 2.0, 2.0)
        if not self.collapsed:
            p.setPen(QPen(theme.blend(col, base, 0.3), 1.4))
            for d in (4, 8, 12):
                p.drawLine(QPointF(self.w - d, self.h - 3), QPointF(self.w - 3, self.h - d))
            if self.count == 0 and lod > 0.3:
                p.setPen(sub_col)
                p.setFont(_font(13))
                p.drawText(rect.adjusted(0, TITLE_H, 0, 0), Qt.AlignCenter,
                           tr("Drop images here, or select this region and use Import"))
