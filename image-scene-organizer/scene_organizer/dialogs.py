"""Dialogs: bulk rename preview, preferences."""
from __future__ import annotations

import os

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QSpinBox, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)

from . import fileops

STATUS_TEXT = {
    "ok": ("rename", "#7bd88f"),
    "unchanged": ("already named", "#999"),
    "missing": ("file missing - skipped", "#e0a052"),
    "duplicate": ("same file listed twice - skipped", "#e0a052"),
    "conflict": ("CONFLICT: target exists", "#ff6b6b"),
}


class BulkRenameDialog(QDialog):
    """Preview real-file renaming by the current visible order."""

    def __init__(self, parent, region_name: str, paths: list[str]):
        super().__init__(parent)
        self.setWindowTitle(f"Rename Actual Files by Order — {region_name}")
        self.resize(980, 620)
        self.paths = paths
        self.entries: list[fileops.RenameEntry] = []

        self.template = QLineEdit(fileops.DEFAULT_TEMPLATE)
        self.region = QLineEdit(region_name)
        self.start = QSpinBox()
        self.start.setRange(0, 999999)
        self.start.setValue(1)
        self.pad = QSpinBox()
        self.pad.setRange(1, 8)
        self.pad.setValue(3)
        form = QFormLayout()
        form.addRow("Name pattern", self.template)
        form.addRow("{region} =", self.region)
        row = QHBoxLayout()
        row.addWidget(QLabel("Start at"))
        row.addWidget(self.start)
        row.addSpacing(20)
        row.addWidget(QLabel("Digits"))
        row.addWidget(self.pad)
        row.addStretch(1)
        form.addRow(row)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["#", "Current file", "New file", "Status"])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)

        self.summary = QLabel()
        warn = QLabel("This renames the REAL files on disk (extensions are kept). The project file "
                      "is saved afterwards so it points to the new names. A rename log is written "
                      "so the operation can be reverted (File → Revert Last File Rename/Move).")
        warn.setWordWrap(True)
        warn.setStyleSheet("color:#e0a052")
        self.buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.apply_btn = self.buttons.addButton("Apply Rename", QDialogButtonBox.AcceptRole)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.table, 1)
        lay.addWidget(self.summary)
        lay.addWidget(warn)
        lay.addWidget(self.buttons)
        for w in (self.template, self.region):
            w.textChanged.connect(self.refresh)
        for w in (self.start, self.pad):
            w.valueChanged.connect(self.refresh)
        self.refresh()

    def refresh(self):
        self.entries = fileops.plan_rename(self.paths, self.template.text(), self.region.text(),
                                           self.start.value(), self.pad.value())
        self.table.setRowCount(len(self.entries))
        counts: dict[str, int] = {}
        for i, e in enumerate(self.entries):
            counts[e.status] = counts.get(e.status, 0) + 1
            txt, col = STATUS_TEXT[e.status]
            cells = [str(i + 1), os.path.basename(e.old), os.path.basename(e.new), txt]
            for c, v in enumerate(cells):
                it = QTableWidgetItem(v)
                if c in (1, 2):
                    it.setToolTip(e.old if c == 1 else e.new)
                if c == 3:
                    it.setForeground(QColor(col))
                self.table.setItem(i, c, it)
        conflicts = counts.get("conflict", 0)
        n_ok = counts.get("ok", 0)
        self.summary.setText(f"{n_ok} file(s) will be renamed"
                             + (f", {conflicts} conflict(s) — change the pattern or start number"
                                if conflicts else "")
                             + "".join(f", {v} {k}" for k, v in counts.items()
                                       if k not in ("ok", "conflict")))
        self.apply_btn.setEnabled(n_ok > 0 and conflicts == 0)


class PreferencesDialog(QDialog):
    def __init__(self, parent, autosave_on: bool, autosave_min: int):
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.autosave = QCheckBox("Enable autosave")
        self.autosave.setChecked(autosave_on)
        self.interval = QSpinBox()
        self.interval.setRange(1, 120)
        self.interval.setSuffix(" min")
        self.interval.setValue(autosave_min)
        form = QFormLayout(self)
        form.addRow(self.autosave)
        form.addRow("Autosave interval", self.interval)
        note = QLabel("Autosave writes to a separate recovery file and never overwrites your "
                      "project file. After a crash you are offered to restore it on next start.")
        note.setWordWrap(True)
        form.addRow(note)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)
