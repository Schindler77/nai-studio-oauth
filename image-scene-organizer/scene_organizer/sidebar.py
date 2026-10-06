"""Left sidebar: canvas preview (minimap), region list and tips."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QStyle, QStyledItemDelegate, QToolButton, QVBoxLayout, QWidget)

from . import theme
from .i18n import tr
from .icons import icon

TIPS = [
    "Drag images into the order you want. With Auto-Arrange ON, the other images "
    "move aside and the row stays in order.",
    "Lock the images you have confirmed (Ctrl+L). New imports never push them around.",
    "Double-click a thumbnail to see it large. Wheel zooms, 100% shows real pixels.",
    "Ctrl+Wheel changes the thumbnail size; the wheel alone zooms the canvas.",
    "Right-click while dragging cancels the move and puts everything back.",
    "Save a region on its own (⋯ → Save Region) and load it into another project.",
]


class MiniMap(QWidget):
    """Overview of all regions; the dashed frame is the visible part of the
    canvas. Click or drag to move the view there."""

    def __init__(self, ctrl):
        super().__init__()
        self.ctrl = ctrl
        self.setMinimumHeight(130)
        self.setCursor(Qt.PointingHandCursor)
        self._map = None  # (world rect, scale, offset)

    def _world(self) -> tuple[QRectF, QRectF]:
        canvas = self.ctrl.canvas
        view = canvas.mapToScene(canvas.viewport().rect()).boundingRect()
        world = QRectF()
        for ri in canvas.region_items.values():
            world = world.united(QRectF(ri.pos(), QSize(int(ri.w), int(ri.h))))
        world = view if world.isNull() else world.united(view)
        pad = max(world.width(), world.height()) * 0.04
        return world.adjusted(-pad, -pad, pad, pad), view

    def _to_widget(self, world: QRectF) -> tuple[float, QPointF]:
        r = QRectF(self.rect()).adjusted(8, 8, -8, -8)
        k = min(r.width() / max(world.width(), 1), r.height() / max(world.height(), 1))
        off = QPointF(r.left() + (r.width() - world.width() * k) / 2 - world.left() * k,
                      r.top() + (r.height() - world.height() * k) / 2 - world.top() * k)
        return k, off

    def paintEvent(self, e):
        t = theme.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(theme.c(t.canvas_bg))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        world, view = self._world()
        k, off = self._to_widget(world)
        self._map = (k, off)
        base = theme.c(t.card_base)
        for reg in self.ctrl.project.regions:
            ri = self.ctrl.canvas.region_items.get(reg.id)
            if ri is None:
                continue
            col = QColor(reg.color)
            rr = QRectF(ri.pos().x() * k + off.x(), ri.pos().y() * k + off.y(), ri.w * k, ri.h * k)
            rr = rr.adjusted(1.5, 1.5, -1.5, -1.5)  # keep neighbouring regions visibly apart
            p.setBrush(theme.blend(col, base, 0.62))
            p.setPen(QPen(theme.blend(col, base, 0.25), 1.2 if reg.id == self.ctrl.active_region_id else 0.8))
            p.drawRoundedRect(rr, 3, 3)
        vr = QRectF(view.left() * k + off.x(), view.top() * k + off.y(), view.width() * k, view.height() * k)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(theme.c(t.subtext), 1.2, Qt.DashLine))
        p.drawRect(vr.intersected(QRectF(self.rect()).adjusted(2, 2, -2, -2)))

    def _jump(self, pos: QPointF) -> None:
        if not self._map:
            return
        k, off = self._map
        self.ctrl.canvas.centerOn(QPointF((pos.x() - off.x()) / k, (pos.y() - off.y()) / k))
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._jump(e.position())

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.LeftButton:
            self._jump(e.position())


class _RegionDelegate(QStyledItemDelegate):
    """Row: colour dot · name · count, active row highlighted."""

    def sizeHint(self, opt, index):
        return QSize(opt.rect.width(), 38)

    def paint(self, p, opt, index):
        t = theme.current()
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(opt.rect).adjusted(4, 2, -4, -2)
        active = bool(index.data(Qt.UserRole + 3))
        if active:
            p.setPen(Qt.NoPen)
            p.setBrush(theme.blend(theme.c(t.accent), theme.c(t.base), 0.86))
            p.drawRoundedRect(r, 7, 7)
        elif opt.state & QStyle.State_MouseOver:
            p.setPen(Qt.NoPen)
            p.setBrush(theme.c(t.hover))
            p.drawRoundedRect(r, 7, 7)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(index.data(Qt.UserRole + 1)))
        p.drawEllipse(QPointF(r.left() + 16, r.center().y()), 7.5, 7.5)
        count = index.data(Qt.UserRole + 2)
        f = QFont(opt.font)
        f.setPixelSize(13)
        p.setFont(f)
        p.setPen(theme.c(t.subtext))
        cw = QFontMetrics(f).horizontalAdvance(count) + 12
        p.drawText(r.adjusted(0, 0, -10, 0), Qt.AlignVCenter | Qt.AlignRight, count)
        f.setPixelSize(14)
        f.setWeight(QFont.Bold if active else QFont.DemiBold)
        p.setFont(f)
        p.setPen(theme.c(t.text))
        name_r = r.adjusted(34, 0, -cw - 10, 0)
        p.drawText(name_r, Qt.AlignVCenter | Qt.AlignLeft,
                   QFontMetrics(f).elidedText(index.data(Qt.DisplayRole), Qt.ElideRight, int(name_r.width())))
        p.restore()


def _card(title: str | None = None) -> tuple[QFrame, QVBoxLayout, QHBoxLayout | None]:
    card = QFrame()
    card.setObjectName("SidebarCard")
    lay = QVBoxLayout(card)
    lay.setContentsMargins(12, 10, 12, 12)
    lay.setSpacing(8)
    head = None
    if title is not None:
        head = QHBoxLayout()
        lbl = QLabel(title)
        lbl.setObjectName("SidebarTitle")
        head.addWidget(lbl)
        head.addStretch(1)
        lay.addLayout(head)
    return card, lay, head


class Sidebar(QWidget):
    closeRequested = Signal()

    def __init__(self, ctrl):
        super().__init__()
        self.ctrl = ctrl
        self.setObjectName("Sidebar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedWidth(250)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(12)

        card, lay, head = _card(tr("Canvas Preview"))
        self.close_btn = QToolButton()
        self.close_btn.setAutoRaise(True)
        self.close_btn.setToolTip(tr("Hide sidebar (View → Sidebar)"))
        self.close_btn.clicked.connect(self.closeRequested.emit)
        head.addWidget(self.close_btn)
        self.minimap = MiniMap(ctrl)
        lay.addWidget(self.minimap)
        outer.addWidget(card)

        card, lay, head = _card(tr("Regions"))
        self.add_btn = QToolButton()
        self.add_btn.setAutoRaise(True)
        self.add_btn.setToolTip(tr("New Region"))
        self.add_btn.clicked.connect(lambda: ctrl.new_region())
        head.addWidget(self.add_btn)
        self.list = QListWidget()
        self.list.setObjectName("RegionList")
        self.list.setItemDelegate(_RegionDelegate(self.list))
        self.list.setMouseTracking(True)
        self.list.setFrameShape(QFrame.NoFrame)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.itemClicked.connect(self._clicked)
        self.list.itemDoubleClicked.connect(lambda it: ctrl.fit_region(it.data(Qt.UserRole)))
        self.list.customContextMenuRequested.connect(self._context_menu)
        lay.addWidget(self.list, 1)
        outer.addWidget(card, 1)

        card, lay, head = _card()
        row = QHBoxLayout()
        self.tip_icon = QLabel()
        self.tip_icon.setFixedWidth(22)
        self.tip_icon.setAlignment(Qt.AlignTop)
        row.addWidget(self.tip_icon)
        col = QVBoxLayout()
        title = QLabel(tr("Tip"))
        title.setObjectName("SidebarTitle")
        col.addWidget(title)
        self.tip = QLabel()
        self.tip.setObjectName("SidebarTip")
        self.tip.setWordWrap(True)
        self.tip.setCursor(Qt.PointingHandCursor)
        self.tip.setToolTip(tr("Click for the next tip"))
        self.tip.mousePressEvent = lambda e: self.next_tip()
        col.addWidget(self.tip)
        row.addLayout(col, 1)
        lay.addLayout(row)
        outer.addWidget(card)
        self._tip_i = 0
        self.next_tip(0)
        self.apply_theme()

    def apply_theme(self) -> None:
        t = theme.current()
        self.close_btn.setIcon(icon("x", t.icon, 16))
        self.add_btn.setIcon(icon("plus", t.icon, 18))
        self.tip_icon.setPixmap(icon("lightbulb", t.icon, 18).pixmap(18, 18))
        self.update()

    def next_tip(self, i: int | None = None) -> None:
        self._tip_i = (self._tip_i + 1) % len(TIPS) if i is None else i
        self.tip.setText(tr(TIPS[self._tip_i]))

    def refresh(self) -> None:
        ctrl = self.ctrl
        lw = self.list
        current = [lw.item(i).data(Qt.UserRole) for i in range(lw.count())]
        if current != [r.id for r in ctrl.project.regions]:
            lw.clear()
            for reg in ctrl.project.regions:
                it = QListWidgetItem(reg.name)
                it.setData(Qt.UserRole, reg.id)
                lw.addItem(it)
        for i, reg in enumerate(ctrl.project.regions):
            it = lw.item(i)
            it.setText(reg.name)
            it.setData(Qt.UserRole + 1, reg.color)
            it.setData(Qt.UserRole + 2, tr("{n} images", n=len(reg.images)))
            it.setData(Qt.UserRole + 3, reg.id == ctrl.active_region_id)
        lw.viewport().update()
        self.minimap.update()

    def _clicked(self, it) -> None:
        rid = it.data(Qt.UserRole)
        self.ctrl.activate_region(rid)
        ri = self.ctrl.canvas.region_items.get(rid)
        if ri:
            self.ctrl.canvas.centerOn(ri.sceneBoundingRect().center())

    def _context_menu(self, pos) -> None:
        it = self.list.itemAt(pos)
        if it is None:
            return
        rid = it.data(Qt.UserRole)
        self.ctrl.activate_region(rid)
        ri = self.ctrl.canvas.region_items.get(rid)
        self.ctrl.region_menu(self.list.viewport().mapToGlobal(pos), rid,
                              ri.sceneBoundingRect().center() if ri else QPointF())
