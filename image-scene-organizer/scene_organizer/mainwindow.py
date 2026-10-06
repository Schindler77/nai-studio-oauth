"""Main window: owns the Project, undo history, clipboard, menus and all
commands. The Canvas calls back into it for every model change."""
from __future__ import annotations

import copy
import math
import os
import time

from PySide6.QtCore import QEvent, QPointF, QRectF, QSettings, QSize, QStandardPaths, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QIcon, QImageReader, QKeySequence, QPixmap
from PySide6.QtWidgets import (QApplication, QColorDialog, QFileDialog, QHBoxLayout,
                               QInputDialog, QLabel, QMainWindow, QMenu, QMessageBox,
                               QLineEdit, QPushButton, QSizePolicy, QSlider, QToolButton, QWidget)

from . import fileops
from .i18n import LANGUAGES, language, tr
from .canvas import ZOOM_MAX, ZOOM_MIN, Canvas
from .dialogs import BulkRenameDialog, PreferencesDialog
from . import theme
from .icons import icon
from .model import (ASPECTS, PAD, PRESET_COLORS, TITLE_H, PROJECT_EXT, REGION_EXT, THUMB_DEFAULT, THUMB_MAX,
                    THUMB_MIN, ImageRef, Project, Region, closest_aspect,
                    default_region_size, grid_cols, grid_pos, load_json, norm_path,
                    region_file_dict, region_from_file_dict, save_json_atomic)
from .thumbs import ThumbnailCache
from .sidebar import Sidebar
from .tips import TipDialog
from .viewer import ImageViewer

APP_NAME = "Image Scene Organizer"
UNDO_LIMIT = 150
AUTOSAVE_DEFAULT_MIN = 3  # open item: default autosave interval


def project_filter() -> str:
    return f"{tr('Image Scene Project')} (*{PROJECT_EXT})"


def region_filter() -> str:
    return f"{tr('Image Scene Region')} (*{REGION_EXT})"


def image_filter() -> str:
    return tr("Images") + " (" + " ".join("*" + e for e in sorted(fileops.SUPPORTED_EXTS)) + ")"


class SearchBox(QLineEdit):
    """Toolbar search field: keeps editing keys for itself, Esc clears,
    Shift+Enter goes to the previous result."""
    escaped = Signal()
    prevRequested = Signal()

    def event(self, e):
        if e.type() == QEvent.ShortcutOverride:
            mods = e.modifiers() & ~Qt.ShiftModifier
            if mods == Qt.NoModifier or e.key() in (Qt.Key_A, Qt.Key_C, Qt.Key_V, Qt.Key_X, Qt.Key_Z, Qt.Key_Y):
                e.accept()
                return True
        return super().event(e)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.escaped.emit()
            return
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and e.modifiers() & Qt.ShiftModifier:
            self.prevRequested.emit()
            return
        super().keyPressEvent(e)


def exec_menu(menu: QMenu, global_pos) -> None:
    """Single place where context menus are shown (patched in tests)."""
    menu.exec(global_pos)


def exec_dialog(dlg) -> int:
    """Single place where non-critical dialogs are run modally (patched in tests)."""
    return dlg.exec()


def _swatch(color: str) -> QIcon:
    pm = QPixmap(14, 14)
    pm.fill(QColor(color))
    return QIcon(pm)


class MainWindow(QMainWindow):
    def __init__(self, open_path: str | None = None):
        super().__init__()
        self.settings = QSettings()
        self.data_dir = QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation) \
            or os.path.join(os.path.expanduser("~"), ".image-scene-organizer")
        os.makedirs(self.data_dir, exist_ok=True)
        self.thumbs = ThumbnailCache(os.path.join(self.data_dir, "thumbs"), self)

        self.project = Project()
        self.project_path: str | None = None
        self.dirty = False
        self._dirty_since_autosave = False
        self.undo_stack: list[dict] = []
        self.redo_stack: list[dict] = []
        self.active_region_id: str | None = None
        self.selected_region_ids: set[str] = set()
        self.clipboard: dict | None = None  # {"mode": "copy"|"cut", "items": [dict], "ids": [str]}
        self.cut_ids: set[str] = set()
        self._color_i = 0
        self._open_path = open_path

        self.canvas = Canvas(self, self.thumbs)
        self.sidebar = Sidebar(self)
        central = QWidget()
        row = QHBoxLayout(central)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self.sidebar)
        row.addWidget(self.canvas, 1)
        self.setCentralWidget(central)
        self.canvas.horizontalScrollBar().valueChanged.connect(self.sidebar.minimap.update)
        self.canvas.verticalScrollBar().valueChanged.connect(self.sidebar.minimap.update)
        self.canvas.zoomChanged.connect(lambda _: self.sidebar.minimap.update())
        self.sidebar.closeRequested.connect(lambda: self.set_sidebar_visible(False))
        self.canvas.scene().selectionChanged.connect(self.on_selection_changed)
        self.canvas.zoomChanged.connect(lambda _: self._update_status())

        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self._build_view_extras()
        self._build_status()

        self.autosave_timer = QTimer(self)
        self.autosave_timer.timeout.connect(self.autosave)
        self.apply_autosave_settings()

        geo = self.settings.value("window/geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        else:
            self.resize(1500, 920)
        self.refresh()
        QTimer.singleShot(0, self._startup)

    # =============================================================== actions
    def _act(self, key, text, slot, shortcut=None, checkable=False, tip=None):
        a = QAction(text, self)
        if shortcut:
            a.setShortcuts(shortcut if isinstance(shortcut, list) else [QKeySequence(shortcut)])
            a.setShortcutContext(Qt.WindowShortcut)
        a.setCheckable(checkable)
        if tip:
            a.setStatusTip(tip)
        a.triggered.connect(lambda checked=False: slot())
        self.addAction(a)
        self.A[key] = a
        return a

    def _build_actions(self):
        self.A: dict[str, QAction] = {}
        a = self._act
        a("new", tr("New Project"), self.new_project, QKeySequence.New)
        a("open", tr("Open Project…"), self.open_project, QKeySequence.Open)
        a("save", tr("Save Current State"), self.save, QKeySequence.Save)
        a("save_as", tr("Save As…"), self.save_as, "Ctrl+Shift+S")
        a("save_full", tr("Save Full Project"), self.save)
        a("save_region", tr("Save Current Region…"), lambda: self.save_region(self.active_region_id))
        a("load_region", tr("Load Saved Region…"), lambda: self.load_region())
        a("relink", tr("Relink Missing Images…"), self.relink_missing)
        a("revert_rename", tr("Revert Last File Rename/Move…"), self.revert_last_rename)
        a("prefs", tr("Preferences…"), self.preferences)
        a("quit", tr("Exit"), self.close, QKeySequence.Quit)

        a("undo", tr("Undo"), self.undo, QKeySequence.Undo)
        a("redo", tr("Redo"), self.redo, [QKeySequence("Ctrl+Y"), QKeySequence("Ctrl+Shift+Z")])
        a("copy", tr("Copy"), self.copy_selection, QKeySequence.Copy)
        a("cut", tr("Cut"), self.cut_selection, QKeySequence.Cut)
        a("paste", tr("Paste"), lambda: self.paste(), QKeySequence.Paste)
        a("remove", tr("Remove from Region (keeps files)"), self.remove_selection, QKeySequence.Delete)
        a("select_all", tr("Select All (active region, else everything)"), self.select_all, QKeySequence.SelectAll)
        a("lock", tr("Lock Selected"), lambda: self.set_locked(True), "Ctrl+L")
        a("unlock", tr("Unlock Selected"), lambda: self.set_locked(False), "Ctrl+Shift+L")
        a("lock_upto", tr("Lock Up To Selected (Confirmed Portion)"), self.lock_up_to_selection)
        a("escape", tr("Cancel / Clear Selection"), self.escape, "Esc")

        a("imp_one", tr("Import Image…"), lambda: self.import_dialog(False))
        a("imp_multi", tr("Import Multiple Images…"), lambda: self.import_dialog(True), "Ctrl+I")
        a("imp_folder", tr("Import Folder…"), lambda: self.import_folder_dialog(False), "Ctrl+Shift+I")
        a("imp_folder_rec", tr("Import Folder Including Subfolders…"), lambda: self.import_folder_dialog(True))

        a("new_region", tr("New Region"), lambda: self.new_region(), "Ctrl+R")
        a("rename_region", tr("Rename Region…"), lambda: self.rename_region(self.active_region_id), "F2")
        a("auto", tr("Auto-Arrange"), lambda: self.toggle_auto(self.active_region_id), "Ctrl+E", checkable=True,
          tip=tr("Persistent per-region auto-arrange (insertion with automatic shifting)"))
        a("dup_region", tr("Duplicate Region"), lambda: self.duplicate_region(self.active_region_id))
        a("clear_region", tr("Clear Region…"), lambda: self.clear_region(self.active_region_id))
        a("del_region", tr("Delete Region…"), lambda: self.delete_region(self.active_region_id))
        a("collapse", tr("Collapse / Expand Region"), lambda: self.toggle_collapse(self.active_region_id))
        a("lock_region", tr("Lock Entire Region"), lambda: self.lock_region(self.active_region_id, True))
        a("unlock_region", tr("Unlock Entire Region"), lambda: self.lock_region(self.active_region_id, False))
        a("bulk_rename", tr("Rename Actual Files by Order…"), lambda: self.bulk_rename_region(self.active_region_id))

        a("arr_h", tr("Arrange Regions Horizontally"), lambda: self.arrange_regions("h"))
        a("arr_v", tr("Arrange Regions Vertically"), lambda: self.arrange_regions("v"))
        a("arr_g", tr("Arrange Regions as Grid"), lambda: self.arrange_regions("g"))
        a("arr_sel", tr("Arrange Selected Regions (Ctrl+click titles)"), lambda: self.arrange_regions("h", True))
        a("regrid", tr("Arrange Images Inside Region (grid, keep order)"), lambda: self.regrid(self.active_region_id))
        a("visual_order", tr("Set Order from Visual Position (free mode)"),
          lambda: self.adopt_visual_order(self.active_region_id))

        a("fit_all", tr("Fit All"), self.canvas.fit_all, "Ctrl+0")
        a("fit_region", tr("Fit Selected Region"), self.fit_active_region, "Ctrl+9")
        a("zoom100", tr("Canvas Zoom 100%"), lambda: self.canvas.set_zoom(1.0), "Ctrl+1")
        a("thumb_up", tr("Larger Thumbnails"), lambda: self.set_thumb_size(int(self.project.thumb_size * 1.15)), "Ctrl+=")
        a("thumb_down", tr("Smaller Thumbnails"), lambda: self.set_thumb_size(int(self.project.thumb_size / 1.15)), "Ctrl+-")
        a("thumb_reset", tr("Default Thumbnail Size"), lambda: self.set_thumb_size(THUMB_DEFAULT))
        a("show_region_names", tr("Show Region Names"), lambda: self._toggle_view("show_region_names"), checkable=True)
        a("show_labels", tr("Show Image Names"), lambda: self._toggle_view("show_labels"), checkable=True)
        a("show_numbers", tr("Show Sequence Numbers"), lambda: self._toggle_view("show_numbers"), checkable=True)
        a("collapse_all", tr("Collapse All Regions"), lambda: self.collapse_all(True))
        a("expand_all", tr("Expand All Regions"), lambda: self.collapse_all(False))

    def _build_menus(self):
        mb = self.menuBar()
        A = self.A
        m = mb.addMenu(tr("&File"))
        for k in ("new", "open"):
            m.addAction(A[k])
        self.recent_menu = m.addMenu(tr("Recent Projects"))
        self.recent_menu.aboutToShow.connect(self._fill_recent)
        m.addSeparator()
        for k in ("save", "save_as", "save_region", "save_full"):
            m.addAction(A[k])
        m.addAction(A["load_region"])
        m.addSeparator()
        for k in ("relink", "revert_rename", "prefs"):
            m.addAction(A[k])
        m.addSeparator()
        m.addAction(A["quit"])

        m = mb.addMenu(tr("&Edit"))
        for k in ("undo", "redo", None, "copy", "cut", "paste", "remove", "select_all", None,
                  "lock", "unlock", "lock_upto"):
            m.addSeparator() if k is None else m.addAction(A[k])

        m = mb.addMenu(tr("&Import"))
        for k in ("imp_one", "imp_multi", "imp_folder", "imp_folder_rec"):
            m.addAction(A[k])

        m = mb.addMenu(tr("&Region"))
        m.addAction(A["new_region"])
        m.addAction(A["rename_region"])
        self.color_menu = m.addMenu(tr("Color"))
        self.color_menu.aboutToShow.connect(lambda: self._fill_color_menu(self.color_menu, None))
        for k in ("auto", "collapse", None, "dup_region", "save_region", "load_region", None,
                  "lock_region", "unlock_region", "bulk_rename", None, "clear_region", "del_region"):
            m.addSeparator() if k is None else m.addAction(A[k])

        m = mb.addMenu(tr("&Arrange"))
        for k in ("arr_h", "arr_v", "arr_g", "arr_sel", None, "regrid", "visual_order"):
            m.addSeparator() if k is None else m.addAction(A[k])

        m = mb.addMenu(tr("&View"))
        for k in ("fit_all", "fit_region", "zoom100", None):
            m.addSeparator() if k is None else m.addAction(A[k])
        tm = m.addMenu(tr("Thumbnail Size"))
        for k in ("thumb_up", "thumb_down", "thumb_reset"):
            tm.addAction(A[k])
        m.addSeparator()
        for k in ("show_region_names", "show_labels", "show_numbers", None, "collapse_all", "expand_all"):
            m.addSeparator() if k is None else m.addAction(A[k])
        self.view_menu = m

    def _build_toolbar(self):
        tb = self.addToolBar("Quick")
        tb.setObjectName("quick_toolbar")
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        tb.setIconSize(QSize(26, 20))  # 20px glyph + gap before the label
        A = self.A
        self._tb_icons: list[tuple[object, str, str | None]] = []  # (action/button, icon, fixed colour)

        def themed(obj, name, color=None):
            self._tb_icons.append((obj, name, color))
            return obj
        A["new"].setIconText(tr("New"))     # short toolbar labels; menus keep the full text
        A["open"].setIconText(tr("Open"))
        tb.addAction(themed(A["new"], "file-plus"))
        tb.addAction(themed(A["open"], "folder-open"))
        save_btn = themed(QToolButton(), "save", "#4f6bed")
        save_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        save_btn.setText(tr("Save"))
        save_btn.setPopupMode(QToolButton.MenuButtonPopup)
        sm = QMenu(save_btn)
        for k in ("save", "save_as", "save_region", "save_full"):
            sm.addAction(A[k])
        save_btn.setMenu(sm)
        save_btn.clicked.connect(self.save)
        tb.addWidget(save_btn)
        tb.addSeparator()
        tb.addAction(themed(A["undo"], "undo-2"))
        tb.addAction(themed(A["redo"], "redo-2"))
        tb.addSeparator()
        img = themed(QAction(tr("Add Image"), self), "image-plus")
        img.triggered.connect(lambda: self.import_dialog(True))
        tb.addAction(img)
        fol = themed(QAction(tr("Add Folder"), self), "folder-plus", "#f59e0b")
        fol.triggered.connect(lambda: self.import_folder_dialog(False))
        tb.addAction(fol)
        reg = themed(QAction(tr("Add Region"), self), "square-plus", "#10b981")
        reg.triggered.connect(lambda: self.new_region())
        tb.addAction(reg)
        tb.addSeparator()
        tb.addAction(themed(A["auto"], "arrow-down-up", "#3b82f6"))
        col_btn = themed(QToolButton(), "palette", "#8b5cf6")
        col_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        col_btn.setText(tr("Region Color"))
        col_btn.setPopupMode(QToolButton.InstantPopup)
        cm = QMenu(col_btn)
        cm.aboutToShow.connect(lambda: self._fill_color_menu(cm, None))
        col_btn.setMenu(cm)
        tb.addWidget(col_btn)
        lk = themed(QAction(tr("Lock / Unlock"), self), "lock", "#f59e0b")
        lk.setToolTip(tr("Lock the selected images, or unlock them if they are all locked (Ctrl+L / Ctrl+Shift+L)"))
        lk.triggered.connect(self.toggle_lock_selection)
        tb.addAction(lk)
        tb.addSeparator()
        tb.addAction(themed(A["fit_all"], "scan"))
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(spacer)
        self.search_box = SearchBox()
        self.search_box.setObjectName("SearchBox")
        self.search_box.setPlaceholderText(tr("Search the canvas (Ctrl+F)"))
        self.search_box.setClearButtonEnabled(True)
        self.search_box.setFixedWidth(270)
        self.search_icon = self.search_box.addAction(QIcon(), QLineEdit.LeadingPosition)
        self.search_box.textChanged.connect(self.run_search)
        self.search_box.returnPressed.connect(lambda: self.search_next(1))
        self.search_box.prevRequested.connect(lambda: self.search_next(-1))
        self.search_box.escaped.connect(self._search_escape)
        tb.addWidget(self.search_box)
        find = QAction(self)
        find.setShortcut(QKeySequence.Find)
        find.triggered.connect(self.focus_search)
        self.addAction(find)
        self._search_order: list[tuple[str, str]] = []
        self._search_pos = -1
        self.apply_toolbar_icons()

    MENU_ICONS = {"save_as": "save", "save_region": "save", "load_region": "folder-input",
                  "relink": "folder-input", "revert_rename": "undo-2", "copy": "copy", "cut": "scissors",
                  "paste": "clipboard-paste", "remove": "eraser", "select_all": "list-checks",
                  "lock": "lock", "unlock": "lock-open", "lock_upto": "lock", "imp_one": "image-plus",
                  "imp_multi": "image-plus", "imp_folder": "folder-plus", "imp_folder_rec": "folder-plus",
                  "new_region": "square-plus", "rename_region": "pencil", "dup_region": "copy-plus",
                  "clear_region": "eraser", "del_region": "trash-2", "collapse": "chevrons-down-up",
                  "lock_region": "lock", "unlock_region": "lock-open", "bulk_rename": "file-pen-line",
                  "arr_h": "columns-3", "arr_v": "rows-3", "arr_g": "layout-grid", "arr_sel": "columns-3",
                  "regrid": "layout-grid", "visual_order": "rows-3", "fit_region": "maximize-2",
                  "collapse_all": "chevrons-down-up", "expand_all": "chevrons-up-down"}

    # ------------------------------------------------------------- search
    def focus_search(self):
        self.search_box.setFocus()
        self.search_box.selectAll()

    def _search_escape(self):
        self.search_box.clear()
        self.canvas.setFocus()

    def run_search(self, text: str):
        """Highlight images (display or file name) and regions matching the text."""
        q = text.strip().lower()
        order: list[tuple[str, str]] = []
        if q:
            for reg in self.project.regions:
                if q in reg.name.lower():
                    order.append(("region", reg.id))
                for ref in reg.images:
                    if q in ref.display_name.lower() or q in os.path.basename(ref.path).lower():
                        order.append(("image", ref.id))
        self._search_order, self._search_pos = order, -1
        self.canvas.set_search({i for k, i in order if k == "image"}, {i for k, i in order if k == "region"})
        if not q:
            return
        if order:
            self.status(tr("Found {i} image(s) and {r} region(s) — Enter: next, Shift+Enter: previous, Esc: clear",
                           i=len(self.canvas.search_hits), r=len(self.canvas.search_regions)), 15000)
        else:
            self.status(tr("No matches for '{q}'", q=text.strip()))

    def search_next(self, step: int):
        if not self._search_order:
            self.run_search(self.search_box.text())
            if not self._search_order:
                return
        self._search_pos = (self._search_pos + step) % len(self._search_order)
        kind, key = self._search_order[self._search_pos]
        if kind == "region":
            self.activate_region(key)
            self.fit_region(key)
        else:
            reg, _ = self.project.find(key)
            if reg is None:
                return
            if reg.collapsed:  # show the hit
                reg.collapsed = False
                self.refresh()
            self.activate_region(reg.id)
            self.canvas.set_selection([key])
            self.canvas.reveal(key)
        self.status(tr("Search result {i} / {n}", i=self._search_pos + 1, n=len(self._search_order)), 15000)

    def apply_toolbar_icons(self):
        for obj, name, color in self._tb_icons:
            obj.setIcon(icon(name, color or theme.current().icon, gap=6))
        for key, name in self.MENU_ICONS.items():
            self.A[key].setIcon(icon(name, theme.current().icon, 16))
        self.search_icon.setIcon(icon("search", theme.current().subtext, 16))

    def _build_view_extras(self):
        self.sidebar_action = QAction(tr("Sidebar"), self)
        self.sidebar_action.setCheckable(True)
        self.sidebar_action.setShortcut(QKeySequence("Ctrl+B"))
        self.sidebar_action.triggered.connect(lambda on: self.set_sidebar_visible(on))
        self.addAction(self.sidebar_action)
        self.view_menu.addSeparator()
        self.view_menu.addAction(self.sidebar_action)
        self.tips_action = QAction(tr("Show Tips"), self)
        self.tips_action.setCheckable(True)
        self.tips_action.triggered.connect(lambda on: self.set_tips_visible(on))
        self.view_menu.addAction(self.tips_action)
        all_tips = QAction(icon("lightbulb", "#f59e0b", 16), tr("All Tips…"), self)
        all_tips.triggered.connect(lambda: self.show_tip_dialog(0))
        self.view_menu.addAction(all_tips)
        self.set_sidebar_visible(self.settings.value("ui/sidebar", True, type=bool))
        self.set_tips_visible(self.settings.value("ui/tips", True, type=bool), announce=False)
        am = self.view_menu.addMenu(tr("Thumbnail Shape"))
        self._aspect_actions = {}
        grp = QActionGroup(self)
        for key in ASPECTS:
            act_a = am.addAction(key)
            act_a.setCheckable(True)
            grp.addAction(act_a)
            act_a.triggered.connect(lambda _=False, k=key: self.set_thumb_aspect(k))
            self._aspect_actions[key] = act_a
        am.addSeparator()
        grp_f = QActionGroup(self)
        self._fill_actions = {}
        for key, label in (("cover", tr("Fill the box (crop edges)")), ("fit", tr("Show whole image"))):
            act_f = am.addAction(label)
            act_f.setCheckable(True)
            grp_f.addAction(act_f)
            act_f.triggered.connect(lambda _=False, k=key: self.set_thumb_fill(k))
            self._fill_actions[key] = act_f
        thm = self.view_menu.addMenu(tr("Theme"))
        grp_t = QActionGroup(self)
        for key, label in (("light", tr("Light")), ("dark", tr("Dark"))):
            act_t = thm.addAction(label)
            act_t.setCheckable(True)
            act_t.setChecked(theme.current().name == key)
            grp_t.addAction(act_t)
            act_t.triggered.connect(lambda _=False, k=key: self.set_ui_theme(k))
        lm = self.view_menu.addMenu(tr("Language"))
        for code, label in LANGUAGES.items():
            la = lm.addAction(label)
            la.setCheckable(True)
            la.setChecked(code == language())
            la.triggered.connect(lambda _=False, c=code: self.set_ui_language(c))

    def set_sidebar_visible(self, on: bool):
        self.sidebar.setVisible(on)
        self.sidebar_action.setChecked(on)
        self.settings.setValue("ui/sidebar", bool(on))

    def set_tips_visible(self, on: bool, announce: bool = True):
        self.sidebar.tip_card.setVisible(on)
        self.tips_action.setChecked(on)
        self.settings.setValue("ui/tips", bool(on))
        if not on and announce:
            self.status(tr("Tips are off — View → Show Tips turns them back on"))

    def show_tip_dialog(self, index: int = 0):
        dlg = TipDialog(self, index, self.tips_action.isChecked())
        exec_dialog(dlg)
        if dlg.show_tips.isChecked() != self.tips_action.isChecked():
            self.set_tips_visible(dlg.show_tips.isChecked())
        self.sidebar.next_tip(dlg.index)

    def set_ui_theme(self, name: str):
        """Switch light/dark immediately (palette, toolbar icons, canvas)."""
        t = theme.set_theme(name)
        self.settings.setValue("ui/theme", t.name)
        app = QApplication.instance()
        app.setPalette(theme.palette(t))
        app.setStyleSheet(theme.stylesheet(t))
        self.apply_toolbar_icons()
        self.apply_status_icons()
        self.sidebar.apply_theme()
        self.canvas.repaint_all_items()

    def set_thumb_aspect(self, key: str):
        self.project.thumb_aspect, self.project.aspect_auto = key, False
        self.set_dirty()
        self.refresh()

    def set_thumb_fill(self, key: str):
        self.project.thumb_fill = key
        self.set_dirty()
        self.refresh()

    def set_ui_language(self, code: str):
        """Saved for the next start (menus are built once at start-up)."""
        self.settings.setValue("ui/language", code)
        QMessageBox.information(self, "언어 / Language",
                                "프로그램을 다시 시작하면 바뀐 언어가 적용됩니다.\n"
                                "The new language is applied after restarting the program.")

    def _build_status(self):
        """Left: selection info (temporary messages cover it briefly).
        Right: hand tool, zoom − slider + percentage, fit to screen."""
        sb = self.statusBar()
        self.lbl_info = QLabel()
        self.lbl_info.setContentsMargins(8, 0, 8, 0)
        sb.addWidget(self.lbl_info, 1)
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 6, 0)
        row.setSpacing(4)
        self.hand_btn = QToolButton()
        self.hand_btn.setCheckable(True)
        self.hand_btn.setAutoRaise(True)
        self.hand_btn.setToolTip(tr("Hand tool: drag with the left button to move around (Space+drag also works)"))
        self.hand_btn.toggled.connect(self.canvas.set_hand_tool)
        self.zoom_out_btn = QToolButton()
        self.zoom_out_btn.setAutoRaise(True)
        self.zoom_out_btn.setToolTip(tr("Zoom out"))
        self.zoom_out_btn.clicked.connect(lambda: self.canvas.zoom_by(1 / 1.25, centered=True))
        self.zoom_slider = QSlider(Qt.Horizontal)
        self.zoom_slider.setRange(0, 1000)
        self.zoom_slider.setFixedWidth(130)
        self.zoom_slider.setToolTip(tr("Canvas zoom"))
        self.zoom_slider.valueChanged.connect(self._zoom_slider_moved)
        self.zoom_in_btn = QToolButton()
        self.zoom_in_btn.setAutoRaise(True)
        self.zoom_in_btn.setToolTip(tr("Zoom in"))
        self.zoom_in_btn.clicked.connect(lambda: self.canvas.zoom_by(1.25, centered=True))
        self.lbl_zoom = QLabel()
        self.lbl_zoom.setMinimumWidth(44)
        self.lbl_zoom.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.fit_btn = QPushButton(tr("Fit to Screen"))
        self.fit_btn.setObjectName("StatusButton")
        self.fit_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.fit_btn.clicked.connect(self.canvas.fit_all)
        for w in (self.hand_btn, self.zoom_out_btn, self.zoom_slider, self.zoom_in_btn, self.lbl_zoom):
            row.addWidget(w)
        row.addSpacing(8)
        row.addWidget(self.fit_btn)
        box.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        sb.addPermanentWidget(box)
        self._file_info_cache: dict[str, tuple[str, str]] = {}
        self.apply_status_icons()

    def apply_status_icons(self):
        col = theme.current().icon
        self.hand_btn.setIcon(icon("hand", col, 18))
        self.zoom_out_btn.setIcon(icon("minus", col, 16))
        self.zoom_in_btn.setIcon(icon("plus", col, 16))

    # zoom slider <-> canvas zoom (logarithmic so small zoom levels get room)
    def _zoom_to_slider(self, z: float) -> int:
        lo, hi = math.log(ZOOM_MIN), math.log(ZOOM_MAX)
        return round((math.log(max(min(z, ZOOM_MAX), ZOOM_MIN)) - lo) / (hi - lo) * 1000)

    def _zoom_slider_moved(self, v: int):
        lo, hi = math.log(ZOOM_MIN), math.log(ZOOM_MAX)
        z = math.exp(lo + (hi - lo) * v / 1000)
        if abs(z - self.canvas.zoom()) / self.canvas.zoom() > 0.004:
            self.canvas.set_zoom(z)

    def _file_info(self, path: str) -> tuple[str, str]:
        """('W × H', '2.4 MB') for the status bar; header read only, cached."""
        if path not in self._file_info_cache:
            size = self.thumbs.original_size(path)
            if size is None or not size.isValid():
                reader = QImageReader(path)
                reader.setAutoTransform(True)
                size = reader.size()
            dims = f"{size.width()} × {size.height()}" if size.isValid() else ""
            try:
                b = os.path.getsize(path)
                mb = f"{b / 1048576:.1f} MB" if b >= 1048576 else f"{b / 1024:.0f} KB"
            except OSError:
                mb = tr("missing file")
            self._file_info_cache[path] = (dims, mb)
        return self._file_info_cache[path]

    # ============================================================ state glue
    def status(self, msg: str, ms: int = 6000):
        self.statusBar().showMessage(msg, ms)

    def refresh(self):
        self.canvas.sync()
        self._update_ui_state()

    def _update_ui_state(self):
        reg = self.project.region(self.active_region_id)
        A = self.A
        A["auto"].setChecked(bool(reg and reg.auto_arrange))
        for k in ("auto", "rename_region", "dup_region", "clear_region", "del_region", "collapse",
                  "save_region", "lock_region", "unlock_region", "bulk_rename", "regrid",
                  "visual_order", "fit_region"):
            A[k].setEnabled(reg is not None)
        A["undo"].setEnabled(bool(self.undo_stack))
        A["redo"].setEnabled(bool(self.redo_stack))
        A["paste"].setEnabled(True)
        for k in ("show_region_names", "show_labels", "show_numbers"):
            A[k].setChecked(getattr(self.project, k))
        if hasattr(self, "_aspect_actions"):
            for key, act in self._aspect_actions.items():
                act.setChecked(key == self.project.thumb_aspect)
            for key, act in self._fill_actions.items():
                act.setChecked(key == self.project.thumb_fill)
        self.sidebar.refresh()
        self._update_status()
        self.update_title()

    def _update_status(self):
        sep = "   |   "
        reg = self.project.region(self.active_region_id)
        parts = [tr("Selected region: {name}", name=reg.name) if reg else
                 tr("Regions: {r}   Images: {i}", r=len(self.project.regions), i=self.project.image_count())]
        refs = self.selected_refs()
        if len(refs) == 1:
            path = refs[0][1].path
            parts.append(tr("1 image selected ({name})", name=os.path.basename(path)))
            dims, mb = self._file_info(path)
            parts += [p for p in (dims, mb) if p]
        elif refs:
            parts.append(tr("{n} images selected", n=len(refs)))
        self.lbl_info.setText(sep.join(parts))
        z = self.canvas.zoom()
        self.lbl_zoom.setText(f"{round(z * 100)}%")
        self.zoom_slider.blockSignals(True)
        self.zoom_slider.setValue(self._zoom_to_slider(z))
        self.zoom_slider.blockSignals(False)

    def update_title(self):
        name = os.path.splitext(os.path.basename(self.project_path))[0] if self.project_path else tr("Untitled")
        self.setWindowTitle(f"{APP_NAME} - {tr('Project')}: {name}{' *' if self.dirty else ''}")

    def set_dirty(self):
        self.dirty = True
        self._dirty_since_autosave = True
        self.update_title()

    def on_selection_changed(self):
        self._update_status()

    def activate_region(self, rid: str | None, toggle: bool = False):
        if toggle and rid:
            if rid in self.selected_region_ids:
                self.selected_region_ids.discard(rid)
                rid = next(iter(self.selected_region_ids), None)
            else:
                self.selected_region_ids.add(rid)
        else:
            self.selected_region_ids = {rid} if rid else set()
        if rid == self.active_region_id and not toggle:
            return
        self.active_region_id = rid
        for z, reg in enumerate(self.project.regions):
            ri = self.canvas.region_items.get(reg.id)
            if ri:
                ri.setZValue(100_000 if reg.id == rid else z)
                ri.set_data(reg, reg.id == rid, reg.id in self.selected_region_ids and
                            len(self.selected_region_ids) > 1)
        self._update_ui_state()

    # ================================================================= undo
    def snapshot(self) -> dict:
        return self.project.to_dict(None)

    def snapshot_changed(self, snap: dict) -> bool:
        return snap["regions"] != self.project.to_dict(None)["regions"]

    def checkpoint(self):
        self.commit_snapshot(self.snapshot())

    def commit_snapshot(self, snap: dict):
        self.undo_stack.append(snap)
        del self.undo_stack[:-UNDO_LIMIT]
        self.redo_stack.clear()
        self.set_dirty()

    def restore_snapshot(self, snap: dict):
        keep = self.project
        p = Project.from_dict(copy.deepcopy(snap))
        # display settings are not part of undo
        p.thumb_size, p.show_labels, p.show_numbers = keep.thumb_size, keep.show_labels, keep.show_numbers
        p.show_region_names, p.view = keep.show_region_names, keep.view
        p.thumb_aspect, p.thumb_fill, p.aspect_auto = keep.thumb_aspect, keep.thumb_fill, keep.aspect_auto
        self.project = p
        if not p.region(self.active_region_id):
            self.active_region_id = None
        self.selected_region_ids &= {r.id for r in p.regions}
        self.refresh()

    def undo(self):
        self.canvas.cancel_interaction()
        if not self.undo_stack:
            self.status(tr("Nothing to undo"))
            return
        self.redo_stack.append(self.snapshot())
        self.restore_snapshot(self.undo_stack.pop())
        self.set_dirty()
        self.status(tr("Undo"))

    def redo(self):
        self.canvas.cancel_interaction()
        if not self.redo_stack:
            self.status(tr("Nothing to redo"))
            return
        self.undo_stack.append(self.snapshot())
        self.restore_snapshot(self.redo_stack.pop())
        self.set_dirty()
        self.status(tr("Redo"))

    def _remap_history(self, mapping: dict[str, str]):
        """Keep undo/redo snapshots valid after a real file rename."""
        for snap in self.undo_stack + self.redo_stack:
            for reg in snap["regions"]:
                for img in reg["images"]:
                    new = mapping.get(norm_path(img["path"]))
                    if new:
                        old_stem = os.path.splitext(os.path.basename(img["path"]))[0]
                        if img.get("display_name") == old_stem:
                            img["display_name"] = os.path.splitext(os.path.basename(new))[0]
                        img["path"] = new
                        img.pop("rel", None)
        if self.clipboard:
            for d in self.clipboard["items"]:
                new = mapping.get(norm_path(d["path"]))
                if new:
                    d["path"] = new

    # ============================================================ selection
    def sequence_key(self) -> dict[str, tuple[int, int]]:
        return {ref.id: (gi, ii) for gi, reg in enumerate(self.project.regions)
                for ii, ref in enumerate(reg.images)}

    def selected_refs(self) -> list[tuple[Region, ImageRef]]:
        ids = set(self.canvas.selected_ids())
        return [(reg, ref) for reg in self.project.regions for ref in reg.images if ref.id in ids]

    def range_ids(self, a: str, b: str) -> list[str]:
        ra, _ = self.project.find(a)
        rb, _ = self.project.find(b)
        if ra is None or ra is not rb:
            return [b]
        i, j = sorted((ra.index_of(a), ra.index_of(b)))
        return [r.id for r in ra.images[i:j + 1]]

    def select_all(self):
        reg = self.project.region(self.active_region_id)
        regs = [reg] if reg else self.project.regions
        self.canvas.set_selection([r.id for g in regs if not g.collapsed for r in g.images])

    def escape(self):
        if self.canvas.cancel_interaction():
            self.status(tr("Cancelled"))
        elif self.canvas.selected_thumbs():
            self.canvas.clear_selection()
        elif self.clipboard and self.clipboard["mode"] == "cut":
            self.clipboard, self.cut_ids = None, set()
            self.refresh()
        else:
            self.activate_region(None)

    # ============================================================== regions
    def _region_display_rect(self, reg: Region) -> QRectF:
        ri = self.canvas.region_items.get(reg.id)
        if ri:
            return QRectF(reg.x, reg.y, ri.w, ri.h)
        return QRectF(reg.x, reg.y, reg.w, reg.h)

    def _free_region_spot(self, w: float, h: float) -> QPointF:
        if not self.project.regions:
            c = self.canvas.view_center()
            return QPointF(c.x() - w / 2, c.y() - h / 2)
        rects = [self._region_display_rect(r) for r in self.project.regions]
        right = max(rects, key=lambda r: r.right())
        return QPointF(right.right() + 40, right.top())

    def _make_region(self, at: QPointF | None = None, name: str | None = None,
                     color: str | None = None) -> Region:
        w, h = default_region_size(*self.project.cell())
        if at is None:
            at = self._free_region_spot(w, h)
        if color is None:
            color = PRESET_COLORS[self._color_i % len(PRESET_COLORS)][1]
            self._color_i += 1
        if name is None:
            name = self.project.unique_region_name(tr("Region {n}", n=len(self.project.regions) + 1))
        reg = Region(name, color, at.x(), at.y(), w, h)
        self.project.regions.append(reg)
        return reg

    def new_region(self, at: QPointF | None = None):
        self.checkpoint()
        reg = self._make_region(at)
        self.active_region_id = None
        self.refresh()
        self.activate_region(reg.id)
        self.canvas.ensureVisible(self._region_display_rect(reg), 40, 40)
        self.status(tr("Created '{name}'. Double-click its title (or F2) to rename.", name=reg.name))

    def rename_region(self, rid):
        reg = self.project.region(rid)
        if not reg:
            return
        name, ok = QInputDialog.getText(self, tr("Rename Region"), tr("Region name:"), text=reg.name)
        name = name.strip()
        if ok and name and name != reg.name:
            self.checkpoint()
            reg.name = name
            self.refresh()

    def _fill_color_menu(self, menu: QMenu, rid):
        menu.clear()
        for nm, col in PRESET_COLORS:
            act = menu.addAction(_swatch(col), tr(nm))
            act.triggered.connect(lambda _=False, c=col: self.set_region_color(c, rid))
        menu.addSeparator()
        act = menu.addAction(tr("Custom…"))
        act.triggered.connect(lambda: self._custom_color(rid))

    def _custom_color(self, rid):
        reg = self.project.region(rid or self.active_region_id)
        c = QColorDialog.getColor(QColor(reg.color) if reg else QColor("#4a86e8"), self, tr("Region Color"))
        if c.isValid():
            self.set_region_color(c.name(), rid)

    def set_region_color(self, color: str, rid=None):
        ids = {rid} if rid else (self.selected_region_ids or {self.active_region_id})
        regs = [r for r in self.project.regions if r.id in ids]
        if not regs:
            self.status(tr("Select a region first"))
            return
        self.checkpoint()
        for r in regs:
            r.color = color
        self.refresh()

    def toggle_auto(self, rid):
        reg = self.project.region(rid)
        if not reg:
            self.status(tr("Select a region first"))
            self._update_ui_state()
            return
        self.checkpoint()
        if reg.auto_arrange:  # freeze current grid positions so nothing jumps
            cw, ch = self.project.cell()
            cols = grid_cols(reg.w, cw)
            for i, ref in enumerate(reg.images):
                ref.x, ref.y = grid_pos(i, cols, cw, ch)
        reg.auto_arrange = not reg.auto_arrange
        self.refresh()
        self.status(tr("Auto-Arrange ON for '{name}'" if reg.auto_arrange else "Auto-Arrange OFF for '{name}'",
                       name=reg.name))

    def duplicate_region(self, rid):
        reg = self.project.region(rid)
        if not reg:
            return
        self.checkpoint()
        dup = Region.from_dict(reg.to_dict(), new_ids=True)
        dup.name = self.project.unique_region_name(tr("{name} copy", name=reg.name))
        r = self._region_display_rect(reg)
        dup.x, dup.y = reg.x, r.bottom() + 40
        self.project.regions.append(dup)
        self.refresh()
        self.activate_region(dup.id)

    def clear_region(self, rid):
        reg = self.project.region(rid)
        if not reg or not reg.images:
            return
        locked = sum(1 for r in reg.images if r.locked)
        keep_locked = False
        if locked:
            b = QMessageBox.question(
                self, tr("Clear Region"),
                tr("'{name}' has {n} locked image(s).\n\nYes = remove everything\nNo = remove only unlocked images",
                   name=reg.name, n=locked), QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
            if b == QMessageBox.Cancel:
                return
            keep_locked = b == QMessageBox.No
        self.checkpoint()
        reg.images = [r for r in reg.images if keep_locked and r.locked]
        self.refresh()
        self.status(tr("Region cleared (source files untouched). Ctrl+Z to undo."))

    def delete_region(self, rid):
        reg = self.project.region(rid)
        if not reg:
            return
        if reg.images and QMessageBox.question(
                self, tr("Delete Region"),
                tr("Delete region '{name}' and its {n} image reference(s)?\nSource files on disk are NOT touched. "
                   "(Undo: Ctrl+Z)", name=reg.name, n=len(reg.images))) != QMessageBox.Yes:
            return
        self.checkpoint()
        self.project.regions.remove(reg)
        self.refresh()

    def toggle_region_scroll(self, rid):
        """Open item (spec §38): fixed region height with scrolling inside."""
        reg = self.project.region(rid)
        if not reg:
            return
        self.checkpoint()
        if not reg.scroll_enabled:
            _, ch = self.project.cell()
            reg.h = min(self._region_display_rect(reg).height(), TITLE_H + 2 * PAD + 2.2 * ch)
            reg.scroll = 0.0
        reg.scroll_enabled = not reg.scroll_enabled
        self.refresh()
        self.status(tr("Scrolling inside '{name}': Shift+Wheel or the scrollbar on the right", name=reg.name)
                    if reg.scroll_enabled else tr("'{name}' grows with its images again", name=reg.name))

    def toggle_collapse(self, rid):
        reg = self.project.region(rid)
        if reg:
            self.checkpoint()
            reg.collapsed = not reg.collapsed
            if reg.collapsed:
                self.canvas.set_selection([i for i in self.canvas.selected_ids() if not reg.get(i)])
            self.refresh()

    def collapse_all(self, collapsed: bool):
        self.checkpoint()
        for r in self.project.regions:
            r.collapsed = collapsed
        if collapsed:
            self.canvas.clear_selection()
        self.refresh()

    def lock_region(self, rid, locked: bool):
        reg = self.project.region(rid)
        if reg:
            self.checkpoint()
            for r in reg.images:
                r.locked = locked
            self.refresh()
            self.status(tr("Locked all {n} images in '{name}'" if locked else "Unlocked all {n} images in '{name}'",
                           n=len(reg.images), name=reg.name))

    def arrange_regions(self, mode: str, only_selected: bool = False):
        regs = list(self.project.regions)
        if only_selected:
            regs = [r for r in regs if r.id in self.selected_region_ids]
            if len(regs) < 2:
                self.status(tr("Ctrl+click two or more region titles first"))
                return
        if not regs:
            return
        self.checkpoint()
        self.canvas.sync()  # sizes must be current (a region may just have been resized)
        rects = {r.id: self._region_display_rect(r) for r in regs}
        x0 = min(r.x for r in regs)
        y0 = min(r.y for r in regs)
        sp = 40
        if mode == "h":
            regs.sort(key=lambda r: (r.x, r.y))
            x = x0
            for r in regs:
                r.x, r.y = x, y0
                x += rects[r.id].width() + sp
        elif mode == "v":
            regs.sort(key=lambda r: (r.y, r.x))
            y = y0
            for r in regs:
                r.x, r.y = x0, y
                y += rects[r.id].height() + sp
        else:
            regs.sort(key=lambda r: (r.y, r.x))
            cols = max(1, round(len(regs) ** 0.5 + 0.49))
            y = y0
            for i in range(0, len(regs), cols):
                row = regs[i:i + cols]
                x = x0
                for r in row:
                    r.x, r.y = x, y
                    x += rects[r.id].width() + sp
                y += max(rects[r.id].height() for r in row) + sp
        self.refresh()
        self.canvas.fit_all()

    def regrid(self, rid):
        reg = self.project.region(rid)
        if not reg:
            return
        if reg.auto_arrange:
            self.status(tr("Auto-Arrange is ON: the region is already arranged"))
            return
        self.checkpoint()
        cw, ch = self.project.cell()
        cols = grid_cols(reg.w, cw)
        for i, ref in enumerate(reg.images):
            if not ref.locked:
                ref.x, ref.y = grid_pos(i, cols, cw, ch)
        self.refresh()

    def adopt_visual_order(self, rid):
        """Free mode: make the sequence follow reading order (top→bottom, left→right).
        Locked images keep their sequence positions."""
        reg = self.project.region(rid)
        if not reg:
            return
        if reg.auto_arrange:
            self.status(tr("Only meaningful with Auto-Arrange OFF"))
            return
        self.checkpoint()
        _, ch = self.project.cell()
        row_h = max(ch / 2, 1)
        free = sorted((r for r in reg.images if not r.locked), key=lambda r: (round(r.y / row_h), r.x))
        it = iter(free)
        reg.images = [r if r.locked else next(it) for r in reg.images]
        self.refresh()
        self.status(tr("Sequence now follows the visual reading order"))

    def fit_region(self, rid):
        reg = self.project.region(rid)
        if reg:
            self.canvas.fit_rect(self._region_display_rect(reg))

    def fit_active_region(self):
        self.fit_region(self.active_region_id)

    def set_thumb_size(self, s: int):
        s = min(max(int(s), THUMB_MIN), THUMB_MAX)
        if s != self.project.thumb_size:
            self.project.thumb_size = s
            self.refresh()

    def _toggle_view(self, attr: str):
        setattr(self.project, attr, not getattr(self.project, attr))
        self.refresh()

    # =============================================================== import
    def resolve_import_target(self, region_id=None, create_at: QPointF | None = None) -> Region:
        """Open item (spec §7 / §38): where imports go.

        Prototype rule: explicit region → active region → (canvas context
        menu) a new region at the click → otherwise a region named
        'Unsorted', created on demand.
        """
        reg = self.project.region(region_id) or self.project.region(self.active_region_id)
        if reg:
            return reg
        if create_at is not None:
            return self._make_region(create_at, self.project.unique_region_name(tr("Imported")))
        for r in self.project.regions:
            if r.name in ("Unsorted", tr("Unsorted")):
                return r
        return self._make_region(None, tr("Unsorted"), PRESET_COLORS[2][1])

    def _pick_aspect(self, files: list[str]):
        """First import into an empty project: thumbnail shape follows the images
        (portrait NovelAI images get 2:3, screenshots 16:9...). Reads headers only."""
        ratios = []
        for f in files[:40]:
            size = QImageReader(f).size()
            if size.isValid() and size.height() > 0:
                ratios.append(size.width() / size.height())
        if ratios:
            ratios.sort()
            self.project.thumb_aspect = closest_aspect(ratios[len(ratios) // 2])
            self.project.aspect_auto = False

    def import_dialog(self, multiple: bool):
        start = self.settings.value("dirs/import", "")
        if multiple:
            files, _ = QFileDialog.getOpenFileNames(self, tr("Import Images"), start, image_filter())
        else:
            f, _ = QFileDialog.getOpenFileName(self, tr("Import Image"), start, image_filter())
            files = [f] if f else []
        if files:
            self.settings.setValue("dirs/import", os.path.dirname(files[0]))
            self.import_paths(files)

    def import_folder_dialog(self, recursive: bool, create_at: QPointF | None = None):
        d = QFileDialog.getExistingDirectory(self, tr("Import Folder"), self.settings.value("dirs/import", ""))
        if d:
            self.settings.setValue("dirs/import", d)
            self.import_paths([d], recursive=recursive, create_at=create_at)

    def import_paths(self, paths: list[str], region_id=None, index: int | None = None,
                     recursive: bool = False, create_at: QPointF | None = None):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            files = fileops.expand_paths(paths, recursive)
        finally:
            QApplication.restoreOverrideCursor()
        if not files:
            self.status(tr("No supported images found"))
            return
        self.checkpoint()
        if self.project.aspect_auto and self.project.image_count() == 0:
            self._pick_aspect(files)
        reg = self.resolve_import_target(region_id, create_at)
        existing = {norm_path(r.path) for r in reg.images}
        new = [ImageRef(f) for f in files if norm_path(f) not in existing]
        skipped = len(files) - len(new)
        if not new:
            self.undo_stack.pop()
            self.refresh()
            self.status(tr("All {n} image(s) are already in '{name}'", n=skipped, name=reg.name))
            return
        if not reg.auto_arrange:
            cw, ch = self.project.cell()
            for ref, (x, y) in zip(new, reg.free_spot_positions(len(new), cw, ch)):
                ref.x, ref.y = x, y
        at = reg.insert(new, index)
        if reg.collapsed:
            reg.collapsed = False
        self.active_region_id = None
        self.refresh()
        self.activate_region(reg.id)
        self.canvas.set_selection([r.id for r in new])
        msg = tr("Imported {n} image(s) into '{name}' at position {pos}", n=len(new), name=reg.name, pos=at + 1)
        if skipped:
            msg += tr(" — {n} already present, skipped", n=skipped)
        if index is not None and at != index:
            msg += tr(" — placed after locked images")
        self.status(msg, 10000)

    # ============================================================ clipboard
    def copy_selection(self):
        refs = self.selected_refs()
        if not refs:
            self.status(tr("Nothing selected"))
            return
        if self.cut_ids:
            self.cut_ids = set()
            self.refresh()
        self.clipboard = {"mode": "copy", "items": [r.to_dict() for _, r in refs], "ids": []}
        self.status(tr("Copied {n} image(s)", n=len(refs)))

    def cut_selection(self):
        refs = self.selected_refs()
        movable = [r for _, r in refs if not r.locked]
        if not movable:
            self.status(tr("Nothing to cut (locked images can't be cut)"))
            return
        self.clipboard = {"mode": "cut", "items": [r.to_dict() for r in movable],
                          "ids": [r.id for r in movable]}
        self.cut_ids = set(self.clipboard["ids"])
        self.refresh()
        extra = tr(" ({n} locked skipped)", n=len(refs) - len(movable)) if len(movable) < len(refs) else ""
        self.status(tr("Cut {n} image(s){extra} — select a region and press Ctrl+V", n=len(movable), extra=extra))

    def paste(self, region_id=None, after_ref: str | None = None, create_at: QPointF | None = None):
        clip = self.clipboard
        if not clip:
            md = QApplication.clipboard().mimeData()
            if md is not None and md.hasUrls():  # files copied in Explorer
                paths = [u.toLocalFile() for u in md.urls() if u.isLocalFile()]
                if paths:
                    self.import_paths(paths, region_id, create_at=create_at)
                    return
            self.status(tr("Clipboard is empty"))
            return
        self.checkpoint()
        target = self.resolve_import_target(region_id, create_at)
        # insertion point: after the given image, else after the last selected image of the target
        anchor = after_ref
        if anchor is None and target.auto_arrange:
            sel = [ref.id for ref in target.images if ref.id in set(self.canvas.selected_ids())]
            anchor = sel[-1] if sel else None
        moving: list[ImageRef] = []
        if clip["mode"] == "cut":
            ids = set(clip["ids"])
            while anchor in ids:  # anchor itself is being moved: use the image before it
                i = target.index_of(anchor)
                anchor = target.images[i - 1].id if i > 0 else None
            for reg in self.project.regions:
                moving += [r for r in reg.images if r.id in ids and not r.locked]
                reg.images = [r for r in reg.images if not (r.id in ids and not r.locked)]
            if not moving:  # originals gone (e.g. undone) - paste as copies
                moving = [ImageRef.from_dict(d, new_ids=True) for d in clip["items"]]
            self.clipboard, self.cut_ids = None, set()
        else:
            moving = [ImageRef.from_dict(d, new_ids=True) for d in clip["items"]]
        for r in moving:
            r.locked = False
        if not target.auto_arrange:
            cw, ch = self.project.cell()
            for ref, (x, y) in zip(moving, target.free_spot_positions(len(moving), cw, ch)):
                ref.x, ref.y = x, y
        index = target.index_of(anchor) + 1 if anchor and target.index_of(anchor) >= 0 else None
        at = target.insert(moving, index)
        if target.collapsed:
            target.collapsed = False
        self.active_region_id = None
        self.refresh()
        self.activate_region(target.id)
        self.canvas.set_selection([r.id for r in moving])
        self.status(tr("Pasted {n} image(s) into '{name}' at position {pos}", n=len(moving), name=target.name,
                       pos=at + 1))

    def remove_selection(self):
        refs = self.selected_refs()
        if not refs:
            return
        ids = {r.id for _, r in refs if not r.locked}
        locked = len(refs) - len(ids)
        if not ids:
            self.status(tr("Selected images are locked — unlock them to remove"))
            return
        self.checkpoint()
        for reg in self.project.regions:
            reg.remove(ids)
        self.cut_ids -= ids
        self.refresh()
        self.status(tr("Removed {n} image reference(s) from the project (files untouched){extra}. Ctrl+Z to undo.",
                       n=len(ids), extra=tr("; {n} locked kept", n=locked) if locked else ""))

    def move_or_copy_to(self, region_id: str | None, copy_: bool):
        refs = self.selected_refs()
        if not refs:
            return
        self.checkpoint()
        target = self.project.region(region_id) or self._make_region(None)
        if copy_:
            items = [r.clone() for _, r in refs]
        else:
            items = [r for _, r in refs if not r.locked]
            ids = {r.id for r in items}
            for reg in self.project.regions:
                reg.remove(ids)
        if not target.auto_arrange:
            cw, ch = self.project.cell()
            for ref, (x, y) in zip(items, target.free_spot_positions(len(items), cw, ch)):
                ref.x, ref.y = x, y
        target.insert(items)
        self.refresh()
        self.canvas.set_selection([r.id for r in items])
        skipped = len(refs) - len(items)
        self.status(tr("Copied {n} image(s) to '{name}'{extra}" if copy_ else "Moved {n} image(s) to '{name}'{extra}",
                       n=len(items), name=target.name,
                       extra=tr(" ({n} locked stayed)", n=skipped) if skipped else ""))

    # ============================================================ drag drop
    def commit_drag(self, ids: list[str], target_id: str, slot: int | None,
                    positions: dict[str, tuple[float, float]], copy_: bool):
        target = self.project.region(target_id)
        refs = [self.project.find(i)[1] for i in ids]
        refs = [r for r in refs if r is not None]
        if target is None or not refs:
            self.refresh()
            return
        self.checkpoint()
        free = not target.auto_arrange
        if copy_:
            idset = set(ids)
            remaining = [r for r in target.images if r.id not in idset]
            index = None
            if slot is not None and not free:
                index = target.index_of(remaining[slot].id) if slot < len(remaining) else len(target.images)
            new = [r.clone() for r in refs]
            for n, r in zip(new, refs):
                n.x, n.y = positions.get(r.id, (r.x, r.y))
            target.insert(new, index)
            self.refresh()
            self.canvas.set_selection([r.id for r in new])
            self.status(tr("Copied {n} image(s) to '{name}'{extra}", n=len(new), name=target.name, extra=""))
            return
        if free and all(target.get(r.id) for r in refs):
            for r in refs:
                r.x, r.y = positions.get(r.id, (r.x, r.y))
        else:
            idset = {r.id for r in refs}
            for reg in self.project.regions:
                reg.remove(idset)
            for r in refs:
                r.x, r.y = positions.get(r.id, (r.x, r.y))
            at = target.insert(refs, None if free or slot is None else slot)
            if slot is not None and not free and at != slot:
                self.status(tr("Locked images keep their place — inserted after them"))
        self.refresh()

    # ================================================================ locks
    def set_locked(self, locked: bool):
        refs = self.selected_refs()
        if not refs:
            self.status(tr("Select images first (or use the region menu to lock a whole region)"))
            return
        self.checkpoint()
        for _, r in refs:
            r.locked = locked
        self.refresh()
        self.status(tr("Locked {n} image(s)" if locked else "Unlocked {n} image(s)", n=len(refs)))

    def toggle_lock_selection(self):
        refs = self.selected_refs()
        self.set_locked(not refs or not all(r.locked for _, r in refs))

    def lock_up_to_selection(self, region_id=None, ref_id: str | None = None):
        reg = self.project.region(region_id or self.active_region_id)
        sel = {ref_id} if ref_id else set(self.canvas.selected_ids())
        idx = [i for i, r in enumerate(reg.images) if r.id in sel] if reg else []
        if not idx:
            self.status(tr("Select the last confirmed image of a region first"))
            return
        self.checkpoint()
        n = reg.lock_up_to(reg.images[max(idx)].id)
        self.refresh()
        self.status(tr("Locked images 1–{n} of '{name}'", n=n, name=reg.name))

    # ======================================================== context menus
    def _mi(self, menu: QMenu, text: str, slot, ic: str | None = None, sc=None, color: str | None = None):
        """Menu entry with an icon and the shortcut shown on the right (display only)."""
        if sc is not None:
            seq = sc if isinstance(sc, QKeySequence) else QKeySequence(sc)
            text = f"{text}\t{seq.toString(QKeySequence.NativeText)}"
        a = menu.addAction(text, slot)
        if ic:
            a.setIcon(icon(ic, color or theme.current().icon, 16))
        return a

    def _region_submenu(self, parent: QMenu, title: str, copy_: bool, exclude: set[str], ic: str):
        sm = parent.addMenu(icon(ic, theme.current().icon, 16), title)
        for reg in self.project.regions:
            if reg.id in exclude and not copy_:
                continue
            a = sm.addAction(_swatch(reg.color), reg.name)
            a.triggered.connect(lambda _=False, rid=reg.id: self.move_or_copy_to(rid, copy_))
        sm.addSeparator()
        self._mi(sm, tr("New Region"), lambda: self.move_or_copy_to(None, copy_), "square-plus")

    def image_menu(self, gpos, ref_id: str):
        refs = self.selected_refs()
        n = len(refs)
        reg, ref = self.project.find(ref_id)
        if ref is None:
            return
        mi = self._mi
        m = QMenu(self)
        mi(m, tr("Open Large View"), lambda: self.open_viewer(ref_id), "maximize-2", tr("Double-click"))
        m.addSeparator()
        mi(m, tr("Cut ({n})", n=n), self.cut_selection, "scissors", QKeySequence.Cut)
        mi(m, tr("Copy ({n})", n=n), self.copy_selection, "copy", QKeySequence.Copy)
        mi(m, tr("Paste After This Image"), lambda: self.paste(reg.id, ref_id), "clipboard-paste", QKeySequence.Paste)
        m.addSeparator()
        mi(m, tr("Lock ({n})", n=n), lambda: self.set_locked(True), "lock", "Ctrl+L", "#f59e0b")
        mi(m, tr("Unlock ({n})", n=n), lambda: self.set_locked(False), "lock-open", "Ctrl+Shift+L")
        mi(m, tr("Lock Up To Here (Confirmed Portion)"), lambda: self.lock_up_to_selection(reg.id, ref_id), "lock")
        m.addSeparator()
        regions_of_sel = {g.id for g, _ in refs}
        self._region_submenu(m, tr("Move to Another Region"), False, regions_of_sel, "arrow-right-left")
        self._region_submenu(m, tr("Copy to Another Region"), True, set(), "copy-plus")
        m.addSeparator()
        mi(m, tr("Change Display Name…"), self.change_display_name, "tag")
        if n > 1:
            mi(m, tr("Rename Actual Files by Order ({n})…", n=n), self.bulk_rename_selection, "file-pen-line")
        else:
            mi(m, tr("Rename Actual File…"), lambda: self.rename_actual_file(ref_id), "file-pen-line")
        mi(m, tr("Move Actual File(s) to Folder ({n})…", n=n),
           lambda: self.move_actual_files([r.path for _, r in self.selected_refs()]), "folder-input")
        mi(m, tr("Open Source File Location"), lambda: self.reveal(ref_id), "folder-open")
        m.addSeparator()
        mi(m, tr("Remove from Current Region ({n})", n=n), self.remove_selection, "eraser", QKeySequence.Delete)
        da = mi(m, tr("Delete Actual Source File(s) ({n})…", n=n), self.delete_actual_files, "trash-2",
                color="#e05252")
        f = da.font()
        f.setBold(True)
        da.setFont(f)
        exec_menu(m, gpos)

    def region_menu(self, gpos, rid: str, scene_pt: QPointF):
        reg = self.project.region(rid)
        if reg is None:
            return
        mi = self._mi
        m = QMenu(self)
        mi(m, tr("Import Image(s)…"), lambda: self.import_dialog(True), "image-plus", "Ctrl+I")
        mi(m, tr("Import Folder…"), lambda: self.import_folder_dialog(False), "folder-plus", "Ctrl+Shift+I",
           "#f59e0b")
        mi(m, tr("Paste"), lambda: self.paste(rid), "clipboard-paste", QKeySequence.Paste)
        mi(m, tr("Select All in Region"), lambda: self.canvas.set_selection([r.id for r in reg.images]),
           "list-checks", QKeySequence.SelectAll)
        m.addSeparator()
        mi(m, tr("Rename Region…"), lambda: self.rename_region(rid), "pencil", "F2")
        cm = m.addMenu(icon("palette", "#8b5cf6", 16), tr("Region Color"))
        self._fill_color_menu(cm, rid)
        a = mi(m, tr("Auto-Arrange"), lambda: self.toggle_auto(rid), "arrow-down-up", "Ctrl+E", "#3b82f6")
        a.setCheckable(True)
        a.setChecked(reg.auto_arrange)
        a = mi(m, tr("Scroll Inside Region (fixed height)"), lambda: self.toggle_region_scroll(rid), "scroll-text")
        a.setCheckable(True)
        a.setChecked(reg.scroll_enabled)
        mi(m, tr("Expand") if reg.collapsed else tr("Collapse"), lambda: self.toggle_collapse(rid),
           "chevrons-up-down" if reg.collapsed else "chevrons-down-up")
        mi(m, tr("Fit Selected Region"), lambda: self.fit_region(rid), "maximize-2", "Ctrl+9")
        m.addSeparator()
        mi(m, tr("Lock Selected Images"), lambda: self.set_locked(True), "lock", "Ctrl+L", "#f59e0b")
        mi(m, tr("Lock Current Organized Portion (up to last selected)"), lambda: self.lock_up_to_selection(rid),
           "lock")
        mi(m, tr("Lock Entire Region"), lambda: self.lock_region(rid, True), "lock")
        mi(m, tr("Unlock All"), lambda: self.lock_region(rid, False), "lock-open")
        m.addSeparator()
        if not reg.auto_arrange:
            mi(m, tr("Arrange Images Inside Region (grid)"), lambda: self.regrid(rid), "layout-grid")
            mi(m, tr("Set Order from Visual Position"), lambda: self.adopt_visual_order(rid), "rows-3")
            m.addSeparator()
        mi(m, tr("Save Region…"), lambda: self.save_region(rid), "save", color="#4f6bed")
        mi(m, tr("Duplicate Region"), lambda: self.duplicate_region(rid), "copy-plus")
        mi(m, tr("Rename Actual Files by Order…"), lambda: self.bulk_rename_region(rid), "file-pen-line")
        mi(m, tr("Move Actual Files of Region to Folder…"),
           lambda: self.move_actual_files([r.path for r in reg.images]), "folder-input")
        m.addSeparator()
        mi(m, tr("Clear Region…"), lambda: self.clear_region(rid), "eraser")
        mi(m, tr("Delete Region…"), lambda: self.delete_region(rid), "trash-2", color="#e05252")
        exec_menu(m, gpos)

    def canvas_menu(self, gpos, scene_pt: QPointF):
        mi = self._mi
        m = QMenu(self)
        mi(m, tr("New Region Here"), lambda: self.new_region(scene_pt), "square-plus", "Ctrl+R", "#10b981")
        mi(m, tr("Load Saved Region Here…"), lambda: self.load_region(scene_pt), "folder-input")
        mi(m, tr("Paste (into a new region here)"), lambda: self.paste(None, None, scene_pt)
           if self.clipboard or QApplication.clipboard().mimeData().hasUrls()
           else self.status(tr("Clipboard is empty")), "clipboard-paste", QKeySequence.Paste)
        mi(m, tr("Import Image(s) (new region here)…"), lambda: self._import_new_region(scene_pt), "image-plus")
        mi(m, tr("Import Folder (new region here)…"), lambda: self.import_folder_dialog(False, scene_pt),
           "folder-plus", color="#f59e0b")
        m.addSeparator()
        mi(m, tr("Arrange Regions Horizontally"), lambda: self.arrange_regions("h"), "columns-3")
        mi(m, tr("Arrange Regions Vertically"), lambda: self.arrange_regions("v"), "rows-3")
        mi(m, tr("Arrange Regions as Grid"), lambda: self.arrange_regions("g"), "layout-grid")
        m.addSeparator()
        mi(m, tr("Fit All to Screen"), self.canvas.fit_all, "scan", "Ctrl+0")
        mi(m, tr("Collapse All Regions"), lambda: self.collapse_all(True), "chevrons-down-up")
        mi(m, tr("Expand All Regions"), lambda: self.collapse_all(False), "chevrons-up-down")
        exec_menu(m, gpos)

    def _import_new_region(self, at: QPointF):
        files, _ = QFileDialog.getOpenFileNames(self, tr("Import Images"), self.settings.value("dirs/import", ""),
                                                image_filter())
        if files:
            self.settings.setValue("dirs/import", os.path.dirname(files[0]))
            self.import_paths(files, create_at=at)

    # ===================================================== image commands
    def open_viewer(self, ref_id: str):
        reg, ref = self.project.find(ref_id)
        if ref is None:
            return
        items = [(r.path, r.display_name) for r in reg.images]
        dlg = ImageViewer(self, items, reg.index_of(ref_id))
        dlg.exec()
        self.canvas.setFocus()

    def change_display_name(self):
        refs = [r for _, r in self.selected_refs()]
        if not refs:
            return
        if len(refs) == 1:
            name, ok = QInputDialog.getText(self, tr("Display Name"),
                                            tr("Display name (internal only, the file is not renamed):"),
                                            text=refs[0].display_name)
            if ok and name.strip():
                self.checkpoint()
                refs[0].display_name = name.strip()
                self.refresh()
            return
        base, ok = QInputDialog.getText(self, tr("Display Names"),
                                        tr("Prefix for {n} images (numbered in order; files untouched):", n=len(refs)))
        if ok and base.strip():
            self.checkpoint()
            for i, r in enumerate(refs, 1):
                r.display_name = f"{base.strip()} {i:03d}"
            self.refresh()

    def reveal(self, ref_id: str):
        _, ref = self.project.find(ref_id)
        if ref and os.path.exists(ref.path):
            fileops.reveal_in_explorer(ref.path)
        elif ref:
            self.status(tr("File not found: {path}", path=ref.path))

    def _after_fs_rename(self, pairs: list[tuple[str, str]], what: str):
        mapping = {norm_path(o): n for o, n in pairs}
        self.project.remap_paths(mapping)
        self._remap_history(mapping)
        for o, n in pairs:
            self.thumbs.rename(o, n)
        self.set_dirty()
        self.refresh()
        if self.project_path:
            self._write_project(self.project_path)
            self.status(tr("{what}; project saved so it points to the new file paths", what=what), 10000)
        else:
            QMessageBox.information(self, what, tr("{what}.\n\nThis project has never been saved. Save it now so it "
                                                   "points to the new file paths.", what=what))
            self.save_as()

    def rename_actual_file(self, ref_id: str):
        _, ref = self.project.find(ref_id)
        if ref is None or not os.path.exists(ref.path):
            self.status(tr("Source file not found"))
            return
        old = ref.path
        name, ok = QInputDialog.getText(self, tr("Rename Actual File"),
                                        tr("New file name for\n{path}\n(this renames the file on disk):", path=old),
                                        text=os.path.basename(old))
        if not ok or not name.strip() or name.strip() == os.path.basename(old):
            return
        try:
            new = fileops.rename_single(old, name.strip())
        except OSError as e:
            QMessageBox.critical(self, tr("Rename failed"), str(e))
            return
        fileops.write_rename_log(os.path.join(self.data_dir, "rename_logs"), [(old, new)])
        self._after_fs_rename([(old, new)], tr("File renamed"))

    def bulk_rename_region(self, rid):
        reg = self.project.region(rid)
        if not reg or not reg.images:
            self.status(tr("Select a region with images first"))
            return
        self._bulk_rename(reg.name, [r.path for r in reg.images])

    def bulk_rename_selection(self):
        refs = self.selected_refs()
        if refs:
            self._bulk_rename(refs[0][0].name, [r.path for _, r in refs])

    def _bulk_rename(self, region_name: str, paths: list[str]):
        dlg = BulkRenameDialog(self, region_name, paths)
        if dlg.exec() != BulkRenameDialog.Accepted:
            return
        try:
            pairs = fileops.apply_rename(dlg.entries)
        except Exception as e:  # noqa: BLE001 - surface any filesystem error
            QMessageBox.critical(self, tr("Rename failed"), tr("Nothing was renamed (rolled back).\n\n{err}", err=e))
            return
        if pairs:
            fileops.write_rename_log(os.path.join(self.data_dir, "rename_logs"), pairs)
            self._after_fs_rename(pairs, tr("Renamed {n} file(s)", n=len(pairs)))

    def _confirm(self, title: str, text: str, ok_label: str, destructive: bool = False) -> bool:
        box = QMessageBox(QMessageBox.Warning, title, text, QMessageBox.Cancel, self)
        ok = box.addButton(ok_label, QMessageBox.DestructiveRole if destructive else QMessageBox.AcceptRole)
        box.setDefaultButton(QMessageBox.Cancel)
        box.exec()
        return box.clickedButton() is ok

    def move_actual_files(self, paths: list[str], dest: str | None = None):
        """Move source files on disk into another folder (file names kept)."""
        paths = list(dict.fromkeys(paths))
        if not paths:
            return
        if dest is None:
            dest = QFileDialog.getExistingDirectory(self, tr("Move {n} file(s) to folder", n=len(paths)),
                                                    self.settings.value("dirs/move", os.path.dirname(paths[0])))
            if not dest:
                return
            self.settings.setValue("dirs/move", dest)
        entries = fileops.plan_move(paths, dest)
        ok = [e for e in entries if e.will_rename]
        skipped = {k: [e for e in entries if e.status == k] for k in ("conflict", "missing", "unchanged")}
        if not ok:
            labels = {"conflict": "{n} with a name conflict", "missing": "{n} missing", "unchanged": "{n} already there"}
            self.status(tr("Nothing to move: {detail}",
                           detail=", ".join(tr(labels[k], n=len(v)) for k, v in skipped.items() if v)))
            return
        listing = "\n".join(os.path.basename(e.old) for e in ok[:12]) + ("\n…" if len(ok) > 12 else "")
        notes = ""
        if skipped["conflict"]:
            notes += tr("\n\n{n} file(s) are SKIPPED because a file with the same name already exists there "
                        "(nothing is overwritten):\n", n=len(skipped["conflict"])) + \
                "\n".join(os.path.basename(e.old) for e in skipped["conflict"][:8])
        if skipped["missing"]:
            notes += tr("\n\n{n} missing file(s) skipped.", n=len(skipped["missing"]))
        if not self._confirm(tr("Move Actual Files"),
                             tr("Move {n} file(s) on disk to\n{dest}\n\n{listing}{notes}\n\nEvery reference in this "
                                "project follows the files. File → Revert Last File Rename/Move undoes it.",
                                n=len(ok), dest=dest, listing=listing, notes=notes), tr("Move Files")):
            return
        try:
            pairs = fileops.apply_move(entries)
        except Exception as e:  # noqa: BLE001 - surface any filesystem error
            QMessageBox.critical(self, tr("Move failed"), tr("Nothing was moved (rolled back).\n\n{err}", err=e))
            return
        fileops.write_rename_log(os.path.join(self.data_dir, "rename_logs"), pairs)
        self._after_fs_rename(pairs, tr("Moved {n} file(s) to {dest}", n=len(pairs), dest=dest))

    def revert_last_rename(self):
        log = fileops.latest_rename_log(os.path.join(self.data_dir, "rename_logs"))
        if not log:
            self.status(tr("No rename/move log found"))
            return
        if QMessageBox.question(self, tr("Revert Last File Rename/Move"),
                                tr("Put the files from\n{log}\nback to their old names/folders?",
                                   log=os.path.basename(log))) \
                != QMessageBox.Yes:
            return
        try:
            reverted, problems = fileops.revert_rename_log(log)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, tr("Revert failed"), str(e))
            return
        if problems:
            QMessageBox.warning(self, tr("Revert"), tr("Some files were not reverted:\n") + "\n".join(problems[:20]))
        if reverted:
            self._after_fs_rename(reverted, tr("Reverted {n} file name(s)", n=len(reverted)))

    def delete_actual_files(self):
        refs = self.selected_refs()
        paths = list(dict.fromkeys(r.path for _, r in refs))
        if not paths:
            return
        others = sum(1 for _, r in self.project.all_refs() if r.path in set(paths)) - len(refs)
        listing = "\n".join(os.path.basename(p) for p in paths[:12]) + ("\n…" if len(paths) > 12 else "")
        extra = tr(" (including {n} copy/copies in other regions)", n=others) if others > 0 else ""
        if not self._confirm(tr("Delete Actual Source Files"),
                             tr("Move {n} file(s) on disk to the Recycle Bin?\n\n{listing}\n\n"
                                "All references to these files in this project are removed{extra}.",
                                n=len(paths), listing=listing, extra=extra),
                             tr("Move to Recycle Bin"), destructive=True):
            return
        failed = []
        deleted = set()
        for p in paths:
            if fileops.move_to_trash(p):
                deleted.add(p)
            else:
                failed.append(p)
        if deleted:
            self.checkpoint()
            for reg in self.project.regions:
                reg.images = [r for r in reg.images if r.path not in deleted]
            self.refresh()
        if failed:
            QMessageBox.warning(self, tr("Delete"), tr("Could not move to Recycle Bin (left untouched):\n")
                                + "\n".join(failed[:20]))
        self.status(tr("Moved {n} file(s) to the Recycle Bin", n=len(deleted)))

    def relink_missing(self):
        missing = [r for _, r in self.project.all_refs() if not os.path.exists(r.path)]
        if not missing:
            self.status(tr("No missing images"))
            return
        d = QFileDialog.getExistingDirectory(self, tr("Find {n} missing image(s) in folder…", n=len(missing)))
        if not d:
            return
        found = fileops.find_by_basename(d, {os.path.basename(r.path).lower() for r in missing})
        hits = [r for r in missing if os.path.basename(r.path).lower() in found]
        if not hits:
            self.status(tr("No matching file names found there"))
            return
        self.checkpoint()
        for r in hits:
            r.path = found[os.path.basename(r.path).lower()]
        self.thumbs.recheck_missing()
        self.refresh()
        self.status(tr("Relinked {n} of {total} missing image(s)", n=len(hits), total=len(missing)))

    # ============================================================== saving
    def _write_project(self, path: str) -> bool:
        c = self.canvas.view_center()
        self.project.view = {"cx": c.x(), "cy": c.y(), "zoom": self.canvas.zoom()}
        data = self.project.to_dict(os.path.dirname(os.path.abspath(path)))
        data["ui"] = {"active_region": self.active_region_id}
        try:
            save_json_atomic(path, data)
        except OSError as e:
            QMessageBox.critical(self, tr("Save failed"), tr("Could not save:\n{path}\n\n{err}", path=path, err=e))
            return False
        self.project_path = path
        self.dirty = False
        self._add_recent(path)
        self.update_title()
        self.status(tr("Saved {path}", path=path))
        return True

    def save(self) -> bool:
        self.canvas.cancel_interaction()
        if not self.project_path:
            return self.save_as()
        return self._write_project(self.project_path)

    def save_as(self) -> bool:
        start = self.project_path or os.path.join(self.settings.value("dirs/project", ""), tr("Untitled") + PROJECT_EXT)
        path, _ = QFileDialog.getSaveFileName(self, tr("Save Project As"), start, project_filter())
        if not path:
            return False
        if not path.lower().endswith(PROJECT_EXT):
            path += PROJECT_EXT
        self.settings.setValue("dirs/project", os.path.dirname(path))
        return self._write_project(path)

    def maybe_save(self) -> bool:
        if not self.dirty:
            return True
        b = QMessageBox.question(self, APP_NAME, tr("Save changes to the current project?"),
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if b == QMessageBox.Save:
            return self.save()
        return b == QMessageBox.Discard

    def _reset(self, project: Project, path: str | None):
        self.project = project
        self.project_path = path
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.clipboard = None if (self.clipboard and self.clipboard["mode"] == "cut") else self.clipboard
        self.cut_ids = set()
        self.active_region_id = None
        self.selected_region_ids = set()
        self.dirty = False
        self.thumbs.recheck_missing()
        self.canvas.clear_selection()
        self.refresh()
        v = project.view
        if v.get("zoom"):
            self.canvas.set_zoom(float(v["zoom"]), QPointF(float(v.get("cx", 0)), float(v.get("cy", 0))))
        else:
            self.canvas.fit_all()

    def new_project(self):
        if self.maybe_save():
            self._reset(Project(), None)
            self.status(tr("New project"))

    def open_project(self, path: str | None = None):
        if not self.maybe_save():
            return
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, tr("Open Project"), self.settings.value("dirs/project", ""),
                                                  project_filter() + ";;" + tr("All files (*)"))
            if not path:
                return
        try:
            data = load_json(path)
            project = Project.from_dict(data, os.path.dirname(os.path.abspath(path)))
        except (OSError, ValueError, KeyError) as e:
            QMessageBox.critical(self, tr("Open failed"), tr("Could not open:\n{path}\n\n{err}", path=path, err=e))
            return
        self.settings.setValue("dirs/project", os.path.dirname(path))
        self._reset(project, path)
        self._add_recent(path)
        active = data.get("ui", {}).get("active_region")
        if project.region(active):
            self.activate_region(active)
        self._report_missing(tr("Opened {name}", name=os.path.basename(path)))

    def _report_missing(self, prefix: str):
        n = sum(1 for _, r in self.project.all_refs() if not os.path.exists(r.path))
        self.status(prefix + (tr(" — {n} image file(s) missing: File → Relink Missing Images", n=n) if n else ""),
                    12000)

    def save_region(self, rid):
        reg = self.project.region(rid)
        if not reg:
            self.status(tr("Select a region first"))
            return
        start = os.path.join(self.settings.value("dirs/region", self.settings.value("dirs/project", "")),
                             fileops.sanitize_filename(reg.name) + REGION_EXT)
        path, _ = QFileDialog.getSaveFileName(self, tr("Save Region '{name}'", name=reg.name), start, region_filter())
        if not path:
            return
        if not path.lower().endswith(REGION_EXT):
            path += REGION_EXT
        self.settings.setValue("dirs/region", os.path.dirname(path))
        try:
            save_json_atomic(path, region_file_dict(reg, os.path.dirname(os.path.abspath(path))))
        except OSError as e:
            QMessageBox.critical(self, tr("Save failed"), str(e))
            return
        self.status(tr("Saved region '{name}' to {path}", name=reg.name, path=path))

    def load_region(self, at: QPointF | None = None):
        path, _ = QFileDialog.getOpenFileName(self, tr("Load Saved Region"), self.settings.value("dirs/region", ""),
                                              region_filter() + ";;" + tr("All files (*)"))
        if not path:
            return
        self.settings.setValue("dirs/region", os.path.dirname(path))
        try:
            reg = region_from_file_dict(load_json(path), os.path.dirname(os.path.abspath(path)))
        except (OSError, ValueError, KeyError) as e:
            QMessageBox.critical(self, tr("Load failed"), tr("Could not load region:\n{path}\n\n{err}", path=path, err=e))
            return
        self.checkpoint()
        p = at if at is not None else self._free_region_spot(reg.w, reg.h)
        reg.x, reg.y = p.x(), p.y()
        self.project.regions.append(reg)
        self.thumbs.recheck_missing()
        self.active_region_id = None
        self.refresh()
        self.activate_region(reg.id)
        self.canvas.ensureVisible(self._region_display_rect(reg), 40, 40)
        self._report_missing(tr("Loaded region '{name}' ({n} images)", name=reg.name, n=len(reg.images)))

    # ---------------------------------------------------------------- recent
    def _add_recent(self, path: str):
        rec = [p for p in (self.settings.value("recent", []) or []) if p != path]
        if isinstance(rec, str):
            rec = [rec]
        self.settings.setValue("recent", [path] + rec[:9])

    def _fill_recent(self):
        self.recent_menu.clear()
        rec = self.settings.value("recent", []) or []
        if isinstance(rec, str):
            rec = [rec]
        for p in rec:
            a = self.recent_menu.addAction(p)
            a.setEnabled(os.path.exists(p))
            a.triggered.connect(lambda _=False, path=p: self.open_project(path))
        if not rec:
            self.recent_menu.addAction(tr("(none)")).setEnabled(False)

    # -------------------------------------------------------------- autosave
    def autosave_path(self) -> str:
        return os.path.join(self.data_dir, "autosave", "autosave" + PROJECT_EXT)

    def lock_path(self) -> str:
        return os.path.join(self.data_dir, "session.lock")

    def apply_autosave_settings(self):
        on = self.settings.value("autosave/on", True, type=bool)
        mins = int(self.settings.value("autosave/minutes", AUTOSAVE_DEFAULT_MIN))
        self.autosave_timer.stop()
        if on:
            self.autosave_timer.start(max(1, mins) * 60_000)

    def autosave(self):
        if not self._dirty_since_autosave:
            return
        data = self.project.to_dict(None)
        data["autosave_meta"] = {"source_path": self.project_path, "time": time.time()}
        try:
            os.makedirs(os.path.dirname(self.autosave_path()), exist_ok=True)
            save_json_atomic(self.autosave_path(), data, keep_backup=False)
            self._dirty_since_autosave = False
            self.status(tr("Autosaved"), 2500)
        except OSError as e:
            self.status(tr("Autosave failed: {err}", err=e))

    def preferences(self):
        dlg = PreferencesDialog(self, self.settings.value("autosave/on", True, type=bool),
                                int(self.settings.value("autosave/minutes", AUTOSAVE_DEFAULT_MIN)))
        if dlg.exec():
            self.settings.setValue("autosave/on", dlg.autosave.isChecked())
            self.settings.setValue("autosave/minutes", dlg.interval.value())
            self.apply_autosave_settings()

    def _startup(self):
        crashed = os.path.exists(self.lock_path())
        try:
            with open(self.lock_path(), "w") as f:
                f.write(str(os.getpid()))
        except OSError:
            pass
        ap = self.autosave_path()
        if crashed and os.path.exists(ap):
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(ap)))
            if QMessageBox.question(self, tr("Restore Autosave"),
                                    tr("{app} did not shut down normally last time.\n\nRestore the autosave from {when}?",
                                       app=APP_NAME, when=when)) == QMessageBox.Yes:
                try:
                    data = load_json(ap)
                    self._reset(Project.from_dict(data), data.get("autosave_meta", {}).get("source_path"))
                    self.set_dirty()
                    self._report_missing(tr("Restored from autosave — save to keep it"))
                    return
                except (OSError, ValueError, KeyError) as e:
                    QMessageBox.warning(self, tr("Restore failed"), str(e))
        if self._open_path:
            self.open_project(self._open_path)

    def closeEvent(self, e):
        self.canvas.cancel_interaction()
        if not self.maybe_save():
            e.ignore()
            return
        self.settings.setValue("window/geometry", self.saveGeometry())
        try:
            os.remove(self.lock_path())
        except OSError:
            pass
        e.accept()

