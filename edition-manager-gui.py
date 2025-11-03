import os
import sys
import re
import configparser
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

APP_TITLE = "Edition Manager"
APP_VERSION = "v1.8.2 - Visual Update"
PRIMARY_SCRIPT = "edition-manager.py"
CONFIG_FILE = str(Path(__file__).parent / "config" / "config.ini")

DEFAULT_MODULES = [
    "Resolution", "Duration", "Rating", "Cut", "Release", "DynamicRange",
    "Country", "ContentRating", "Language", "AudioChannels", "Director",
    "Genre", "SpecialFeatures", "Studio", "AudioCodec", "Bitrate",
    "FrameRate", "Size", "Source", "VideoCodec",
]

# ---------------------------
# Light palette helper (no external themes)
# ---------------------------

def apply_light_palette(app: QtWidgets.QApplication, primary_color: str = "#6750A4") -> None:
    app.setStyle("Fusion")  # modern, consistent base
    pal = QtGui.QPalette()
    pal.setColor(QtGui.QPalette.Window,        QtGui.QColor("#F6F6FA"))
    pal.setColor(QtGui.QPalette.WindowText,    QtGui.QColor(20, 18, 26))
    pal.setColor(QtGui.QPalette.Base,          QtGui.QColor("#FFFFFF"))
    pal.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor("#F4F4F8"))
    pal.setColor(QtGui.QPalette.ToolTipBase,   QtGui.QColor("#FFFFFF"))
    pal.setColor(QtGui.QPalette.ToolTipText,   QtGui.QColor(20, 18, 26))
    pal.setColor(QtGui.QPalette.Text,          QtGui.QColor(20, 18, 26))
    pal.setColor(QtGui.QPalette.Button,        QtGui.QColor("#FFFFFF"))
    pal.setColor(QtGui.QPalette.ButtonText,    QtGui.QColor(20, 18, 26))
    pal.setColor(QtGui.QPalette.BrightText,    QtCore.Qt.red)
    pal.setColor(QtGui.QPalette.Highlight,     QtGui.QColor(primary_color))  # primary
    pal.setColor(QtGui.QPalette.HighlightedText, QtGui.QColor("#FFFFFF"))
    app.setPalette(pal)

# ---------------------------
# Process worker
# ---------------------------
class ProcessWorker(QtCore.QObject):
    """Run the CLI and stream output."""
    started = QtCore.Signal()
    line = QtCore.Signal(str)
    progress = QtCore.Signal(int)
    finished = QtCore.Signal(int)

    def __init__(self, flag: str, parent=None):
        super().__init__(parent)
        self.flag = flag
        self.proc = QtCore.QProcess(self)
        self.proc.setProcessChannelMode(QtCore.QProcess.MergedChannels)
        # Hide extra console window on Windows for the spawned CLI process
        if sys.platform.startswith("win"):
            def _no_console(args):
                # CREATE_NO_WINDOW
                args["creationFlags"] = 0x08000000
            try:
                self.proc.setCreateProcessArgumentsModifier(_no_console)
            except Exception:
                pass
        self.proc.readyReadStandardOutput.connect(self._read)
        self.proc.finished.connect(self._done)

    def start(self):
        self.started.emit()
        python = sys.executable or "python3"
        script_path = str(Path(__file__).parent / PRIMARY_SCRIPT)
        if not os.path.exists(script_path):
            self.line.emit(f"Error: '{PRIMARY_SCRIPT}' not found next to GUI.")
            self.finished.emit(1)
            return
        args = [script_path, self.flag]
        self.line.emit("Running: {} {}".format(python, " ".join(args)))
        self.proc.start(python, args)

    @QtCore.Slot()
    def _read(self):
        data = self.proc.readAllStandardOutput().data().decode(errors="replace")
        for raw in data.splitlines():
            s = raw.rstrip("\n")
            self.line.emit(s)
            if s.startswith("PROGRESS "):
                try:
                    pct = int(s.split()[1])
                    pct = max(0, min(100, pct))
                    self.progress.emit(pct)
                except Exception:
                    pass

    @QtCore.Slot(int, QtCore.QProcess.ExitStatus)
    def _done(self, code: int, _status):
        self.finished.emit(code)

# ---------------------------
# Modules list
# ---------------------------
class ModulesList(QtWidgets.QListWidget):
    """Checkbox list with drag-to-reorder."""
    def __init__(self, modules: list[str], enabled_order: list[str], parent=None):
        super().__init__(parent)
        self.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QtWidgets.QAbstractItemView.InternalMove)
        self.setAlternatingRowColors(True)
        # Fill items: enabled first (in provided order), then the rest alpha
        enabled = [m for m in enabled_order if m in modules]
        disabled = [m for m in modules if m not in enabled]
        for m in enabled + disabled:
            it = QtWidgets.QListWidgetItem(m, self)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsDragEnabled | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            it.setCheckState(Qt.Checked if m in enabled else Qt.Unchecked)

    def enabled_modules_in_order(self) -> list[str]:
        out = []
        for i in range(self.count()):
            it = self.item(i)
            if it.checkState() == Qt.Checked:
                out.append(it.text())
        return out

# ---------------------------
# Settings dialog
# ---------------------------
class SettingsDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(720, 560)
        vbox = QtWidgets.QVBoxLayout(self)
        vbox.setContentsMargins(12, 12, 12, 12)
        
        # Header / App Bar (simple)
        header = QtWidgets.QLabel("Settings")
        header.setObjectName("SectionHeaderBig")
        vbox.addWidget(header)

        tabs = QtWidgets.QTabWidget()
        vbox.addWidget(tabs, 1)

        # Prepare config
        self.cfg = configparser.ConfigParser()
        if os.path.exists(CONFIG_FILE):
            self.cfg.read(CONFIG_FILE)
        for sec in ("server","modules","language","rating","performance","appearance"):
            if not self.cfg.has_section(sec):
                self.cfg.add_section(sec)

        # --- Server tab ---
        server = QtWidgets.QWidget(); tabs.addTab(server, "Server")
        form = QtWidgets.QFormLayout(server)
        form.setHorizontalSpacing(14); form.setVerticalSpacing(8)
        self.server_address = QtWidgets.QLineEdit(self.cfg.get("server","address", fallback=""))
        self.server_token = QtWidgets.QLineEdit(self.cfg.get("server","token", fallback=""))
        self.server_token.setEchoMode(QtWidgets.QLineEdit.Password)
        self.skip_libraries = QtWidgets.QLineEdit(self.cfg.get("server","skip_libraries", fallback=""))
        form.addRow("Server URL", self.server_address)
        form.addRow(QtWidgets.QLabel("e.g., http://127.0.0.1:32400"))
        form.addRow("Token", self.server_token)
        form.addRow("Skip Libraries", self.skip_libraries)
        form.addRow(QtWidgets.QLabel("Use semicolons to separate library names"))

        tool_row = QtWidgets.QHBoxLayout()
        tool_row.setContentsMargins(0,0,0,0)
        tool_row.setSpacing(8)
        self.btn_test = QtWidgets.QPushButton("Test Connection")
        self.btn_test.setObjectName("Primary")
        self.btn_test.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_DialogApplyButton))
        self.btn_pick = QtWidgets.QPushButton("Library Picker…")
        self.btn_pick.setObjectName("Outlined")
        self.btn_pick.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_DirOpenIcon))
        tool_row.addWidget(self.btn_test)
        tool_row.addWidget(self.btn_pick)
        tool_row.addStretch(1)
        tool_wrap = QtWidgets.QWidget(); tool_wrap.setLayout(tool_row)
        form.addRow("", tool_wrap)
        self.btn_test.clicked.connect(self._test_connection)
        self.btn_pick.clicked.connect(self._pick_libraries)

        # --- Modules tab ---
        modules_tab = QtWidgets.QWidget(); tabs.addTab(modules_tab, "Modules")
        m_v = QtWidgets.QVBoxLayout(modules_tab)
        m_v.setContentsMargins(8, 8, 8, 8)
        m_v.addWidget(QtWidgets.QLabel("Drag to reorder. Check to enable. Enabled run top-to-bottom."))
        current_order = [m for m in re.split(r"[;]", self.cfg.get("modules","order", fallback="")) if m]
        self.modules_list = ModulesList(DEFAULT_MODULES, current_order)
        m_v.addWidget(self.modules_list, 1)

        # --- Language tab ---
        lang_tab = QtWidgets.QWidget(); tabs.addTab(lang_tab, "Language")
        lf = QtWidgets.QFormLayout(lang_tab)
        lf.setHorizontalSpacing(14); lf.setVerticalSpacing(8)
        self.excluded_languages = QtWidgets.QLineEdit(self.cfg.get("language","excluded_languages", fallback=""))
        self.skip_multiple = QtWidgets.QCheckBox("Skip Multiple Audio Tracks")
        self.skip_multiple.setChecked(self.cfg.getboolean("language","skip_multiple_audio_tracks", fallback=False))
        lf.addRow("Excluded Languages", self.excluded_languages)
        lf.addRow(QtWidgets.QLabel("Use commas to separate languages"))
        lf.addRow("", self.skip_multiple)

        # --- Rating tab ---
        rating_tab = QtWidgets.QWidget(); tabs.addTab(rating_tab, "Rating")
        rf = QtWidgets.QFormLayout(rating_tab)
        rf.setHorizontalSpacing(14); rf.setVerticalSpacing(10)

        src_box = QtWidgets.QWidget(); src_layout = QtWidgets.QHBoxLayout(src_box)
        src_layout.setContentsMargins(0,0,0,0); src_layout.setSpacing(12)
        self.src_imdb = QtWidgets.QRadioButton("IMDB")
        self.src_rt   = QtWidgets.QRadioButton("Rotten Tomatoes")
        src_layout.addWidget(self.src_imdb)
        src_layout.addWidget(self.src_rt)
        src_layout.addStretch(1)
        _src_val = self.cfg.get("rating","source", fallback="imdb").strip().lower()
        (self.src_imdb if _src_val == "imdb" else self.src_rt).setChecked(True)
        rf.addRow("Rating Source", src_box)

        rt_box = QtWidgets.QWidget(); rt_layout = QtWidgets.QHBoxLayout(rt_box)
        rt_layout.setContentsMargins(0,0,0,0); rt_layout.setSpacing(12)
        self.rt_critics  = QtWidgets.QRadioButton("Critics")
        self.rt_audience = QtWidgets.QRadioButton("Audiences")
        rt_layout.addWidget(self.rt_critics)
        rt_layout.addWidget(self.rt_audience)
        rt_layout.addStretch(1)
        _rt_val = self.cfg.get("rating","rotten_tomatoes_type", fallback="critic").strip().lower()
        (self.rt_critics if _rt_val == "critic" else self.rt_audience).setChecked(True)
        rf.addRow("Rotten Tomatoes Type", rt_box)
        rf.addRow(QtWidgets.QLabel("Rotten Tomatoes type is used only when the source is Rotten Tomatoes."))

        # TMDb API Key
        self.tmdb_key = QtWidgets.QLineEdit(self.cfg.get("rating", "tmdb_api_key", fallback=""))
        rf.addRow("TMDb API Key", self.tmdb_key)

        # --- Performance tab ---
        perf_tab = QtWidgets.QWidget(); tabs.addTab(perf_tab, "Performance")
        pf = QtWidgets.QFormLayout(perf_tab)
        pf.setHorizontalSpacing(14); pf.setVerticalSpacing(8)
        self.max_workers = QtWidgets.QSpinBox(); self.max_workers.setRange(1, 256)
        self.max_workers.setValue(int(self.cfg.get("performance","max_workers", fallback="10")))
        self.batch_size = QtWidgets.QSpinBox(); self.batch_size.setRange(1, 5000)
        self.batch_size.setValue(int(self.cfg.get("performance","batch_size", fallback="25")))
        pf.addRow("Max Workers", self.max_workers)
        pf.addRow("Batch Size", self.batch_size)

        # --- Appearance tab ---
        appearance_tab = QtWidgets.QWidget(); tabs.addTab(appearance_tab, "Appearance")
        af = QtWidgets.QFormLayout(appearance_tab)
        af.setHorizontalSpacing(14); af.setVerticalSpacing(8)
        current_color = self.cfg.get("appearance", "primary_color", fallback="#6750A4")
        self.primary_color_btn = QtWidgets.QPushButton("Select Primary Color…")
        self.primary_color_display = QtWidgets.QLabel(current_color)
        self.primary_color_display.setMinimumWidth(90)
        self.primary_color_display.setAlignment(Qt.AlignCenter)
        self.primary_color_display.setStyleSheet(
            f"background-color: {current_color}; border: 1px solid #CAC4D0; border-radius: 6px; padding: 6px;")
        self.primary_color_btn.clicked.connect(self.choose_primary_color)
        af.addRow("Primary Highlight Color", self.primary_color_btn)
        af.addRow("Current Color", self.primary_color_display)

        # Footer buttons
        btn_box = QtWidgets.QDialogButtonBox()
        self.btn_save = btn_box.addButton("Save", QtWidgets.QDialogButtonBox.AcceptRole)
        btn_box.addButton("Cancel", QtWidgets.QDialogButtonBox.RejectRole)
        vbox.addWidget(btn_box)
        btn_box.accepted.connect(self.on_save)
        btn_box.rejected.connect(self.reject)

    # ---- Server helpers ----
    def _plex_headers(self):
        return {"X-Plex-Token": self.server_token.text().strip(), "Accept": "application/json"}

    def _server_base(self):
        return self.server_address.text().strip().rstrip("/")

    # ---- Banner (snackbar-like) helper ----
    def _show_banner(self, message: str, ok: bool = True):
        # Create once and reuse
        if not hasattr(self, "_banner"):
            self._banner = QtWidgets.QFrame(self)
            self._banner.setObjectName("Banner")
            self._banner.setStyleSheet("QFrame#Banner { border-radius: 8px; padding: 10px 16px; }")
            self._banner_lab = QtWidgets.QLabel(self._banner)
            h = QtWidgets.QHBoxLayout(self._banner); h.setContentsMargins(12,8,12,8); h.addWidget(self._banner_lab)
            self._banner.hide()

        # Color + text
        bg = "#1E8E3E" if ok else "#D93025"  # green / red
        self._banner.setStyleSheet(f"QFrame#Banner {{ background: {bg}; color: #FFFFFF; }}")
        self._banner_lab.setText(message)

        # Position top-center inside dialog
        geo = self.geometry()
        self._banner.adjustSize()
        w, h = self._banner.sizeHint().width(), self._banner.sizeHint().height()
        x = geo.width()//2 - w//2
        y = 10
        self._banner.setGeometry(x, y, w, h)
        self._banner.show()

        # Auto-hide after 2.2s
        QtCore.QTimer.singleShot(2200, self._banner.hide)

    @QtCore.Slot()
    def _test_connection(self):
        import requests
        try:
            r = requests.get(self._server_base() + "/library/sections", headers=self._plex_headers(), timeout=8)
            r.raise_for_status()
            libs = [d.get("title") for d in r.json().get("MediaContainer", {}).get("Directory", [])]
            self._show_banner("Connection Successful", ok=True)
        except Exception as e:
            self._show_banner("Connection Unsuccessful", ok=False)

    @QtCore.Slot()
    def _pick_libraries(self):
        import requests
        try:
            r = requests.get(
                self._server_base() + "/library/sections",
                headers=self._plex_headers(),
                timeout=8
            )
            r.raise_for_status()
            dirs = [
                d for d in r.json().get("MediaContainer", {}).get("Directory", [])
                if d.get("type") == "movie"
            ]
        except Exception as e:
            QtWidgets.QMessageBox.warning(
                self,
                "Error",
                f"Could not fetch libraries:\n{e}"
            )
            return

        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("Pick movie libraries to SKIP")
        v = QtWidgets.QVBoxLayout(dlg)
        v.addWidget(QtWidgets.QLabel("Checked libraries will be SKIPPED by the CLI."))
        listw = QtWidgets.QListWidget()
        listw.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        skip_now = {s.strip() for s in self.skip_libraries.text().split(";") if s.strip()}
        for d in dirs:
            it = QtWidgets.QListWidgetItem(d.get("title", ""))
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if d.get("title") in skip_now else Qt.Unchecked)
            listw.addItem(it)
        v.addWidget(listw)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        v.addWidget(bb)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)

        if dlg.exec() == QtWidgets.QDialog.Accepted:
            chosen = []
            for i in range(listw.count()):
                it = listw.item(i)
                if it.checkState() == Qt.Checked:
                    chosen.append(it.text())
            self.skip_libraries.setText(";".join(chosen))

    def choose_primary_color(self):
        color = QtWidgets.QColorDialog.getColor(QtGui.QColor(self.primary_color_display.text()), self, "Select Primary Color")
        if color.isValid():
            hex_color = color.name()
            self.primary_color_display.setText(hex_color)
            self.primary_color_display.setStyleSheet(
                f"background-color: {hex_color}; border: 1px solid #CAC4D0; border-radius: 6px; padding: 6px;")

    def on_save(self):
        # Ensure sections exist
        for sec in ("server","modules","language","rating","performance","appearance"):
            if not self.cfg.has_section(sec):
                self.cfg.add_section(sec)
        # server
        self.cfg.set("server", "address", self.server_address.text().strip())
        self.cfg.set("server", "token", self.server_token.text().strip())
        self.cfg.set("server", "skip_libraries", self.skip_libraries.text().strip())
        # modules
        self.cfg.set("modules", "order", ";".join(self.modules_list.enabled_modules_in_order()))
        # language
        self.cfg.set("language", "excluded_languages", self.excluded_languages.text().strip())
        self.cfg.set("language", "skip_multiple_audio_tracks", "yes" if self.skip_multiple.isChecked() else "no")
        # rating
        src_val = "imdb" if self.src_imdb.isChecked() else "rotten_tomatoes"
        rt_val = "critic" if self.rt_critics.isChecked() else "audience"
        self.cfg.set("rating", "source", src_val)
        self.cfg.set("rating", "rotten_tomatoes_type", rt_val)
        self.cfg.set("rating", "tmdb_api_key", self.tmdb_key.text().strip())  # NEW
        # performance
        self.cfg.set("performance", "max_workers", str(self.max_workers.value()))
        self.cfg.set("performance", "batch_size", str(self.batch_size.value()))
        # appearance
        self.cfg.set("appearance", "primary_color", self.primary_color_display.text().strip())

        cfg_dir = Path(CONFIG_FILE).parent
        cfg_dir.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            self.cfg.write(f)
        self.accept()

# ---------------------------
# Main window
# ---------------------------
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.cfg = configparser.ConfigParser()
        if os.path.exists(CONFIG_FILE):
            self.cfg.read(CONFIG_FILE)
        self.primary_color = self.cfg.get("appearance", "primary_color", fallback="#6750A4")

        self.setWindowTitle(f"{APP_TITLE} for Plex")
        self.resize(980, 720)

        central = QtWidgets.QWidget(); self.setCentralWidget(central)
        root = QtWidgets.QVBoxLayout(central)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # ---- App Bar ----
        bar = QtWidgets.QFrame()
        bar.setObjectName("AppBar")
        bar_layout = QtWidgets.QHBoxLayout(bar)
        bar_layout.setContentsMargins(14, 10, 14, 10)
        title_lab = QtWidgets.QLabel(APP_TITLE); title_lab.setObjectName("AppTitle")
        ver_lab = QtWidgets.QLabel(APP_VERSION); ver_lab.setObjectName("AppVersion")
        bar_layout.addWidget(title_lab); bar_layout.addSpacing(8); bar_layout.addWidget(ver_lab); bar_layout.addStretch(1)
        root.addWidget(bar)

        # ---- Section: Actions ----
        actions_header = QtWidgets.QLabel("Actions"); actions_header.setObjectName("SectionTitle")
        root.addWidget(actions_header)
        actions_group = QtWidgets.QGroupBox(); actions_group.setObjectName("Card"); actions_group.setTitle("")
        ag = QtWidgets.QGridLayout(actions_group)
        ag.setContentsMargins(16, 16, 16, 16)
        ag.setHorizontalSpacing(10)

        self.btn_all = QtWidgets.QPushButton("Process All Movies"); self.btn_all.setObjectName("Primary")
        self.btn_reset = QtWidgets.QPushButton("Reset All Movies"); self.btn_reset.setObjectName("Outlined")
        self.btn_backup = QtWidgets.QPushButton("Backup Editions"); self.btn_backup.setObjectName("Outlined")
        self.btn_restore = QtWidgets.QPushButton("Restore Editions"); self.btn_restore.setObjectName("Outlined")
        self.btn_settings = QtWidgets.QPushButton("Settings"); self.btn_settings.setObjectName("Outlined")

        ag.addWidget(self.btn_all,    0, 0)
        ag.addWidget(self.btn_reset,  0, 1)
        ag.addWidget(self.btn_backup, 0, 2)
        ag.addWidget(self.btn_restore,0, 3)
        ag.addWidget(self.btn_settings,0,4)
        root.addWidget(actions_group)

        # ---- Section: Progress ----
        prog_header = QtWidgets.QLabel("Progress"); prog_header.setObjectName("SectionTitle")
        root.addWidget(prog_header)
        prog_group = QtWidgets.QGroupBox(); prog_group.setObjectName("Card"); prog_group.setTitle("")
        pg = QtWidgets.QGridLayout(prog_group)
        pg.setContentsMargins(16, 16, 16, 16)
        self.progress = QtWidgets.QProgressBar(); self.progress.setRange(0, 100); self.progress.setValue(0)
        self.percent_lab = QtWidgets.QLabel("0%")
        pg.addWidget(self.progress, 0, 0, 1, 1)
        pg.addWidget(self.percent_lab, 1, 0, 1, 1, alignment=Qt.AlignLeft)
        root.addWidget(prog_group)

        # ---- Section: Status ----
        status_header = QtWidgets.QLabel("Status"); status_header.setObjectName("SectionTitle")
        root.addWidget(status_header)
        status_group = QtWidgets.QGroupBox(); status_group.setObjectName("Card"); status_group.setTitle("")
        sg = QtWidgets.QGridLayout(status_group)
        sg.setContentsMargins(16, 16, 16, 16)
        self.status = QtWidgets.QPlainTextEdit(); self.status.setReadOnly(True); self.status.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        mono = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont); mono.setPointSize(10)
        self.status.setFont(mono)
        sg.addWidget(self.status, 0, 0, 1, 1)
        self.btn_clear = QtWidgets.QPushButton("Clear Status"); self.btn_clear.setObjectName("Text")
        sg.addWidget(self.btn_clear, 1, 0, 1, 1, alignment=Qt.AlignRight)
        root.addWidget(status_group, 1)

        # Footer
        foot = QtWidgets.QHBoxLayout(); root.addLayout(foot)
        foot.addStretch(1)
        pyver = ".".join(map(str, sys.version_info[:3]))
        foot.addWidget(QtWidgets.QLabel(f"{APP_TITLE} • Python {pyver}"))

        # Shadows for cards
        for g in (actions_group, prog_group, status_group):
            self._add_shadow(g)

        # Wiring
        self.btn_clear.clicked.connect(lambda: self.status.setPlainText(""))
        self.btn_settings.clicked.connect(self.open_settings)
        self.btn_all.clicked.connect(lambda: self.run_flag("--all"))
        self.btn_reset.clicked.connect(lambda: self.run_flag("--reset"))
        self.btn_backup.clicked.connect(lambda: self.run_flag("--backup"))
        self.btn_restore.clicked.connect(lambda: self.run_flag("--restore"))

        # Timer to update percent label
        self._percent_timer = QtCore.QTimer(self)
        self._percent_timer.timeout.connect(self._update_percent)
        self._percent_timer.start(120)

        self._current_worker = None

        # Apply local style sheet for polish (light-only) with dynamic color
        self._apply_light_styles()

    # ---- Styling helpers ----
    def _add_shadow(self, widget, radius=18, opacity=0.20, offset=(0, 4)):
        eff = QtWidgets.QGraphicsDropShadowEffect(widget)
        eff.setBlurRadius(radius)
        eff.setColor(QtGui.QColor(0, 0, 0, int(255 * opacity)))
        eff.setOffset(*offset)
        widget.setGraphicsEffect(eff)

    def _apply_light_styles(self):
        c = self.primary_color
        # Slightly darker for hover/disabled states
        def darken(hex_color, factor=0.15):
            col = QtGui.QColor(hex_color)
            r, g, b = col.red(), col.green(), col.blue()
            r = max(0, int(r * (1 - factor)))
            g = max(0, int(g * (1 - factor)))
            b = max(0, int(b * (1 - factor)))
            return f"#{r:02x}{g:02x}{b:02x}"
        hover = darken(c, 0.12)
        disabled = darken(c, 0.40)

        self.setStyleSheet(self.styleSheet() + f"""
            QLabel#AppTitle {{ font-size: 20pt; font-weight: 700; letter-spacing: .2px; color: #FFFFFF; }}
            QLabel#AppVersion {{ color: rgba(255,255,255,.95); font-size: 10pt; }}
            QLabel#SectionHeaderBig {{ font-size: 16pt; font-weight: 700; margin: 2px 0 10px 2px; color: rgba(0,0,0,.84); }}
            QLabel#SectionTitle {{ margin-top: 8px; margin-bottom: 6px; font-size: 12pt; font-weight: 600; color: rgba(0,0,0,.60); }}

            QFrame#AppBar {{ background: {c}; border-radius: 10px; }}

            QGroupBox#Card {{ background: #FFFFFF; border: 1px solid #E5E5EC; border-radius: 12px; padding: 6px; margin-top: 0px; }}

            QPushButton {{ padding: 8px 14px; border-radius: 8px; font-weight: 600; }}
            QPushButton#Primary {{ background: {c}; color: #FFFFFF; border: none; }}
            QPushButton#Primary:hover {{ background: {hover}; }}
            QPushButton#Primary:disabled {{ background: {disabled}; color: #FFFFFF; }}

            QPushButton#Outlined {{ background: #FFFFFF; color: #1D1B20; border: 1px solid #CAC4D0; }}
            QPushButton#Outlined:hover {{ background: #F4EFF7; }}

            QPushButton#Text {{ background: transparent; color: {c}; border: none; padding: 6px 10px; }}
            QPushButton#Text:hover {{ background: #EEE6F7; border-radius: 6px; }}

            QProgressBar {{ border: 1px solid #E5E5EC; border-radius: 8px; background: #F4F4F8; height: 14px; color: rgba(0,0,0,.65); text-align: center; }}
            QProgressBar::chunk {{ background-color: {c}; border-radius: 8px; }}

            QPlainTextEdit {{ background: #FAFAFD; border: 1px solid #E5E5EC; border-radius: 8px; padding: 8px; color: rgba(0,0,0,.84); }}

            QTabWidget::pane {{ border: 1px solid #E5E5EC; border-radius: 10px; padding: 6px; background: #FFFFFF; }}
            QTabBar::tab {{ padding: 8px 14px; margin: 2px; border-radius: 8px; background: #F6F2FB; color: #3A3650; border: 1px solid transparent; font-weight: 600; }}
            QTabBar::tab:selected {{ background: #FFFFFF; border-color: #CAC4D0; }}
        """)

    # --- Settings ---
    def open_settings(self):
        dlg = SettingsDialog(self)
        before = self.primary_color
        if dlg.exec():  # if saved
            # If color changed, persist immediately in UI without restart
            self.cfg.read(CONFIG_FILE)
            self.primary_color = self.cfg.get("appearance", "primary_color", fallback=before)
            self._apply_light_styles()
            # Also update the app palette highlight so selection bars match
            app = QtWidgets.QApplication.instance()
            if app is not None:
                apply_light_palette(app, self.primary_color)

    # --- Process execution ---
    def run_flag(self, flag: str):
        if self._current_worker is not None:
            return
        self._set_buttons_enabled(False)

        self._current_worker = ProcessWorker(flag)
        self._current_worker.line.connect(self.append_status)
        self._current_worker.progress.connect(self.set_progress)
        self._current_worker.started.connect(self._on_started)
        self._current_worker.finished.connect(self._on_finished)

        QtCore.QTimer.singleShot(0, self._current_worker.start)

    @QtCore.Slot()
    def _on_started(self):
        self.progress.setRange(0, 0)  # indeterminate until we see PROGRESS

    @QtCore.Slot(int)
    def _on_finished(self, code: int):
        self._current_worker = None
        self._set_buttons_enabled(True)
        if self.progress.maximum() == 0:
            self.progress.setRange(0, 100)
        if code == 0:
            self.set_progress(100)
            self.append_status("Completed successfully.")
        else:
            self.append_status(f"Exited with code {code}.")

    @QtCore.Slot(int)
    def set_progress(self, value: int):
        if self.progress.maximum() == 0:
            self.progress.setRange(0, 100)
        value = max(0, min(100, value))
        self.progress.setValue(value)

    def _update_percent(self):
        if self.progress.maximum() == 0:
            self.percent_lab.setText("…")
        else:
            self.percent_lab.setText(f"{self.progress.value()}%")

    @QtCore.Slot(str)
    def append_status(self, text: str):
        self.status.appendPlainText(text)
        self.status.verticalScrollBar().setValue(self.status.verticalScrollBar().maximum())

    def _set_buttons_enabled(self, enabled: bool):
        for b in (self.btn_all, self.btn_reset, self.btn_backup, self.btn_restore, self.btn_settings):
            b.setEnabled(enabled)

# ---------------------------
# App entry
# ---------------------------

def main():
    app = QtWidgets.QApplication(sys.argv)

    # Subtle global font bump for nicer density
    f = app.font(); f.setPointSize(f.pointSize() + 1); app.setFont(f)

    # Read preferred color before palette + window creation
    cfg = configparser.ConfigParser()
    if os.path.exists(CONFIG_FILE):
        cfg.read(CONFIG_FILE)
    primary_color = cfg.get("appearance", "primary_color", fallback="#6750A4")

    # Enforce LIGHT palette with chosen highlight color
    apply_light_palette(app, primary_color)

    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()