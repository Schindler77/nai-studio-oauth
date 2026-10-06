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

from scene_organizer import i18n
from scene_organizer import mainwindow as mw_mod
from scene_organizer.mainwindow import MainWindow
from scene_organizer.model import PAD, TITLE_H
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


@pytest.fixture(params=["en", "ko"])
def win(request, qapp, tmp_path, monkeypatch):
    i18n.set_language(request.param)
    from PySide6.QtCore import QSettings
    QSettings().clear()  # every test starts from default settings (sidebar, tips, theme...)
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Discard))
    w = MainWindow()
    w.resize(1400, 900)
    w.show()
    w.activateWindow()  # window shortcuts need an active window on real platforms
    QTest.qWaitForWindowActive(w, 3000)
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
    assert reg_by_name(win, i18n.tr("Region {n}", n=2)).images[0].id == moved

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
    reg2 = reg_by_name(win, i18n.tr("Region {n}", n=2))
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
    a = win.canvas.mapFromScene(r.topLeft() + QPointF(14, TITLE_H + 14))
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


def test_move_actual_files_updates_project(win, tmp_path, monkeypatch):
    paths = make_images(str(tmp_path / "src"), 3)
    dest = tmp_path / "Battle"
    dest.mkdir()
    win.new_region()
    reg = win.project.regions[0]
    win.import_paths([str(tmp_path / "src")])
    win.copy_selection()  # clipboard must follow the move too
    proj = str(tmp_path / "p.isproj")
    win._write_project(proj)
    monkeypatch.setattr(MainWindow, "_confirm", lambda self, *a: True)
    win.move_actual_files([r.path for r in reg.images[:2]], str(dest))
    assert [os.path.dirname(r.path) for r in reg.images] == [str(dest), str(dest), str(tmp_path / "src")]
    assert all(os.path.exists(r.path) for r in reg.images) and not os.path.exists(paths[0])
    assert not win.dirty  # saved so the project points to the new locations
    assert os.path.dirname(win.clipboard["items"][0]["path"]) == str(dest)
    win.undo()  # undoing the import must not resurrect old paths
    win.redo()
    assert os.path.dirname(win.project.regions[0].images[0].path) == str(dest)
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    win.revert_last_rename()
    assert all(os.path.exists(p) for p in paths)
    assert [r.path for r in win.project.regions[0].images] == paths


def test_autoscroll_while_dragging(win, tmp_path):
    make_images(str(tmp_path / "a"), 3)
    win.new_region()
    reg = win.project.regions[0]
    win.import_paths([str(tmp_path / "a")])
    win.canvas.set_zoom(1.0, win._region_display_rect(reg).center())
    win.canvas.clear_selection()
    pump()
    vp = win.canvas.viewport()
    start = view_pos(win, reg.images[0].id)
    edge = QPoint(vp.width() - 5, start.y())
    h0 = win.canvas.horizontalScrollBar().value()
    send_mouse(vp, QMouseEvent.MouseButtonPress, start)
    send_mouse(vp, QMouseEvent.MouseMove, start + QPoint(20, 0), Qt.NoButton, Qt.LeftButton)
    send_mouse(vp, QMouseEvent.MouseMove, edge, Qt.NoButton, Qt.LeftButton)
    ti = win.canvas.thumb_items[reg.images[0].id]
    x_before = ti.scenePos().x()
    pump(300)
    assert win.canvas.horizontalScrollBar().value() > h0 + 50
    assert ti.scenePos().x() > x_before + 50  # the dragged image travels with the view
    send_mouse(vp, QMouseEvent.MouseMove, vp.rect().center(), Qt.NoButton, Qt.LeftButton)
    pump(60)
    h1 = win.canvas.horizontalScrollBar().value()
    pump(100)
    assert win.canvas.horizontalScrollBar().value() == h1  # stops away from the edge
    send_mouse(vp, QMouseEvent.MouseButtonPress, vp.rect().center(), Qt.RightButton, Qt.LeftButton | Qt.RightButton)
    send_mouse(vp, QMouseEvent.MouseButtonRelease, vp.rect().center(), Qt.RightButton, Qt.LeftButton)
    send_mouse(vp, QMouseEvent.MouseButtonRelease, vp.rect().center(), Qt.LeftButton, Qt.NoButton)
    assert win.canvas.mode is None and len(reg.images) == 3


def _has_hangul(text: str) -> bool:
    return any("가" <= ch <= "힣" for ch in text)


def _menu_texts(menu, out):
    menu.aboutToShow.emit()  # fill dynamic menus (recent projects, colours)
    for a in menu.actions():
        if a.isSeparator():
            continue
        out.append(a.text())
        if a.menu() is not None:
            _menu_texts(a.menu(), out)


def test_korean_ui_is_complete(qapp, tmp_path, monkeypatch):
    """Every menu, context menu, toolbar button and dialog shows Korean."""
    from PySide6.QtWidgets import QToolButton
    from scene_organizer.dialogs import BulkRenameDialog, PreferencesDialog
    i18n.set_language("ko")
    make_images(str(tmp_path / "a"), 2)
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Discard))
    w = MainWindow()
    w.show()
    pump(50)
    w.new_region()
    w.import_paths([str(tmp_path / "a")])
    reg = w.project.regions[0]
    assert reg.name == "영역 1"
    w.canvas.set_selection([reg.images[0].id])
    texts = []
    for a in w.menuBar().actions():
        texts.append(a.text())
        _menu_texts(a.menu(), texts)
    for tb_action in w.findChildren(QToolButton):
        if tb_action.text():
            texts.append(tb_action.text())
    from PySide6.QtWidgets import QLabel
    texts += [lbl.text() for lbl in w.sidebar.findChildren(QLabel) if lbl.text()]
    texts += [b.toolTip() for b in (w.sidebar.close_btn, w.sidebar.add_btn)]
    menus = []
    monkeypatch.setattr(mw_mod, "exec_menu", lambda m, pos: menus.append(m))
    w.image_menu(QPoint(0, 0), reg.images[0].id)
    w.region_menu(QPoint(0, 0), reg.id, QPointF(0, 0))
    w.canvas_menu(QPoint(0, 0), QPointF(0, 0))
    for m in menus:
        _menu_texts(m, texts)
    from scene_organizer.model import ASPECTS
    allowed = {"English", "한국어", reg.name, *ASPECTS}  # language names, user content, ratios
    untranslated = sorted({t for t in texts if t and t not in allowed and not _has_hangul(t)
                           and not t.endswith(".isproj")})  # recent-project paths
    assert not untranslated, untranslated
    for dlg in (BulkRenameDialog(w, reg.name, [r.path for r in reg.images]), PreferencesDialog(w, True, 3)):
        assert _has_hangul(dlg.windowTitle())
    v = ImageViewer(w, [(r.path, r.display_name) for r in reg.images], 0)
    assert _has_hangul(v.windowTitle())
    w.grab()  # paints region title / badges / hint through tr()
    from scene_organizer.tips import TIPS, TipDialog
    dlg = TipDialog(w, 0, True)
    texts += [dlg.windowTitle(), dlg.show_tips.text(), dlg.prev_btn.text(), dlg.next_btn.text()]
    for i in range(len(TIPS)):
        dlg.show_index(i)
        texts += [dlg.title.text(), dlg.text.text()]
        dlg.canvas.fixed_t = 0.5
        dlg.canvas.grab()  # picture labels go through tr()
    texts += [w.search_box.placeholderText(), w.fit_btn.text(), w.hand_btn.toolTip()]
    assert _has_hangul(w.lbl_info.text()) and _has_hangul(w.windowTitle())
    w.dirty = False
    w.close()
    shutil.rmtree(w.data_dir, ignore_errors=True)


def test_card_header_switch_menu_and_appearance(win, tmp_path, monkeypatch):
    from scene_organizer import theme
    make_images(str(tmp_path / "p"), 3, size=(400, 600))  # portrait, like NovelAI output
    win.new_region()
    reg = win.project.regions[0]
    win.import_paths([str(tmp_path / "p")])
    assert win.project.thumb_aspect == "2:3"  # picked from the first import
    cw, ch = win.project.cell()
    assert cw < ch
    win.canvas.fit_rect(win._region_display_rect(reg))
    pump()
    ri = win.canvas.region_items[reg.id]
    vp = win.canvas.viewport()
    # click the auto-arrange switch in the header
    sw = win.canvas.mapFromScene(ri.mapToScene(ri.r_switch.center()))
    send_mouse(vp, QMouseEvent.MouseButtonPress, sw)
    send_mouse(vp, QMouseEvent.MouseButtonRelease, sw, Qt.LeftButton, Qt.NoButton)
    assert win.project.regions[0].auto_arrange is False
    ri = win.canvas.region_items[reg.id]
    sw = win.canvas.mapFromScene(ri.mapToScene(ri.r_switch.center()))
    send_mouse(vp, QMouseEvent.MouseButtonPress, sw)
    send_mouse(vp, QMouseEvent.MouseButtonRelease, sw, Qt.LeftButton, Qt.NoButton)
    assert win.project.regions[0].auto_arrange is True
    # the ⋯ button opens the region menu
    opened = []
    monkeypatch.setattr(mw_mod, "exec_menu", lambda m, pos: opened.append(m))
    menu_pt = win.canvas.mapFromScene(ri.mapToScene(ri.r_menu.center()))
    send_mouse(vp, QMouseEvent.MouseButtonPress, menu_pt)
    send_mouse(vp, QMouseEvent.MouseButtonRelease, menu_pt, Qt.LeftButton, Qt.NoButton)
    assert len(opened) == 1 and win.canvas.mode is None
    # thumbnail shape / fill and theme switch repaint without errors
    win.set_thumb_aspect("16:9")
    assert win.project.cell()[0] > win.project.cell()[1]
    win.set_thumb_fill("fit")
    win.set_ui_theme("dark")
    assert theme.current().name == "dark"
    win.grab()
    win.set_ui_theme("light")
    win.grab()
    # combined lock / unlock toolbar command
    win.canvas.set_selection([r.id for r in reg.images[:2]])
    win.toggle_lock_selection()
    assert [r.locked for r in win.project.regions[0].images] == [True, True, False]
    win.toggle_lock_selection()
    assert not any(r.locked for r in win.project.regions[0].images)


def test_sidebar_preview_list_and_tips(win, tmp_path, monkeypatch):
    from PySide6.QtCore import Qt as _Qt
    sb = win.sidebar
    assert sb.isVisible()  # shown by default
    make_images(str(tmp_path / "a"), 3)
    win.new_region()
    win.import_paths([str(tmp_path / "a")])
    win.new_region()
    regs = win.project.regions
    pump()
    # list mirrors the regions: name, colour, count, active row
    assert sb.list.count() == 2
    assert sb.list.item(0).text() == regs[0].name
    assert sb.list.item(0).data(_Qt.UserRole + 2) == i18n.tr("{n} images", n=3)
    assert sb.list.item(1).data(_Qt.UserRole + 3) is True  # the new region is active
    # clicking a row activates and centres that region
    win.canvas.centerOn(QPointF(50_000, 50_000))
    rect = sb.list.visualItemRect(sb.list.item(0))
    QTest.mouseClick(sb.list.viewport(), Qt.LeftButton, Qt.NoModifier, rect.center())
    assert win.active_region_id == regs[0].id
    assert win._region_display_rect(regs[0]).contains(win.canvas.view_center())
    # + adds a region, right-click opens the region menu
    QTest.mouseClick(sb.add_btn, Qt.LeftButton)
    assert len(win.project.regions) == 3 and sb.list.count() == 3
    opened = []
    monkeypatch.setattr(mw_mod, "exec_menu", lambda m, pos: opened.append(m))
    sb._context_menu(rect.center())
    assert opened
    # minimap click moves the view there
    sb.minimap.repaint()
    target = win._region_display_rect(win.project.regions[2]).center()
    win.canvas.centerOn(QPointF(-50_000, -50_000))
    sb.minimap.repaint()
    k, off = sb.minimap._map
    pt = QPoint(int(target.x() * k + off.x()), int(target.y() * k + off.y()))
    QTest.mouseClick(sb.minimap, Qt.LeftButton, Qt.NoModifier, pt)
    c = win.canvas.view_center()
    assert abs(c.x() - target.x()) < 1 / k + 60 and abs(c.y() - target.y()) < 1 / k + 60
    # tips cycle; × hides the sidebar, View → Sidebar brings it back
    first = sb.tip.text()
    sb.next_tip()
    assert sb.tip.text() and sb.tip.text() != first
    QTest.mouseClick(sb.close_btn, Qt.LeftButton)
    assert not sb.isVisible() and not win.sidebar_action.isChecked()
    win.sidebar_action.trigger()
    assert sb.isVisible()


def test_status_bar_zoom_and_hand_tool(win, tmp_path):
    paths = make_images(str(tmp_path / "a"), 3, size=(1200, 800))
    win.new_region()
    reg = win.project.regions[0]
    win.import_paths([str(tmp_path / "a")])
    win.canvas.set_selection([reg.images[1].id])
    info = win.lbl_info.text()
    assert reg.name in info and os.path.basename(paths[1]) in info and "1200 × 800" in info
    assert "KB" in info or "MB" in info
    win.canvas.set_selection([r.id for r in reg.images])
    assert i18n.tr("{n} images selected", n=3) in win.lbl_info.text()
    # slider, buttons and percentage follow each other
    win.canvas.set_zoom(1.0)
    win.zoom_slider.setValue(win._zoom_to_slider(2.0))
    assert win.canvas.zoom() == pytest.approx(2.0, rel=0.01) and win.lbl_zoom.text() == "200%"
    QTest.mouseClick(win.zoom_out_btn, Qt.LeftButton)
    assert win.canvas.zoom() == pytest.approx(1.6, rel=0.01)
    QTest.mouseClick(win.zoom_in_btn, Qt.LeftButton)
    assert win.canvas.zoom() == pytest.approx(2.0, rel=0.01)
    QTest.mouseClick(win.fit_btn, Qt.LeftButton)
    assert win.zoom_slider.value() == win._zoom_to_slider(win.canvas.zoom())
    # hand tool: left drag pans instead of starting a selection box
    win.hand_btn.setChecked(True)
    vp = win.canvas.viewport()
    h0 = win.canvas.horizontalScrollBar().value()
    send_mouse(vp, QMouseEvent.MouseButtonPress, QPoint(300, 300))
    send_mouse(vp, QMouseEvent.MouseMove, QPoint(220, 300), Qt.NoButton, Qt.LeftButton)
    send_mouse(vp, QMouseEvent.MouseButtonRelease, QPoint(220, 300), Qt.LeftButton, Qt.NoButton)
    assert win.canvas.horizontalScrollBar().value() == h0 + 80 and win.canvas.rubber is None
    win.hand_btn.setChecked(False)
    assert "Image Scene Organizer" in win.windowTitle() and i18n.tr("Project") in win.windowTitle()


def test_canvas_search(win, tmp_path):
    make_images(str(tmp_path / "a"), 4, prefix="sky")
    make_images(str(tmp_path / "b"), 2, prefix="night")
    win.new_region()
    a = win.project.regions[0]
    win.import_paths([str(tmp_path / "a")])
    win.new_region()
    b = win.project.regions[1]
    b.name = "Night scenes"
    win.import_paths([str(tmp_path / "b")])
    a.collapsed = True
    win.refresh()
    win.search_box.setText("abc")
    win.search_box.deselect()
    QTest.keySequence(win, QKeySequence.Find)  # Ctrl+F focuses the box and selects its text
    assert win.search_box.selectedText() == "abc"
    win.search_box.setText("sky0")
    assert len(win.canvas.search_hits) == 4 and not win.canvas.search_regions
    win.search_box.setText("night")
    assert len(win.canvas.search_hits) == 2 and win.canvas.search_regions == {b.id}
    win.search_box.setText("sky02")
    QTest.keyClick(win.search_box, Qt.Key_Return)
    assert win.canvas.selected_ids() == [a.images[1].id]
    assert not a.collapsed  # a hit inside a collapsed region opens it
    QTest.keyClick(win.search_box, Qt.Key_Escape)
    assert win.search_box.text() == "" and not win.canvas.search_hits
    # typing Ctrl+C in the box copies text, not images
    win.search_box.setFocus()
    win.search_box.setText("x")
    win.search_box.selectAll()
    QTest.keySequence(win.search_box, QKeySequence.Copy)
    assert win.clipboard is None


def test_context_menus_have_icons_and_shortcuts(win, tmp_path, monkeypatch):
    make_images(str(tmp_path / "a"), 2)
    win.new_region()
    reg = win.project.regions[0]
    win.import_paths([str(tmp_path / "a")])
    menus = []
    monkeypatch.setattr(mw_mod, "exec_menu", lambda m, pos: menus.append(m))
    win.image_menu(QPoint(0, 0), reg.images[0].id)
    win.region_menu(QPoint(0, 0), reg.id, QPointF(0, 0))
    win.canvas_menu(QPoint(0, 0), QPointF(0, 0))
    for m in menus:
        acts = [a for a in m.actions() if not a.isSeparator()]
        assert all(not a.icon().isNull() for a in acts), [a.text() for a in acts if a.icon().isNull()]
    n = len(win.selected_refs())
    cut = next(a for a in menus[0].actions() if a.text().startswith(i18n.tr("Cut ({n})", n=n)))
    assert "\t" in cut.text() and cut.text().endswith(QKeySequence(QKeySequence.Cut).toString(
        QKeySequence.NativeText))


def test_drag_ghost_placeholder_and_smooth_reflow(win, tmp_path):
    make_images(str(tmp_path / "a"), 5)
    win.new_region()
    reg = win.project.regions[0]
    win.import_paths([str(tmp_path / "a")])
    win.canvas.fit_rect(win._region_display_rect(reg))
    win.canvas.clear_selection()
    pump()
    vp = win.canvas.viewport()
    moving = win.canvas.thumb_items[reg.images[3].id]
    first = view_pos(win, reg.images[0].id)
    start = view_pos(win, reg.images[3].id)
    send_mouse(vp, QMouseEvent.MouseButtonPress, start)
    send_mouse(vp, QMouseEvent.MouseMove, start + QPoint(30, 0), Qt.NoButton, Qt.LeftButton)
    send_mouse(vp, QMouseEvent.MouseMove, first, Qt.NoButton, Qt.LeftButton)
    assert moving.rotation() != 0 and moving.graphicsEffect() is not None  # lifted ghost
    assert len(win.canvas._placeholders) == 1  # dashed box where it will land
    shifted = win.canvas.thumb_items[reg.images[0].id]
    assert win.canvas._anim  # neighbours glide instead of jumping
    pump(400)
    assert not win.canvas._anim and shifted.pos().x() > first.x() * 0  # settled
    send_mouse(vp, QMouseEvent.MouseButtonRelease, first, Qt.LeftButton, Qt.NoButton)
    pump()
    assert [os.path.basename(r.path)[3:5] for r in win.project.regions[0].images] == ["04", "01", "02", "03", "05"]
    assert not win.canvas._placeholders and moving.rotation() == 0 and moving.graphicsEffect() is None


def test_region_internal_scrolling(win, tmp_path):
    make_images(str(tmp_path / "a"), 18)
    win.new_region()
    reg = win.project.regions[0]
    win.import_paths([str(tmp_path / "a")])
    grown = win._region_display_rect(reg).height()
    win.toggle_region_scroll(reg.id)
    reg = win.project.regions[0]
    ri = win.canvas.region_items[reg.id]
    assert reg.scroll_enabled and ri.h < grown and ri.h == pytest.approx(reg.h)
    assert ri.scrollbar_rects() is not None
    hidden = [r for r in reg.images if not win.canvas.thumb_items[r.id].isVisible()]
    assert hidden  # the rest is below the fold
    win.canvas.fit_rect(win._region_display_rect(reg))
    pump()
    y0 = win.canvas.thumb_items[reg.images[0].id].pos().y()
    send_wheel(win.canvas.viewport(), win.canvas.mapFromScene(ri.sceneBoundingRect().center()), -120,
               Qt.ShiftModifier)
    assert reg.scroll > 0 and win.canvas.thumb_items[reg.images[0].id].pos().y() < y0
    win.canvas.scroll_region(reg, 1e6)  # clamped to the content
    assert reg.scroll == pytest.approx(ri.content_h - reg.h)
    assert win.canvas.thumb_items[reg.images[-1].id].isVisible()
    # an image scrolled under the header can't be clicked there; the header still works
    head = win.canvas.mapFromScene(ri.mapToScene(QPointF(ri.w / 3, 10)))
    assert win.canvas.item_at(head) is ri
    # ...and is not drawn over the header (same colour as header with no image under it)
    first = win.canvas.thumb_items[reg.images[0].id]
    win.canvas.scroll_region(reg, -1e6)
    win.canvas.scroll_region(reg, PAD + first.img_h * 0.6)  # first row half under the header
    win.canvas.fit_rect(ri.sceneBoundingRect())  # whole card on screen, any window size
    pump(100)
    assert first.isVisible() and win.canvas.zoom() > 0.35  # detailed painting (rounded clip) is in use
    img = win.canvas.viewport().grab().toImage()
    over = win.canvas.mapFromScene(ri.mapToScene(QPointF(first.pos().x() + first.cw / 2, TITLE_H - 6)))
    clear = win.canvas.mapFromScene(ri.mapToScene(QPointF(6, TITLE_H - 6)))
    assert img.rect().contains(over) and img.rect().contains(clear)
    assert first.pos().y() < TITLE_H  # it really is scrolled up under the header
    assert img.pixelColor(over) == img.pixelColor(clear)
    # reveal scrolls back to an image
    win.canvas.reveal(reg.images[0].id)
    assert win.canvas.thumb_items[reg.images[0].id].isVisible()
    # saved with the project and undoable
    d = win.project.to_dict()["regions"][0]
    assert d["scroll_enabled"] is True
    win.toggle_region_scroll(reg.id)
    assert not win.project.regions[0].scroll_enabled
    win.undo()
    assert win.project.regions[0].scroll_enabled


def test_tips_sidebar_popup_and_toggle(win, monkeypatch):
    from scene_organizer.tips import TIPS, TipCanvas
    sb = win.sidebar
    assert sb.tip_card.isVisible() and win.tips_action.isChecked()
    first = sb.tip.text()
    QTest.mouseClick(sb.tip_next, Qt.LeftButton)
    assert sb.tip.text() != first
    QTest.mouseClick(sb.tip_prev, Qt.LeftButton)
    assert sb.tip.text() == first
    shown = []

    def fake_exec(dlg):
        shown.append((dlg.index, dlg.title.text()))
        dlg.step(1)
        dlg.show_tips.setChecked(False)  # user unticks "show tips"
        return 0
    monkeypatch.setattr(mw_mod, "exec_dialog", fake_exec)
    QTest.mouseClick(sb.tip, Qt.LeftButton)
    assert shown and shown[0][0] == 0 and shown[0][1] == i18n.tr(TIPS[0]["title"])
    assert not sb.tip_card.isVisible() and not win.tips_action.isChecked()
    assert sb.tip.text() == i18n.tr(TIPS[1]["text"])  # sidebar follows the popup page
    win.tips_action.trigger()
    assert sb.tip_card.isVisible()
    QTest.mouseClick(sb.tip_close, Qt.LeftButton)
    assert not sb.tip_card.isVisible()
    canvas = TipCanvas(0)
    canvas.resize(800, 340)
    for i in range(len(TIPS)):  # every picture paints at every phase
        canvas.set_index(i)
        for t in (0.0, 0.3, 0.5, 0.75, 0.99):
            canvas.fixed_t = t
            assert not canvas.grab().isNull()


def test_spec_coverage_details(win, tmp_path, monkeypatch):
    """Spec items without a dedicated scenario elsewhere (§3 §6 §10 §11 §15 §19 §26 §28 §31 §32)."""
    paths = make_images(str(tmp_path / "a"), 5)
    # §3: canvas right-click → New Region appears at the clicked point
    win.new_region(QPointF(1234, 567))
    reg = win.project.regions[0]
    assert (reg.x, reg.y) == (1234, 567)
    # §6: import a single image
    win.import_paths([paths[0]])
    assert len(reg.images) == 1
    win.import_paths(paths[1:])
    win.canvas.fit_rect(win._region_display_rect(reg))
    pump()
    vp = win.canvas.viewport()
    # §11: click then Shift+click selects the range
    win.canvas.clear_selection()
    p1, p4 = view_pos(win, reg.images[1].id), view_pos(win, reg.images[3].id)
    send_mouse(vp, QMouseEvent.MouseButtonPress, p1)
    send_mouse(vp, QMouseEvent.MouseButtonRelease, p1, Qt.LeftButton, Qt.NoButton)
    send_mouse(vp, QMouseEvent.MouseButtonPress, p4, Qt.LeftButton, Qt.LeftButton, Qt.ShiftModifier)
    send_mouse(vp, QMouseEvent.MouseButtonRelease, p4, Qt.LeftButton, Qt.NoButton, Qt.ShiftModifier)
    assert set(win.canvas.selected_ids()) == {r.id for r in reg.images[1:4]}
    # §10: lock / unlock the whole region
    win.lock_region(reg.id, True)
    assert all(r.locked for r in reg.images)
    win.lock_region(reg.id, False)
    assert not any(r.locked for r in reg.images)
    # §19: middle-button drag pans
    h0 = win.canvas.horizontalScrollBar().value()
    send_mouse(vp, QMouseEvent.MouseButtonPress, QPoint(400, 300), Qt.MiddleButton)
    send_mouse(vp, QMouseEvent.MouseMove, QPoint(350, 300), Qt.NoButton, Qt.MiddleButton)
    send_mouse(vp, QMouseEvent.MouseButtonRelease, QPoint(350, 300), Qt.MiddleButton, Qt.NoButton)
    assert win.canvas.horizontalScrollBar().value() == h0 + 50
    # §28: the ▼ arrow collapses, keeping name and count visible
    ri = win.canvas.region_items[reg.id]
    arrow = win.canvas.mapFromScene(ri.mapToScene(ri.r_arrow.center()))
    send_mouse(vp, QMouseEvent.MouseButtonPress, arrow)
    send_mouse(vp, QMouseEvent.MouseButtonRelease, arrow, Qt.LeftButton, Qt.NoButton)
    reg = win.project.regions[0]
    assert reg.collapsed and win.canvas.region_items[reg.id].h == TITLE_H
    win.toggle_collapse(reg.id)
    # §31: required shortcuts
    want = {"new": "Ctrl+N", "open": "Ctrl+O", "save": "Ctrl+S", "save_as": "Ctrl+Shift+S", "copy": "Ctrl+C",
            "cut": "Ctrl+X", "paste": "Ctrl+V", "undo": "Ctrl+Z", "redo": "Ctrl+Y", "select_all": "Ctrl+A",
            "remove": "Del", "escape": "Esc"}
    for key, seq in want.items():
        assert QKeySequence(seq) in win.A[key].shortcuts(), key
    # §32: undo region rename, colour, creation and deletion
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Renamed", True)))
    win.rename_region(reg.id)
    win.set_region_color("#123456", reg.id)
    win.new_region()
    assert len(win.project.regions) == 2
    win.undo()
    assert len(win.project.regions) == 1
    win.undo()
    assert win.project.regions[0].color != "#123456"
    win.undo()
    assert win.project.regions[0].name != "Renamed"
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    win.delete_region(win.project.regions[0].id)
    assert not win.project.regions
    win.undo()
    reg = win.project.regions[0]
    assert len(reg.images) == 5
    # §15: Save As writes a new project file
    target = str(tmp_path / "copy.isproj")
    monkeypatch.setattr(mw_mod.QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (target, "")))
    assert win.save_as() and os.path.exists(target) and win.project_path == target
    # §26: remove keeps the file; delete moves it to the Recycle Bin after confirmation
    win.canvas.set_selection([reg.images[0].id])
    win.remove_selection()
    assert os.path.exists(paths[0]) and len(win.project.regions[0].images) == 4
    trashed = []
    monkeypatch.setattr(mw_mod.fileops, "move_to_trash", lambda p: trashed.append(p) or True)
    monkeypatch.setattr(MainWindow, "_confirm", lambda self, *a, **k: False)
    win.canvas.set_selection([win.project.regions[0].images[0].id])
    win.delete_actual_files()
    assert not trashed  # cancelled: nothing happens
    monkeypatch.setattr(MainWindow, "_confirm", lambda self, *a, **k: True)
    win.delete_actual_files()
    assert trashed == [paths[1]] and len(win.project.regions[0].images) == 3
