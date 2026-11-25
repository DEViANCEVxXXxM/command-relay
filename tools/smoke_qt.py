# SPDX-License-Identifier: Apache-2.0
"""Non-executing Qt smoke check, intended for an isolated CI checkout."""
import os
import json
import tempfile
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialog, QPlainTextEdit, QPushButton, QMessageBox
from command_relay import relay_qt
from command_relay.relay_version import VERSION
from command_relay.relay_terms import confirm_usage_terms, disclaimer_text

app = QApplication([])
root = Path(__file__).resolve().parents[1]

# Exercise the real modal dialog without opening a workspace or running commands.
for action, expected in [('terms_decline', False), ('close', False), ('terms_agree', True)]:
    errors = []
    def interact():
        dialog = QApplication.activeModalWidget()
        try:
            assert isinstance(dialog, QDialog)
            notice = dialog.findChild(QPlainTextEdit)
            assert notice.isReadOnly()
            assert notice.toPlainText() == disclaimer_text(root)
            assert dialog.findChild(QPushButton, 'terms_decline').isDefault()
            assert not dialog.findChild(QPushButton, 'terms_agree').isDefault()
            if action == 'close':
                dialog.close()
            else:
                dialog.findChild(QPushButton, action).click()
        except Exception as exc:
            errors.append(exc)
            if dialog is not None:
                dialog.reject()
    QTimer.singleShot(0, interact)
    assert confirm_usage_terms(root) == expected
    assert not errors, errors
print('Qt startup disclaimer checks passed (accept, decline, close).')
# Disable local restoration; no reports or commands are opened/executed.
with patch.object(relay_qt, 'read_settings', return_value={}), patch.object(relay_qt.App, 'start_initial_restore'):
    window = relay_qt.App()
    window.show()
    app.processEvents()
    assert VERSION in window.windowTitle()
    assert not window.running
    assert window.editor.toPlainText() == ''
    assert window.runbtn.isEnabled()
    # Exercise the real pre-run gate without actually executing or journaling a command.
    with tempfile.TemporaryDirectory() as tmp, patch.object(relay_qt, 'REPORTS', Path(tmp)), \
            patch.object(window, 'begin') as begin, patch.object(window, 'start_process') as start:
        window.cwd.setText(str(root))
        task = {'schema': 'command-relay/task-v1', 'task_id': 'smoke-repeat',
                'script': "Write-Output 'COUNT=15'", 'assertions': {'metrics': [{'key': 'COUNT', 'equals': 15}]}}
        window.import_data(json.dumps(task).encode(), 'smoke.json')
        window.run()
        try:
            assert start.call_count == 1
            header = begin.call_args.args[1]
            (Path(tmp) / 'report-20261125-070000-000001.txt').write_text(
                header + 'COUNT=15\n@step END\nProcess exit code: 0\nCancelled: False\nFinished: 2026-11-25T07:00:01\n', encoding='utf-8')
        finally:
            window.cleanup_temp()
        for accept, expected_calls in [(False, 1), (True, 2)]:
            errors = []
            def interact_repeat():
                dialog = QApplication.activeModalWidget()
                try:
                    assert isinstance(dialog, QMessageBox)
                    assert dialog.windowTitle() == 'Review previous execution'
                    assert 'PASS' in dialog.text()
                    assert dialog.defaultButton() is dialog.button(QMessageBox.StandardButton.Cancel)
                    if accept:
                        next(b for b in dialog.buttons() if b.text() == 'Run anyway').click()
                    else:
                        dialog.defaultButton().click()
                except Exception as exc:
                    errors.append(exc)
                    if dialog is not None:
                        dialog.reject()
            QTimer.singleShot(0, interact_repeat)
            try:
                window.run()
                assert not errors, errors
                assert start.call_count == expected_calls
            finally:
                window.cleanup_temp()
    print('Qt repeated-task confirmation checks passed (cancel and explicit rerun; no commands executed).')
    window.hide()
    window.deleteLater()
    app.processEvents()
print('Qt startup smoke check passed (no commands executed).')
