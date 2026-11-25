# SPDX-License-Identifier: Apache-2.0
"""Command Relay Qt workbench. Local-only, explicit execution."""
import time
STARTUP_T0 = time.perf_counter()
import sys, os, pathlib, json, codecs, tempfile, subprocess, threading, shutil, difflib, re, datetime, queue
from PySide6.QtCore import Qt, QProcess, QTimer, QUrl, Signal, QObject, QEvent, QSize, QRect
from PySide6.QtGui import QColor, QFont, QTextCursor, QTextDocument, QSyntaxHighlighter, QTextCharFormat, QDesktopServices, QShortcut, QKeySequence, QPainter, QIcon
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QLineEdit,QPlainTextEdit,QSplitter,QTabWidget,QListWidget,QFileDialog,QMessageBox,QCheckBox,QDialog,QTableWidget,QTableWidgetItem,QHeaderView,QAbstractItemView,QComboBox,QMenu,QInputDialog,QSizePolicy,QLayout,QStyle)
from .relay_core import (
    ASSETS, GIT_ACTIONS, MARK, PACKET_LIMIT, REPORTS, ROOT, SETTINGS,
    atomic_text, compact_report, copy_mode, file_hash, git_args, load_input,
    prepare, read_settings, sha,
)
from .relay_version import VERSION
from .relay_terms import confirm_usage_terms
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
                apply_neutral_chrome(int(obj.winId()))
            except (RuntimeError, OSError, ValueError):
                pass
        return False


STYLE='''QWidget {background:#181818;color:#d4d4d4;font-family:"Segoe UI";font-size:12px} QLineEdit,QPlainTextEdit,QListWidget,QTableWidget,QComboBox {background:#202020;border:1px solid #333;selection-background-color:#264f78} QPlainTextEdit {border:0} QPushButton {background:#292929;border:1px solid transparent;border-radius:3px;padding:6px 12px} QPushButton:hover {background:#3a3a3a} QPushButton:disabled {color:#666;background:#222} QPushButton#run {background:#0078d4;color:white} QPushButton#run:disabled {background:#263744;color:#888} QMenu {background:#252526;border:1px solid #444;padding:4px} QMenu::item {padding:7px 24px 7px 12px} QMenu::item:selected {background:#264f78} QMenu::item:disabled {color:#777} QMenu::separator {height:1px;background:#414141;margin:4px 6px} QTabWidget::pane {border:0} QTabBar::tab {padding:7px 12px;background:#252526;color:#aaa} QTabBar::tab:selected {background:#181818;color:white} QSplitter::handle {background:#333} QSplitter::handle:hover {background:#0078d4} QHeaderView::section {background:#292929;border:0;padding:6px} QScrollBar:vertical {width:9px;background:#222} QScrollBar::handle:vertical {background:#505050;min-height:24px} QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {height:0} QScrollBar:horizontal {height:9px;background:#222} QScrollBar::handle:horizontal {background:#505050;min-width:24px} QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal {width:0} QPushButton:focus,QLineEdit:focus,QListWidget:focus,QTableWidget:focus,QComboBox:focus {border:1px solid #73b8ff} QPlainTextEdit:focus {border:1px solid #73b8ff} QCheckBox:focus,QTabBar::tab:focus {outline:1px solid #73b8ff}'''

# A tiny indeterminate indicator: repaint only this 4-pixel strip, not the log.
# No claimed percentage; scripts have no universal progress metric.
class ActivityBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(4)
        self.setAccessibleName('Execution in progress (indeterminate)')
        self._epoch = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self.update)
        self.hide()

    def set_running(self, running):
        if running:
            self._epoch = time.monotonic()
            self.show()
            self._timer.start()
        else:
            self._timer.stop()
            self.hide()

    def paintEvent(self, event):
        painter = QPainter(self)
        width = self.width()
        painter.fillRect(self.rect(), QColor('#263746'))
        segment = min(width, max(36, width // 5))
        phase = ((time.monotonic() - self._epoch) % 1.25) / 1.25
        x = int(phase * (width + segment)) - segment
        painter.fillRect(x, 0, segment, self.height(), QColor('#3794ff'))
        painter.end()


STATUS_COLORS = {
    'ready': '#0078d4', 'running': '#005f9e', 'success': '#237346',
    'failed': '#a12632', 'cancelled': '#80550d', 'stopping': '#80550d',
}
COPY_TIP = 'Click: Copy AI (best-effort secret masking)\nShift + click: Copy text (masked)\nCtrl + click: Copy RAW full report (unmasked)\nCtrl takes priority if both are held.'

class Highlight(QSyntaxHighlighter):
    def highlightBlock(self,text):
        t=text.strip(); color=None
        if MARK.match(t): color='#569cd6'
        elif re.search(r'\b\w*PASS=False\b',t) or re.match(r'^(error[\[:]|Runner error:|Process exit code: (?!0$))',t,re.I): color='#f48771'
        elif re.search(r'\b\w*PASS=True\b',t) or t=='Process exit code: 0': color='#b5cea8'
        elif re.match(r'^(warning:|Cancelled: True)',t,re.I): color='#d7ba7d'
        elif re.match(r'^[A-Z][A-Z0-9_]+=',t): color='#9cdcfe'
        if color:
            fmt=QTextCharFormat();fmt.setForeground(QColor(color));self.setFormat(0,len(text),fmt)

class DropEditor(QPlainTextEdit):
    fileDropped=Signal(str)
    def dragEnterEvent(self,e):
        if e.mimeData().hasUrls() and len(e.mimeData().urls())==1 and e.mimeData().urls()[0].isLocalFile(): e.acceptProposedAction()
        else: super().dragEnterEvent(e)
    def dragMoveEvent(self,e):
        if e.mimeData().hasUrls(): e.acceptProposedAction()
        else: super().dragMoveEvent(e)
    def dropEvent(self,e):
        if e.mimeData().hasUrls():
            urls=e.mimeData().urls()
            if len(urls)==1 and urls[0].isLocalFile(): self.fileDropped.emit(urls[0].toLocalFile());e.acceptProposedAction()
            else:e.ignore()
        else:super().dropEvent(e)

class WorkerSignals(QObject):
    hashDone=Signal(str,str)
    stopDone=Signal(object,bool)
    initialTail=Signal(object,object,object)
    toolDone=Signal(str,object,object)
    copyDone=Signal(object,object,object)
    warmDone=Signal(object,object)
    historyDone=Signal(object,object,object)

class UpdatesDialog(QDialog):
    """Explicit metadata lookup and in-memory verification; no installation."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Updates'); self.resize(560, 300)
        self.results = None
        self.info = None
        layout = QVBoxLayout(self)
        def label(text):
            item = QLabel(text); item.setWordWrap(True)
            item.setTextFormat(Qt.TextFormat.PlainText); layout.addWidget(item)
            return item
        label('Current version: ' + VERSION)
        label('Check official GitHub release metadata or verify a newer package in memory. Nothing is installed.')
        self.latest = label('Latest stable release: Not checked')
        self.status = label('Select Check for updates to start.')
        self.trust = label('Publisher signature: Not verified')
        self.digest = label('')
        layout.addStretch()
        row = QHBoxLayout(); layout.addLayout(row)
        self.check_button = QPushButton('Check for updates'); self.check_button.setObjectName('updates_check')
        self.check_button.setAutoDefault(False); self.check_button.clicked.connect(self.check); row.addWidget(self.check_button)
        self.verify_button = QPushButton('Download & Verify'); self.verify_button.setObjectName('updates_verify')
        self.verify_button.setAutoDefault(False); self.verify_button.setEnabled(False)
        self.verify_button.clicked.connect(self.verify); row.addWidget(self.verify_button)
        row.addStretch()
        close = QPushButton('Close'); close.setAutoDefault(False); close.clicked.connect(self.reject); row.addWidget(close)
        self.poll = QTimer(self); self.poll.setInterval(50); self.poll.timeout.connect(self.finish_check)

    def _start(self, work, failure):
        results = queue.Queue(maxsize=1)
        self.results = results
        self.check_button.setEnabled(False); self.verify_button.setEnabled(False)
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
        self.digest.clear()
        self.latest.setText('Latest stable release: Checking…')
        self.status.setText('Requesting official release metadata…')
        self.trust.setText('Publisher signature: Not verified')
        def work():
            info = updates.check_latest(VERSION)
            availability, trust = updates.describe_release(info)
            return ('check', info, availability, trust, '')
        self._start(work, ('check', None, 'Release check failed. Retry later.', 'Publisher signature: Not verified', ''))

    def verify(self):
        from . import relay_updates as updates
        if self.results is not None or not updates.can_verify_release(self.info): return
        info = self.info
        self.digest.clear()
        self.status.setText('Downloading and verifying signed package…')
        self.trust.setText('Publisher signature: Not verified')
        def work():
            digest = updates.verify_release_for_display(info)
            return ('verify', info, 'Package verified in memory and discarded. No installation performed.',
                    'Publisher signature: Verified', digest)
        self._start(work, ('verify', info, 'Package verification failed. Retry or check again.',
                           'Publisher signature: Not verified', ''))

    def finish_check(self):
        if self.results is None: return
        try: mode, info, status, trust, digest = self.results.get_nowait()
        except queue.Empty: return
        self.poll.stop(); self.results = None
        from . import relay_updates as updates
        self.info = info
        self.latest.setText('Latest stable release: ' + (info.latest if info else 'Unavailable'))
        self.status.setText(status); self.trust.setText(trust)
        self.digest.setText('Verified archive SHA-256: ' + digest if digest else '')
        self.check_button.setEnabled(True)
        self.verify_button.setEnabled(not digest and updates.can_verify_release(info))

    def done(self, result):
        self.poll.stop(); self.results = None; self.info = None
        self.digest.clear(); self.trust.setText('Publisher signature: Not verified')
        self.verify_button.setEnabled(False)
        super().done(result)


class SafetyDialog(QDialog):
    """Only implemented automation is exposed; no network or task execution."""
    completed = Signal(object, object, str)

    def __init__(self, workspace, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Safety settings'); self.resize(650, 490)
        self.workspace = workspace; self.scope = None; self.snapshot = None; self.busy = False
        self.completed.connect(self.finish_policy, Qt.ConnectionType.QueuedConnection)
        layout = QVBoxLayout(self)
        def label(text):
            widget = QLabel(text); widget.setWordWrap(True); widget.setTextFormat(Qt.TextFormat.PlainText)
            layout.addWidget(widget); return widget
        label('Automation permissions — disabled by default')
        label('Built-in merge and update installation permissions are separate. Manual Run and manual merge remain separate. Arbitrary scripts are not sandboxed.')
        self.target = label('Workspace: ' + workspace)
        self.notice = label('Refresh to read local policy and origin.')
        self.toggle = QCheckBox('Allow automatic squash merge for this workspace and repository')
        self.toggle.setAccessibleName('Allow scoped automatic squash merge'); layout.addWidget(self.toggle)
        label('Every automatic merge still requires explicit task review.')
        self.update_target = label('Installation: ' + str(ROOT))
        self.update_toggle = QCheckBox('Allow signed update installation for this application')
        self.update_toggle.setAccessibleName('Allow installation of signed updates'); layout.addWidget(self.update_toggle)
        label('Separate terminal confirmation is still required. No automatic download, install or restart from this setting.')
        self.update_save_button = QPushButton('Apply update permission…')
        self.update_save_button.setAutoDefault(False); self.update_save_button.clicked.connect(self.save_update)
        layout.addWidget(self.update_save_button)
        self.update_scope = None
        layout.addStretch()
        row = QHBoxLayout(); layout.addLayout(row)
        def button(text, fn):
            b = QPushButton(text); b.setAutoDefault(False); b.clicked.connect(fn); row.addWidget(b); return b
        self.refresh_button = button('Refresh', self.refresh)
        self.history_button = button('History…', self.show_history)
        self.revoke_button = button('Revoke all grants…', self.revoke_all)
        self.save_button = button('Apply change…', self.save)
        self.close_button = button('Close', self.reject)
        self.update_controls()

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
        self.busy = True; self.update_controls(); self.notice.setText('Reading or saving local policy…')
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
        self.target.setText('Workspace: ' + (scope[0] if scope else self.workspace) + '\nRepository: ' + (scope[1] if scope else 'Not resolved'))
        self.toggle.setChecked(bool(scope and snapshot is not None and policy.allowed(snapshot, 'squash_merge', workspace=scope[0], repository=scope[1])))
        self.update_scope = None
        if snapshot is not None:
            try: self.update_scope = policy.update_permission_scope(ROOT)
            except Exception: pass
        self.update_target.setText('Installation: ' + str(ROOT) + (' — eligible for permission changes' if self.update_scope else ' — update permission unavailable'))
        self.update_toggle.setChecked(bool(snapshot is not None and policy.allowed(snapshot, 'update_install')))
        self.notice.setText(note); self.update_controls()

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
        dialog = QDialog(self); dialog.setWindowTitle('Permission history'); dialog.resize(680, 360)
        layout = QVBoxLayout(dialog)
        view = QPlainTextEdit(); view.setReadOnly(True); view.setAccessibleName('Local permission history')
        view.setPlainText(policy.audit_text(self.snapshot)); layout.addWidget(view)
        close = QPushButton('Close'); close.clicked.connect(dialog.accept); layout.addWidget(close)
        dialog.exec()

    def confirm(self, text):
        box = QMessageBox(QMessageBox.Icon.Warning, 'Confirm permission change', text, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, self)
        box.setTextFormat(Qt.TextFormat.PlainText); box.setDefaultButton(QMessageBox.StandardButton.Cancel); box.setEscapeButton(QMessageBox.StandardButton.Cancel)
        return box.exec() == QMessageBox.StandardButton.Yes

    def save(self):
        from . import relay_permissions as policy
        if self.busy or self.scope is None or self.snapshot is None: return
        scope, snapshot, enabled = self.scope, self.snapshot, self.toggle.isChecked()
        if enabled == policy.allowed(snapshot, 'squash_merge', workspace=scope[0], repository=scope[1]):
            self.notice.setText('No permission change selected.'); return
        if not self.confirm(('Allow' if enabled else 'Revoke') + ' automatic squash merge?\n\n' + scope[0] + '\n' + scope[1] + '\n\nNo merge will be executed now.'):
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
            self.notice.setText('No update permission change selected.'); return
        if not self.confirm(('Allow' if enabled else 'Revoke') + ' signed update installation?\n\n' + str(root) + '\n\nInstallation still requires explicit terminal confirmation. No update will be executed now.'):
            self.finish_policy(scope, snapshot, 'Cancelled. No changes made.'); return
        self.start(lambda: (scope, policy.save_update_permission(snapshot, root=root, enabled=enabled),
                           'Update permission saved. No update or network operation executed.'))

    def revoke_all(self):
        from . import relay_permissions as policy
        if self.busy or self.snapshot is None: return
        if not self.confirm('Revoke all saved automation grants for all workspaces?'): return
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


class App(QMainWindow):
    def __init__(self):
        super().__init__();self.setWindowTitle(f'Command Relay {VERSION} — Qt Workbench');self.resize(1180,740);self.setMinimumSize(850,560)
        self.settings=read_settings();self.running=False;self.cancelled=False;self.proc=None;self.temp=None;self.journal=None;self.active=None;self.current=None;self.source='Untitled';self.source_hash=None;self.loaded=None;self.task={};self.pending=[];self.blank=False;self.started=0;self.stop_pending=False;self.stop_inflight=False
        self.signals=WorkerSignals();self.signals.hashDone.connect(self.hash_done);self.signals.stopDone.connect(self.stop_done);self.signals.initialTail.connect(self.finish_initial_tail);self.initial_restore_pending=True;self.tool_busy=False;self.task_queue=[];self.signals.toolDone.connect(self.tool_done);self.copy_busy=False;self.signals.copyDone.connect(self.copy_done);self.warm_path=None;self.warm_result=None;self.warm_waiting=False;self.signals.warmDone.connect(self.warm_done)
        self.edit_controls=[];self.lib=pathlib.Path(self.settings.get('library') or ROOT/'scripts');
        central=QWidget();self.setCentralWidget(central);v=QVBoxLayout(central);v.setContentsMargins(12,9,12,8);v.setSpacing(7)
        leading,row=action_group();h=QLabel('COMMAND RELAY');h.setStyleSheet('font-size:20px;font-weight:700;color:#f0f0f0');row.addWidget(h);row.addWidget(QLabel(f'{VERSION}  /  QT WORKBENCH'))
        trailing,row=action_group();self.more=QPushButton('More');row.addWidget(self.more);self.more.setToolTip('Project tools, reports and settings')
        self.header_row=AdaptiveActionRow(leading,trailing);v.addLayout(self.header_row)
        row=QHBoxLayout();row.addWidget(QLabel('WORKSPACE'));self.cwd=QLineEdit(self.settings.get('workspace') or os.getcwd());row.addWidget(self.cwd,1);self.edit_controls.append(self.cwd);self.btn(row,'Browse',self.browse,True);self.btn(row,'Profiles',self.profiles,True);v.addLayout(row)
        leading,row=action_group();self.openbtn=self.btn(row,'Open file',self.open,True);self.pastebtn=self.btn(row,'Paste / AI task',self.paste,True)
        trailing,row=action_group();self.stopbtn=self.btn(row,'■ Stop',self.stop);self.stopbtn.setEnabled(False);self.runbtn=self.btn(row,'▶ Run commands',self.run);self.runbtn.setObjectName('run');self.runbtn.setToolTip('Run (Ctrl+Enter). Review the script and workspace first; identical task history is checked before execution. Commands use your account permissions.')
        self.command_row=AdaptiveActionRow(leading,trailing);v.addLayout(self.command_row)
        split=QSplitter(Qt.Orientation.Horizontal);self.main_split=split;split.setChildrenCollapsible(False);split.setOpaqueResize(True);split.setHandleWidth(5);v.addWidget(split,1)
        self.tabs=QTabWidget();self.tabs.setMinimumWidth(175);split.addWidget(self.tabs)
        w=QWidget();l=QVBoxLayout(w);l.setContentsMargins(5,5,5,5);l.addWidget(QLabel('LIVE OUTPUT (visible tail)'));self.steps=QListWidget();l.addWidget(self.steps,3);l.addWidget(QLabel('COMMAND OUTLINE'));self.outline=QListWidget();l.addWidget(self.outline,2);self.tabs.addTab(w,'Steps');self.steps.itemClicked.connect(lambda item:self.jump(self.output,item));self.outline.itemClicked.connect(lambda item:self.jump(self.editor,item));self.steps.itemActivated.connect(lambda item:self.jump(self.output,item));self.outline.itemActivated.connect(lambda item:self.jump(self.editor,item))
        w=QWidget();l=QVBoxLayout(w);l.addWidget(QLabel('SCRIPT LIBRARY'));self.liblabel=QLabel(str(self.lib));self.liblabel.setWordWrap(True);l.addWidget(self.liblabel);r=QHBoxLayout();self.btn(r,'Folder…',self.choose_lib,True);self.btn(r,'Refresh',self.refresh_lib);l.addLayout(r);self.libfind=QLineEdit();self.libfind.setPlaceholderText('Filter scripts');l.addWidget(self.libfind);self.library=QListWidget();l.addWidget(self.library,1);self.btn(l,'Load selected',self.load_lib,True);self.btn(l,'Save editor as…',self.save_script,True);self.tabs.addTab(w,'Scripts');self.libfind.textChanged.connect(self.refresh_lib);self.library.itemDoubleClicked.connect(lambda _:self.load_lib())
        right=QSplitter(Qt.Orientation.Vertical);right.setChildrenCollapsible(False);right.setOpaqueResize(True);right.setHandleWidth(5);split.addWidget(right);split.setSizes([250,900]);split.setStretchFactor(1,1)
        w=QWidget();l=QVBoxLayout(w);l.setContentsMargins(4,0,0,0);self.command_label=QLabel('COMMANDS  /  Untitled');r=QHBoxLayout();r.addWidget(self.command_label,1);self.inspector_label=QLabel();self.inspector_label.hide();r.addWidget(self.inspector_label);l.addLayout(r);self.editor=DropEditor();self.editor.setMinimumHeight(100);self.editor.setPlaceholderText('Drop a task file here or use Paste / AI task.');self.editor.setStyleSheet('QPlainTextEdit {font-family: Consolas, monospace; font-size: 13px;}');self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap);l.addWidget(self.editor,1);self.editor.fileDropped.connect(self.load);self.editor.textChanged.connect(self.refresh_outline);self.inspector_timer=QTimer(self);self.inspector_timer.setSingleShot(True);self.inspector_timer.setInterval(220);self.inspector_timer.timeout.connect(self.update_inspector);self.editor.textChanged.connect(lambda:self.inspector_timer.start());self.editor_highlight=Highlight(self.editor.document());right.addWidget(w)
        w=QWidget();l=QVBoxLayout(w);l.setContentsMargins(4,0,0,0);r=QHBoxLayout();self.output_label=QLabel('TERMINAL  /  No report');r.addWidget(self.output_label);r.addStretch();self.dense=QCheckBox('Dense',w);self.dense.setChecked(self.settings.get('dense_output',True));self.wrap=QCheckBox('Wrap',w);self.wrap.setChecked(self.settings.get('wrap_output',True));self.follow=QCheckBox('Follow');self.follow.setChecked(True)
        # Follow remains a visible live control; rarely changed options live in More.
        self.dense.hide();self.wrap.hide();r.addWidget(self.follow);self.btn(r,'Find',self.toggle_search)
        l.addLayout(r);self.searchbar=QWidget();r=QHBoxLayout(self.searchbar);r.setContentsMargins(0,0,0,0);self.search=QLineEdit();self.search.setPlaceholderText('Find in visible output');r.addWidget(self.search,1);self.find_previous=self.btn(r,'↑',lambda:self.find(True));self.find_next=self.btn(r,'↓',lambda:self.find(False));self.close_search=self.btn(r,'×',self.hide_search);l.addWidget(self.searchbar);self.searchbar.hide();self.search.returnPressed.connect(lambda:self.find(False));self.output=QPlainTextEdit();self.output.setReadOnly(True);self.output.setUndoRedoEnabled(False);self.output.setMaximumBlockCount(6000);self.output.setStyleSheet('QPlainTextEdit {font-family: Consolas, monospace; font-size: 13px;}');self.output_highlight=Highlight(self.output.document());l.addWidget(self.output,1);right.addWidget(w);right.setSizes([240,430]);right.setStretchFactor(1,1);self.wrap.toggled.connect(self.apply_wrap);self.dense.toggled.connect(self.reload_tail);self.apply_wrap()
        r=QHBoxLayout();self.detail=QLabel('Drop a script or import an AI task.');r.addWidget(self.detail,1);self.copy_button(r,lambda mode:self.copy_report(mode));self.btn(r,'History',self.history);v.addLayout(r)
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
        self.statusBar().setSizeGripEnabled(False)
        self.set_status('ready','READY  |  PowerShell  |  UTF-8')
        self.timer=QTimer(self);self.timer.setInterval(80);self.timer.timeout.connect(self.flush_view);self.timer.start();self.clock=QTimer(self);self.clock.setInterval(1000);self.clock.timeout.connect(self.update_clock);self.clock.start()
        for key,fn in [('Ctrl+O',self.open),('Ctrl+Return',self.run),('Ctrl+F',self.show_search),('F3',lambda:self.find(False)),('Shift+F3',lambda:self.find(True)),('Ctrl+Shift+C',lambda:self.copy_report('full'))]:QShortcut(QKeySequence(key),self).activated.connect(fn)
        self.tabs.currentChanged.connect(self.load_library_on_tab)
        self.tabs.setVisible(self.settings.get('show_sidebar',True) is not False)
        QTimer.singleShot(0, self.start_initial_restore)
    def configure_accessibility(self):
        # Keep the visible workbench compact; expose meaning to keyboard and assistive tools.
        for control, name in ((self.cwd, 'Working directory'), (self.editor, 'Command editor'),
                              (self.output, 'Read-only terminal output'), (self.steps, 'Execution steps'),
                              (self.outline, 'Command outline'), (self.library, 'Script library'),
                              (self.libfind, 'Filter scripts'), (self.search, 'Find in visible output'),
                              (self.tabs, 'Workbench sidebar'), (self.detail, 'Task and export status'),
                              (self.inspector_label, 'Task Inspector result'), (self.more, 'More tools'),
                              (self.runbtn, 'Run commands'), (self.stopbtn, 'Stop execution')):
            control.setAccessibleName(name)
        for control, name in ((self.find_previous, 'Find previous match (Shift+F3)'),
                              (self.find_next, 'Find next match (F3)'),
                              (self.close_search, 'Close output search')):
            control.setAccessibleName(name);control.setToolTip(name)
        self.follow.setAccessibleDescription('Automatically scroll terminal output to the latest line.')
        self.editor.setAccessibleDescription('Review imported commands before running. Ctrl+Enter requests execution.')
        self.output.setAccessibleDescription('Visible tail of the report. Use Copy or History for the complete report.')
    def build_more_menu(self):
        menu=QMenu(self.more);menu.setObjectName('workbench_more');self.more.setMenu(menu)
        def action(parent,label,fn,edit=False):
            a=parent.addAction(label);a.triggered.connect(lambda checked=False:fn())
            if edit:self.edit_controls.append(a)
            return a
        action(menu,'Copy session context',self.copy_session_context,True)
        action(menu,'Clear editor',self.clear,True)
        menu.addSeparator()
        ctx=menu.addMenu('Project')
        action(ctx,'Project context',self.project_context,True)
        action(ctx,'AI context…',self.ai_context,True)
        git=menu.addMenu('Git')
        action(git,'Git dashboard',self.dashboard,True)
        action(git,'GitHub pull requests…',self.github_prs,True)
        git.addSeparator()
        for name in GIT_ACTIONS:action(git,name,lambda n=name:self.run_git(n),True)
        reports=menu.addMenu('Reports')
        # Named alternatives to modifier-click, including a conspicuous raw warning.
        self.copy_ai_action=action(reports,'Copy AI result (masked)',lambda:self.copy_report('ai'))
        self.copy_text_action=action(reports,'Copy compact text (masked)',lambda:self.copy_report('compact'))
        self.copy_raw_action=action(reports,'Copy full report (RAW, unmasked)',lambda:self.copy_report('full'))
        reports.addSeparator()
        action(reports,'Metrics — latest',self.latest_metrics,True)
        action(reports,'Open latest',lambda:self.open_path(REPORTS/'latest.txt'))
        action(reports,'Folder',lambda:self.open_path(REPORTS))
        action(menu,'Task queue…',self.queue_dialog,True)
        action(menu,'SHA-256 file…',self.hash_tool,True)
        menu.addSeparator()
        # One settings entry for current preferences and future language/update tools.
        self.settings_menu=menu.addMenu('Settings');self.settings_menu.setObjectName('workbench_settings')
        self.safety_action=action(self.settings_menu,'Safety settings…',self.safety_settings,True)
        self.safety_action.setObjectName('settings_safety')
        self.updates_action=action(self.settings_menu,'Updates…',self.updates_settings,True)
        self.updates_action.setObjectName('settings_updates')
        self.settings_menu.addSeparator()
        self.sidebar_action=self.settings_menu.addAction('Show sidebar');self.sidebar_action.setObjectName('settings_sidebar');self.sidebar_action.setCheckable(True)
        self.sidebar_action.setChecked(self.settings.get('show_sidebar',True) is not False)
        self.sidebar_action.toggled.connect(self.tabs.setVisible)
        for label,control in [('Wrap output',self.wrap),('Dense output',self.dense)]:
            a=self.settings_menu.addAction(label);a.setObjectName('settings_wrap' if control is self.wrap else 'settings_dense');a.setCheckable(True);a.setChecked(control.isChecked());a.toggled.connect(control.setChecked);control.toggled.connect(a.setChecked)
            if control is self.dense:self.edit_controls.append(a)
        action(menu,'Find in output',self.show_search)
    def show_search(self):
        self.searchbar.show();self.search.setFocus();self.search.selectAll()
    def hide_search(self):
        self.searchbar.hide();self.output.setFocus()
    def toggle_search(self):
        if self.searchbar.isVisible():self.hide_search()
        else:self.show_search()
    def load_library_on_tab(self, index):
        if index == 1:
            self.refresh_lib()
    def start_initial_restore(self):
        startup_mark('event_loop_ms')
        latest=REPORTS/'latest.txt'
        if not self.initial_restore_pending or self.running:
            save_startup_marks()
            return
        if self.source=='Untitled':self.detail.setText('Restoring previous report…')
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
            self.current=path;self.output_label.setText('TERMINAL  /  latest.txt (previous run)')
            if self.dense.isChecked():data=re.sub(r'\n{3,}','\n\n',data)
            # Avoid inserting blocks that Qt would immediately discard.
            data=view.visible_tail(data)
            self.output.setPlainText(data);self.refresh_steps();self.output.moveCursor(QTextCursor.MoveOperation.End)
            if self.source=='Untitled':self.detail.setText('Previous report restored.')
        elif self.source=='Untitled':
            self.detail.setText('Drop a script or import an AI task.')
        startup_mark('restore_finished_ms');save_startup_marks()
    def btn(self,layout,title,fn,edit=False):
        b=QPushButton(title);b.clicked.connect(lambda checked=False:fn());layout.addWidget(b)
        if edit:self.edit_controls.append(b)
        return b
    def copy_button(self,layout,action):
        button=self.btn(layout,'Copy',lambda:action(self.copy_modifier_mode()))
        button.setToolTip(COPY_TIP)
        button.setAccessibleName('Copy report — AI result by default')
        button.setAccessibleDescription(COPY_TIP)
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
        script,task=load_input(data);self.task=task;self.source=name;self.editor.setPlainText(script);self.loaded=self.editor.toPlainText();self.source_hash=digest;self.command_label.setText('COMMANDS  /  '+name);self.detail.setText('Task imported; review before running' if task else 'Loaded '+name)
        # Import is a preview only. Keep metadata available without blocking the UI.
        metadata = '\n'.join(f'{k}: {v}' for k,v in task.items() if v)
        self.command_label.setToolTip(metadata or 'Loaded script: '+name)
        self.detail.setToolTip(metadata or '')
        if task:
            task_id = task.get('task_id') or task.get('title') or name
            self.detail.setText('AI task loaded: '+task_id.replace('\n',' ').replace('\r',' ')[:80]+' — review before running')
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
        self.inspector_label.setStyleSheet('color:'+('#f48771' if level=='high' else '#d7ba7d')+';font-weight:600')
        self.inspector_label.setToolTip('\n'.join(m['label'] for m in matches)+('\nScan limited.' if result['scan_limited'] else '')+'\n'+result['note'])
        return result
    def refresh_outline(self):
        self.outline.clear()
        for i,line in enumerate(self.editor.toPlainText().splitlines()):
            m=MARK.match(line)
            if m:self.outline.addItem(m.group(1));self.outline.item(self.outline.count()-1).setData(Qt.ItemDataRole.UserRole,i)
    def jump(self,widget,item):
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
        self.running=b;self.editor.setReadOnly(b);self.runbtn.setEnabled(not b and not self.stop_inflight);self.stopbtn.setEnabled(b and not self.stop_pending)
        for c in self.edit_controls:c.setEnabled(not b)
        self.activity.set_running(b)
        if b:self.set_status('running','RUNNING  |  0s  |  Full log on disk')
    def begin(self,name,header):
        self.initial_restore_pending=False
        self.current=None;self.warm_result=None
        REPORTS.mkdir(exist_ok=True);stamp=datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f');self.active=REPORTS/f'report-{stamp}.partial.txt';self.journal=self.active.open('x',encoding='utf-8',newline='');self.started=time.monotonic();self.cancelled=False;self.pending=[];self.stop_pending=False;self.decoder=codecs.getincrementaldecoder('utf-8')('replace');self.set_busy(True);self.output.clear();self.steps.clear();self.follow.setChecked(True);self.output_label.setText('TERMINAL  /  '+name);self.append(header);self.tabs.setCurrentIndex(0)
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
            answer=QMessageBox.question(self,'Review commands',
                'The script matches potentially risky command patterns:\n\n'+labels+'\n\nReview the script and workspace. This is not a safety verdict. Run anyway?',
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
        except OSError as e:self.error(e);self.cleanup_temp();self.set_busy(False);self.set_status('failed','FAILED / START ERROR')
    def confirm_repeat(self, previous):
        status=previous['status']
        if status in ('not_applicable','no_match'):return True
        if status=='matched':
            text='A matching task was previously run in this workspace.\n\nReport: '+previous['report_file']+'\nAssertions / run status: '+previous['verdict']
            if previous.get('process_exit') is not None:text+='\nProcess exit: '+str(previous['process_exit'])
        else:text='Previous execution could not be fully checked.'
        if previous.get('reason'):text+='\n'+previous['reason']
        text+='\n\nMatching history does not prove the current environment or effects are unchanged. Review before running again.'
        dialog=QMessageBox(QMessageBox.Icon.Warning,'Review previous execution',text,parent=self)
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        run=dialog.addButton('Run anyway',QMessageBox.ButtonRole.AcceptRole)
        cancel=dialog.addButton(QMessageBox.StandardButton.Cancel)
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
        except OSError as e:self.error(e);self.set_busy(False);self.set_status('failed','FAILED / START ERROR')
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
        self.set_busy(False)
        elapsed=int(time.monotonic()-self.started)
        kind='cancelled' if self.cancelled else 'success' if code==0 else 'failed'
        label='CANCELLED' if self.cancelled else 'EXIT 0' if code==0 else f'FAILED / EXIT {code}'
        self.set_status(kind,f'{label}  |  {elapsed}s  |  PowerShell')
        if self.current and self.current!=self.active:self.warm_export(self.current)
    def update_clock(self):
        if self.running:
            self.statusBar().showMessage(f'●  {"STOPPING" if self.stop_pending else "RUNNING"}  |  {int(time.monotonic()-self.started)}s  |  Full log on disk')
            if self.output.blockCount()>=6000:self.refresh_steps()
    def stop(self):
        if not self.running or not self.proc or self.stop_pending:return
        if QMessageBox.question(self,'Stop','Terminate the running process tree? This does not undo changes.')!=QMessageBox.StandardButton.Yes:return
        self.cancelled=True;self.stop_pending=True;self.stopbtn.setEnabled(False);self.set_status('stopping','STOPPING  |  Waiting for process termination');pid=self.proc.processId();token=self.active
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
        ed=QPlainTextEdit(text);ed.setReadOnly(True);ed.setStyleSheet('font-family: Consolas; font-size: 12px');l.addWidget(ed,1)
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
        dialog.exec()
        dialog.deleteLater()

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
                        if i==2:item.setForeground(QColor({'success':'#b5cea8','warning':'#d7ba7d','error':'#f48771'}[tag]))
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
        try:atomic_text(SETTINGS,json.dumps({**self.settings,'workspace':self.cwd.text(),'library':str(self.lib),'wrap_output':self.wrap.isChecked(),'dense_output':self.dense.isChecked(),'show_sidebar':self.sidebar_action.isChecked()},ensure_ascii=False,indent=2))
        except OSError:pass
        event.accept()

def main():
    set_app_identity()
    app=QApplication(sys.argv);app.setApplicationName('Command Relay');app.setApplicationVersion(VERSION)
    icon=QIcon(str(ASSETS/'relay-icon.ico'))
    if icon.isNull():icon=QIcon(str(ASSETS/'relay-icon.png'))
    if not icon.isNull():app.setWindowIcon(icon)
    app.setStyle('Fusion');app.setStyleSheet(STYLE)
    chrome=NeutralChrome(app);app.installEventFilter(chrome)
    startup_mark('qt_initialized_ms')
    if not confirm_usage_terms(ROOT):
        return 0
    startup_mark('terms_accepted_ms')
    w=App()
    if not icon.isNull():w.setWindowIcon(icon)
    startup_mark('widgets_created_ms');w.show();startup_mark('show_called_ms');return app.exec()


if __name__ == "__main__":
    from .__main__ import main as launch
    raise SystemExit(launch(main))
