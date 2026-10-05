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
