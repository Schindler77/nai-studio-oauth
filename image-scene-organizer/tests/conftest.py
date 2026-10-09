import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtCore import QStandardPaths
    from PySide6.QtWidgets import QApplication
    QStandardPaths.setTestModeEnabled(True)  # keep settings/autosave/thumb cache out of the real profile
    app = QApplication.instance() or QApplication([])
    app.setOrganizationName("ImageSceneOrganizerTest")
    app.setApplicationName("ImageSceneOrganizerTest")
    return app


@pytest.fixture(autouse=True)
def _ui_language():
    """Tests run in English unless they ask for another language; a Korean
    run must not hit a single untranslated string."""
    from scene_organizer import i18n
    i18n.set_language("en")
    i18n.MISSES.clear()
    yield
    lang = i18n.language()
    i18n.set_language("en")
    if lang == "ko":
        assert not i18n.MISSES, f"untranslated: {sorted(i18n.MISSES)}"
