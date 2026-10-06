"""Self-test for packaged builds:  ImageSceneOrganizer.exe --self-test=<dir>

Runs the core workflow inside the real application (as packaged) and
writes report.txt plus screenshots into <dir>. Exit code 0 = all passed.
Used by CI on Windows to check the frozen .exe (image plugins bundled,
real Windows rename / move / Recycle Bin, viewer, save & reopen).
"""
from __future__ import annotations

import os
import shutil
import tempfile
import time
import traceback

from PySide6.QtCore import QLibraryInfo, Qt, QTranslator
from PySide6.QtGui import QColor, QImage, QImageReader, QPainter
from PySide6.QtWidgets import QApplication

from . import fileops, i18n
from .model import Project, load_json, region_file_dict, region_from_file_dict, save_json_atomic

NEEDED_FORMATS = {"png", "jpg", "jpeg", "webp", "bmp", "gif", "tif", "tiff"}


def _pump(ms: int) -> None:
    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        QApplication.processEvents()
        time.sleep(0.005)


def _image(path: str, i: int, fmt: str) -> None:
    img = QImage(800, 520, QImage.Format_RGB32)
    img.fill(QColor.fromHsv((i * 53) % 360, 150, 225))
    p = QPainter(img)
    f = p.font()
    f.setPixelSize(200)
    p.setFont(f)
    p.drawText(img.rect(), Qt.AlignCenter, f"{i:02d}")
    p.end()
    if not img.save(path, fmt):
        raise RuntimeError(f"cannot write {fmt}: {path}")


def run(out_dir: str) -> int:
    from .mainwindow import MainWindow
    from .viewer import ImageViewer

    os.makedirs(out_dir, exist_ok=True)
    lines: list[str] = []
    failures = 0

    def check(name: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        failures += 0 if ok else 1
        lines.append(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))

    work = tempfile.mkdtemp(prefix="iso_selftest_")
    win = None
    try:
        fmts = {bytes(f).decode() for f in QImageReader.supportedImageFormats()}
        missing = sorted(NEEDED_FORMATS - fmts)
        check("image format plugins bundled", not missing, f"missing: {missing}" if missing else "")

        qt_ko = QTranslator()
        check("Korean Qt dialog translations bundled",
              qt_ko.load("qtbase_ko", QLibraryInfo.path(QLibraryInfo.TranslationsPath)))
        check("Korean UI is the default", i18n.language() == "ko" and i18n.tr("Save") == "저장",
              f"language={i18n.language()}")

        src = os.path.join(work, "shots")
        os.makedirs(src)
        kinds = [("png", "PNG"), ("jpg", "JPG"), ("webp", "WEBP"), ("tif", "TIFF"), ("bmp", "BMP")]
        for i, (ext, fmt) in enumerate(kinds, 1):
            _image(os.path.join(src, f"IMG_{i:02d}.{ext}"), i, fmt)

        win = MainWindow()
        win._confirm = lambda *a: True  # no modal dialogs during the self-test
        win.resize(1400, 860)
        win.show()
        _pump(200)
        win.new_region()
        reg = win.project.regions[0]
        reg.name = "First Meeting"
        win.import_paths([src])
        check("folder import", len(reg.images) == len(kinds), f"{len(reg.images)} images")
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and not all(win.thumbs.get(r.path) for r in reg.images):
            _pump(50)
        bad = [os.path.basename(r.path) for r in reg.images if not win.thumbs.get(r.path)]
        check("thumbnails for png/jpg/webp/tif/bmp", not bad, f"not loaded: {bad}" if bad else "")

        ids = [r.id for r in reg.images]
        win.commit_drag([ids[2]], reg.id, 0, {}, False)
        check("auto-arrange insertion (03 to front)", [r.id for r in reg.images][:3] == [ids[2], ids[0], ids[1]])
        for r in reg.images[:2]:
            r.locked = True
        extra = os.path.join(work, "extra")
        os.makedirs(extra)
        _image(os.path.join(extra, "late.png"), 9, "PNG")
        win.import_paths([extra], index=0)
        check("locked images stay in place on import", [r.id for r in reg.images][:2] == [ids[2], ids[0]])

        proj = os.path.join(work, "project.isproj")
        want = win.project.to_dict()["regions"]
        win._write_project(proj)
        win.new_project()
        win.open_project(proj)
        check("save → new → reopen restores state", win.project.to_dict()["regions"] == want)
        reg = win.project.regions[0]

        rfile = os.path.join(work, "first.isregion")
        save_json_atomic(rfile, region_file_dict(reg, work))
        loaded = region_from_file_dict(load_json(rfile), work)
        check("region save/load keeps order and locks",
              [(r.path, r.locked) for r in loaded.images] == [(r.path, r.locked) for r in reg.images])

        win.canvas.fit_all()
        _pump(300)
        win.grab().save(os.path.join(out_dir, "canvas.png"))

        v = ImageViewer(win, [(r.path, r.display_name) for r in reg.images], 0)
        v.show()
        _pump(200)
        v.actual_size()
        ok100 = v.zoom_lbl.text() == "100%"
        v.fit()
        v.grab().save(os.path.join(out_dir, "viewer.png"))
        v.accept()
        check("viewer opens, 100% / fit", ok100 and not v.view.item.pixmap().isNull())

        deadline = time.monotonic() + 20  # no reader may hold a file open during the rename
        while time.monotonic() < deadline and not all(win.thumbs.get(r.path) for r in reg.images):
            _pump(50)
        paths = [r.path for r in reg.images]
        plan = fileops.plan_rename(paths, fileops.DEFAULT_TEMPLATE, reg.name)
        pairs = fileops.apply_rename(plan)
        win._after_fs_rename(pairs, "renamed")
        names = [os.path.basename(r.path) for r in reg.images]
        check("bulk rename on disk by order",
              names[0].startswith("[First Meeting] 001.") and all(os.path.exists(r.path) for r in reg.images),
              ", ".join(names))
        reopened = Project.from_dict(load_json(proj), work)
        check("project auto-saved after rename",
              [r.path for r in reopened.regions[0].images] == [r.path for r in reg.images])

        dest = os.path.join(work, "Scene 1")
        os.makedirs(dest)
        win.move_actual_files([r.path for r in reg.images[:2]], dest)
        check("move actual files to folder",
              all(os.path.dirname(r.path) == dest and os.path.exists(r.path) for r in reg.images[:2]))

        victim = os.path.join(work, "trash_me.png")
        _image(victim, 1, "PNG")
        trashed = fileops.move_to_trash(victim)
        check("Recycle Bin delete", trashed and not os.path.exists(victim))

        win.dirty = False
    except Exception:  # noqa: BLE001 - everything goes into the report
        failures += 1
        lines.append("[FAIL] exception\n" + traceback.format_exc())
    finally:
        if win is not None:
            win.dirty = False
            win.close()
        shutil.rmtree(work, ignore_errors=True)
    lines.append(f"\n{'ALL PASSED' if not failures else f'{failures} FAILURE(S)'}")
    with open(os.path.join(out_dir, "report.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return 1 if failures else 0
