"""The freeform canvas: mirrors the Project and turns mouse input into
calls on the main window controller (which owns the model and undo)."""
from __future__ import annotations


from PySide6.QtCore import QLineF, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QApplication, QGraphicsDropShadowEffect, QGraphicsPathItem,
                               QGraphicsRectItem, QGraphicsScene, QGraphicsView)

from . import theme
from .items import RegionItem, ThumbItem
from .i18n import tr
from .model import (PAD, TITLE_H, adjust_insert_index, grid_cols,
                    grid_content_height, grid_pos, slot_at)

ZOOM_MIN = 0.04  # open item: canvas zoom limits
ZOOM_MAX = 4.0
WORLD = 1_000_000
AUTOSCROLL_EDGE = 48     # px from the viewport edge where auto-scroll starts
AUTOSCROLL_SPEED = 28    # max px per tick (~60 ticks/s)
AUTOSCROLL_MODES = ("drag", "region_move", "region_resize", "rubber")
REGION_SCROLL_STEP = 60  # px per wheel notch (Shift+Wheel) inside a scrolling region
ANIM_FACTOR = 0.3        # share of the remaining distance moved per frame (smooth reflow)


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
        self.hand_tool = False
        self._right_cancelled = False
        self._last_pos = QPointF()
        self.drag: dict | None = None
        self.rubber: QGraphicsRectItem | None = None
        self.anchor_id: str | None = None  # for shift-click ranges
        self._last_vp = QPointF()
        self._autoscroll = QTimer(self)
        self._autoscroll.setInterval(16)
        self._autoscroll.timeout.connect(self._autoscroll_tick)
        self._anim: dict[ThumbItem, QPointF] = {}
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(16)
        self._anim_timer.timeout.connect(self._anim_tick)
        self._placeholders: list[QGraphicsPathItem] = []
        self.search_hits: set[str] = set()
        self.search_regions: set[str] = set()

    # ------------------------------------------------------------ settings
    def show_numbers(self) -> bool:
        return self.ctrl.project.show_numbers

    def show_labels(self) -> bool:
        return self.ctrl.project.show_labels

    def show_region_names(self) -> bool:
        return self.ctrl.project.show_region_names

    def label_shown(self) -> bool:
        return self.ctrl.project.label_shown()

    def thumb_fill(self) -> str:
        return self.ctrl.project.thumb_fill

    def cell(self) -> tuple[int, int]:
        return self.ctrl.project.cell()

    def zoom(self) -> float:
        return self.transform().m11()

    # ---------------------------------------------------------------- sync
    def sync(self) -> None:
        """Bring the scene in line with the model (create / update / remove)."""
        if self.drag:
            self.cancel_drag()
        p = self.ctrl.project
        cw, ch = self.cell()
        img_h = p.image_box()[1]
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
                ti.setRotation(0)
                ti.setGraphicsEffect(None)
                ti.set_cell(cw, ch, img_h)
                ti.set_data(ref, i, ref.id in self.ctrl.cut_ids)
                ti.update()  # display settings (fill, labels, theme) may have changed: redo the cached paint
                live_refs.add(ref.id)
                self._by_path.setdefault(ref.path, set()).add(ref.id)
            self.layout_region(reg, ri)
        for rid in [k for k in self.thumb_items if k not in live_refs]:
            ti = self.thumb_items.pop(rid)
            self._anim.pop(ti, None)
            self.scene().removeItem(ti)
        for gid in [k for k in self.region_items if k not in live_regions]:
            self.scene().removeItem(self.region_items.pop(gid))
        self.viewport().update()

    @staticmethod
    def scroll_offset(reg) -> float:
        return reg.scroll if reg.scroll_enabled and not reg.collapsed else 0.0

    def layout_region(self, reg, ri: RegionItem | None = None, animate: bool = False) -> None:
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
            ri.set_scroll(False, 0, 0)
            ri.set_geometry(reg.w, TITLE_H)
            return
        if reg.auto_arrange:
            cols = grid_cols(reg.w, cw)
            spots = [grid_pos(i, cols, cw, ch) for i in range(len(reg.images))]
            w, content_h = reg.w, grid_content_height(len(reg.images), cols, ch)
        else:
            spots = [(ref.x, ref.y) for ref in reg.images]
            w, content_h = reg.w, reg.h
            for x, y in spots:
                w, content_h = max(w, x + cw + PAD), max(content_h, y + ch + PAD)
        h = self._apply_scroll(reg, content_h)
        off = self.scroll_offset(reg)
        for ref, (x, y) in zip(reg.images, spots):
            ti = self.thumb_items.get(ref.id)
            if ti and ref.id not in skip:
                ti.setVisible(not reg.scroll_enabled or (y - off + ch > TITLE_H and y - off < h))
                self._place(ti, x, y - off, animate)
                if reg.scroll_enabled:
                    ti.update()  # its clip to the region body depends on where it sits
        ri.set_scroll(reg.scroll_enabled, off, content_h)
        ri.set_geometry(w, h)

    def _apply_scroll(self, reg, content_h: float) -> float:
        """Clamp the region's scroll; returns the displayed height."""
        if not reg.scroll_enabled:
            return max(reg.h, content_h)
        reg.scroll = min(max(reg.scroll, 0.0), max(0.0, content_h - reg.h))
        return reg.h

    def scroll_region(self, reg, delta: float) -> None:
        reg.scroll += delta
        self.layout_region(reg)
        self.ctrl.sidebar.minimap.update()

    def reveal(self, ref_id: str) -> None:
        """Scroll a scrolling region so the image is inside, then centre it."""
        ti = self.thumb_items.get(ref_id)
        if ti is None or not isinstance(ti.parentItem(), RegionItem):
            return
        reg = self.ctrl.project.region(ti.parentItem().region_id)
        if reg and reg.scroll_enabled:
            y = ti.pos().y() + reg.scroll
            reg.scroll = y - TITLE_H - PAD
            self.layout_region(reg)
        self.centerOn(ti.sceneBoundingRect().center())

    # smooth movement of thumbnails (drag preview reflow)
    def _place(self, ti: ThumbItem, x: float, y: float, animate: bool) -> None:
        target = QPointF(x, y)
        if animate and (ti.pos() - target).manhattanLength() > 0.5:
            self._anim[ti] = target
            if not self._anim_timer.isActive():
                self._anim_timer.start()
        else:
            self._anim.pop(ti, None)
            ti.setPos(target)

    def _anim_tick(self) -> None:
        for ti, tgt in list(self._anim.items()):
            d = tgt - ti.pos()
            if d.manhattanLength() < 0.6:
                ti.setPos(tgt)
                del self._anim[ti]
            else:
                ti.setPos(ti.pos() + d * ANIM_FACTOR)
            parent = ti.parentItem()
            if isinstance(parent, RegionItem) and parent.scroll_on:
                ti.update()
        if not self._anim:
            self._anim_timer.stop()

    def set_search(self, hits: set[str], regions: set[str]) -> None:
        changed = self.search_hits ^ hits
        self.search_hits, self.search_regions = hits, regions
        for rid in changed:
            ti = self.thumb_items.get(rid)
            if ti:
                ti.update()
        for ri in self.region_items.values():
            ri.update()

    def repaint_all_items(self) -> None:
        """After a theme change: cached item pictures must be redrawn."""
        for it in list(self.thumb_items.values()) + list(self.region_items.values()):
            it.update()
        self.scene().update()
        self.viewport().update()

    def _thumb_ready(self, path: str) -> None:
        for rid in self._by_path.get(path, ()):
            ti = self.thumb_items.get(rid)
            if ti:
                ti.update()

    # --------------------------------------------------------- hit testing
    def item_at(self, view_pt) -> ThumbItem | RegionItem | None:
        sp = self.mapToScene(view_pt)
        for it in self.items(view_pt):
            if isinstance(it, ThumbItem) and it.parentItem() is not None and it.isVisible():
                parent = it.parentItem()
                if isinstance(parent, RegionItem) and parent.scroll_on \
                        and not parent.body_rect().contains(parent.mapFromScene(sp)):
                    continue  # scrolled under the header / out of the window
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
    def zoom_by(self, factor: float, centered: bool = False) -> None:
        cur = self.zoom()
        target = min(max(cur * factor, ZOOM_MIN), ZOOM_MAX)
        if abs(target - cur) > 1e-9:
            if centered:  # buttons: keep the view centre (wheel zooms under the mouse)
                self.set_zoom(target)
                return
            self.scale(target / cur, target / cur)
            self.zoomChanged.emit(self.zoom())

    def set_hand_tool(self, on: bool) -> None:
        self.hand_tool = on
        if self.mode is None:
            self.viewport().setCursor(Qt.OpenHandCursor if on else Qt.ArrowCursor)

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
        if e.modifiers() & Qt.ShiftModifier and not e.modifiers() & Qt.ControlModifier:
            ri = self.region_at(self.mapToScene(e.position().toPoint()))
            reg = self.ctrl.project.region(ri.region_id) if ri else None
            if reg is not None and reg.scroll_enabled and not reg.collapsed:
                self.scroll_region(reg, -steps * REGION_SCROLL_STEP)
                e.accept()
                return
        if e.modifiers() & Qt.ControlModifier:
            self.ctrl.set_thumb_size(round(self.ctrl.project.thumb_size * (1.1 ** steps)))
        else:
            self.zoom_by(1.15 ** steps)
        e.accept()

    def drawBackground(self, p, rect):
        t = theme.current()
        p.fillRect(rect, theme.c(t.canvas_bg))
        step = 50
        if self.zoom() * step < 10:
            step *= 5
            if self.zoom() * step < 10:
                return
        left = int(rect.left()) - int(rect.left()) % step
        top = int(rect.top()) - int(rect.top()) % step
        grid = theme.c(t.grid)  # pre-blend: opaque hairlines without antialiasing are far cheaper
        bg = theme.c(t.canvas_bg)
        p.save()
        p.setRenderHint(QPainter.Antialiasing, False)
        p.setPen(QPen(theme.blend(bg, QColor(grid.red(), grid.green(), grid.blue()), grid.alphaF()), 0))
        lines = [QLineF(x, rect.top(), x, rect.bottom()) for x in range(left, int(rect.right()) + 1, step)]
        lines += [QLineF(rect.left(), y, rect.right(), y) for y in range(top, int(rect.bottom()) + 1, step)]
        p.drawLines(lines)
        p.restore()

    def drawForeground(self, p, rect):
        if self.region_items:
            return
        p.save()
        p.resetTransform()
        p.setPen(theme.c(theme.current().subtext))
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
        if btn == Qt.MiddleButton or (btn == Qt.LeftButton and (self.space_down or self.hand_tool)):
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
            elif zone == "switch":
                self.ctrl.toggle_auto(it.region_id)
            elif zone == "scrollbar":
                self.mode = "region_scroll"
                self._region = reg
                self._orig = (reg.scroll, it.body_rect().height(), it.content_h)
            elif zone == "menu":
                below = it.mapToScene(it.r_menu.bottomLeft())
                self.ctrl.region_menu(self.viewport().mapToGlobal(self.mapFromScene(below)), it.region_id, sp)
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
        elif self.mode == "region_scroll":
            scroll0, body_h, content_h = self._orig
            dy = self.mapToScene(vp.toPoint()).y() - self._press_scene.y()
            self._region.scroll = scroll0 + dy * content_h / max(body_h, 1.0)
            self.layout_region(self._region)
            self.ctrl.sidebar.minimap.update()
        elif self.mode in ("press_thumb",) + AUTOSCROLL_MODES:
            self._pointer_moved(vp)
            if self.mode in AUTOSCROLL_MODES and (self._edge_speed(vp) != (0, 0)
                                                 or self._region_edge_speed(vp)[1]):
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

    def _region_edge_speed(self, vp: QPointF):
        """While dragging images over a scrolling region: scroll it near its top/bottom."""
        if self.mode != "drag" or not self.drag or self.drag.get("target") is None:
            return None, 0
        ri = self.drag["target"]
        reg = self.ctrl.project.region(ri.region_id)
        if reg is None or not reg.scroll_enabled or reg.collapsed:
            return None, 0
        y = ri.mapFromScene(self.mapToScene(vp.toPoint())).y()
        body = ri.body_rect()
        edge = 36
        if y < body.top() + edge:
            return reg, -round(AUTOSCROLL_SPEED * 0.6 * min(1.0, (body.top() + edge - y) / edge))
        if y > body.bottom() - edge:
            return reg, round(AUTOSCROLL_SPEED * 0.6 * min(1.0, (y - body.bottom() + edge) / edge))
        return None, 0

    def _autoscroll_tick(self) -> None:
        if self.mode not in AUTOSCROLL_MODES:
            self._autoscroll.stop()
            return
        dx, dy = self._edge_speed(self._last_vp)
        reg, rdy = self._region_edge_speed(self._last_vp)
        if (dx, dy) == (0, 0) and not rdy:
            self._autoscroll.stop()
            return
        h, v = self.horizontalScrollBar(), self.verticalScrollBar()
        h.setValue(h.value() + dx)
        v.setValue(v.value() + dy)
        if rdy:
            reg.scroll += rdy  # clamped by the next layout
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
            hit = {it.ref_id for it in self.scene().items(r, Qt.IntersectsItemShape)
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
            self.viewport().setCursor(Qt.OpenHandCursor if self.space_down or self.hand_tool else Qt.ArrowCursor)
        elif e.button() != Qt.LeftButton:
            return
        elif self.mode == "press_thumb":
            if self._select_only_on_release is not None:
                self.set_selection([self._select_only_on_release.ref_id])
            self.mode = None
        elif self.mode == "drag":
            self._finish_drag(sp, e.modifiers())
        elif self.mode == "region_scroll":
            self.mode = None
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
        c = theme.c(theme.current().accent)
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
        anchor = self._press_item if self._press_item in movable else movable[0]
        for t in movable:
            p0 = t.scenePos()
            self.drag["scene0"][t] = p0
            self._anim.pop(t, None)
            t.setParentItem(None)
            t.setPos(p0)
            t.setZValue(1_000_001 if t is anchor else 1_000_000)
            t.setOpacity(0.92 if t is anchor else 0.8)
            t.setTransformOriginPoint(t.cw / 2, t.img_h / 2)
            t.setRotation(-4.0 if t is anchor else -2.0)  # "lifted" ghost
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(26)
        shadow.setOffset(0, 10)
        shadow.setColor(QColor(0, 0, 0, 90))
        anchor.setGraphicsEffect(shadow)
        if len(movable) < len(sel):
            self.ctrl.status(tr("{n} locked image(s) stay in place", n=len(sel) - len(movable)))
        self.mode = "drag"
        self.viewport().setCursor(Qt.ClosedHandCursor)

    def _show_placeholders(self, ri: RegionItem | None, rects: list[QRectF]) -> None:
        """Dashed boxes where the dragged images will land."""
        while len(self._placeholders) > len(rects):
            self.scene().removeItem(self._placeholders.pop())
        t = theme.current()
        pen = QPen(theme.c(t.accent), 2, Qt.DashLine)
        fill = theme.c(t.accent)
        fill.setAlpha(28)
        for i, r in enumerate(rects):
            if i >= len(self._placeholders):
                item = QGraphicsPathItem()
                item.setPen(pen)
                item.setBrush(fill)
                item.setZValue(-1)
                item.setAcceptedMouseButtons(Qt.NoButton)
                self._placeholders.append(item)
            item = self._placeholders[i]
            if item.parentItem() is not ri:
                item.setParentItem(ri)
            path = QPainterPath()
            path.addRoundedRect(r, 6, 6)
            item.setPath(path)

    def _clear_placeholders(self) -> None:
        self._show_placeholders(None, [])

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
                self.layout_region(preg, prev, animate=True)
        dr["target"], dr["slot"] = target, None
        if target is None:
            self._clear_placeholders()
            return
        target.set_drop_hint(True)
        reg = self.ctrl.project.region(target.region_id)
        if reg is None or reg.collapsed or not reg.auto_arrange:
            self._clear_placeholders()
            return
        ids = set(dr["ids"])
        remaining = [r for r in reg.images if r.id not in ids]
        cw, ch = self.cell()
        img_h = self.ctrl.project.image_box()[1]
        cols = grid_cols(reg.w, cw)
        n = len(ids)
        content_h = grid_content_height(len(remaining) + n, cols, ch)
        h = self._apply_scroll(reg, content_h)
        off = self.scroll_offset(reg)
        local = target.mapFromScene(sp)
        slot = adjust_insert_index(remaining, slot_at(local.x(), local.y() + off, cols, cw, ch, len(remaining)))
        dr["slot"] = slot
        for j, ref in enumerate(remaining):  # live preview: open a gap at the slot
            ti = self.thumb_items.get(ref.id)
            if ti is not None:
                x, y = grid_pos(j if j < slot else j + n, cols, cw, ch)
                ti.setVisible(not reg.scroll_enabled or (y - off + ch > TITLE_H and y - off < h))
                self._place(ti, x, y - off, animate=True)
                if reg.scroll_enabled:
                    ti.update()
        spots = [grid_pos(slot + i, cols, cw, ch) for i in range(n)]
        self._show_placeholders(target, [QRectF(x, y - off, cw, img_h) for x, y in spots
                                         if not reg.scroll_enabled or TITLE_H - ch < y - off < h])
        target.set_scroll(reg.scroll_enabled, off, content_h)
        target.set_geometry(reg.w, h)

    def _finish_drag(self, sp: QPointF, mods) -> None:
        dr = self.drag
        target = dr["target"]
        self.viewport().setCursor(Qt.ArrowCursor)
        self._clear_placeholders()
        if target is None:
            self.cancel_drag()
            self.ctrl.status(tr("Dropped outside any region: move cancelled"))
            return
        target.set_drop_hint(False)
        reg = self.ctrl.project.region(target.region_id)
        off = self.scroll_offset(reg) if reg else 0.0
        positions = {}
        for t in dr["items"]:
            t.setRotation(0)
            lp = target.mapFromScene(t.scenePos())
            positions[t.ref_id] = (max(0.0, lp.x()), max(float(TITLE_H), lp.y()) + off)
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
        self._clear_placeholders()
        for t, (parent, pos) in dr["orig"].items():
            t.setParentItem(parent)
            t.setPos(pos)
            t.setZValue(0)
            t.setOpacity(1.0)
            t.setRotation(0)
            t.setGraphicsEffect(None)
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
