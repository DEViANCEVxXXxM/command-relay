# SPDX-License-Identifier: Apache-2.0
"""Command Relay Qt workbench. Local-only, explicit execution."""
import time
from string import Template
STARTUP_T0 = time.perf_counter()
import sys, os, pathlib, json, codecs, tempfile, subprocess, threading, shutil, difflib, re, datetime, queue
from PySide6.QtCore import Qt, QProcess, QTimer, QUrl, Signal, QObject, QEvent, QSize, QRect, QPropertyAnimation
from PySide6.QtGui import QColor, QFont, QTextCursor, QTextDocument, QSyntaxHighlighter, QTextCharFormat, QDesktopServices, QShortcut, QKeySequence, QPainter, QIcon, QPalette
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QLineEdit,QPlainTextEdit,QSplitter,QTabWidget,QListWidget,QFileDialog,QMessageBox,QCheckBox,QDialog,QTableWidget,QTableWidgetItem,QHeaderView,QAbstractItemView,QComboBox,QMenu,QInputDialog,QSizePolicy,QLayout,QStyle,QRadioButton,QButtonGroup,QGraphicsOpacityEffect)
from .relay_core import (
    ASSETS, GIT_ACTIONS, MARK, PACKET_LIMIT, REPORTS, ROOT, SETTINGS,
    atomic_text, compact_report, copy_mode, file_hash, git_args, load_input,
    prepare, read_settings, sha,
)
from .relay_version import VERSION
from .relay_terms import dialog_result_text, casual_stage, casual_task_title
from .relay_terms import (confirm_usage_terms, choose_language, saved_language, startup_language, tr,
                          MODES, DEFAULT_MODE, saved_mode, startup_mode, sidebar_preference)
from .relay_windows import apply_neutral_chrome, set_app_identity
from . import relay_features as features
from . import relay_intelligence as intelligence
from . import relay_session as session
from . import relay_privacy as privacy
from . import relay_export as exports
from . import relay_compare as comparison
from . import relay_view as view

STARTUP_MARKS = {'imports_ms': round((time.perf_counter()-STARTUP_T0)*1000)}

def startup_mark(name):
    STARTUP_MARKS[name] = round((time.perf_counter()-STARTUP_T0)*1000)

def save_startup_marks():
    snapshot = dict(STARTUP_MARKS)
    def work():
        try:
            atomic_text(ROOT/'startup-timing.json', json.dumps(snapshot, indent=2))
        except OSError:
            pass
    threading.Thread(target=work, daemon=True).start()

class NeutralChrome(QObject):
    def eventFilter(self, obj, event):
        if sys.platform == 'win32' and event.type() == QEvent.Type.Show and isinstance(obj, QWidget) and obj.isWindow() and not (obj.windowType() in (Qt.WindowType.ToolTip, Qt.WindowType.Popup)):
            try:
                apply_neutral_chrome(int(obj.winId()), current_theme())
            except (RuntimeError, OSError, ValueError):
                pass
        return False


# Shared workbench geometry and motion tokens.
WINDOW_MARGINS = (12, 9, 12, 8)
LAYOUT_GAP = 7
SPLITTER_WIDTH = 5
ACTIVITY_INTERVAL_MS = 33
OUTPUT_INTERVAL_MS = 80
CLOCK_INTERVAL_MS = 1000
OUTLINE_DELAY_MS = 120
CONTROL_RADIUS = 5
CONTROL_PADDING = '6px 12px'

_THEME_QSS = Template("""
QWidget { background:$canvas; color:$text; font-family:"Segoe UI"; font-size:12px; }
QLabel[role="brand"] { font-size:20px; font-weight:700; }
QLabel[role="section"] { font-weight:600; color:$muted; }
QLabel[role="muted"] { color:$muted; }
QWidget#casualCard { background:$surface; border:1px solid $border; border-radius:$radius; }
QLabel[role="casualTitle"] { font-size:14px; font-weight:600; background:transparent; }
QLabel[role="casualHelp"] { color:$muted; background:transparent; }
QLineEdit,QPlainTextEdit,QListWidget,QTableWidget,QComboBox {
    background:$surface; border:1px solid $border; border-radius:$radius;
    selection-background-color:$selection; selection-color:$selected_text;
}
QPlainTextEdit[role="code"] { font-family:Consolas,monospace; font-size:13px; }
QPushButton { background:$raised; border:1px solid transparent; border-radius:$radius; padding:$padding; }
QPushButton:hover { background:$hover; }
QPushButton:pressed { background:$border; }
QPushButton:disabled { color:$disabled; background:$canvas; }
QPushButton#run { background:$accent; color:$on_accent; font-weight:600; }
QPushButton#run:hover,QPushButton#run:pressed { background:$accent_hover; }
QPushButton#run:disabled { background:$raised; color:$disabled; }
QMenu { background:$surface; border:1px solid $border; padding:4px; }
QMenu::item { padding:7px 24px 7px 12px; }
QMenu::item:selected { background:$selection; color:$selected_text; }
QMenu::item:disabled { color:$disabled; }
QMenu::separator { height:1px; background:$border; margin:4px 6px; }
QTabWidget::pane { border:0; }
QTabBar::tab { padding:7px 12px; background:$raised; color:$muted; }
QTabBar::tab:selected { background:$surface; color:$text; }
QSplitter::handle { background:$border; }
QSplitter::handle:hover { background:$accent; }
QHeaderView::section { background:$raised; border:0; padding:6px; }
QScrollBar:vertical { width:9px; background:$canvas; }
QScrollBar::handle:vertical { background:$thumb; min-height:24px; border-radius:4px; }
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical { height:0; }
QScrollBar:horizontal { height:9px; background:$canvas; }
QScrollBar::handle:horizontal { background:$thumb; min-width:24px; border-radius:4px; }
QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal { width:0; }
QPushButton:focus,QLineEdit:focus,QListWidget:focus,QTableWidget:focus,QComboBox:focus,QPlainTextEdit:focus { border:1px solid $focus; }
QCheckBox:focus,QRadioButton:focus,QTabBar::tab:focus { outline:1px solid $focus; }
QPlainTextEdit[fileDropActive="true"] { border:1px solid $accent; background:$raised; }
QToolTip { background:$surface; color:$text; border:1px solid $border; }
""")


def current_theme():
    app = QApplication.instance()
    return view.saved_theme({'theme': app.property('relay_theme') if app else None})


def colors():
    return view.theme_colors(current_theme())


def apply_theme(theme):
    """One application-wide palette, no fades or widget reconstruction."""
    app = QApplication.instance()
    theme = view.saved_theme({'theme': theme})
    if app.property('relay_theme') == theme:
        return
    c = view.theme_colors(theme)
    palette = QPalette()
    for role, token in [('Window','canvas'), ('WindowText','text'), ('Base','surface'),
                        ('AlternateBase','raised'), ('Text','text'), ('Button','raised'),
                        ('ButtonText','text'), ('Highlight','selection'), ('HighlightedText','selected_text'),
                        ('ToolTipBase','surface'), ('ToolTipText','text'), ('PlaceholderText','muted'),
                        ('Link','info'), ('BrightText','error')]:
        palette.setColor(getattr(QPalette.ColorRole, role), QColor(c[token]))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(c['disabled']))
    app.setProperty('relay_theme', theme)
    app.setPalette(palette)
    app.setStyleSheet(_THEME_QSS.substitute(**c, radius=f'{CONTROL_RADIUS}px', padding=CONTROL_PADDING))
    for window in app.topLevelWidgets():
        if window.isVisible() and not (window.windowType() in (Qt.WindowType.Popup, Qt.WindowType.ToolTip)):
            if sys.platform == 'win32':
                apply_neutral_chrome(int(window.winId()), theme)


# A tiny indeterminate indicator: repaint only this 4-pixel strip, not the log.
# No claimed percentage; scripts have no universal progress metric.
class ActivityBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(4)
        self.setAccessibleName('Execution in progress (indeterminate)')
        self._epoch = 0.0
        self._running = False
        self._reduced_motion = False
        self._timer = QTimer(self)
        self._timer.setInterval(ACTIVITY_INTERVAL_MS)
        self._timer.timeout.connect(self.update)
        self.hide()

    def set_running(self, running):
        self._running = bool(running)
        if running:
            self._epoch = time.monotonic()
            self.show()
        else:
            self.hide()
        self._sync_timer()
        self.update()

    def set_reduced_motion(self, enabled):
        self._reduced_motion = bool(enabled)
        self._sync_timer()
        self.update()

    def _sync_timer(self):
        if self._running and self.isVisible() and not self._reduced_motion:
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_timer()

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        width = self.width()
        c = colors()
        painter.fillRect(self.rect(), QColor(c['raised']))
        segment = min(width, max(36, width // 5))
        phase = ((time.monotonic() - self._epoch) % 1.25) / 1.25
        x = (width - segment) // 2 if self._reduced_motion else int(phase * (width + segment)) - segment
        painter.fillRect(x, 0, segment, self.height(), QColor(c['focus']))
        painter.end()


STATUS_COLORS = {
    'ready': '#145a98', 'running': '#005f9e', 'success': '#237346',
    'failed': '#a12632', 'cancelled': '#80550d', 'stopping': '#80550d',
}
COPY_TIP = 'Click: Copy AI (best-effort secret masking)\nShift + click: Copy text (masked)\nCtrl + click: Copy RAW full report (unmasked)\nCtrl takes priority if both are held.'

class Highlight(QSyntaxHighlighter):
    def __init__(self, document):
        self.tokens = colors()
        super().__init__(document)

    def refresh_theme(self):
        self.tokens = colors()
        self.rehighlight()

    def highlightBlock(self,text):
        t=text.strip(); color=None; c=self.tokens
        if MARK.match(t): color=c['info']
        elif re.search(r'\b\w*PASS=False\b',t) or re.match(r'^(error[\[:]|Runner error:|Process exit code: (?!0$))',t,re.I): color=c['error']
        elif re.search(r'\b\w*PASS=True\b',t) or t=='Process exit code: 0': color=c['success']
        elif re.match(r'^(warning:|Cancelled: True)',t,re.I): color=c['warning']
        elif re.match(r'^[A-Z][A-Z0-9_]+=',t): color=c['metric']
        if color:
            fmt=QTextCharFormat();fmt.setForeground(QColor(color));self.setFormat(0,len(text),fmt)

class DropEditor(QPlainTextEdit):
    fileDropped=Signal(str)

    def set_file_drop_active(self, active):
        if bool(self.property('fileDropActive')) == active:
            return
        self.setProperty('fileDropActive', active)
        self.style().unpolish(self); self.style().polish(self); self.update()

    def accepts_file(self, mime):
        urls=mime.urls()
        return not self.isReadOnly() and len(urls)==1 and urls[0].isLocalFile() and bool(urls[0].toLocalFile())

    def dragEnterEvent(self,e):
        if self.isReadOnly(): e.ignore(); return
        if e.mimeData().hasUrls():
            accepted=self.accepts_file(e.mimeData()); self.set_file_drop_active(accepted)
            if accepted: e.acceptProposedAction()
            else: e.ignore()
        else: super().dragEnterEvent(e)

    def dragMoveEvent(self,e):
        if self.isReadOnly(): self.set_file_drop_active(False); e.ignore(); return
        if e.mimeData().hasUrls():
            accepted=self.accepts_file(e.mimeData()); self.set_file_drop_active(accepted)
            if accepted: e.acceptProposedAction()
            else: e.ignore()
        else: super().dragMoveEvent(e)

    def dragLeaveEvent(self,e):
        self.set_file_drop_active(False); super().dragLeaveEvent(e)

    def dropEvent(self,e):
        self.set_file_drop_active(False)
        if self.isReadOnly(): e.ignore(); return
        if e.mimeData().hasUrls():
            if self.accepts_file(e.mimeData()):
                self.fileDropped.emit(e.mimeData().urls()[0].toLocalFile()); e.acceptProposedAction()
            else: e.ignore()
        else: super().dropEvent(e)

    def hideEvent(self,e):
        self.set_file_drop_active(False); super().hideEvent(e)

class WorkerSignals(QObject):
    hashDone=Signal(str,str)
    stopDone=Signal(object,bool)
    initialTail=Signal(object,object,object)
    toolDone=Signal(str,object,object)
    copyDone=Signal(object,object,object)
    warmDone=Signal(object,object)
    historyDone=Signal(object,object,object)

class UpdatesDialog(QDialog):
    """Explicit lookup, verification and optional guarded exit handoff."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.ui_language = getattr(parent, 'ui_language', 'en')
        self.setWindowTitle(self.ui('update_title')); self.resize(560, 300)
        self.results = None
        self.info = None
        self.signed = None
        self.handoff = None
        layout = QVBoxLayout(self)
        def label(text):
            item = QLabel(text); item.setWordWrap(True)
            item.setTextFormat(Qt.TextFormat.PlainText); layout.addWidget(item)
            return item
        label(self.ui('update_current') + VERSION)
        label(self.ui('update_intro'))
        self.latest = label(self.ui('update_latest_initial'))
        self.status = label(self.ui('update_start'))
        self.trust = label(self.ui('update_unverified'))
        self.digest = label('')
        layout.addStretch()
        row = QHBoxLayout(); layout.addLayout(row)
        self.check_button = QPushButton(self.ui('update_check')); self.check_button.setObjectName('updates_check')
        self.check_button.setAutoDefault(False); self.check_button.clicked.connect(self.check); row.addWidget(self.check_button)
        self.verify_button = QPushButton(self.ui('update_verify')); self.verify_button.setObjectName('updates_verify')
        self.verify_button.setAutoDefault(False); self.verify_button.setEnabled(False)
        self.verify_button.clicked.connect(self.verify); row.addWidget(self.verify_button)
        row.addStretch()
        close = QPushButton(self.ui('dialog_close')); close.setAutoDefault(False); close.clicked.connect(self.reject); row.addWidget(close)
        self.prepare_button = QPushButton(self.ui('update_prepare'))
        self.prepare_button.setObjectName('updates_prepare')
        self.prepare_button.setAutoDefault(False); self.prepare_button.setEnabled(False)
        self.prepare_button.clicked.connect(self.prepare_installation)
        layout.addWidget(self.prepare_button)
        self.poll = QTimer(self); self.poll.setInterval(50); self.poll.timeout.connect(self.finish_check)

    def ui(self, key):
        return tr(key, self.ui_language)

    def _start(self, work, failure):
        results = queue.Queue(maxsize=1)
        self.results = results
        self.check_button.setEnabled(False); self.verify_button.setEnabled(False); self.prepare_button.setEnabled(False)
        # Worker owns only a queue and captured plain Python data, not Qt objects.
        def run():
            try: results.put(work())
            except Exception: results.put(failure)
        try:
            threading.Thread(target=run, daemon=True).start()
        except RuntimeError:
            results.put(failure)
        self.poll.start()

    def check(self):
        if self.results is not None: return
        from . import relay_updates as updates
        self.info = None
        self.signed = None
        self.digest.clear()
        self.latest.setText(self.ui('update_checking'))
        self.status.setText(self.ui('update_request'))
        self.trust.setText(self.ui('update_unverified'))
        def work():
            info = updates.check_latest(VERSION)
            availability, trust = updates.describe_release(info)
            return ('check', info, availability, trust, None)
        self._start(work, ('check', None, 'Release check failed. Retry later.', 'Publisher signature: Not verified', None))

    def verify(self):
        from . import relay_updates as updates
        if self.results is not None or not updates.can_verify_release(self.info): return
        info = self.info
        self.signed = None
        self.digest.clear()
        self.status.setText(self.ui('update_downloading'))
        self.trust.setText(self.ui('update_unverified'))
        def work():
            signed = updates.download_signed_update(info)
            return ('verify', info, 'Package verified and retained in memory until this dialog closes. No installation performed.',
                    'Publisher signature: Verified', signed)
        self._start(work, ('verify', info, 'Package verification failed. Retry or check again.',
                           'Publisher signature: Not verified', None))

    def finish_check(self):
        if self.results is None: return
        try: mode, info, status, trust, signed = self.results.get_nowait()
        except queue.Empty: return
        self.poll.stop(); self.results = None
        from . import relay_updates as updates
        self.info = info
        self.signed = signed
        digest = signed.download.sha256 if signed is not None else None
        self.latest.setText(self.ui('update_latest') + (info.latest if info else self.ui('update_unavailable')))
        self.status.setText(dialog_result_text(status, self.ui_language)); self.trust.setText(dialog_result_text(trust, self.ui_language))
        self.digest.setText(self.ui('update_digest') + digest if digest else '')
        self.check_button.setEnabled(True)
        self.verify_button.setEnabled(not digest and updates.can_verify_release(info))
        self.prepare_button.setEnabled(signed is not None and updates.gui_handoff_available(ROOT))

    def prepare_installation(self):
        from . import relay_updates as updates
        if self.results is not None or self.signed is None or not updates.gui_handoff_available(ROOT):
            return
        folder = QFileDialog.getExistingDirectory(self, self.ui('update_original'))
        if not folder:
            return
        answer = QMessageBox.question(self, self.ui('update_prepare_title'),
            self.ui('update_prepare_confirm'),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.handoff = updates.prepare_gui_update_handoff(ROOT, pathlib.Path(folder), self.signed)
        except (updates.UpdateError, OSError) as exc:
            # UpdateError messages are bounded; do not expose raw OS details.
            self.status.setText(str(exc) if isinstance(exc, updates.UpdateError) else self.ui('update_prepare_failed'))
            return
        self.accept()

    def done(self, result):
        self.poll.stop(); self.results = None; self.info = None; self.signed = None
        if result != QDialog.DialogCode.Accepted: self.handoff = None
        self.prepare_button.setEnabled(False)
        self.digest.clear(); self.trust.setText(self.ui('update_unverified'))
        self.verify_button.setEnabled(False)
        super().done(result)


class SafetyDialog(QDialog):
    """Only implemented automation is exposed; no network or task execution."""
    completed = Signal(object, object, str)

    def __init__(self, workspace, parent=None):
        super().__init__(parent)
        self.ui_language = getattr(parent, 'ui_language', 'en')
        self.setWindowTitle(self.ui('safety_title')); self.resize(650, 490)
        self.workspace = workspace; self.scope = None; self.snapshot = None; self.busy = False
        self.completed.connect(self.finish_policy, Qt.ConnectionType.QueuedConnection)
        layout = QVBoxLayout(self)
        def label(text):
            widget = QLabel(text); widget.setWordWrap(True); widget.setTextFormat(Qt.TextFormat.PlainText)
            layout.addWidget(widget); return widget
        label(self.ui('safety_default'))
        label(self.ui('safety_intro'))
        self.target = label(self.ui('safety_workspace') + workspace)
        self.notice = label(self.ui('safety_refresh_hint'))
        self.toggle = QCheckBox(self.ui('safety_merge'))
        self.toggle.setAccessibleName(self.ui('safety_merge_accessible')); layout.addWidget(self.toggle)
        label(self.ui('safety_review'))
        self.update_target = label(self.ui('safety_installation') + str(ROOT))
        self.update_toggle = QCheckBox(self.ui('safety_update'))
        self.update_toggle.setAccessibleName(self.ui('safety_update_accessible')); layout.addWidget(self.update_toggle)
        label(self.ui('safety_terminal'))
        self.update_save_button = QPushButton(self.ui('safety_update_apply'))
        self.update_save_button.setAutoDefault(False); self.update_save_button.clicked.connect(self.save_update)
        layout.addWidget(self.update_save_button)
        self.update_scope = None
        layout.addStretch()
        row = QHBoxLayout(); layout.addLayout(row)
        def button(text, fn):
            b = QPushButton(text); b.setAutoDefault(False); b.clicked.connect(fn); row.addWidget(b); return b
        self.refresh_button = button(self.ui('safety_refresh'), self.refresh)
        self.history_button = button(self.ui('safety_history'), self.show_history)
        self.revoke_button = button(self.ui('safety_revoke_all'), self.revoke_all)
        self.save_button = button(self.ui('safety_apply'), self.save)
        self.close_button = button(self.ui('dialog_close'), self.reject)
        self.update_controls()

    def ui(self, key):
        return tr(key, self.ui_language)

    def update_controls(self):
        self.toggle.setEnabled(not self.busy and self.scope is not None and self.snapshot is not None)
        self.save_button.setEnabled(self.toggle.isEnabled())
        self.update_toggle.setEnabled(not self.busy and self.update_scope is not None and self.snapshot is not None)
        self.update_save_button.setEnabled(self.update_toggle.isEnabled())
        self.revoke_button.setEnabled(not self.busy and self.snapshot is not None)
        self.history_button.setEnabled(not self.busy and self.snapshot is not None)
        self.refresh_button.setEnabled(not self.busy); self.close_button.setEnabled(not self.busy)

    def start(self, fn):
        if self.busy: return
        self.busy = True; self.update_controls(); self.notice.setText(self.ui('safety_busy'))
        def work():
            try: scope, snapshot, note = fn()
            except Exception:
                scope, snapshot, note = None, None, 'Policy operation not verified. Refresh; if invalid or locked, inspect the local policy file before making changes.'
            self.completed.emit(scope, snapshot, note)
        try: threading.Thread(target=work, daemon=True).start()
        except RuntimeError: self.finish_policy(None, None, 'Could not start local worker.')

    def finish_policy(self, scope, snapshot, note):
        from . import relay_permissions as policy
        self.busy = False; self.scope = scope; self.snapshot = snapshot
        self.target.setText(self.ui('safety_workspace') + (scope[0] if scope else self.workspace) + self.ui('safety_repository') + (scope[1] if scope else self.ui('safety_unresolved')))
        self.toggle.setChecked(bool(scope and snapshot is not None and policy.allowed(snapshot, 'squash_merge', workspace=scope[0], repository=scope[1])))
        self.update_scope = None
        if snapshot is not None:
            try: self.update_scope = policy.update_permission_scope(ROOT)
            except Exception: pass
        self.update_target.setText(self.ui('safety_installation') + str(ROOT) + (self.ui('safety_eligible') if self.update_scope else self.ui('safety_unavailable')))
        self.update_toggle.setChecked(bool(snapshot is not None and policy.allowed(snapshot, 'update_install')))
        self.notice.setText(dialog_result_text(note, self.ui_language)); self.update_controls()

    def refresh(self):
        from . import relay_permissions as policy
        def work():
            snapshot = policy.policy_snapshot()
            try: scope = policy.merge_scope(self.workspace)
            except Exception: return None, snapshot, 'No supported GitHub origin. You can still revoke all saved grants.'
            return scope, snapshot, 'Local policy loaded. No changes made.'
        self.start(work)

    def show_history(self):
        from . import relay_permissions as policy
        if self.busy or self.snapshot is None: return
        dialog = QDialog(self); dialog.setWindowTitle(self.ui('safety_history_title')); dialog.resize(680, 360)
        layout = QVBoxLayout(dialog)
        view = QPlainTextEdit(); view.setReadOnly(True); view.setAccessibleName(self.ui('safety_history_accessible'))
        view.setPlainText(policy.audit_text(self.snapshot)); layout.addWidget(view)
        close = QPushButton(self.ui('dialog_close')); close.clicked.connect(dialog.accept); layout.addWidget(close)
        dialog.exec()

    def confirm(self, text):
        box = QMessageBox(QMessageBox.Icon.Warning, self.ui('safety_confirm'), text, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, self)
        box.button(QMessageBox.StandardButton.Yes).setText(self.ui('confirm_yes'))
        box.button(QMessageBox.StandardButton.Cancel).setText(self.ui('confirm_cancel'))
        box.setTextFormat(Qt.TextFormat.PlainText); box.setDefaultButton(QMessageBox.StandardButton.Cancel); box.setEscapeButton(QMessageBox.StandardButton.Cancel)
        return box.exec() == QMessageBox.StandardButton.Yes

    def save(self):
        from . import relay_permissions as policy
        if self.busy or self.scope is None or self.snapshot is None: return
        scope, snapshot, enabled = self.scope, self.snapshot, self.toggle.isChecked()
        if enabled == policy.allowed(snapshot, 'squash_merge', workspace=scope[0], repository=scope[1]):
            self.notice.setText(self.ui('safety_no_change')); return
        if not self.confirm(self.ui('merge_allow' if enabled else 'merge_revoke').format(workspace=scope[0], repository=scope[1])):
            self.finish_policy(scope, snapshot, 'Cancelled. No changes made.'); return
        def work():
            updated = policy.save_merge_permission(snapshot, workspace=scope[0], repository=scope[1], enabled=enabled)
            return scope, updated, 'Permission saved. No commands or network writes executed.'
        self.start(work)

    def save_update(self):
        from . import relay_permissions as policy
        if self.busy or self.update_scope is None or self.snapshot is None: return
        root, snapshot, scope, enabled = self.update_scope, self.snapshot, self.scope, self.update_toggle.isChecked()
        if enabled == policy.allowed(snapshot, 'update_install'):
            self.notice.setText(self.ui('safety_no_update_change')); return
        if not self.confirm(self.ui('install_allow' if enabled else 'install_revoke').format(root=str(root))):
            self.finish_policy(scope, snapshot, 'Cancelled. No changes made.'); return
        self.start(lambda: (scope, policy.save_update_permission(snapshot, root=root, enabled=enabled),
                           'Update permission saved. No update or network operation executed.'))

    def revoke_all(self):
        from . import relay_permissions as policy
        if self.busy or self.snapshot is None: return
        if not self.confirm(self.ui('safety_revoke_confirm')): return
        scope, snapshot = self.scope, self.snapshot
        self.start(lambda: (scope, policy.revoke_all_permissions(snapshot), 'All grants revoked.'))

    def reject(self):
        if not self.busy: super().reject()

    def closeEvent(self, event):
        if self.busy: event.ignore()
        else: super().closeEvent(event)


class AdaptiveActionRow(QLayout):
    """Two natural-width groups; wrap the trailing group when space is tight."""
    def __init__(self, leading, trailing):
        super().__init__()
        self._items = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(7)
        self.addWidget(leading)
        self.addWidget(trailing)

    def addItem(self, item):
        self._items.append(item)
        self.invalidate()

    def count(self): return len(self._items)
    def itemAt(self, index): return self._items[index] if 0 <= index < self.count() else None
    def takeAt(self, index): return self._items.pop(index) if 0 <= index < self.count() else None
    def expandingDirections(self): return Qt.Orientation.Horizontal
    def hasHeightForWidth(self): return True

    def sizeHint(self):
        sizes = [item.sizeHint() for item in self._items]
        return QSize(sum(s.width() for s in sizes) + self.spacing() * max(0, len(sizes)-1),
                     max((s.height() for s in sizes), default=0))

    def minimumSize(self):
        sizes = [item.minimumSize() for item in self._items]
        return QSize(max((s.width() for s in sizes), default=0),
                     max((s.height() for s in sizes), default=0))

    def heightForWidth(self, width):
        sizes = [item.sizeHint() for item in self._items]
        if width >= self.sizeHint().width(): return self.sizeHint().height()
        return sum(s.height() for s in sizes) + self.spacing() * max(0, len(sizes)-1)

    def minimumHeightForWidth(self, width): return self.heightForWidth(width)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        if not self._items: return
        direction = self.parentWidget().layoutDirection()
        wrap = rect.width() < self.sizeHint().width()
        y = rect.y()
        for index, item in enumerate(self._items):
            hint = item.sizeHint()
            width = min(hint.width(), rect.width())
            height = hint.height()
            x = rect.x() if index == 0 else rect.x() + rect.width() - width
            top = y if wrap else rect.y() + (rect.height()-height)//2
            item.setGeometry(QStyle.visualRect(direction, rect, QRect(x, top, width, height)))
            if wrap: y += height + self.spacing()


def action_group():
    widget = QWidget()
    layout = QHBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    return widget, layout


class ModePreview(QWidget):
    """Small inert schematic. No editor, timer, process or external resources."""
    def __init__(self, mode, parent=None):
        super().__init__(parent)
        self.mode = mode
        self.selected = False
        self.setMinimumSize(190, 112)
        self.setAccessibleName(mode.capitalize() + ' workspace preview')

    def paintEvent(self, event):
        p = QPainter(self)
        c = colors()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.setPen(QColor(c['accent'] if self.selected else c['border']))
        p.setBrush(QColor(c['surface']))
        p.drawRoundedRect(self.rect().adjusted(1, 1, -2, -2), 5, 5)
        p.fillRect(8, 9, 42, 4, QColor(c['muted']))
        p.fillRect(w-42, 7, 32, 10, QColor(c['accent']))
        p.fillRect(8, 22, w-16, 7, QColor(c['border']))
        left = 8
        if self.mode == 'advanced':
            p.fillRect(8, 36, 40, h-45, QColor(c['raised']))
            for y in range(44, h-12, 12):
                p.fillRect(13, y, 27, 3, QColor(c['muted']))
            left = 54
        p.fillRect(left, 36, w-left-8, 25, QColor(c['raised']))
        p.fillRect(left, 66, w-left-8, h-75, QColor(c['raised']))
        for y, fraction in ((43, .60), (51, .38), (74, .70), (82, .45), (90, .55)):
            p.fillRect(left+5, y, max(1, int((w-left-18)*fraction)), 3, QColor(c['muted']))
        p.end()


def choose_workspace_mode(current=None, parent=None, language='en', reduced_motion=False):
    dialog = QDialog(parent)
    dialog.setObjectName('workspace_mode_dialog')
    dialog.setWindowTitle(tr('mode_title', language))
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(16, 16, 16, 16)
    layout.setSpacing(12)
    heading = QLabel(tr('mode_heading', language)); heading.setWordWrap(True); layout.addWidget(heading)
    cards = QHBoxLayout(); group = QButtonGroup(dialog); previews = {}; radios = {}
    for mode in MODES:
        column = QVBoxLayout()
        radio = QRadioButton(tr('mode_'+mode, language)); radio.setObjectName('mode_'+mode)
        radio.setAccessibleDescription(tr('mode_'+mode+'_desc', language))
        group.addButton(radio); radios[mode] = radio
        preview = ModePreview(mode); previews[mode] = preview
        description = QLabel(tr('mode_'+mode+'_desc', language)); description.setWordWrap(True)
        column.addWidget(radio); column.addWidget(preview); column.addWidget(description); column.addStretch()
        cards.addLayout(column, 1)
    layout.addLayout(cards)
    note = QLabel(tr('mode_safety', language)); note.setWordWrap(True); layout.addWidget(note)
    buttons = QHBoxLayout(); buttons.addStretch()
    cancel = QPushButton(tr('mode_cancel', language)); cancel.setObjectName('mode_cancel'); cancel.clicked.connect(dialog.reject)
    proceed = QPushButton(tr('mode_continue', language)); proceed.setObjectName('mode_continue'); proceed.clicked.connect(dialog.accept)
    proceed.setDefault(True); buttons.addWidget(cancel); buttons.addWidget(proceed); layout.addLayout(buttons)
    # Only animate a selection change. No animation on initial paint or when reduced motion is enabled.
    animation = QPropertyAnimation(dialog); animation.setPropertyName(b'opacity'); animation.setDuration(150)
    effects = {}
    if not reduced_motion:
        for mode, preview in previews.items():
            effect = QGraphicsOpacityEffect(preview); effect.setOpacity(1.0); preview.setGraphicsEffect(effect); effects[mode] = effect
    def select(mode, animate):
        animation.stop()
        for key, preview in previews.items():
            preview.selected = key == mode; preview.update()
            if key in effects: effects[key].setOpacity(1.0)
        if animate and mode in effects and dialog.isVisible():
            animation.setTargetObject(effects[mode]); animation.setStartValue(0.70); animation.setEndValue(1.0); animation.start()
    initial = current if current in MODES else DEFAULT_MODE
    radios[initial].setChecked(True); select(initial, False)
    for mode, radio in radios.items():
        radio.toggled.connect(lambda checked, key=mode: select(key, True) if checked else None)
    dialog.resize(500, 280)
    result = dialog.exec()
    animation.stop()
    if result != QDialog.DialogCode.Accepted:
        return None
    return next((mode for mode, radio in radios.items() if radio.isChecked()), None)


class App(QMainWindow):
    def __init__(self):
        super().__init__();self.resize(1180,740);self.setMinimumSize(850,560)
        self.update_handoff = None
        self.settings=read_settings();self.running=False;self.cancelled=False;self.proc=None;self.temp=None;self.journal=None;self.active=None;self.current=None;self.source='Untitled';self.source_hash=None;self.loaded=None;self.task={};self.pending=[];self.blank=False;self.started=0;self.stop_pending=False;self.stop_inflight=False
        self.signals=WorkerSignals();self.signals.hashDone.connect(self.hash_done);self.signals.stopDone.connect(self.stop_done);self.signals.initialTail.connect(self.finish_initial_tail);self.initial_restore_pending=True;self.tool_busy=False;self.task_queue=[];self.signals.toolDone.connect(self.tool_done);self.copy_busy=False;self.signals.copyDone.connect(self.copy_done);self.warm_path=None;self.warm_result=None;self.warm_waiting=False;self.signals.warmDone.connect(self.warm_done)
        self.ui_language=saved_language(self.settings) or 'en'
        self.setWindowTitle(self.ui('window_title').format(version=VERSION))
        self.mode=saved_mode(self.settings) or DEFAULT_MODE
        apply_theme(view.saved_theme(self.settings))
        self.edit_controls=[];self.lib=pathlib.Path(self.settings.get('library') or ROOT/'scripts');
        central=QWidget();self.setCentralWidget(central);v=QVBoxLayout(central);v.setContentsMargins(*WINDOW_MARGINS);v.setSpacing(LAYOUT_GAP)
        leading,row=action_group();h=QLabel('COMMAND RELAY');h.setProperty('role','brand');row.addWidget(h);self.mode_label=QLabel();self.mode_label.setProperty('role','muted');row.addWidget(self.mode_label)
        trailing,row=action_group();self.more=QPushButton(self.ui('more'));row.addWidget(self.more);self.more.setToolTip(self.ui('more_tip'))
        self.header_row=AdaptiveActionRow(leading,trailing);v.addLayout(self.header_row)
        row=QHBoxLayout();row.addWidget(QLabel(self.ui('workspace')));self.cwd=QLineEdit(self.settings.get('workspace') or os.getcwd());row.addWidget(self.cwd,1);self.edit_controls.append(self.cwd);self.btn(row,self.ui('browse'),self.browse,True);self.btn(row,self.ui('profiles'),self.profiles,True);v.addLayout(row)
        leading,row=action_group();self.openbtn=self.btn(row,self.ui('open_file'),self.open,True);self.pastebtn=self.btn(row,self.ui('paste_ai'),self.paste,True)
        trailing,row=action_group();self.stopbtn=self.btn(row,self.ui('stop'),self.stop);self.stopbtn.setEnabled(False);self.runbtn=self.btn(row,self.ui('run_commands'),self.run);self.runbtn.setObjectName('run');self.runbtn.setToolTip(self.ui('run_tip'))
        self.command_row=AdaptiveActionRow(leading,trailing);v.addLayout(self.command_row)
        self.casual_report_ready=False;self.casual_run_title=None;self.casual_style_state=None
        self.casual_hint=QWidget();self.casual_hint.setObjectName('casualCard');v.addWidget(self.casual_hint)
        card=QVBoxLayout(self.casual_hint);card.setContentsMargins(10,7,10,7);card.setSpacing(4)
        flow=QHBoxLayout();flow.setSpacing(4);self.casual_steps={}
        for stage in ('import','review','run','result'):
            label=QLabel(self.ui('casual_'+stage));label.setAlignment(Qt.AlignmentFlag.AlignCenter);label.setWordWrap(True)
            self.casual_steps[stage]=label;flow.addWidget(label,1)
        card.addLayout(flow)
        self.casual_title=QLabel();self.casual_title.setTextFormat(Qt.TextFormat.PlainText);self.casual_title.setProperty('role','casualTitle');self.casual_title.setWordWrap(True);self.casual_title.setAccessibleName(self.ui('casual_title_accessible'));card.addWidget(self.casual_title)
        self.casual_help=QLabel();self.casual_help.setProperty('role','casualHelp');self.casual_help.setWordWrap(True);card.addWidget(self.casual_help)
        split=QSplitter(Qt.Orientation.Horizontal);self.main_split=split;split.setChildrenCollapsible(False);split.setOpaqueResize(True);split.setHandleWidth(SPLITTER_WIDTH);v.addWidget(split,1)
        self.tabs=QTabWidget();self.tabs.setMinimumWidth(175);split.addWidget(self.tabs)
        w=QWidget();l=QVBoxLayout(w);l.setContentsMargins(5,5,5,5);l.addWidget(QLabel(self.ui('live_output')));self.steps=QListWidget();l.addWidget(self.steps,3);l.addWidget(QLabel(self.ui('outline')));self.outline=QListWidget();l.addWidget(self.outline,2);self.tabs.addTab(w,self.ui('steps'));self.steps.itemClicked.connect(lambda item:self.jump(self.output,item));self.outline.itemClicked.connect(lambda item:self.jump(self.editor,item));self.steps.itemActivated.connect(lambda item:self.jump(self.output,item));self.outline.itemActivated.connect(lambda item:self.jump(self.editor,item))
        w=QWidget();l=QVBoxLayout(w);l.addWidget(QLabel(self.ui('library_heading')));self.liblabel=QLabel(str(self.lib));self.liblabel.setWordWrap(True);l.addWidget(self.liblabel);r=QHBoxLayout();self.btn(r,self.ui('folder_ellipsis'),self.choose_lib,True);self.btn(r,self.ui('refresh'),self.refresh_lib);l.addLayout(r);self.libfind=QLineEdit();self.libfind.setPlaceholderText(self.ui('filter_scripts'));l.addWidget(self.libfind);self.library=QListWidget();l.addWidget(self.library,1);self.btn(l,self.ui('load_selected'),self.load_lib,True);self.btn(l,self.ui('save_editor'),self.save_script,True);self.tabs.addTab(w,self.ui('scripts'));self.libfind.textChanged.connect(self.refresh_lib);self.library.itemDoubleClicked.connect(lambda _:self.load_lib())
        right=QSplitter(Qt.Orientation.Vertical);right.setChildrenCollapsible(False);right.setOpaqueResize(True);right.setHandleWidth(SPLITTER_WIDTH);split.addWidget(right);split.setSizes([250,900]);split.setStretchFactor(1,1)
        w=QWidget();l=QVBoxLayout(w);l.setContentsMargins(4,0,0,0);self.command_label=QLabel(self.ui('commands_initial'));self.command_label.setProperty('role','section');r=QHBoxLayout();r.addWidget(self.command_label,1);self.inspector_label=QLabel();self.inspector_label.hide();r.addWidget(self.inspector_label);l.addLayout(r);self.editor=DropEditor();self.editor.setMinimumHeight(100);self.editor.setPlaceholderText(self.ui('editor_placeholder'));self.editor.setProperty('role','code');self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap);l.addWidget(self.editor,1);self.editor.fileDropped.connect(self.load);self.outline_dirty=True;self.outline_timer=QTimer(self);self.outline_timer.setSingleShot(True);self.outline_timer.setInterval(OUTLINE_DELAY_MS);self.outline_timer.timeout.connect(self.refresh_outline);self.editor.textChanged.connect(self.invalidate_outline);self.inspector_timer=QTimer(self);self.inspector_timer.setSingleShot(True);self.inspector_timer.setInterval(220);self.inspector_timer.timeout.connect(self.update_inspector);self.editor.textChanged.connect(lambda:self.inspector_timer.start());self.editor_highlight=Highlight(self.editor.document());right.addWidget(w)
        w=QWidget();l=QVBoxLayout(w);l.setContentsMargins(4,0,0,0);r=QHBoxLayout();self.output_label=QLabel(self.ui('terminal_initial'));self.output_label.setProperty('role','section');r.addWidget(self.output_label);r.addStretch();self.dense=QCheckBox(self.ui('dense'),w);self.dense.setChecked(self.settings.get('dense_output',True));self.wrap=QCheckBox(self.ui('wrap'),w);self.wrap.setChecked(self.settings.get('wrap_output',True));self.follow=QCheckBox(self.ui('follow'));self.follow.setChecked(True)
        # Follow remains a visible live control; rarely changed options live in More.
        self.dense.hide();self.wrap.hide();r.addWidget(self.follow);self.btn(r,self.ui('find'),self.toggle_search)
        l.addLayout(r);self.searchbar=QWidget();r=QHBoxLayout(self.searchbar);r.setContentsMargins(0,0,0,0);self.search=QLineEdit();self.search.setPlaceholderText(self.ui('find_output'));r.addWidget(self.search,1);self.find_previous=self.btn(r,'↑',lambda:self.find(True));self.find_next=self.btn(r,'↓',lambda:self.find(False));self.close_search=self.btn(r,'×',self.hide_search);l.addWidget(self.searchbar);self.searchbar.hide();self.search.returnPressed.connect(lambda:self.find(False));self.output=QPlainTextEdit();self.output.setReadOnly(True);self.output.setUndoRedoEnabled(False);self.output.setMaximumBlockCount(6000);self.output.setProperty('role','code');self.output_highlight=Highlight(self.output.document());l.addWidget(self.output,1);right.addWidget(w);right.setSizes([240,430]);right.setStretchFactor(1,1);self.wrap.toggled.connect(self.apply_wrap);self.dense.toggled.connect(self.reload_tail);self.apply_wrap()
        r=QHBoxLayout();self.detail=QLabel(self.ui('import_hint'));r.addWidget(self.detail,1);self.copy_button(r,lambda mode:self.copy_report(mode));self.btn(r,self.ui('history'),self.history);v.addLayout(r)
        # Keep the primary actions at their natural text-dependent width.
        # Fixed is a size policy, not a pixel width; Qt recalculates sizeHint
        # when the label, font or style changes.
        for button in (self.more, self.runbtn):
            sizing = button.sizePolicy()
            sizing.setHorizontalPolicy(QSizePolicy.Policy.Fixed)
            button.setSizePolicy(sizing)
        self.configure_accessibility()
        self.build_more_menu()
        self.activity=ActivityBar(self);v.addWidget(self.activity)
        self.activity.set_reduced_motion(self.motion_action.isChecked())
        self.motion_action.toggled.connect(self.activity.set_reduced_motion)
        self.statusBar().setSizeGripEnabled(False)
        self.set_status('ready',self.ui('ready'))
        self.timer=QTimer(self);self.timer.setInterval(OUTPUT_INTERVAL_MS);self.timer.timeout.connect(self.flush_view);self.clock=QTimer(self);self.clock.setInterval(CLOCK_INTERVAL_MS);self.clock.timeout.connect(self.update_clock)
        for key,fn in [('Ctrl+O',self.open),('Ctrl+Return',self.run),('Ctrl+F',self.show_search),('F3',lambda:self.find(False)),('Shift+F3',lambda:self.find(True)),('Ctrl+Shift+C',lambda:self.copy_report('full'))]:QShortcut(QKeySequence(key),self).activated.connect(fn)
        self.tabs.currentChanged.connect(self.load_library_on_tab)
        self.editor.textChanged.connect(self.invalidate_casual_result)
        self.cwd.textChanged.connect(self.invalidate_casual_result)
        self.apply_mode(self.mode)
        QTimer.singleShot(0, self.start_initial_restore)
    def ui(self, key):
        return tr(key, self.ui_language)

    def configure_accessibility(self):
        # Keep the visible workbench compact; expose meaning to keyboard and assistive tools.
        for control, name in ((self.cwd, self.ui('working_directory')), (self.editor, self.ui('command_editor')),
                              (self.output, self.ui('terminal_accessible')), (self.steps, self.ui('execution_steps')),
                              (self.outline, self.ui('command_outline')), (self.library, self.ui('script_library')),
                              (self.libfind, self.ui('filter_scripts')), (self.search, self.ui('find_output')),
                              (self.tabs, self.ui('sidebar')), (self.detail, self.ui('status_accessible')),
                              (self.inspector_label, self.ui('inspector_accessible')), (self.more, self.ui('more_accessible')),
                              (self.runbtn, self.ui('run_accessible')), (self.stopbtn, self.ui('stop_accessible'))):
            control.setAccessibleName(name)
        for control, name in ((self.find_previous, self.ui('previous_match')),
                              (self.find_next, self.ui('next_match')),
                              (self.close_search, self.ui('close_search'))):
            control.setAccessibleName(name);control.setToolTip(name)
        self.follow.setAccessibleDescription(self.ui('follow_desc'))
        self.editor.setAccessibleDescription(self.ui('editor_desc'))
        self.output.setAccessibleDescription(self.ui('output_desc'))
    def build_more_menu(self):
        menu=QMenu(self.more);menu.setObjectName('workbench_more');self.more.setMenu(menu)
        def action(parent,label,fn,edit=False):
            a=parent.addAction(label);a.triggered.connect(lambda checked=False:fn())
            if edit:self.edit_controls.append(a)
            return a
        action(menu,self.ui('copy_session'),self.copy_session_context,True)
        action(menu,self.ui('clear_editor'),self.clear,True)
        menu.addSeparator()
        ctx=menu.addMenu(self.ui('project'))
        action(ctx,self.ui('project_context'),self.project_context,True)
        action(ctx,self.ui('ai_context'),self.ai_context,True)
        git=menu.addMenu('Git')
        action(git,self.ui('git_dashboard'),self.dashboard,True)
        action(git,self.ui('github_prs'),self.github_prs,True)
        git.addSeparator()
        for name in GIT_ACTIONS:action(git,name,lambda n=name:self.run_git(n),True)
        reports=menu.addMenu(self.ui('reports'))
        # Named alternatives to modifier-click, including a conspicuous raw warning.
        self.copy_ai_action=action(reports,self.ui('copy_ai'),lambda:self.copy_report('ai'))
        self.copy_text_action=action(reports,self.ui('copy_compact'),lambda:self.copy_report('compact'))
        self.copy_raw_action=action(reports,self.ui('copy_raw'),lambda:self.copy_report('full'))
        reports.addSeparator()
        action(reports,self.ui('metrics_latest'),self.latest_metrics,True)
        action(reports,self.ui('open_latest'),lambda:self.open_path(REPORTS/'latest.txt'))
        action(reports,self.ui('folder'),lambda:self.open_path(REPORTS))
        action(menu,self.ui('queue'),self.queue_dialog,True)
        action(menu,self.ui('sha_file'),self.hash_tool,True)
        menu.addSeparator()
        # One settings entry for current preferences and future language/update tools.
        self.settings_menu=menu.addMenu(self.ui('settings'));self.settings_menu.setObjectName('workbench_settings')
        self.safety_action=action(self.settings_menu,self.ui('safety_settings'),self.safety_settings,True)
        self.safety_action.setObjectName('settings_safety')
        self.updates_action=action(self.settings_menu,self.ui('updates'),self.updates_settings,True)
        self.updates_action.setObjectName('settings_updates')
        self.language_action=action(self.settings_menu,self.ui('language_settings'),self.language_settings,True)
        self.language_action.setObjectName('settings_language')
        self.mode_action=action(self.settings_menu,self.ui('mode_settings'),self.mode_settings,True)
        self.mode_action.setObjectName('settings_mode')
        self.settings_menu.addSeparator()
        self.theme_action=self.settings_menu.addAction(self.ui('light_theme'))
        self.theme_action.setObjectName('settings_light_theme');self.theme_action.setCheckable(True)
        self.theme_action.setChecked(view.saved_theme(self.settings)=='light')
        self.theme_action.toggled.connect(self.theme_settings)
        self.edit_controls.append(self.theme_action)
        self.sidebar_action=self.settings_menu.addAction(self.ui('show_sidebar'));self.sidebar_action.setObjectName('settings_sidebar');self.sidebar_action.setCheckable(True)
        self.sidebar_action.setChecked(sidebar_preference(self.settings,self.mode))
        self.sidebar_action.toggled.connect(self.set_sidebar_visible)
        self.motion_action=self.settings_menu.addAction(self.ui('reduced_motion'));self.motion_action.setObjectName('settings_reduced_motion');self.motion_action.setCheckable(True)
        self.motion_action.setChecked(self.settings.get('reduced_motion') is True)
        self.motion_action.toggled.connect(lambda value: self.settings.update(reduced_motion=value))
        for label,control in [(self.ui('wrap_output'),self.wrap),(self.ui('dense_output'),self.dense)]:
            a=self.settings_menu.addAction(label);a.setObjectName('settings_wrap' if control is self.wrap else 'settings_dense');a.setCheckable(True);a.setChecked(control.isChecked());a.toggled.connect(control.setChecked);control.toggled.connect(a.setChecked)
            if control is self.dense:self.edit_controls.append(a)
        action(menu,self.ui('find_in_output'),self.show_search)
    def theme_settings(self, light):
        theme = 'light' if light else 'dark'
        previous = view.saved_theme(self.settings)
        if theme == previous:
            return
        try:
            atomic_text(SETTINGS, json.dumps({**read_settings(), **self.settings, 'theme': theme}, ensure_ascii=False, indent=2))
        except OSError as exc:
            self.theme_action.blockSignals(True)
            try: self.theme_action.setChecked(previous == 'light')
            finally: self.theme_action.blockSignals(False)
            return self.error(exc)
        self.settings['theme'] = theme
        apply_theme(theme)
        self.editor_highlight.refresh_theme();self.output_highlight.refresh_theme()
        self.activity.update()
        self.style_inspector()
        self.refresh_casual()

    def set_sidebar_visible(self, visible):
        self.tabs.setVisible(visible)
        key = 'show_sidebar_casual' if self.mode == 'casual' else 'show_sidebar'
        self.settings[key] = bool(visible)
        self.schedule_outline()

    def apply_mode(self, mode):
        # Only presentation changes: same editor, inspector, output, actions and engine.
        if mode not in MODES:
            raise ValueError('Unknown workspace mode')
        self.mode = mode
        casual = mode == 'casual'
        self.mode_label.setText(f'{VERSION}  /  {mode.upper()}')
        self.casual_hint.setVisible(casual)
        self.openbtn.setText(self.ui('open_task') if casual else self.ui('open_file'))
        self.pastebtn.setText(self.ui('paste_task') if casual else self.ui('paste_ai'))
        self.runbtn.setText(self.ui('run_short') if casual else self.ui('run_commands'))
        visible = sidebar_preference(self.settings, mode)
        self.sidebar_action.setChecked(visible)
        self.tabs.setVisible(visible)
        self.schedule_outline()
        self.refresh_casual()

    def invalidate_casual_result(self):
        self.casual_report_ready=False;self.casual_run_title=None
        self.refresh_casual()

    def refresh_casual(self):
        if self.mode != 'casual':
            return
        raw=self.editor.toPlainText()
        stage=casual_stage(bool(raw.strip()),self.running,self.casual_report_ready)
        title=casual_task_title(self.task,self.source,has_script=bool(raw.strip()),
                               edited=raw!=self.loaded,language=self.ui_language)
        if stage in ('run','result') and self.casual_run_title:
            title=self.casual_run_title
        if self.casual_title.text()!=title:self.casual_title.setText(title)
        help_key={'import':'casual_import_help','review':'casual_review_help',
                  'run':'casual_running_help','result':'casual_result_help'}[stage]
        self.casual_help.setText(self.ui(help_key))
        self.casual_hint.setAccessibleName(self.ui('casual_stage_accessible').format(stage=self.ui('casual_'+stage)))
        style_state=(stage,current_theme())
        if self.casual_style_state==style_state:return
        self.casual_style_state=style_state
        c=colors()
        for key,label in self.casual_steps.items():
            active=key==stage
            label.setStyleSheet('QLabel { padding:3px; border-radius:4px; font-weight:%s; background:%s; color:%s; }' %
                                ('600' if active else '400',c['accent'] if active else c['raised'],c['on_accent'] if active else c['muted']))

    def show_search(self):
        self.searchbar.show();self.search.setFocus();self.search.selectAll()
    def hide_search(self):
        self.searchbar.hide();self.output.setFocus()
    def toggle_search(self):
        if self.searchbar.isVisible():self.hide_search()
        else:self.show_search()
    def load_library_on_tab(self, index):
        self.schedule_outline()
        if index == 1:
            self.refresh_lib()
    def start_initial_restore(self):
        startup_mark('event_loop_ms')
        latest=REPORTS/'latest.txt'
        if not self.initial_restore_pending or self.running:
            save_startup_marks()
            return
        if self.source=='Untitled':self.detail.setText(self.ui('restoring'))
        def work():
            try:
                data=view.read_tail(latest)
                self.signals.initialTail.emit(latest,data,None)
            except FileNotFoundError:
                self.signals.initialTail.emit(latest,None,None)
            except OSError as e:
                self.signals.initialTail.emit(latest,None,str(e))
        threading.Thread(target=work,daemon=True).start()
    def finish_initial_tail(self,path,data,error):
        startup_mark('restore_read_ms')
        if not self.initial_restore_pending or self.running:
            save_startup_marks()
            return
        self.initial_restore_pending=False
        if error:
            self.detail.setText('Restore failed: '+error)
        elif data is not None:
            self.current=path;self.output_label.setText(self.ui('terminal_previous'))
            if self.dense.isChecked():data=re.sub(r'\n{3,}','\n\n',data)
            # Avoid inserting blocks that Qt would immediately discard.
            data=view.visible_tail(data)
            self.output.setPlainText(data);self.refresh_steps();self.output.moveCursor(QTextCursor.MoveOperation.End)
            if self.source=='Untitled':self.detail.setText(self.ui('restored'))
        elif self.source=='Untitled':
            self.detail.setText(self.ui('import_hint'))
        startup_mark('restore_finished_ms');save_startup_marks()
    def btn(self,layout,title,fn,edit=False):
        b=QPushButton(title);b.clicked.connect(lambda checked=False:fn());layout.addWidget(b)
        if edit:self.edit_controls.append(b)
        return b
    def copy_button(self,layout,action):
        button=self.btn(layout,self.ui('copy'),lambda:action(self.copy_modifier_mode()))
        button.setToolTip(self.ui('copy_tip'))
        button.setAccessibleName(self.ui('copy_accessible'))
        button.setAccessibleDescription(self.ui('copy_tip'))
        return button
    def copy_modifier_mode(self):
        mods=QApplication.keyboardModifiers()
        return copy_mode(bool(mods & Qt.KeyboardModifier.ControlModifier),bool(mods & Qt.KeyboardModifier.ShiftModifier))
    def set_status(self,kind,text):
        bar=self.statusBar()
        color=STATUS_COLORS[kind]
        bar.setStyleSheet(f'QStatusBar {{background:{color}; color:#ffffff;}} QStatusBar QLabel {{background:transparent;color:#ffffff;}} QStatusBar::item {{border:0;}}')
        bar.showMessage('●  '+text)
    def error(self,s):QMessageBox.warning(self,'Command Relay',str(s))
    def browse(self):
        d=QFileDialog.getExistingDirectory(self,'Workspace',self.cwd.text())
        if d:self.cwd.setText(d)
    def apply_wrap(self):self.output.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth if self.wrap.isChecked() else QPlainTextEdit.LineWrapMode.NoWrap)
    def choose_lib(self):
        p=QFileDialog.getExistingDirectory(self,'Script library',str(self.lib))
        if p:self.lib=pathlib.Path(p);self.liblabel.setText(p);self.refresh_lib()
    def refresh_lib(self):
        self.library.clear()
        try:
            self.lib.mkdir(parents=True,exist_ok=True)
            for p in sorted(self.lib.iterdir()):
                if p.is_file() and p.suffix.lower() in ('.txt','.ps1','.md','.json') and self.libfind.text().lower() in p.name.lower():self.library.addItem(p.name)
        except OSError as e:self.detail.setText(str(e))
    def load_lib(self):
        if self.library.currentItem():self.load(str(self.lib/self.library.currentItem().text()))
    def save_script(self):
        p,_=QFileDialog.getSaveFileName(self,'Save script',str(self.lib/'script.txt'),'Scripts (*.txt *.ps1)')
        if p:
            try:atomic_text(pathlib.Path(p),self.editor.toPlainText());self.refresh_lib()
            except OSError as e:self.error(e)
    def open(self):
        if self.running:return
        p,_=QFileDialog.getOpenFileName(self,'Open task or script','','Commands (*.txt *.ps1 *.md *.json);;All files (*)')
        if p:self.load(p)
    def load(self,path):
        if self.running:return
        try:
            p=pathlib.Path(path);data=p.read_bytes();self.import_data(data,p.name,sha(data))
        except (OSError,ValueError,UnicodeError) as e:self.error(e)
    def import_data(self,data,name,digest=None):
        script,task=load_input(data);self.task=task;self.source=name;self.editor.setPlainText(script);self.loaded=self.editor.toPlainText();self.source_hash=digest;self.command_label.setText(self.ui('commands_prefix')+name);self.detail.setText(self.ui('imported') if task else 'Loaded '+name)
        # Import is a preview only. Keep metadata available without blocking the UI.
        metadata = '\n'.join(f'{k}: {v}' for k,v in task.items() if v)
        self.command_label.setToolTip(metadata or 'Loaded script: '+name)
        self.detail.setToolTip(metadata or '')
        if task:
            task_id = task.get('task_id') or task.get('title') or name
            self.detail.setText('AI task loaded: '+task_id.replace('\n',' ').replace('\r',' ')[:80]+' — review before running')
        self.invalidate_casual_result()
    def paste(self):
        if not self.running:
            try:self.import_data(QApplication.clipboard().text().encode(),'Clipboard')
            except ValueError as e:self.error(e)
    def clear(self):
        if not self.running:self.import_data(b'','Untitled')
    def update_inspector(self, prepared=None):
        raw=self.editor.toPlainText()
        result=privacy.inspect_script(raw if prepared is None else prepared)
        level=result['level'];matches=result['matches']
        self.inspector_label.setVisible(level!='none')
        self.inspector_label.setText('⚠ Review commands' if level=='high' else 'Review effects')
        self.inspector_label.setProperty('risk_level',level);self.style_inspector()
        self.inspector_label.setToolTip('\n'.join(m['label'] for m in matches)+('\nScan limited.' if result['scan_limited'] else '')+'\n'+result['note'])
        return result
    def style_inspector(self):
        self.inspector_label.setStyleSheet('color:'+colors()['error' if self.inspector_label.property('risk_level')=='high' else 'warning']+';font-weight:600')

    def invalidate_outline(self):
        self.outline_dirty=True
        # Existing row offsets are stale until the next coalesced rebuild.
        self.outline.setEnabled(False)
        self.schedule_outline()

    def schedule_outline(self):
        if self.outline_dirty and not self.tabs.isHidden() and self.tabs.currentIndex()==0:
            self.outline_timer.start()
        else:
            self.outline_timer.stop()

    def refresh_outline(self):
        self.outline_timer.stop()
        if not self.outline_dirty or self.tabs.isHidden() or self.tabs.currentIndex()!=0:
            return
        self.outline.setUpdatesEnabled(False)
        try:
            self.outline.clear()
            block=self.editor.document().firstBlock()
            while block.isValid():
                m=MARK.match(block.text())
                if m:
                    self.outline.addItem(m.group(1))
                    self.outline.item(self.outline.count()-1).setData(Qt.ItemDataRole.UserRole,block.blockNumber())
                block=block.next()
            self.outline_dirty=False
            self.outline.setEnabled(True)
        finally:
            self.outline.setUpdatesEnabled(True)

    def jump(self,widget,item):
        if widget is self.editor and self.outline_dirty:return
        if widget is self.output:self.follow.setChecked(False)
        b=widget.document().findBlockByNumber(item.data(Qt.ItemDataRole.UserRole));
        if b.isValid():widget.setTextCursor(QTextCursor(b));widget.centerCursor()
    def refresh_steps(self):
        self.steps.clear();b=self.output.document().firstBlock()
        while b.isValid():
            m=MARK.match(b.text())
            if m:self.steps.addItem(m.group(1));self.steps.item(self.steps.count()-1).setData(Qt.ItemDataRole.UserRole,b.blockNumber())
            b=b.next()
    def find(self,back):
        text=self.search.text()
        if not text:return
        self.follow.setChecked(False);flags=QTextDocument.FindFlag.FindBackward if back else QTextDocument.FindFlag(0)
        if not self.output.find(text,flags):self.output.moveCursor(QTextCursor.MoveOperation.End if back else QTextCursor.MoveOperation.Start);self.output.find(text,flags)
    def open_path(self,path):
        try:
            if path==REPORTS:path.mkdir(exist_ok=True)
            if not path.exists():raise ValueError('No file yet')
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        except (OSError,ValueError) as e:self.error(e)
    def reload_tail(self):
        if self.running:return
        if self.current and self.current.exists():
            try:
                data=view.read_tail(self.current)
                self.output.setPlainText(view.visible_tail(re.sub(r'\n{3,}','\n\n',data) if self.dense.isChecked() else data));self.refresh_steps();self.output.moveCursor(QTextCursor.MoveOperation.End)
            except OSError as e:self.error(e)
    def set_busy(self,b):
        self.running=b;self.editor.set_file_drop_active(False);self.editor.setReadOnly(b);self.runbtn.setEnabled(not b and not self.stop_inflight);self.stopbtn.setEnabled(b and not self.stop_pending)
        for c in self.edit_controls:c.setEnabled(not b)
        self.activity.set_running(b)
        if b:
            self.timer.start();self.clock.start()
        else:
            self.timer.stop();self.clock.stop()
        if b:
            self.casual_report_ready=False
            self.set_status('running',self.ui('running'))
        self.refresh_casual()
    def begin(self,name,header):
        raw=self.editor.toPlainText()
        self.casual_run_title=casual_task_title(self.task if name==self.source else {},name,
            has_script=True,edited=name==self.source and raw!=self.loaded,language=self.ui_language)
        self.initial_restore_pending=False
        self.current=None;self.warm_result=None
        REPORTS.mkdir(exist_ok=True);stamp=datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f');self.active=REPORTS/f'report-{stamp}.partial.txt';self.journal=self.active.open('x',encoding='utf-8',newline='');self.started=time.monotonic();self.cancelled=False;self.pending=[];self.stop_pending=False;self.decoder=codecs.getincrementaldecoder('utf-8')('replace');self.set_busy(True);self.output.clear();self.steps.clear();self.follow.setChecked(True);self.output_label.setText(self.ui('terminal_prefix')+name);self.append(header);self.tabs.setCurrentIndex(0)
    def header(self,name,extra=''):
        return f'COMMAND RELAY REPORT\nStarted: {datetime.datetime.now().isoformat(timespec="seconds")}\nWorking directory: {self.cwd.text()}\nCommand file: {name}\n{extra}\n'
    def run(self):
        if self.running or self.stop_inflight:return
        if self.copy_busy:self.detail.setText('Wait for Copied before starting another run');return
        raw=self.editor.toPlainText();cwd=self.cwd.text()
        if not raw.strip() or not pathlib.Path(cwd).is_dir():return self.error('Enter a script and valid workspace')
        try:script=prepare(raw)
        except ValueError as e:return self.error(e)
        inspection=self.update_inspector(script)
        if inspection['level']=='high':
            labels='\n'.join('• '+m['label'] for m in inspection['matches'] if m['level']=='high')
            answer=QMessageBox.question(self,self.ui('review_commands'),
                self.ui('review_risk_intro')+labels+self.ui('review_risk_end'),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)
            if answer!=QMessageBox.StandardButton.Yes:return
        source=self.source_hash if raw==self.loaded and self.source_hash else 'not applicable (pasted or edited)';taskid=self.task.get('task_id','').replace('\n',' ').replace('\r',' ')
        metadata_obj=intelligence.run_metadata(cwd,self.task,raw==self.loaded);metadata_obj['inspector']=inspection
        metadata=json.dumps(metadata_obj,ensure_ascii=True,separators=(',',':'),allow_nan=False)
        header=self.header(self.source,f'Command SHA256: {sha(raw.encode())}\nSource file SHA256: {source}\nPrepared script SHA256: {sha(script.encode("utf-8-sig"))}\n'+(f'Task ID: {taskid}\n' if taskid else '')+f'Relay metadata: {metadata}\n')
        if not self.confirm_repeat(comparison.previous_run(REPORTS,header)):return
        # Import never runs commands. Explicit Run (and confirmations, if needed) authorizes execution.
        try:
            with tempfile.NamedTemporaryFile(suffix='.ps1',delete=False,mode='wb') as f:self.temp=pathlib.Path(f.name);f.write(script.encode('utf-8-sig'))
            self.begin(self.source,header)
            self.start_process('powershell.exe',['-NoLogo','-NoProfile','-NonInteractive','-File',str(self.temp)])
        except OSError as e:self.error(e);self.cleanup_temp();self.set_busy(False);self.set_status('failed',self.ui('start_failed'))
    def confirm_repeat(self, previous):
        status=previous['status']
        if status in ('not_applicable','no_match'):return True
        if status=='matched':
            text=self.ui('repeat_report')+previous['report_file']+self.ui('repeat_verdict')+previous['verdict']
            if previous.get('process_exit') is not None:text+=self.ui('repeat_exit')+str(previous['process_exit'])
        else:text=self.ui('repeat_unknown')
        if previous.get('reason'):text+='\n'+previous['reason']
        text+=self.ui('repeat_warning')
        dialog=QMessageBox(QMessageBox.Icon.Warning,self.ui('repeat_title'),text,parent=self)
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        run=dialog.addButton(self.ui('repeat_run'),QMessageBox.ButtonRole.AcceptRole)
        cancel=dialog.addButton(QMessageBox.StandardButton.Cancel)
        cancel.setText(self.ui('confirm_cancel'))
        dialog.setDefaultButton(cancel);dialog.setEscapeButton(cancel)
        dialog.exec()
        return dialog.clickedButton() is run
    def run_git(self,action):
        if self.running or self.stop_inflight:return
        if self.copy_busy:self.detail.setText('Wait for Copied before starting another run');return
        if not pathlib.Path(self.cwd.text()).is_dir():return self.error('Select a valid workspace')
        try:
            metadata=json.dumps(intelligence.run_metadata(self.cwd.text(),{},True),separators=(',',':'))
            self.begin(action,self.header('Built-in: '+action,'Relay metadata: '+metadata+'\nOperation: read-only Git\n'));self.start_process('git',git_args(action))
        except OSError as e:self.error(e);self.set_busy(False);self.set_status('failed',self.ui('start_failed'))
    def start_process(self,exe,args):
        self.proc=QProcess(self);self.proc.setWorkingDirectory(self.cwd.text());self.proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels);self.proc.readyReadStandardOutput.connect(self.read_process);self.proc.finished.connect(self.process_finished);self.proc.errorOccurred.connect(self.process_error);self.proc.start(exe,args);self.proc.closeWriteChannel()
    def read_process(self):
        if self.proc:self.append(self.decoder.decode(bytes(self.proc.readAllStandardOutput())))
    def process_error(self,error):
        if error==QProcess.ProcessError.FailedToStart and self.running:self.append('\nRunner error: '+self.proc.errorString()+'\n');self.finish(None)
    def process_finished(self,code,status):
        if not self.running:return
        self.read_process();self.append(self.decoder.decode(b'',final=True));self.finish(code if status==QProcess.ExitStatus.NormalExit else (code or 1))
    def append(self,text):
        if not text:return
        if self.journal:
            try:self.journal.write(text);self.journal.flush()
            except OSError as e:self.detail.setText('Recovery log error: '+str(e));self.journal.close();self.journal=None
        self.pending.append(text)
        if not self.running:self.flush_view()
    def flush_view(self):
        if not self.pending:return
        text=''.join(self.pending);self.pending=[]
        if self.dense.isChecked():text=re.sub(r'\n{3,}','\n\n',text)
        # Bound the GUI even for pathological output without newline characters.
        # The journal was already written by append(); this does not affect Copy.
        clipped=self.output.document().characterCount()+len(text)>view.MAX_CHARS
        if clipped:
            self.output.setPlainText(view.visible_tail(self.output.toPlainText()+text))
        else:
            cur=QTextCursor(self.output.document());cur.movePosition(QTextCursor.MoveOperation.End);cur.insertText(text)
        if self.follow.isChecked():self.output.moveCursor(QTextCursor.MoveOperation.End)
        if clipped or '@step' in text.lower():self.refresh_steps()
    def cleanup_temp(self):
        if self.temp:
            try:self.temp.unlink(missing_ok=True)
            except OSError:pass
            self.temp=None
    def finish(self,code):
        self.append(f'\n@step END\nProcess exit code: {code}\nCancelled: {self.cancelled}\nFinished: {datetime.datetime.now().isoformat(timespec="seconds")}\n');self.flush_view();self.cleanup_temp()
        if self.proc:self.proc.deleteLater();self.proc=None
        try:
            if self.journal is None:raise OSError('Recovery log was interrupted; partial report retained')
            self.journal.close();self.journal=None;archive=self.active.with_name(self.active.name.replace('.partial.txt','.txt'));os.replace(self.active,archive);self.current=archive
            fd,tmp=tempfile.mkstemp(dir=REPORTS,prefix='.latest-',suffix='.tmp');os.close(fd)
            try:shutil.copyfile(archive,tmp);os.replace(tmp,REPORTS/'latest.txt')
            finally:pathlib.Path(tmp).unlink(missing_ok=True)
            self.detail.setText('Saved '+archive.name)
        except OSError as e:self.current=self.active if self.active.exists() else self.current;self.detail.setText('Save failed: '+str(e))
        self.casual_report_ready=bool(self.current and self.current!=self.active and self.current.is_file())
        self.set_busy(False)
        elapsed=int(time.monotonic()-self.started)
        kind='cancelled' if self.cancelled else 'success' if code==0 else 'failed'
        label='CANCELLED' if self.cancelled else 'EXIT 0' if code==0 else f'FAILED / EXIT {code}'
        self.set_status(kind,f'{label}  |  {elapsed}s  |  PowerShell')
        if self.current and self.current!=self.active:self.warm_export(self.current)
    def update_clock(self):
        if self.running:
            self.statusBar().showMessage(f"●  {self.ui('clock_stopping' if self.stop_pending else 'clock_running')}  |  {int(time.monotonic()-self.started)}s  |  {self.ui('clock_log')}")
            if self.output.blockCount()>=6000:self.refresh_steps()
    def stop(self):
        if not self.running or not self.proc or self.stop_pending:return
        if QMessageBox.question(self,self.ui('stop_title'),self.ui('stop_confirm'))!=QMessageBox.StandardButton.Yes:return
        self.cancelled=True;self.stop_pending=True;self.stopbtn.setEnabled(False);self.set_status('stopping',self.ui('stopping'));pid=self.proc.processId();token=self.active
        if sys.platform=='win32' and pid:
            self.stop_inflight=True
            def work():
                try:r=subprocess.run(['taskkill','/PID',str(pid),'/T','/F'],capture_output=True,timeout=10,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0));self.signals.stopDone.emit(token,r.returncode==0)
                except (OSError,subprocess.TimeoutExpired):self.signals.stopDone.emit(token,False)
            threading.Thread(target=work,daemon=True).start()
        else:self.proc.kill()
    def stop_done(self,token,ok):
        self.stop_inflight=False
        if not self.running:self.runbtn.setEnabled(True)
        if self.running and self.active==token and self.proc and not ok:self.proc.kill();self.append('\nRunner warning: process-tree termination not confirmed.\n')
    def hash_tool(self):
        if self.running:return
        p,_=QFileDialog.getOpenFileName(self,'Compute SHA-256')
        if not p:return
        self.detail.setText('Hashing selected file…')
        def work():
            try:self.signals.hashDone.emit(p,file_hash(p))
            except OSError as e:self.signals.hashDone.emit(p,'ERROR: '+str(e))
        threading.Thread(target=work,daemon=True).start()
    def hash_done(self,path,digest):
        box=QMessageBox(self);box.setWindowTitle('SHA-256');box.setText(path+'\n'+digest);copy=box.addButton('Copy result',QMessageBox.ButtonRole.ActionRole);box.addButton(QMessageBox.StandardButton.Close);box.exec()
        if box.clickedButton()==copy:QApplication.clipboard().setText(privacy.protect_text('FILE='+path+'\nSHA256='+digest)[0])
        self.detail.setText('Hash operation complete')
    def copy_session_context(self):
        if self.running or self.copy_busy:return self.error('Finish the current run or copy first')
        cwd=self.cwd.text()
        if not pathlib.Path(cwd).is_dir():return self.error('Select a valid workspace')
        self.copy_busy=True;self.detail.setText('Preparing session context…')
        def work():
            try:
                packet=privacy.protect_packet(session.session_packet(REPORTS,cwd))
                out=json.dumps(packet,ensure_ascii=False,separators=(',',':'),allow_nan=False)
                self.signals.copyDone.emit(('session context',str(len(packet['runs']))+' runs',None,packet['privacy']['replacements']),out,None)
            except Exception as e:self.signals.copyDone.emit(('session context','',None,0),None,'Could not prepare protected session export')
        threading.Thread(target=work,daemon=True).start()
    def review_session_context(self):
        if self.running or self.copy_busy:return self.error('Finish the current run or copy first')
        cwd=self.cwd.text()
        if not pathlib.Path(cwd).is_dir():return self.error('Select a valid workspace')
        self.start_tool('Workspace session context',lambda:session.session_packet(REPORTS,cwd))
    def warm_export(self,path):
        # One bounded speculative worker. Never write to clipboard on completion.
        if self.warm_path is not None or self.copy_busy:return
        self.warm_path=path
        def work():
            try:prepared=exports.build_ai(path,warm=True)
            except Exception:prepared=None
            try:self.signals.warmDone.emit(path,prepared)
            except RuntimeError:pass # window closed while preparing an optional export
        threading.Thread(target=work,daemon=True).start()
    def warm_done(self,path,prepared):
        if path!=self.warm_path:return
        waiting=self.warm_waiting
        self.warm_path=None;self.warm_waiting=False
        if prepared is not None and not prepared.fresh():prepared=None
        if prepared is not None and self.current==path and not self.running:
            self.warm_result=prepared
            if not waiting and not self.copy_busy:
                # Do not replace status/error messages or clipboard content.
                self.detail.setToolTip('AI result prepared locally. Click Copy to share; review before sending.')
        if waiting:
            if prepared is not None:self.copy_done(prepared.info,prepared.text,None)
            else:self.start_copy_worker(path,'ai')
    def start_copy_worker(self,p,mode):
        threading.Thread(target=lambda:self.signals.copyDone.emit(*exports.build_copy(p,mode)),daemon=True).start()
    def copy_report(self,mode,path=None):
        if self.running and path is None:return self.error('Wait for completion or choose a historical report')
        p=path or self.current
        if not p:return self.error('No report selected')
        if self.copy_busy:self.detail.setText('Preparing previous copy…');return
        self.copy_busy=True;self.detail.setText('Preparing '+mode+'…')
        if mode=='ai':
            cached=self.warm_result
            if cached is not None and cached.path==p:
                if cached.fresh():self.copy_done(cached.info,cached.text,None);return
                self.warm_result=None
            if self.warm_path==p:
                self.warm_waiting=True;return
        self.start_copy_worker(p,mode)
    def copy_done(self,info,out,error):
        self.copy_busy=False
        if error:self.detail.setText('Copy failed');return self.error(error)
        mode,name,verdict,masked=info;QApplication.clipboard().setText(out)
        self.detail.setText('Copied '+mode+' — '+name+(' | Checks: '+verdict if verdict and verdict!='NOT_REQUESTED' else '')+(' | Masked: '+str(masked) if masked else '')+(' | RAW' if mode=='full' else ''))
        self.detail.setToolTip('Raw copy: no privacy masking. Review before sharing.' if mode=='full' else 'Best-effort masking only. Review before sharing. Checks apply to declared assertions before masking.')
    def start_tool(self,title,work):
        if self.tool_busy:return self.error('Another local tool is running')
        self.tool_busy=True;self.detail.setText(title+'…')
        def worker():
            try:self.signals.toolDone.emit(title,privacy.protect_packet(work()),None)
            except Exception as e:self.signals.toolDone.emit(title,None,'Local tool could not prepare export')
        threading.Thread(target=worker,daemon=True).start()
    def tool_done(self,title,result,error):
        self.tool_busy=False
        if error:self.detail.setText(title+' failed');return self.error(error)
        self.detail.setText(title+' ready — local only')
        text=json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)
        d=QDialog(QApplication.activeModalWidget() or self);d.setWindowTitle(title);d.resize(850,580);l=QVBoxLayout(d)
        l.addWidget(QLabel('Best-effort masking applied. Review before copying or saving; no automatic sharing.'))
        ed=QPlainTextEdit(text);ed.setReadOnly(True);ed.setProperty('role','code');l.addWidget(ed,1)
        row=QHBoxLayout();self.btn(row,'Copy JSON',lambda:QApplication.clipboard().setText(text))
        def save():
            path,_=QFileDialog.getSaveFileName(d,'Save local JSON',str(ROOT/'relay-export.json'),'JSON (*.json)')
            if path:
                try:atomic_text(pathlib.Path(path),text+'\n')
                except OSError as e:self.error(e)
        self.btn(row,'Save JSON…',save);row.addStretch();self.btn(row,'Close',d.accept);l.addLayout(row);d.exec()
    def profiles(self):
        if self.running:return
        stored=self.settings.get('workspace_profiles',{})
        if not isinstance(stored,dict):stored={}
        profiles={str(k):v for k,v in stored.items() if isinstance(v,str)}
        d=QDialog(self);d.setWindowTitle('Workspace profiles');d.resize(560,350);l=QVBoxLayout(d);items=QListWidget();l.addWidget(items,1)
        def fill():
            items.clear()
            for name,path in sorted(profiles.items()):
                items.addItem(name+'  —  '+path);items.item(items.count()-1).setData(Qt.ItemDataRole.UserRole,name)
        def persist():
            self.settings['workspace_profiles']=profiles.copy()
            try:atomic_text(SETTINGS,json.dumps({**self.settings,'workspace':self.cwd.text()},ensure_ascii=False,indent=2))
            except OSError as e:self.error(e)
        def add():
            path=self.cwd.text()
            if not pathlib.Path(path).is_dir():return self.error('Select an existing workspace first')
            name,ok=QInputDialog.getText(d,'Save current workspace','Profile name')
            if ok and name.strip():
                name=name.strip()
                if name in profiles and profiles[name]!=path:
                    if QMessageBox.question(d,'Replace profile?',name)!=QMessageBox.StandardButton.Yes:return
                profiles[name]=path;persist();fill()
        def use():
            item=items.currentItem()
            if item:
                path=profiles[item.data(Qt.ItemDataRole.UserRole)]
                if not pathlib.Path(path).is_dir():return self.error('Workspace no longer exists')
                self.cwd.setText(path);persist();d.accept()
        def remove():
            item=items.currentItem()
            if item:profiles.pop(item.data(Qt.ItemDataRole.UserRole),None);persist();fill()
        row=QHBoxLayout();self.btn(row,'Save current',add);self.btn(row,'Use selected',use);self.btn(row,'Remove profile',remove);l.addLayout(row);items.itemDoubleClicked.connect(lambda _:use());fill();d.exec()
    def project_context(self):
        cwd=self.cwd.text()
        if not pathlib.Path(cwd).is_dir():return self.error('Select a valid workspace')
        self.start_tool('Project context',lambda:{'schema':'command-relay/project-context-v1','workspace':cwd,**intelligence.project_snapshot(cwd)})
    def language_settings(self):
        if self.running or self.tool_busy or self.copy_busy or self.stop_inflight:
            return self.error('Finish the active operation first')
        language = choose_language(saved_language(self.settings), self)
        if language is None or language == saved_language(self.settings):
            return
        try:
            atomic_text(SETTINGS, json.dumps({**read_settings(), 'language': language}, ensure_ascii=False, indent=2))
        except OSError as exc:
            return self.error(exc)
        self.settings['language'] = language
        QMessageBox.information(self, 'Command Relay', tr('language_saved', language))

    def mode_settings(self):
        if self.running or self.tool_busy or self.copy_busy or self.stop_inflight:
            return self.error('Finish the active operation first')
        mode = choose_workspace_mode(self.mode, self, self.ui_language,
                                     self.motion_action.isChecked())
        if mode is None or mode == self.mode:
            return
        try:
            atomic_text(SETTINGS, json.dumps({**read_settings(), **self.settings, 'mode': mode}, ensure_ascii=False, indent=2))
        except OSError as exc:
            return self.error(exc)
        self.settings['mode'] = mode
        self.apply_mode(mode)

    def safety_settings(self):
        if self.running or self.tool_busy or self.copy_busy or self.stop_inflight:
            return self.error('Finish the active operation first')
        dialog = SafetyDialog(self.cwd.text(), self)
        dialog.refresh()
        dialog.exec()

    def updates_settings(self):
        if self.running or self.tool_busy or self.copy_busy or self.stop_inflight:
            return self.error('Finish the active operation first')
        dialog = UpdatesDialog(self)
        result = dialog.exec()
        handoff = dialog.handoff if result == QDialog.DialogCode.Accepted else None
        dialog.deleteLater()
        if handoff is not None:
            self.update_handoff = handoff
            if not self.close():
                self.update_handoff = None
                self.error('Updater prepared but application did not close. Preserve the external bundle.')

    def github_prs(self):
        if self.running or self.tool_busy or self.copy_busy or self.stop_inflight:
            return self.error('Finish the active operation first')
        from .relay_github_qt import GitHubDialog
        dialog = GitHubDialog(self.cwd.text(), self)
        dialog.detect_repo()
        dialog.exec()

    def dashboard(self):
        cwd=self.cwd.text()
        if not pathlib.Path(cwd).is_dir():return self.error('Select a valid workspace')
        self.start_tool('Git dashboard',lambda:features.git_dashboard(cwd))
    def ai_context(self):
        cwd=self.cwd.text()
        if not pathlib.Path(cwd).is_dir():return self.error('Select a valid workspace')
        d=QDialog(self);d.setWindowTitle('AI context — selected data');d.resize(620,350);l=QVBoxLayout(d)
        l.addWidget(QLabel('Select text files within the workspace. Review all content for secrets before sharing.'))
        files=QListWidget();l.addWidget(files,1);diff=QCheckBox('Include staged and unstaged Git diff');l.addWidget(diff)
        paths=[]
        def add():
            p,_=QFileDialog.getOpenFileNames(d,'Choose workspace files',cwd)
            for x in p:
                if x not in paths:paths.append(x);files.addItem(x)
        def remove():
            i=files.currentRow()
            if i>=0:paths.pop(i);files.takeItem(i)
        row=QHBoxLayout();self.btn(row,'Add files…',add);self.btn(row,'Remove selected',remove);row.addStretch();self.btn(row,'Preview',d.accept);self.btn(row,'Cancel',d.reject);l.addLayout(row)
        if d.exec()==QDialog.DialogCode.Accepted and (paths or diff.isChecked()):
            selected=tuple(paths);include=diff.isChecked();self.start_tool('AI context',lambda:features.context_packet(cwd,selected,include))
    def queue_dialog(self):
        if self.running:return
        d=QDialog(self);d.setWindowTitle('Task queue — manual');d.resize(650,380);l=QVBoxLayout(d)
        l.addWidget(QLabel('Session queue only. Loading a task never runs it or changes workspace.'))
        items=QListWidget();l.addWidget(items,1)
        def fill():
            items.clear()
            for name,data,task in self.task_queue:items.addItem(name+'  |  '+(task.get('task_id') or task.get('title') or 'script'))
        def add():
            files,_=QFileDialog.getOpenFileNames(d,'Add tasks','','Commands (*.txt *.ps1 *.md *.json)')
            for path in files:
                try:
                    data=features.read_bounded(path,PACKET_LIMIT);script,task=load_input(data)
                    if not script.strip():raise ValueError('Empty script')
                    if len(self.task_queue)>=50:raise ValueError('Queue limit: 50 tasks')
                    self.task_queue.append((pathlib.Path(path).name,data,task))
                except (OSError,ValueError,UnicodeError) as e:self.error(e)
            fill()
        def load():
            i=items.currentRow()
            if i>=0:
                if self.editor.toPlainText().strip() and QMessageBox.question(d,'Replace editor?','Load selected task into editor?')!=QMessageBox.StandardButton.Yes:return
                name,data,task=self.task_queue[i];self.import_data(data,name,sha(data));self.task_queue.pop(i);d.accept()
        def remove():
            i=items.currentRow()
            if i>=0:self.task_queue.pop(i);fill()
        row=QHBoxLayout();self.btn(row,'Add tasks…',add);self.btn(row,'Load selected',load);self.btn(row,'Remove',remove);row.addStretch();self.btn(row,'Close',d.accept);l.addLayout(row);fill();d.exec()
    def latest_metrics(self):
        if self.running or not self.current:return self.error('Choose a completed report')
        self.show_metrics(self.current)
    def show_metrics(self,path):self.start_tool('Observed metrics',lambda:features.metrics_for(path))
    def compare_selected_metrics(self,paths):
        if len(paths)!=2:return self.error('Select two reports')
        a,b=sorted(paths);self.start_tool('Compare metrics (old → new)',lambda:features.compare_metrics(a,b))
    def export_evidence(self,paths):
        if not paths:return self.error('Select reports to export')
        dest,_=QFileDialog.getSaveFileName(self,'Export selected reports',str(ROOT/('evidence-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'.zip')),'ZIP (*.zip)')
        if dest:
            selected=tuple(paths);self.start_tool('Evidence bundle',lambda:features.evidence_bundle(selected,dest))
    def history(self):
        dlg=QDialog(self);dlg.setWindowTitle('Run history');dlg.resize(940,580);l=QVBoxLayout(dlg);r=QHBoxLayout();q=QLineEdit();q.setPlaceholderText('Search history');r.addWidget(q,1);flt=QComboBox();flt.addItems(['All','Exit 0','Failed','Cancelled','Partial / unknown']);r.addWidget(flt);l.addLayout(r);table=QTableWidget(0,4);table.setHorizontalHeaderLabels(['Started','Command','Process status','Elapsed']);table.verticalHeader().hide();table.setColumnWidth(0,180);table.setColumnWidth(2,110);table.setColumnWidth(3,85);table.horizontalHeader().setSectionResizeMode(1,QHeaderView.ResizeMode.Stretch);table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows);table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection);table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);l.addWidget(table,1)
        paths=[];snapshot=[];token=object();loading=False;closed=False
        status_label=QLabel('Loading history…');status_row=QHBoxLayout();status_row.addWidget(status_label,1);self.btn(status_row,'Review workspace session…',self.review_session_context);l.addLayout(status_row)
        def fill():
            table.setUpdatesEnabled(False)
            try:
                table.setRowCount(0);paths.clear()
                kind=flt.currentText();query=q.text().lower()
                matches=[]
                for p,(date,name,status,duration,workspace,tag) in snapshot:
                    hay=' '.join((p.name,date,name,status,workspace)).lower()
                    if query not in hay or (kind=='Exit 0' and status!='Exit 0') or (kind=='Failed' and tag!='error') or (kind=='Cancelled' and status!='Cancelled') or (kind=='Partial / unknown' and status not in ('Partial','Unknown','Exit None')):continue
                    matches.append((p,date,name,status,duration,tag))
                table.setRowCount(len(matches))
                for row,(p,date,name,status,duration,tag) in enumerate(matches):
                    paths.append(p)
                    for i,val in enumerate((date,name,status,duration)):
                        item=QTableWidgetItem(val);table.setItem(row,i,item)
                        if i==2:item.setForeground(QColor(colors()[tag]))
            finally:table.setUpdatesEnabled(True)
        def loaded(key,result,error):
            nonlocal loading
            if closed or key is not token:return
            loading=False;refresh.setEnabled(True)
            if error:status_label.setText('History could not be read; use Refresh or Reports > Folder.');return
            rows,unreadable,limited=result;snapshot[:]=rows;fill()
            status_label.setText(f'{len(rows)} reports'+(f' | {unreadable} unreadable' if unreadable else '')+(' | Limited history; older files remain in Reports folder.' if limited else ''))
        def reload():
            nonlocal loading
            if loading:return
            loading=True;refresh.setEnabled(False);status_label.setText('Loading history…')
            def work():
                try:result=view.history_snapshot(REPORTS);error=None
                except Exception:result=None;error=True
                try:self.signals.historyDone.emit(token,result,error)
                except RuntimeError:pass
            threading.Thread(target=work,daemon=True).start()
        self.signals.historyDone.connect(loaded,Qt.ConnectionType.QueuedConnection)
        filter_timer=QTimer(dlg);filter_timer.setSingleShot(True);filter_timer.setInterval(120);filter_timer.timeout.connect(fill)
        def selected():return [paths[i.row()] for i in table.selectionModel().selectedRows()]
        def one(fn):
            a=selected()
            if len(a)!=1:return self.error('Select one report')
            fn(a[0])
        def compare():
            a=sorted(selected())
            if len(a)!=2:return self.error('Select two reports')
            try:
                if any(p.stat().st_size>4_000_000 for p in a):return self.error('Large report: use external diff viewer')
                texts=[compact_report(p.read_text(encoding='utf-8',errors='replace')).splitlines() for p in a]
                if any(len(x)>10000 for x in texts):return self.error('Too many compact lines for inline comparison')
                diff='\n'.join(difflib.unified_diff(*texts,fromfile=a[0].name,tofile=a[1].name,lineterm=''));d=QDialog(dlg);d.setWindowTitle('Compact comparison');d.resize(950,600);ll=QVBoxLayout(d);ed=QPlainTextEdit(diff or 'No differences');ed.setReadOnly(True);ed.setFont(QFont('Consolas',10));ll.addWidget(ed);d.exec()
            except OSError as e:self.error(e)
        r=QHBoxLayout();self.btn(r,'View full',lambda:one(self.open_path));self.btn(r,'Compare 2',compare);self.copy_button(r,lambda mode:one(lambda p:self.copy_report(mode,p)));self.btn(r,'Metrics',lambda:one(self.show_metrics));self.btn(r,'Compare metrics',lambda:self.compare_selected_metrics(selected()));self.btn(r,'Export ZIP',lambda:self.export_evidence(selected()));r.addStretch();refresh=self.btn(r,'Refresh',reload);l.addLayout(r);q.textChanged.connect(lambda _:filter_timer.start());flt.currentTextChanged.connect(lambda _:filter_timer.start());table.cellDoubleClicked.connect(lambda *_:one(self.open_path));reload()
        try:dlg.exec()
        finally:
            closed=True;self.signals.historyDone.disconnect(loaded);filter_timer.stop()
    def closeEvent(self,event):
        if self.running or self.stop_inflight or self.tool_busy or self.copy_busy:self.error('Wait for local tools or stop the current run before closing');event.ignore();return
        try:atomic_text(SETTINGS,json.dumps({**self.settings,'workspace':self.cwd.text(),'library':str(self.lib),'wrap_output':self.wrap.isChecked(),'dense_output':self.dense.isChecked(),'mode':self.mode},ensure_ascii=False,indent=2))
        except OSError:pass
        event.accept()

def main():
    set_app_identity()
    app=QApplication(sys.argv);app.setApplicationName('Command Relay');app.setApplicationVersion(VERSION)
    icon=QIcon(str(ASSETS/'relay-icon.ico'))
    if icon.isNull():icon=QIcon(str(ASSETS/'relay-icon.png'))
    if not icon.isNull():app.setWindowIcon(icon)
    app.setStyle('Fusion')
    settings = read_settings()
    apply_theme(view.saved_theme(settings))
    chrome=NeutralChrome(app);app.installEventFilter(chrome)
    startup_mark('qt_initialized_ms')
    try:
        language = startup_language(settings, choose_language,
                                    lambda selected: confirm_usage_terms(ROOT, selected),
                                    lambda selected: None)
        if language is None:
            return 0
        mode = startup_mode(settings, lambda: choose_workspace_mode(
            language=language, reduced_motion=settings.get('reduced_motion') is True))
        if mode is None:
            return 0
        if language != saved_language(settings) or mode != saved_mode(settings):
            atomic_text(SETTINGS, json.dumps({**settings, 'language': language, 'mode': mode},
                                             ensure_ascii=False, indent=2))
    except (OSError, ValueError) as exc:
        QMessageBox.warning(None, 'Command Relay', str(exc))
        return 1
    startup_mark('terms_accepted_ms')
    w=App()
    if not icon.isNull():w.setWindowIcon(icon)
    startup_mark('widgets_created_ms');w.show();startup_mark('show_called_ms');code = app.exec()
    return w.update_handoff if code == 0 and w.update_handoff is not None else code


if __name__ == "__main__":
    from .__main__ import main as launch
    raise SystemExit(launch(main))
