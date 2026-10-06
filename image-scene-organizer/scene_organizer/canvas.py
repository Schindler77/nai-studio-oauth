"""The freeform canvas: mirrors the Project and turns mouse input into
calls on the main window controller (which owns the model and undo)."""
from __future__ import annotations


from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen
from PySide6.QtWidgets import (QApplication, QGraphicsRectItem, QGraphicsScene,
                               QGraphicsView)

from .items import ACCENT, RegionItem, ThumbItem
from .i18n import tr
from .model import (PAD, TITLE_H, adjust_insert_index, cell_size, grid_cols,
                    grid_content_height, grid_pos, slot_at)

ZOOM_MIN = 0.04  # open item: canvas zoom limits
ZOOM_MAX = 4.0
WORLD = 1_000_000
AUTOSCROLL_EDGE = 48     # px from the viewport edge where auto-scroll starts
AUTOSCROLL_SPEED = 28    # max px per tick (~60 ticks/s)
AUTOSCROLL_MODES = ("drag", "region_move", "region_resize", "rubber")


class Canvas(QGraphicsView):
    zoomChanged = Signal(float)

    def __init__(self, ctrl, thumbs):
        super().__init__()
        self.ctrl = ctrl  # MainWindow
        self.thumbs = thumbs
        scene = QGraphicsScene(self)
        scene.setSceneRect(-WORLD / 2, -WORLD / 2, WORLD, WORLD)
        self.setScene(scene)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing)
        self.setViewportUpdateMode(QGraphicsView.SmartViewportUpdate)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFrameShape(QGraphicsView.NoFrame)

        self.region_items: dict[str, RegionItem] = {}
        self.thumb_items: dict[str, ThumbItem] = {}
        self._by_path: dict[str, set[str]] = {}
        thumbs.ready.connect(self._thumb_ready)

        self.mode: str | None = None
        self.space_down = False
        self._right_cancelled = False
        self._last_pos = QPointF()
        self.drag: dict | None = None
        self.rubber: QGraphicsRectItem | None = None
        self.anchor_id: str | None = None  # for shift-click ranges
        self._last_vp = QPointF()
        self._autoscroll = QTimer(self)
        self._autoscroll.setInterval(16)
        self._autoscroll.timeout.connect(self._autoscroll_tick)

    # ------------------------------------------------------------ settings
    def show_numbers(self) -> bool:
        return self.ctrl.project.show_numbers

    def show_labels(self) -> bool:
        return self.ctrl.project.show_labels

    def show_region_names(self) -> bool:
        return self.ctrl.project.show_region_names

    def cell(self) -> tuple[int, int]:
        p = self.ctrl.project
        return cell_size(p.thumb_size, p.show_labels)

    def zoom(self) -> float:
        return self.transform().m11()

    # ---------------------------------------------------------------- sync
    def sync(self) -> None:
        """Bring the scene in line with the model (create / update / remove)."""
        if self.drag:
            self.cancel_drag()
        p = self.ctrl.project
        cw, ch = self.cell()
        live_refs: set[str] = set()
        live_regions: set[str] = set()
        self._by_path.clear()
        for z, reg in enumerate(p.regions):
            ri = self.region_items.get(reg.id)
            if ri is None:
                ri = RegionItem(self, reg.id)
                self.scene().addItem(ri)
                self.region_items[reg.id] = ri
            live_regions.add(reg.id)
            active = reg.id == self.ctrl.active_region_id
            ri.setPos(reg.x, reg.y)
            ri.setZValue(100_000 if active else z)
            ri.set_data(reg, active, reg.id in self.ctrl.selected_region_ids
                        and len(self.ctrl.selected_region_ids) > 1)
            for i, ref in enumerate(reg.images):
                ti = self.thumb_items.get(ref.id)
                if ti is None:
                    ti = ThumbItem(self, ref.id)
                    self.thumb_items[ref.id] = ti
                    ti.setParentItem(ri)
                elif ti.parentItem() is not ri:
                    ti.setParentItem(ri)
                ti.setOpacity(1.0)
                ti.setZValue(0)
                ti.set_cell(cw, ch)
                ti.set_data(ref, i, ref.id in self.ctrl.cut_ids)
                live_refs.add(ref.id)
                self._by_path.setdefault(ref.path, set()).add(ref.id)
            self.layout_region(reg, ri)
        for rid in [k for k in self.thumb_items if k not in live_refs]:
            ti = self.thumb_items.pop(rid)
            self.scene().removeItem(ti)
        for gid in [k for k in self.region_items if k not in live_regions]:
            self.scene().removeItem(self.region_items.pop(gid))
        self.viewport().update()

    def layout_region(self, reg, ri: RegionItem | None = None) -> None:
        ri = ri or self.region_items.get(reg.id)
        if ri is None:
            return
        cw, ch = self.cell()
        skip = set(self.drag["ids"]) if self.drag else set()
        if reg.collapsed:
            for ref in reg.images:
                ti = self.thumb_items.get(ref.id)
                if ti and ref.id not in skip:
                    ti.setVisible(False)
            ri.set_geometry(reg.w, TITLE_H)
            return
        if reg.auto_arrange:
            cols = grid_cols(reg.w, cw)
            for i, ref in enumerate(reg.images):
                ti = self.thumb_items.get(ref.id)
                if ti and ref.id not in skip:
                    ti.setVisible(True)
                    ti.setPos(*grid_pos(i, cols, cw, ch))
            ri.set_geometry(reg.w, max(reg.h, grid_content_height(len(reg.images), cols, ch)))
        else:
            w, h = reg.w, reg.h
            for ref in reg.images:
                ti = self.thumb_items.get(ref.id)
                if ti and ref.id not in skip:
                    ti.setVisible(True)
                    ti.setPos(ref.x, ref.y)
                w, h = max(w, ref.x + cw + PAD), max(h, ref.y + ch + PAD)
            ri.set_geometry(w, h)

    def _thumb_ready(self, path: str) -> None:
        for rid in self._by_path.get(path, ()):
            ti = self.thumb_items.get(rid)
            if ti:
                ti.update()

    # --------------------------------------------------------- hit testing
    def item_at(self, view_pt) -> ThumbItem | RegionItem | None:
        for it in self.items(view_pt):
            if isinstance(it, ThumbItem) and it.parentItem() is not None and it.isVisible():
                return it
            if isinstance(it, RegionItem):
                return it
        return None

    def region_at(self, scene_pt: QPointF) -> RegionItem | None:
        for it in self.scene().items(scene_pt):
            if isinstance(it, RegionItem):
                return it
            if isinstance(it, ThumbItem) and isinstance(it.parentItem(), RegionItem):
                return it.parentItem()
        return None

    def selected_thumbs(self) -> list[ThumbItem]:
        return [it for it in self.scene().selectedItems() if isinstance(it, ThumbItem)]

    def selected_ids(self) -> list[str]:
        return [t.ref_id for t in self.selected_thumbs()]

    def set_selection(self, ids, add=False) -> None:
        ids = set(ids)
        sc = self.scene()
        sc.blockSignals(True)
        if not add:
            for t in self.selected_thumbs():
                if t.ref_id not in ids:
                    t.setSelected(False)
        for rid in ids:
            t = self.thumb_items.get(rid)
            if t is not None and t.isVisible():
                t.setSelected(True)
        sc.blockSignals(False)
        self.ctrl.on_selection_changed()

    def clear_selection(self) -> None:
        self.set_selection([])

    # ------------------------------------------------------------ viewport
    def zoom_by(self, factor: float) -> None:
        cur = self.zoom()
        target = min(max(cur * factor, ZOOM_MIN), ZOOM_MAX)
        if abs(target - cur) > 1e-9:
            self.scale(target / cur, target / cur)
            self.zoomChanged.emit(self.zoom())

    def set_zoom(self, z: float, center: QPointF | None = None) -> None:
        z = min(max(z, ZOOM_MIN), ZOOM_MAX)
        c = center if center is not None else self.mapToScene(self.viewport().rect().center())
        self.resetTransform()
        self.scale(z, z)
        self.centerOn(c)
        self.zoomChanged.emit(self.zoom())

    def fit_rect(self, rect: QRectF) -> None:
        if rect.isNull() or rect.isEmpty():
            return
        rect = rect.adjusted(-40, -40, 40, 40)
        vw, vh = max(self.viewport().width(), 50), max(self.viewport().height(), 50)
        self.set_zoom(min(vw / rect.width(), vh / rect.height(), 1.5), rect.center())

    def fit_all(self) -> None:
        r = QRectF()
        for ri in self.region_items.values():
            r = r.united(ri.sceneBoundingRect())
        if r.isNull():
            self.set_zoom(1.0, QPointF(0, 0))
        else:
            self.fit_rect(r)

    def view_center(self) -> QPointF:
        return self.mapToScene(self.viewport().rect().center())

    def wheelEvent(self, e):
        d = e.angleDelta().y() or e.angleDelta().x()
        if not d:
            return
        steps = d / 120.0
        if e.modifiers() & Qt.ControlModifier:
            self.ctrl.set_thumb_size(round(self.ctrl.project.thumb_size * (1.1 ** steps)))
        else:
            self.zoom_by(1.15 ** steps)
        e.accept()

    def drawBackground(self, p, rect):
        p.fillRect(rect, QColor("#1b1c1f"))
        step = 50
        if self.zoom() * step < 10:
            step *= 5
            if self.zoom() * step < 10:
                return
        left = int(rect.left()) - int(rect.left()) % step
        top = int(rect.top()) - int(rect.top()) % step
        p.setPen(QPen(QColor(255, 255, 255, 14), 0))
        x = left
        while x < rect.right():
            p.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            x += step
        y = top
        while y < rect.bottom():
            p.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            y += step

    def drawForeground(self, p, rect):
        if self.region_items:
            return
        p.save()
        p.resetTransform()
        p.setPen(QColor(200, 200, 200, 160))
        f = p.font()
        f.setPixelSize(16)
        p.setFont(f)
        p.drawText(QRectF(self.viewport().rect()), Qt.AlignCenter,
                   tr("Right-click → New Region   ·   or drop images / folders here\n"
                      "Wheel = zoom   ·   Ctrl+Wheel = thumbnail size   ·   Middle-drag or Space+drag = pan"))
        p.restore()

    # --------------------------------------------------------------- mouse
    def mousePressEvent(self, e):
        self.setFocus()
        vp = e.position()
        sp = self.mapToScene(vp.toPoint())
        btn, mods = e.button(), e.modifiers()
        if btn == Qt.RightButton:
            if self.mode in ("drag", "region_move", "region_resize", "rubber", "press_thumb"):
                self.cancel_interaction()
                self._right_cancelled = True
                self.ctrl.status(tr("Cancelled (right-click)"))
            e.accept()
            return
        if btn == Qt.MiddleButton or (btn == Qt.LeftButton and self.space_down):
            self.mode = "pan"
            self._last_pos = vp
            self.viewport().setCursor(Qt.ClosedHandCursor)
            e.accept()
            return
        if btn != Qt.LeftButton:
            return
        ctrl_mod = bool(mods & Qt.ControlModifier)
        shift_mod = bool(mods & Qt.ShiftModifier)
        it = self.item_at(vp.toPoint())
        self._press_scene = sp
        self._press_view = vp
        if isinstance(it, ThumbItem):
            region_id = it.parentItem().region_id
            self.ctrl.activate_region(region_id)
            self._select_only_on_release = None
            if shift_mod and self.anchor_id:
                self.set_selection(self.ctrl.range_ids(self.anchor_id, it.ref_id), add=ctrl_mod)
            elif ctrl_mod:
                it.setSelected(not it.isSelected())
                self.ctrl.on_selection_changed()
                self.anchor_id = it.ref_id
            else:
                if not it.isSelected():
                    self.set_selection([it.ref_id])
                else:
                    self._select_only_on_release = it
                self.anchor_id = it.ref_id
            self.mode = "press_thumb"
            self._press_item = it
        elif isinstance(it, RegionItem):
            reg = self.ctrl.project.region(it.region_id)
            zone = it.zone(it.mapFromScene(sp))
            self.ctrl.activate_region(it.region_id, toggle=ctrl_mod and zone in ("title", "arrow"))
            if zone == "arrow":
                self.ctrl.toggle_collapse(it.region_id)
            elif zone == "title":
                self.mode = "region_move"
                self._snapshot = self.ctrl.snapshot()
                self._orig = (reg.x, reg.y)
                self._region = reg
            elif zone == "grip":
                self.mode = "region_resize"
                self._snapshot = self.ctrl.snapshot()
                self._orig = (reg.w, reg.h, it.w, it.h)
                self._region = reg
            else:
                self._start_rubber(sp, ctrl_mod)
        else:
            self.ctrl.activate_region(None)
            self._start_rubber(sp, ctrl_mod)
        e.accept()

    def mouseMoveEvent(self, e):
        vp = e.position()
        self._last_vp = vp
        if self.mode == "pan":
            d = vp - self._last_pos
            self._last_pos = vp
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(d.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(d.y()))
        elif self.mode in ("press_thumb",) + AUTOSCROLL_MODES:
            self._pointer_moved(vp)
            if self.mode in AUTOSCROLL_MODES and self._edge_speed(vp) != (0, 0):
                if not self._autoscroll.isActive():
                    self._autoscroll.start()
        else:
            super().mouseMoveEvent(e)
            return
        e.accept()

    def _edge_speed(self, vp: QPointF) -> tuple[int, int]:
        """Scroll speed when the pointer is near/outside the viewport edge."""
        r = self.viewport().rect()

        def axis(pos: float, size: int) -> int:
            if pos < AUTOSCROLL_EDGE:
                return -round(AUTOSCROLL_SPEED * min(1.0, (AUTOSCROLL_EDGE - pos) / AUTOSCROLL_EDGE))
            if pos > size - AUTOSCROLL_EDGE:
                return round(AUTOSCROLL_SPEED * min(1.0, (pos - size + AUTOSCROLL_EDGE) / AUTOSCROLL_EDGE))
            return 0
        return axis(vp.x(), r.width()), axis(vp.y(), r.height())

    def _autoscroll_tick(self) -> None:
        if self.mode not in AUTOSCROLL_MODES:
            self._autoscroll.stop()
            return
        dx, dy = self._edge_speed(self._last_vp)
        if (dx, dy) == (0, 0):
            self._autoscroll.stop()
            return
        h, v = self.horizontalScrollBar(), self.verticalScrollBar()
        h.setValue(h.value() + dx)
        v.setValue(v.value() + dy)
        self._pointer_moved(self._last_vp)  # the pointer now covers another scene point

    def _pointer_moved(self, vp: QPointF) -> None:
        sp = self.mapToScene(vp.toPoint())
        if self.mode == "press_thumb":
            if (vp - self._press_view).manhattanLength() >= QApplication.startDragDistance():
                self._begin_drag()
                if self.mode == "drag":
                    self._update_drag(sp)
        elif self.mode == "drag":
            self._update_drag(sp)
        elif self.mode == "region_move":
            d = sp - self._press_scene
            self._region.x, self._region.y = self._orig[0] + d.x(), self._orig[1] + d.y()
            self.region_items[self._region.id].setPos(self._region.x, self._region.y)
        elif self.mode == "region_resize":
            d = sp - self._press_scene
            cw, ch = self.cell()
            # start from the displayed size so an auto-grown region resizes intuitively
            self._region.w = max(2 * PAD + cw, self._orig[2] + d.x())
            self._region.h = max(TITLE_H + 2 * PAD + 20, self._orig[3] + d.y())
            self.layout_region(self._region)
        elif self.mode == "rubber":
            r = QRectF(self._press_scene, sp).normalized()
            self.rubber.setRect(r)
            hit = {it.ref_id for it in self.scene().items(r, Qt.IntersectsItemBoundingRect)
                   if isinstance(it, ThumbItem) and it.isVisible() and it.parentItem() is not None}
            self.set_selection(hit | self._rubber_base)

    def mouseReleaseEvent(self, e):
        vp = e.position()
        sp = self.mapToScene(vp.toPoint())
        if e.button() == Qt.RightButton:
            if self._right_cancelled:
                self._right_cancelled = False
            elif self.mode is None:
                self.open_context_menu(vp.toPoint(), e.globalPosition().toPoint())
            e.accept()
            return
        if self.mode == "pan" and e.button() in (Qt.MiddleButton, Qt.LeftButton):
            self.mode = None
            self.viewport().setCursor(Qt.OpenHandCursor if self.space_down else Qt.ArrowCursor)
        elif e.button() != Qt.LeftButton:
            return
        elif self.mode == "press_thumb":
            if self._select_only_on_release is not None:
                self.set_selection([self._select_only_on_release.ref_id])
            self.mode = None
        elif self.mode == "drag":
            self._finish_drag(sp, e.modifiers())
        elif self.mode in ("region_move", "region_resize"):
            self.mode = None
            if self.ctrl.snapshot_changed(self._snapshot):
                self.ctrl.commit_snapshot(self._snapshot)
            self.ctrl.refresh()
        elif self.mode == "rubber":
            self._end_rubber()
        e.accept()

    def mouseDoubleClickEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        it = self.item_at(e.position().toPoint())
        if isinstance(it, ThumbItem):
            self.mode = None
            self.ctrl.open_viewer(it.ref_id)
        elif isinstance(it, RegionItem):
            zone = it.zone(it.mapFromScene(self.mapToScene(e.position().toPoint())))
            if zone == "title":
                self.mode = None
                self.ctrl.rename_region(it.region_id)
            elif zone == "body":
                self._start_rubber(self.mapToScene(e.position().toPoint()), False)
        e.accept()

    def contextMenuEvent(self, e):
        # Mouse-triggered menus are opened on right-button release (so a
        # right-click that cancels a drag never opens one). Keyboard menu key:
        if e.reason() != e.Reason.Mouse:
            pos = self.mapFromGlobal(self.cursor().pos())
            self.open_context_menu(pos, self.cursor().pos())
        e.accept()

    def open_context_menu(self, view_pt, global_pt) -> None:
        sp = self.mapToScene(view_pt)
        it = self.item_at(view_pt)
        if isinstance(it, ThumbItem):
            if not it.isSelected():
                self.set_selection([it.ref_id])
                self.anchor_id = it.ref_id
            self.ctrl.activate_region(it.parentItem().region_id)
            self.ctrl.image_menu(global_pt, it.ref_id)
        elif isinstance(it, RegionItem):
            self.ctrl.activate_region(it.region_id)
            self.ctrl.region_menu(global_pt, it.region_id, sp)
        else:
            self.ctrl.canvas_menu(global_pt, sp)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Space and not e.isAutoRepeat():
            self.space_down = True
            if self.mode is None:
                self.viewport().setCursor(Qt.OpenHandCursor)
            e.accept()
            return
        super().keyPressEvent(e)

    def keyReleaseEvent(self, e):
        if e.key() == Qt.Key_Space and not e.isAutoRepeat():
            self.space_down = False
            if self.mode != "pan":
                self.viewport().setCursor(Qt.ArrowCursor)
            e.accept()
            return
        super().keyReleaseEvent(e)

    def focusOutEvent(self, e):
        self.space_down = False
        super().focusOutEvent(e)

    # -------------------------------------------------------- rubber band
    def _start_rubber(self, sp: QPointF, additive: bool) -> None:
        self._rubber_base = set(self.selected_ids()) if additive else set()
        if not additive:
            self.clear_selection()
        self.rubber = QGraphicsRectItem(QRectF(sp, sp))
        c = QColor(ACCENT)
        self.rubber.setPen(QPen(c, 0, Qt.DashLine))
        c.setAlpha(40)
        self.rubber.setBrush(QBrush(c))
        self.rubber.setZValue(10_000_000)
        self.scene().addItem(self.rubber)
        self.mode = "rubber"

    def _end_rubber(self) -> None:
        if self.rubber is not None:
            self.scene().removeItem(self.rubber)
            self.rubber = None
        self.mode = None

    # ---------------------------------------------------------- image drag
    def _begin_drag(self) -> None:
        sel = [t for t in self.selected_thumbs() if t.isVisible() and t.parentItem() is not None]
        movable = [t for t in sel if not t.locked]
        if self._press_item.locked or not movable:
            self.ctrl.status(tr("Locked images can't be moved. Unlock them first."))
            self.mode = None
            return
        order = self.ctrl.sequence_key()
        movable.sort(key=lambda t: order.get(t.ref_id, (1 << 30, 0)))
        self.drag = {"items": movable, "ids": [t.ref_id for t in movable],
                     "orig": {t: (t.parentItem(), t.pos()) for t in movable},
                     "scene0": {}, "target": None, "slot": None}
        for t in movable:
            p0 = t.scenePos()
            self.drag["scene0"][t] = p0
            t.setParentItem(None)
            t.setPos(p0)
            t.setZValue(1_000_000)
            t.setOpacity(0.82)
        if len(movable) < len(sel):
            self.ctrl.status(tr("{n} locked image(s) stay in place", n=len(sel) - len(movable)))
        self.mode = "drag"
        self.viewport().setCursor(Qt.ClosedHandCursor)

    def _update_drag(self, sp: QPointF) -> None:
        dr = self.drag
        d = sp - self._press_scene
        for t in dr["items"]:
            t.setPos(dr["scene0"][t] + d)
        target = self.region_at(sp)
        prev = dr["target"]
        if prev is not None and prev is not target:
            prev.set_drop_hint(False)
            preg = self.ctrl.project.region(prev.region_id)
            if preg:
                self.layout_region(preg, prev)
        dr["target"], dr["slot"] = target, None
        if target is None:
            return
        target.set_drop_hint(True)
        reg = self.ctrl.project.region(target.region_id)
        if reg is None or reg.collapsed or not reg.auto_arrange:
            return
        ids = set(dr["ids"])
        remaining = [r for r in reg.images if r.id not in ids]
        cw, ch = self.cell()
        cols = grid_cols(reg.w, cw)
        local = target.mapFromScene(sp)
        slot = adjust_insert_index(remaining, slot_at(local.x(), local.y(), cols, cw, ch, len(remaining)))
        dr["slot"] = slot
        n = len(ids)
        for j, ref in enumerate(remaining):  # live preview: open a gap at the slot
            ti = self.thumb_items.get(ref.id)
            if ti is not None:
                ti.setPos(*grid_pos(j if j < slot else j + n, cols, cw, ch))
        target.set_geometry(reg.w, max(reg.h, grid_content_height(len(remaining) + n, cols, ch)))

    def _finish_drag(self, sp: QPointF, mods) -> None:
        dr = self.drag
        target = dr["target"]
        self.viewport().setCursor(Qt.ArrowCursor)
        if target is None:
            self.cancel_drag()
            self.ctrl.status(tr("Dropped outside any region: move cancelled"))
            return
        target.set_drop_hint(False)
        positions = {}
        for t in dr["items"]:
            lp = target.mapFromScene(t.scenePos())
            positions[t.ref_id] = (max(0.0, lp.x()), max(float(TITLE_H), lp.y()))
        copy = bool(mods & Qt.ControlModifier)
        ids, slot = dr["ids"], dr["slot"]
        self.drag = None
        self.mode = None
        self.ctrl.commit_drag(ids, target.region_id, slot, positions, copy)

    def cancel_drag(self) -> None:
        dr = self.drag
        if not dr:
            return
        self.drag = None
        for t, (parent, pos) in dr["orig"].items():
            t.setParentItem(parent)
            t.setPos(pos)
            t.setZValue(0)
            t.setOpacity(1.0)
        if dr["target"] is not None:
            dr["target"].set_drop_hint(False)
        for ri in self.region_items.values():
            reg = self.ctrl.project.region(ri.region_id)
            if reg:
                self.layout_region(reg, ri)
        self.mode = None
        self.viewport().setCursor(Qt.ArrowCursor)

    def cancel_interaction(self) -> bool:
        """Esc / right-click: abort whatever the mouse is doing."""
        m = self.mode
        if m == "drag":
            self.cancel_drag()
        elif m in ("region_move", "region_resize"):
            self.ctrl.restore_snapshot(self._snapshot)
        elif m == "rubber":
            self._end_rubber()
            self.set_selection(self._rubber_base)
        self.mode = None
        return m is not None

    # ---------------------------------------------------------- file drops
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if not paths:
            return
        sp = self.mapToScene(e.position().toPoint())
        ri = self.region_at(sp)
        index = None
        if ri is not None:
            reg = self.ctrl.project.region(ri.region_id)
            if reg and reg.auto_arrange and not reg.collapsed:
                cw, ch = self.cell()
                local = ri.mapFromScene(sp)
                index = slot_at(local.x(), local.y(), grid_cols(reg.w, cw), cw, ch, len(reg.images))
        e.acceptProposedAction()
        self.ctrl.import_paths(paths, ri.region_id if ri else None, index)
