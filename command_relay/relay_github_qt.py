# SPDX-License-Identifier: Apache-2.0
"""Optional modal GitHub workbench. Network work is never on the GUI thread."""
import datetime
import json
import threading

from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout)
from .relay_terms import tr
from .relay_github import GitHubClient, GitHubError, MergeUnknown, workspace_repo, status_packet


class _Signals(QObject):
    done = Signal(str, object, str)


class GitHubDialog(QDialog):
    def __init__(self, workspace, parent=None, *, language="en"):
        super().__init__(parent)
        self.language = language
        self.setWindowTitle(self.ui('gh_title'))
        self.resize(820, 590)
        self.workspace = workspace
        self.busy = False
        self.snapshot = None
        self.observed = ''
        self.merge_sha = None
        self.outcome = 'observed'
        self.signals = _Signals(self)
        self.signals.done.connect(self.finished_work, Qt.ConnectionType.QueuedConnection)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(self.ui('gh_intro')))
        row = QHBoxLayout()
        row.addWidget(QLabel(self.ui('gh_repository')))
        self.repo = QLineEdit(); self.repo.setPlaceholderText('owner/repository'); self.repo.setMaxLength(140)
        row.addWidget(self.repo, 1)
        self.detect = self.button(row, self.ui('gh_origin'), self.detect_repo)
        self.refresh = self.button(row, self.ui('gh_refresh'), self.list_prs)
        layout.addLayout(row)
        row = QHBoxLayout(); row.addWidget(QLabel(self.ui('gh_pull_request')))
        self.prs = QComboBox(); self.prs.setEditable(True); self.prs.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.prs.lineEdit().setPlaceholderText(self.ui('gh_number'))
        self.prs.lineEdit().setMaxLength(510); row.addWidget(self.prs, 1)
        self.inspect_button = self.button(row, self.ui('gh_inspect'), self.inspect_pr)
        layout.addLayout(row)
        self.detail = QPlainTextEdit(); self.detail.setReadOnly(True)
        self.detail.setPlaceholderText(self.ui('gh_detail'))
        layout.addWidget(self.detail, 1)
        self.notice = QLabel(self.ui('gh_ready')); self.notice.setWordWrap(True)
        self.notice.setTextFormat(Qt.TextFormat.PlainText); layout.addWidget(self.notice)
        row = QHBoxLayout()
        self.merge_button = self.button(row, self.ui('gh_merge'), self.confirm_merge)
        self.copy_button = self.button(row, self.ui('gh_review_copy'), self.copy_status)
        row.addStretch(1); self.close_button = self.button(row, self.ui('gh_close'), self.reject)
        layout.addLayout(row)
        self.repo.textChanged.connect(self.clear_selection)
        self.prs.currentTextChanged.connect(self.invalidate)
        self.update_controls()

    def ui(self, key):
        return tr(key, self.language)

    @staticmethod
    def button(row, text, callback):
        button = QPushButton(text); button.clicked.connect(callback); row.addWidget(button)
        button.setAutoDefault(False)
        return button

    def update_controls(self):
        for control in (self.repo, self.detect, self.refresh, self.prs, self.inspect_button, self.close_button):
            control.setEnabled(not self.busy)
        self.merge_button.setEnabled(not self.busy and self.snapshot is not None and self.snapshot.ready and self.outcome == 'observed')
        self.copy_button.setEnabled(not self.busy and self.snapshot is not None)

    def invalidate(self, *_):
        self.snapshot = None; self.merge_sha = None; self.outcome = 'observed'
        self.detail.clear(); self.update_controls()

    def clear_selection(self, *_):
        self.prs.clear(); self.invalidate()

    def start(self, operation, fn):
        if self.busy: return
        self.busy = True; self.update_controls(); self.notice.setText(self.ui('gh_working'))
        def work():
            try: result, error = fn(), ''
            except MergeUnknown: result, error = None, 'unknown'
            except GitHubError as exc: result, error = None, str(exc)
            except Exception: result, error = None, 'Unexpected GitHub operation error.'
            self.signals.done.emit(operation, result, error)
        try:
            threading.Thread(target=work, daemon=True).start()
        except RuntimeError:
            self.busy = False; self.update_controls(); self.notice.setText(self.ui('gh_worker_failed'))

    def detect_repo(self):
        if self.busy: return
        self.invalidate(); self.start('origin', lambda: workspace_repo(self.workspace))

    def list_prs(self):
        if self.busy: return
        repo = self.repo.text().strip()
        self.clear_selection(); self.start('list', lambda: GitHubClient(repo).list_open())

    def inspect_pr(self):
        if self.busy: return
        repo = self.repo.text().strip()
        value = self.prs.currentText().split(' — ', 1)[0].strip()
        if not value.isascii() or not value.isdecimal() or len(value) > 10 or int(value) < 1:
            self.notice.setText(self.ui('gh_invalid_number')); return
        number = int(value)
        self.invalidate(); self.start('inspect', lambda: GitHubClient(repo).inspect(number))

    def render(self):
        pr = self.snapshot
        lines = [f'{pr.repo} · PR #{pr.number}', pr.title, f'{pr.head} → {pr.base}',
                 'Head SHA: ' + pr.head_sha, 'Base SHA: ' + pr.base_sha, self.ui('gh_state') + pr.state,
                 self.ui('gh_observed') + self.observed, '', self.ui('gh_checks')]
        lines += [f'  {c.state:<16} {c.name}' for c in pr.checks]
        lines += ['', self.ui('gh_readiness') + (self.ui('gh_readiness_yes') if pr.ready else self.ui('gh_readiness_no'))]
        lines += list(pr.blockers)
        if self.outcome != 'observed':
            lines += ['', self.ui('gh_outcome') + self.outcome]
        if self.merge_sha: lines += [self.ui('gh_verified_sha') + self.merge_sha]
        self.detail.setPlainText('\n'.join(lines))

    def finished_work(self, operation, result, error):
        self.busy = False
        if error:
            if operation == 'merge':
                # Any error disables another write until a fresh explicit inspection.
                self.outcome = 'unknown' if error == 'unknown' else 'not_verified'
                self.render()
                self.notice.setText(self.ui('gh_merge_unverified'))
            else:
                self.notice.setText(error)
        elif operation == 'origin':
            self.repo.setText(result); self.notice.setText(self.ui('gh_origin_detected'))
        elif operation == 'list':
            for number, title in result: self.prs.addItem(f'{number} — {title}')
            self.notice.setText(self.ui('gh_list_count').format(count=len(result)) + (self.ui('gh_list_limit') if len(result) == 100 else self.ui('gh_list_select')))
        elif operation == 'inspect':
            self.snapshot = result; self.observed = datetime.datetime.now(datetime.timezone.utc).isoformat()
            self.render(); self.notice.setText(self.ui('gh_snapshot'))
        elif operation == 'merge':
            self.merge_sha = result; self.outcome = 'verified_merged'; self.render()
            self.notice.setText(self.ui('gh_merge_verified'))
        self.update_controls()

    def confirm_merge(self):
        pr = self.snapshot
        if self.busy or pr is None or not pr.ready or self.outcome != 'observed': return
        box = QMessageBox(QMessageBox.Icon.Warning, self.ui('gh_confirm_title'),
            self.ui('gh_confirm_body').format(repo=pr.repo, number=pr.number, title=pr.title,
                head=pr.head, base=pr.base, head_sha=pr.head_sha, base_sha=pr.base_sha),
            QMessageBox.StandardButton.Cancel, self)
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.button(QMessageBox.StandardButton.Cancel).setText(self.ui('gh_cancel'))
        confirm = box.addButton(self.ui('gh_confirm_action'), QMessageBox.ButtonRole.AcceptRole)
        box.setDefaultButton(QMessageBox.StandardButton.Cancel); box.setEscapeButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        if box.clickedButton() is confirm and self.snapshot is pr and not self.busy:
            self.start('merge', lambda: GitHubClient(pr.repo).squash_merge(pr, confirmed=True))

    def copy_status(self):
        if self.busy or self.snapshot is None: return
        try:
            packet = status_packet(self.snapshot, self.observed, merge_sha=self.merge_sha, outcome=self.outcome)
            text = json.dumps(packet, ensure_ascii=False, indent=2, allow_nan=False)
        except Exception:
            self.notice.setText(self.ui('gh_export_failed')); return
        dialog = QDialog(self); dialog.setWindowTitle(self.ui('gh_review_json')); dialog.resize(760, 530)
        layout = QVBoxLayout(dialog); layout.addWidget(QLabel(self.ui('gh_mask_warning')))
        preview = QPlainTextEdit(text); preview.setReadOnly(True); layout.addWidget(preview, 1)
        row = QHBoxLayout(); self.button(row, self.ui('gh_copy_json'), lambda: QApplication.clipboard().setText(text))
        row.addStretch(); self.button(row, self.ui('gh_close'), dialog.reject); layout.addLayout(row); dialog.exec()

    def reject(self):
        if not self.busy: super().reject()

    def closeEvent(self, event):
        if self.busy: event.ignore()
        else: super().closeEvent(event)
