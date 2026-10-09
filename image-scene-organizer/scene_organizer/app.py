"""Application entry point."""
from __future__ import annotations

import os
import sys
import time
import traceback

from PySide6.QtCore import QLibraryInfo, QLocale, QSettings, QStandardPaths, QTranslator
from PySide6.QtGui import QImageReader
from PySide6.QtWidgets import QApplication, QMessageBox

from . import i18n, theme
from .i18n import tr
from .mainwindow import APP_NAME, MainWindow


def apply_appearance(app: QApplication) -> None:
    """Fusion style + saved theme (default light) + bundled Pretendard font."""
    app.setStyle("Fusion")
    family = theme.load_fonts()
    if family:
        app.setFont(theme.ui_font(family))
    t = theme.set_theme(str(QSettings().value("ui/theme", theme.DEFAULT_THEME)))
    app.setPalette(theme.palette(t))
    app.setStyleSheet(theme.stylesheet(t))


def _install_excepthook() -> None:
    """Prototype safety net: an exception in a slot shows a dialog and is
    logged instead of silently breaking the current action."""
    log_dir = QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation)

    def hook(etype, value, tb):
        text = "".join(traceback.format_exception(etype, value, tb))
        if sys.stderr:  # None in the windowed .exe
            sys.stderr.write(text)
        try:
            os.makedirs(log_dir, exist_ok=True)
            with open(os.path.join(log_dir, "error.log"), "a", encoding="utf-8") as f:
                f.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')}\n{text}")
        except OSError:
            pass
        QMessageBox.critical(None, tr("Unexpected error"),
                             tr("{etype}: {value}\n\nDetails were written to\n{log}\n\nYour project is still open - "
                                "save it with File → Save As.", etype=etype.__name__, value=value,
                                log=os.path.join(log_dir, "error.log")))

    sys.excepthook = hook


def _apply_language(app: QApplication) -> None:
    """UI language from the settings (default Korean) + Qt's own dialog texts."""
    lang = QSettings().value("ui/language", i18n.DEFAULT_LANGUAGE)
    i18n.set_language(str(lang))
    if i18n.language() == "ko":
        QLocale.setDefault(QLocale(QLocale.Korean, QLocale.SouthKorea))
        qt_tr = QTranslator(app)
        if qt_tr.load("qtbase_ko", QLibraryInfo.path(QLibraryInfo.TranslationsPath)):
            app.installTranslator(qt_tr)  # Save / Cancel / Yes / No, file dialogs


def _self_test(app: QApplication, out_dir: str) -> int:
    from PySide6.QtCore import QTimer

    from . import selftest

    def hook(etype, value, tb):  # never block on a dialog in unattended mode
        with open(os.path.join(out_dir, "crash.txt"), "a", encoding="utf-8") as f:
            f.write("".join(traceback.format_exception(etype, value, tb)))
        os._exit(3)

    os.makedirs(out_dir, exist_ok=True)
    sys.excepthook = hook
    QTimer.singleShot(180_000, lambda: os._exit(2))  # watchdog
    result = []
    QTimer.singleShot(0, lambda: (result.append(selftest.run(out_dir)), app.quit()))
    app.exec()
    return result[0] if result else 4


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    self_test = next((a.split("=", 1)[1] for a in argv[1:] if a.startswith("--self-test=")), None)
    if self_test:
        QStandardPaths.setTestModeEnabled(True)  # keep the real profile untouched
    app = QApplication(argv)
    app.setOrganizationName("ImageSceneOrganizer")
    app.setApplicationName("ImageSceneOrganizer")
    app.setApplicationDisplayName(APP_NAME)
    QImageReader.setAllocationLimit(2048)  # MB; allow very large source images in the viewer
    apply_appearance(app)
    _apply_language(app)
    if self_test:
        return _self_test(app, os.path.abspath(self_test))
    _install_excepthook()
    open_path = next((a for a in argv[1:] if not a.startswith("-")), None)
    win = MainWindow(open_path)
    win.show()
    return app.exec()
