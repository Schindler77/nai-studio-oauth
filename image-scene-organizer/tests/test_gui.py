"""End-to-end test of the §33 flow, driving the real window with synthetic
mouse / keyboard / wheel events (offscreen Qt platform)."""
import os
import shutil
import time

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QImage, QKeySequence, QMouseEvent, QPainter, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox

from scene_organizer import mainwindow as mw_mod
from scene_organizer.mainwindow import MainWindow
from scene_organizer.viewer import ImageViewer


def make_images(folder, n, prefix="img", size=(640, 400)):
    os.makedirs(folder, exist_ok=True)
    out = []
    for i in range(1, n + 1):
        img = QImage(size[0], size[1], QImage.Format_RGB32)
        img.fill(QColor.fromHsv((i * 47) % 360, 160, 220))
        p = QPainter(img)
        p.setPen(Qt.black)
        f = p.font()
        f.setPixelSize(160)
        p.setFont(f)
        p.drawText(img.rect(), Qt.AlignCenter, f"{i:02d}")
        p.end()
        path = os.path.join(folder, f"{prefix}{i:02d}.png")
        img.save(path)
        out.append(path)
    return out


def pump(ms=50):
    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        QApplication.processEvents()
        time.sleep(0.005)


def send_mouse(w, typ, pos, button=Qt.LeftButton, buttons=None, mods=Qt.NoModifier):
    pos = QPointF(pos)
    ev = QMouseEvent(typ, pos, QPointF(w.mapToGlobal(pos.toPoint())), button,
                     button if buttons is None else buttons, mods)
    QApplication.sendEvent(w, ev)


def send_wheel(w, pos, dy, mods=Qt.NoModifier):
    pos = QPointF(pos)
    ev = QWheelEvent(pos, QPointF(w.mapToGlobal(pos.toPoint())), QPoint(), QPoint(0, dy),
                     Qt.NoButton, mods, Qt.NoScrollPhase, False)
    QApplication.sendEvent(w, ev)


def view_pos(win, ref_id):
    ti = win.canvas.thumb_items[ref_id]
    return win.canvas.mapFromScene(ti.sceneBoundingRect().center())


def order(reg):
    return [os.path.basename(r.path)[3:5] for r in reg.images]


@pytest.fixture
def win(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Discard))
    w = MainWindow()
    w.resize(1400, 900)
    w.show()
    pump(100)
    yield w
    w.dirty = False
    w.close()
    shutil.rmtree(w.data_dir, ignore_errors=True)


def drag(win, ref_id, target_view_pt, cancel_with_right=False):
    vp = win.canvas.viewport()
    start = view_pos(win, ref_id)
    send_mouse(vp, QMouseEvent.MouseButtonPress, start)
    for k in range(1, 6):
        p = start + (target_view_pt - start) * (k / 5)
        send_mouse(vp, QMouseEvent.MouseMove, p, Qt.NoButton, Qt.LeftButton)
    if cancel_with_right:
        send_mouse(vp, QMouseEvent.MouseButtonPress, target_view_pt, Qt.RightButton, Qt.LeftButton | Qt.RightButton)
        send_mouse(vp, QMouseEvent.MouseButtonRelease, target_view_pt, Qt.RightButton, Qt.LeftButton)
    send_mouse(vp, QMouseEvent.MouseButtonRelease, target_view_pt, Qt.LeftButton, Qt.NoButton)
    pump()


def test_first_prototype_flow(win, tmp_path, monkeypatch):
    shots = os.environ.get("ISO_SCREENSHOTS")
    imgs = make_images(str(tmp_path / "shots"), 5)
    make_images(str(tmp_path / "more"), 3, prefix="new")

    # 2-4: region, rename, colour
    win.new_region()
    reg = win.project.regions[0]
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("First Meeting", True)))
    win.rename_region(reg.id)
    win.set_region_color("#e05252", reg.id)
    assert (reg.name, reg.color) == ("First Meeting", "#e05252")

    # 5-7: select region, import folder -> goes into the active region
    win.activate_region(reg.id)
    win.import_paths([str(tmp_path / "shots")])
    assert order(reg) == ["01", "02", "03", "04", "05"]
    win.canvas.fit_rect(win._region_display_rect(reg))
    for _ in range(100):
        pump(20)
        if all(win.thumbs.get(p) is not None for p in imgs):
            break
    assert all(win.thumbs.get(p) is not None for p in imgs), "thumbnails not generated"

    # 8-9 / §34A: drag 03 onto the first cell -> 03 01 02 04 05
    win.canvas.clear_selection()
    first = view_pos(win, reg.images[0].id)
    drag(win, reg.images[2].id, first)
    assert order(reg) == ["03", "01", "02", "04", "05"]
    assert reg.auto_arrange
    # move 05 onto 04's cell -> inserted between 02 and 04
    win.canvas.clear_selection()
    drag(win, reg.images[4].id, view_pos(win, reg.images[3].id))
    assert order(reg) == ["03", "01", "02", "05", "04"]

    # §25: right-click during a drag cancels it and opens no menu
    opened = []
    monkeypatch.setattr(mw_mod, "exec_menu", lambda m, pos: opened.append(1))
    win.canvas.clear_selection()
    before_pos = win.canvas.thumb_items[reg.images[4].id].pos()
    drag(win, reg.images[4].id, first, cancel_with_right=True)
    assert order(reg) == ["03", "01", "02", "05", "04"]
    assert win.canvas.thumb_items[reg.images[4].id].pos() == before_pos
    assert win.canvas.mode is None and not opened

    # §24: right-click on a selected image keeps multi-selection
    ids = [r.id for r in reg.images[:3]]
    win.canvas.set_selection(ids)
    p = view_pos(win, ids[1])
    send_mouse(win.canvas.viewport(), QMouseEvent.MouseButtonPress, p, Qt.RightButton)
    send_mouse(win.canvas.viewport(), QMouseEvent.MouseButtonRelease, p, Qt.RightButton, Qt.NoButton)
    assert opened and set(win.canvas.selected_ids()) == set(ids)

    # 10-12 / §34B: lock the first three, import more, locked order stays
    win.set_locked(True)
    locked_before = [r.id for r in reg.images[:3]]
    win.import_paths([str(tmp_path / "more")], index=0)  # even an explicit insert at 0
    assert [r.id for r in reg.images[:3]] == locked_before
    assert len(reg.images) == 8
    # locked images can't be dragged
    win.canvas.clear_selection()
    drag(win, reg.images[0].id, view_pos(win, reg.images[6].id))
    assert [r.id for r in reg.images[:3]] == locked_before

    # 13-15: another region, Ctrl+C / Ctrl+V, Ctrl+X / Ctrl+V
    win.new_region()
    reg2 = win.project.regions[1]
    win.canvas.set_selection([reg.images[3].id, reg.images[4].id])
    QTest.keySequence(win, QKeySequence.Copy)
    win.activate_region(reg2.id)
    win.canvas.clear_selection()
    QTest.keySequence(win, QKeySequence.Paste)
    assert len(reg2.images) == 2 and len(reg.images) == 8
    win.canvas.set_selection([reg.images[7].id])
    cut_id = reg.images[7].id
    QTest.keySequence(win, QKeySequence.Cut)
    win.activate_region(reg2.id)
    win.canvas.clear_selection()
    QTest.keySequence(win, QKeySequence.Paste)
    assert len(reg.images) == 7 and reg2.images[-1].id == cut_id
    # 14: drag between regions
    win.canvas.fit_all()
    pump()
    win.canvas.clear_selection()
    moved = reg.images[5].id
    drag(win, moved, view_pos(win, reg2.images[0].id))
    assert reg2.images[0].id == moved and len(reg.images) == 6

    # Undo / redo
    win.undo()
    assert reg_by_name(win, "First Meeting").images[5].id == moved
    win.redo()
    assert reg_by_name(win, "Region 2").images[0].id == moved

    # 16 / §34F: wheel zooms canvas, Ctrl+wheel changes thumbnail size only
    z0, t0 = win.canvas.zoom(), win.project.thumb_size
    c = win.canvas.viewport().rect().center()
    send_wheel(win.canvas.viewport(), c, 120)
    assert win.canvas.zoom() > z0 and win.project.thumb_size == t0
    z1 = win.canvas.zoom()
    send_wheel(win.canvas.viewport(), c, 120, Qt.ControlModifier)
    assert win.project.thumb_size > t0 and win.canvas.zoom() == pytest.approx(z1)
    win.canvas.fit_all()
    pump(200)
    if shots:
        win.grab().save(os.path.join(shots, "canvas.png"))

    # 17: double-click opens the viewer
    seen = []
    monkeypatch.setattr(ImageViewer, "exec", lambda self: seen.append(self.items[self.index]))
    reg = reg_by_name(win, "First Meeting")
    p = view_pos(win, reg.images[0].id)
    vp = win.canvas.viewport()
    send_mouse(vp, QMouseEvent.MouseButtonPress, p)
    send_mouse(vp, QMouseEvent.MouseButtonRelease, p, Qt.LeftButton, Qt.NoButton)
    send_mouse(vp, QMouseEvent.MouseButtonDblClick, p)
    send_mouse(vp, QMouseEvent.MouseButtonRelease, p, Qt.LeftButton, Qt.NoButton)
    assert seen and seen[0][0] == reg.images[0].path

    # 18-21 / §34C: save, new, reopen
    reg.auto_arrange = True
    reg2 = reg_by_name(win, "Region 2")
    win.toggle_auto(reg2.id)  # OFF, must be restored
    snapshot = win.project.to_dict()["regions"]
    path = str(tmp_path / "proj.isproj")
    assert win._write_project(path)
    win.new_project()
    assert not win.project.regions
    win.open_project(path)
    assert win.project.to_dict()["regions"] == snapshot

    # 22-25 / §34D: save region, new project, load it
    rpath = str(tmp_path / "first.isregion")
    monkeypatch.setattr(mw_mod.QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (rpath, "")))
    monkeypatch.setattr(mw_mod.QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (rpath, "")))
    src = reg_by_name(win, "First Meeting")
    win.save_region(src.id)
    want = [(r.path, r.locked) for r in src.images]
    win.new_project()
    win.load_region()
    loaded = win.project.regions[0]
    assert loaded.name == "First Meeting" and loaded.color == "#e05252"
    assert [(r.path, r.locked) for r in loaded.images] == want

    # 26-27: bulk rename preview + apply (dialog accepted programmatically)
    win._write_project(path)
    from scene_organizer import dialogs
    monkeypatch.setattr(dialogs.BulkRenameDialog, "exec", lambda self: dialogs.BulkRenameDialog.Accepted)
    win.bulk_rename_region(loaded.id)
    names = [os.path.basename(r.path) for r in loaded.images]
    assert names[0] == "[First Meeting] 001.png" and names[-1] == f"[First Meeting] {len(names):03d}.png"
    assert all(os.path.exists(r.path) for r in loaded.images)
    assert not win.dirty  # project auto-saved after the rename


def reg_by_name(win, name):
    return next(r for r in win.project.regions if r.name == name)


def test_viewer_controls(qapp, tmp_path):
    big = make_images(str(tmp_path), 2, size=(4000, 3000))
    v = ImageViewer(None, [(p, os.path.basename(p)) for p in big], 0)
    v.resize(1000, 700)
    v.show()
    pump(100)
    fit_zoom = v.zoom()
    assert fit_zoom < 1 and v.zoom_lbl.text() == f"{round(fit_zoom * 100)}%"
    send_wheel(v.view.viewport(), v.view.viewport().rect().center(), 240)
    assert v.zoom() > fit_zoom and v.zoom_lbl.text().endswith("%")
    v.actual_size()
    assert v.zoom() == pytest.approx(1.0) and v.zoom_lbl.text() == "100%"
    h = v.view.horizontalScrollBar().value()
    vp = v.view.viewport()
    c = vp.rect().center()
    send_mouse(vp, QMouseEvent.MouseButtonPress, c)
    send_mouse(vp, QMouseEvent.MouseMove, c + QPoint(-200, 0), Qt.NoButton, Qt.LeftButton)
    send_mouse(vp, QMouseEvent.MouseButtonRelease, c + QPoint(-200, 0), Qt.LeftButton, Qt.NoButton)
    assert v.view.horizontalScrollBar().value() != h  # drag-pan
    v.fit()
    assert v.zoom() == pytest.approx(fit_zoom, rel=0.05)
    v.step(1)
    assert v.index == 1
    QTest.keyClick(v, Qt.Key_Escape)
    pump()
    assert not v.isVisible()
    v2 = ImageViewer(None, [(big[0], "x")], 0)
    v2.show()
    pump()
    send_mouse(v2.view.viewport(), QMouseEvent.MouseButtonDblClick, QPoint(50, 50))
    pump()
    assert not v2.isVisible()


def test_region_and_canvas_interactions(win, tmp_path):
    from PySide6.QtCore import QMimeData, QUrl
    from PySide6.QtGui import QDropEvent
    make_images(str(tmp_path / "a"), 4)
    vp = win.canvas.viewport()
    win.new_region()
    reg = win.project.regions[0]
    win.import_paths([str(tmp_path / "a")])
    win.canvas.fit_rect(win._region_display_rect(reg).adjusted(-300, -300, 300, 300))
    pump()

    # move region by its title bar, then undo
    x0, y0 = reg.x, reg.y
    title = win.canvas.mapFromScene(QPointF(reg.x + 200, reg.y + 10))
    send_mouse(vp, QMouseEvent.MouseButtonPress, title)
    send_mouse(vp, QMouseEvent.MouseMove, title + QPoint(60, 40), Qt.NoButton, Qt.LeftButton)
    send_mouse(vp, QMouseEvent.MouseButtonRelease, title + QPoint(60, 40), Qt.LeftButton, Qt.NoButton)
    assert reg.x > x0 and reg.y > y0
    win.undo()
    reg = win.project.regions[0]
    assert (reg.x, reg.y) == (x0, y0)

    # resize from the grip reflows the grid (fewer columns -> taller)
    ri = win.canvas.region_items[reg.id]
    h0 = ri.h
    grip = win.canvas.mapFromScene(QPointF(reg.x + ri.w - 5, reg.y + ri.h - 5))
    send_mouse(vp, QMouseEvent.MouseButtonPress, grip)
    send_mouse(vp, QMouseEvent.MouseMove, grip - QPoint(int(ri.w * 0.6 * win.canvas.zoom()), 0),
               Qt.NoButton, Qt.LeftButton)
    send_mouse(vp, QMouseEvent.MouseButtonRelease, grip, Qt.LeftButton, Qt.NoButton)
    assert ri.h > h0

    # rubber band inside the region selects images
    win.canvas.clear_selection()
    r = win.canvas.region_items[reg.id].sceneBoundingRect()
    a = win.canvas.mapFromScene(r.topLeft() + QPointF(4, 34))
    b = win.canvas.mapFromScene(r.bottomRight() - QPointF(4, 4))
    send_mouse(vp, QMouseEvent.MouseButtonPress, a)
    send_mouse(vp, QMouseEvent.MouseMove, b, Qt.NoButton, Qt.LeftButton)
    send_mouse(vp, QMouseEvent.MouseButtonRelease, b, Qt.LeftButton, Qt.NoButton)
    assert len(win.canvas.selected_ids()) == 4

    # right-click on empty region space keeps the selection
    opened = []
    import scene_organizer.mainwindow as m
    orig = m.exec_menu
    m.exec_menu = lambda menu, pos: opened.append(menu)
    try:
        empty = win.canvas.mapFromScene(r.bottomRight() - QPointF(20, 20))
        send_mouse(vp, QMouseEvent.MouseButtonPress, empty, Qt.RightButton)
        send_mouse(vp, QMouseEvent.MouseButtonRelease, empty, Qt.RightButton, Qt.NoButton)
        assert opened and len(win.canvas.selected_ids()) == 4
        far = win.canvas.mapFromScene(r.topLeft() - QPointF(150, 150))
        send_mouse(vp, QMouseEvent.MouseButtonPress, far, Qt.RightButton)
        send_mouse(vp, QMouseEvent.MouseButtonRelease, far, Qt.RightButton, Qt.NoButton)
        assert len(opened) == 2 and len(win.canvas.selected_ids()) == 4
    finally:
        m.exec_menu = orig

    # space + drag pans
    hv = win.canvas.horizontalScrollBar().value()
    QTest.keyPress(win.canvas, Qt.Key_Space)
    send_mouse(vp, QMouseEvent.MouseButtonPress, QPoint(300, 300))
    send_mouse(vp, QMouseEvent.MouseMove, QPoint(200, 300), Qt.NoButton, Qt.LeftButton)
    send_mouse(vp, QMouseEvent.MouseButtonRelease, QPoint(200, 300), Qt.LeftButton, Qt.NoButton)
    QTest.keyRelease(win.canvas, Qt.Key_Space)
    assert win.canvas.horizontalScrollBar().value() == hv + 100

    # Explorer file drop onto the region inserts at the drop slot
    extra = make_images(str(tmp_path / "b"), 1, prefix="drop")
    md = QMimeData()
    md.setUrls([QUrl.fromLocalFile(extra[0])])
    first = view_pos(win, reg.images[0].id)
    from PySide6.QtGui import QDragEnterEvent
    QApplication.sendEvent(vp, QDragEnterEvent(first, Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier))
    QApplication.sendEvent(vp, QDropEvent(QPointF(first), Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier))
    assert os.path.basename(reg.images[0].path) == "drop01.png" and len(reg.images) == 5

    # ctrl-drag copies, Esc clears selection
    win.canvas.clear_selection()
    n = len(reg.images)
    start = view_pos(win, reg.images[1].id)
    end = view_pos(win, reg.images[3].id)
    send_mouse(vp, QMouseEvent.MouseButtonPress, start)
    send_mouse(vp, QMouseEvent.MouseMove, end, Qt.NoButton, Qt.LeftButton)
    send_mouse(vp, QMouseEvent.MouseButtonRelease, end, Qt.LeftButton, Qt.NoButton, Qt.ControlModifier)
    assert len(reg.images) == n + 1
    QTest.keyClick(win, Qt.Key_Escape)
    assert not win.canvas.selected_ids()


def test_autosave_and_crash_recovery(qapp, tmp_path, monkeypatch):
    make_images(str(tmp_path / "a"), 3)
    w = MainWindow()
    w.show()
    pump(50)  # _startup writes the session lock
    w.new_region()
    w.import_paths([str(tmp_path / "a")])
    w.autosave()
    assert os.path.exists(w.autosave_path()) and os.path.exists(w.lock_path())
    want = w.project.to_dict()["regions"]
    # simulate a crash: the window goes away without closeEvent removing the lock
    w.hide()
    w.deleteLater()
    pump(20)
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    w2 = MainWindow()
    w2.show()
    pump(80)
    assert w2.project.to_dict()["regions"] == want and w2.dirty
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Discard))
    w2.close()
    assert not os.path.exists(w2.lock_path())
    shutil.rmtree(w2.data_dir, ignore_errors=True)
