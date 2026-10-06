"""Enlarged image viewer (double-click a thumbnail).

Wheel = zoom the image (around the cursor), drag = pan, 100% / Fit buttons,
live zoom percentage, Esc or double-click closes, Left/Right = prev/next
image of the same region.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImageReader, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (QDialog, QGraphicsPixmapItem, QGraphicsScene, QGraphicsView,
                               QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget)

ZMIN, ZMAX = 0.02, 32.0


class _View(QGraphicsView):
    def __init__(self, viewer):
        super().__init__()
        self.viewer = viewer
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(QPainter.SmoothPixmapTransform | QPainter.Antialiasing)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setBackgroundBrush(QColor("#0e0e10"))
        self.setFrameShape(QGraphicsView.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.item = QGraphicsPixmapItem()
        self.item.setTransformationMode(Qt.SmoothTransformation)
        self.scene().addItem(self.item)

    def wheelEvent(self, e):
        d = e.angleDelta().y() or e.angleDelta().x()
        if d:
            self.viewer.zoom_by(1.2 ** (d / 120.0))
        e.accept()

    def mouseDoubleClickEvent(self, e):
        self.viewer.accept()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.viewer.fit_mode:
            self.viewer.fit()


class ImageViewer(QDialog):
    def __init__(self, parent, paths_and_names: list[tuple[str, str]], index: int):
        super().__init__(parent)
        self.setWindowTitle("Image Viewer")
        self.setModal(True)
        self.items = paths_and_names
        self.index = index
        self.fit_mode = True
        self.setStyleSheet("QDialog{background:#0e0e10;} QLabel{color:#ddd;}"
                           "QPushButton{padding:4px 12px;}")
        self.view = _View(self)
        bar = QWidget()
        hl = QHBoxLayout(bar)
        hl.setContentsMargins(8, 4, 8, 4)
        self.title = QLabel()
        self.prev_btn = QPushButton("◀")
        self.next_btn = QPushButton("▶")
        fit_btn = QPushButton("Fit to Screen")
        one_btn = QPushButton("100%")
        self.zoom_lbl = QLabel("100%")
        self.zoom_lbl.setMinimumWidth(60)
        self.zoom_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        close_btn = QPushButton("Close (Esc)")
        for w in (self.prev_btn, self.next_btn):
            w.setFixedWidth(36)
        hl.addWidget(self.prev_btn)
        hl.addWidget(self.next_btn)
        hl.addWidget(self.title, 1)
        hl.addWidget(fit_btn)
        hl.addWidget(one_btn)
        hl.addWidget(self.zoom_lbl)
        hl.addWidget(close_btn)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(bar)
        lay.addWidget(self.view, 1)
        fit_btn.clicked.connect(self.fit)
        one_btn.clicked.connect(self.actual_size)
        close_btn.clicked.connect(self.accept)
        self.prev_btn.clicked.connect(lambda: self.step(-1))
        self.next_btn.clicked.connect(lambda: self.step(1))
        QShortcut(QKeySequence(Qt.Key_Left), self, lambda: self.step(-1))
        QShortcut(QKeySequence(Qt.Key_Right), self, lambda: self.step(1))
        QShortcut(QKeySequence("1"), self, self.actual_size)
        QShortcut(QKeySequence("0"), self, self.fit)
        for w in (fit_btn, one_btn, close_btn, self.prev_btn, self.next_btn):
            w.setFocusPolicy(Qt.NoFocus)
        if parent is not None:
            self.setGeometry(parent.geometry().adjusted(30, 40, -30, -30))
        self.load()

    def load(self):
        path, name = self.items[self.index]
        reader = QImageReader(path)
        reader.setAutoTransform(True)
        img = reader.read()
        pix = QPixmap.fromImage(img) if not img.isNull() else QPixmap()
        self.view.item.setPixmap(pix)
        self.view.scene().setSceneRect(QRectF(pix.rect()))
        dims = f"{pix.width()}×{pix.height()}" if not pix.isNull() else f"cannot open ({reader.errorString()})"
        self.title.setText(f"{self.index + 1} / {len(self.items)}   {name}   —   {dims}   "
                           f"<span style='color:#888'>{os.path.basename(path)}</span>")
        self.prev_btn.setEnabled(self.index > 0)
        self.next_btn.setEnabled(self.index < len(self.items) - 1)
        self._pix_size = pix.size()
        self.fit_mode = True
        self.fit() if self._needs_fit() else self.actual_size()

    def _needs_fit(self) -> bool:
        vp = self.view.viewport().size()
        return self._pix_size.width() > vp.width() or self._pix_size.height() > vp.height()

    def zoom(self) -> float:
        return self.view.transform().m11()

    def _set_zoom(self, z: float):
        z = min(max(z, ZMIN), ZMAX)
        self.view.resetTransform()
        self.view.scale(z, z)
        self._update_label()

    def zoom_by(self, f: float):
        self.fit_mode = False
        cur = self.zoom()
        t = min(max(cur * f, ZMIN), ZMAX)
        self.view.scale(t / cur, t / cur)
        self._update_label()

    def fit(self):
        self.fit_mode = True
        if self._pix_size.isEmpty():
            return
        self.view.fitInView(self.view.item, Qt.KeepAspectRatio)
        self._update_label()

    def actual_size(self):
        self.fit_mode = False
        self._set_zoom(1.0)
        self.view.centerOn(self.view.item)

    def step(self, d: int):
        i = self.index + d
        if 0 <= i < len(self.items):
            self.index = i
            self.load()

    def _update_label(self):
        self.zoom_lbl.setText(f"{round(self.zoom() * 100)}%")

    def showEvent(self, e):
        super().showEvent(e)
        if self.fit_mode:  # viewport size is only final once shown
            self.fit() if self._needs_fit() else self.actual_size()
