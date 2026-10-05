"""Application entry point."""
from __future__ import annotations

import os
import sys
import time
import traceback

from PySide6.QtCore import QStandardPaths, Qt
from PySide6.QtGui import QColor, QImageReader, QPalette
from PySide6.QtWidgets import QApplication, QMessageBox

from .mainwindow import APP_NAME, MainWindow


def _dark_palette(app: QApplication) -> None:
    app.setStyle("Fusion")
    p = QPalette()
    base, alt, text = QColor("#232428"), QColor("#2b2d31"), QColor("#e6e6e6")
    p.setColor(QPalette.Window, alt)
    p.setColor(QPalette.WindowText, text)
    p.setColor(QPalette.Base, base)
    p.setColor(QPalette.AlternateBase, alt)
    p.setColor(QPalette.ToolTipBase, QColor("#333"))
    p.setColor(QPalette.ToolTipText, text)
    p.setColor(QPalette.Text, text)
    p.setColor(QPalette.Button, alt)
    p.setColor(QPalette.ButtonText, text)
    p.setColor(QPalette.Highlight, QColor("#2f7fb8"))
    p.setColor(QPalette.HighlightedText, Qt.white)
    p.setColor(QPalette.Disabled, QPalette.Text, QColor("#777"))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#777"))
    p.setColor(QPalette.Disabled, QPalette.WindowText, QColor("#777"))
    app.setPalette(p)


def _install_excepthook() -> None:
    """Prototype safety net: an exception in a slot shows a dialog and is
    logged instead of silently breaking the current action."""
    log_dir = QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation)

    def hook(etype, value, tb):
        text = "".join(traceback.format_exception(etype, value, tb))
        sys.stderr.write(text)
        try:
            os.makedirs(log_dir, exist_ok=True)
            with open(os.path.join(log_dir, "error.log"), "a", encoding="utf-8") as f:
                f.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')}\n{text}")
        except OSError:
            pass
        QMessageBox.critical(None, "Unexpected error",
                             f"{etype.__name__}: {value}\n\nDetails were written to\n"
                             f"{os.path.join(log_dir, 'error.log')}\n\n"
                             "Your project is still open - save it with File → Save As.")

    sys.excepthook = hook


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    app = QApplication(argv)
    app.setOrganizationName("ImageSceneOrganizer")
    app.setApplicationName("ImageSceneOrganizer")
    app.setApplicationDisplayName(APP_NAME)
    QImageReader.setAllocationLimit(2048)  # MB; allow very large source images in the viewer
    _dark_palette(app)
    _install_excepthook()
    open_path = next((a for a in argv[1:] if not a.startswith("-")), None)
    win = MainWindow(open_path)
    win.show()
    return app.exec()
