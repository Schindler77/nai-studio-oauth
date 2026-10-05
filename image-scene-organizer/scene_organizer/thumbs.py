"""Background thumbnail generation with memory + disk cache.

The canvas never draws full-resolution originals: each source file is
decoded once at reduced size on a worker thread (QImageReader decodes
JPEGs at reduced scale directly), stored on disk keyed by path+mtime+size,
and kept in memory as one QPixmap per file.
"""
from __future__ import annotations

import hashlib
import os

from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, Signal
from PySide6.QtGui import QImage, QImageReader, QPixmap

THUMB_DIM = 320  # max edge of cached thumbnails (= THUMB_MAX of the canvas)


class _Emitter(QObject):
    done = Signal(str, QImage, QSize, bool)  # path, image, original size, missing


class _Job(QRunnable):
    def __init__(self, path: str, cache_dir: str, emitter: _Emitter):
        super().__init__()
        self.path, self.cache_dir, self.emitter = path, cache_dir, emitter

    def run(self):
        path = self.path
        try:
            st = os.stat(path)
        except OSError:
            self.emitter.done.emit(path, QImage(), QSize(), True)
            return
        key = hashlib.sha1(f"{path}|{st.st_mtime_ns}|{st.st_size}|{THUMB_DIM}".encode()).hexdigest()
        cached = os.path.join(self.cache_dir, key[:2], key + ".png")
        meta = cached + ".size"
        img = QImage()
        orig = QSize()
        if os.path.exists(cached) and os.path.exists(meta):
            img = QImage(cached)
            try:
                w, h = open(meta).read().split("x")
                orig = QSize(int(w), int(h))
            except (OSError, ValueError):
                pass
        if img.isNull():
            reader = QImageReader(path)
            reader.setAutoTransform(True)
            size = reader.size()
            if size.isValid() and max(size.width(), size.height()) > THUMB_DIM:
                reader.setScaledSize(size.scaled(THUMB_DIM, THUMB_DIM, Qt.KeepAspectRatio))
            img = reader.read()
            if img.isNull():
                self.emitter.done.emit(path, QImage(), QSize(), True)
                return
            orig = size if size.isValid() else img.size()
            if (img.width() > img.height()) != (orig.width() > orig.height()) \
                    and img.width() != img.height():
                orig = orig.transposed()  # EXIF rotation: size() is pre-transform
            if max(img.width(), img.height()) > THUMB_DIM:  # formats without scaled decode
                img = img.scaled(THUMB_DIM, THUMB_DIM, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            try:
                os.makedirs(os.path.dirname(cached), exist_ok=True)
                img.save(cached, "PNG")
                with open(meta, "w") as f:
                    f.write(f"{orig.width()}x{orig.height()}")
            except OSError:
                pass
        self.emitter.done.emit(path, img, orig, False)


class ThumbnailCache(QObject):
    ready = Signal(str)

    def __init__(self, cache_dir: str, parent=None):
        super().__init__(parent)
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)
        self._pix: dict[str, QPixmap] = {}
        self._orig: dict[str, QSize] = {}
        self._missing: set[str] = set()
        self._pending: set[str] = set()
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(max(2, (os.cpu_count() or 4) - 1))
        self._emitter = _Emitter()
        self._emitter.done.connect(self._on_done)

    def get(self, path: str) -> QPixmap | None:
        pix = self._pix.get(path)
        if pix is None and path not in self._missing and path not in self._pending:
            self._pending.add(path)
            self._pool.start(_Job(path, self.cache_dir, self._emitter))
        return pix

    def is_missing(self, path: str) -> bool:
        return path in self._missing

    def original_size(self, path: str) -> QSize | None:
        return self._orig.get(path)

    def invalidate(self, path: str) -> None:
        self._pix.pop(path, None)
        self._missing.discard(path)

    def recheck_missing(self) -> None:
        self._missing.clear()

    def _on_done(self, path: str, img: QImage, orig: QSize, missing: bool):
        self._pending.discard(path)
        if missing:
            self._missing.add(path)
        else:
            self._pix[path] = QPixmap.fromImage(img)
            if orig.isValid():
                self._orig[path] = orig
        self.ready.emit(path)
