# SPDX-License-Identifier: Apache-2.0
"""Non-executing Qt smoke check, intended for an isolated CI checkout."""
import os
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialog, QPlainTextEdit, QPushButton
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
    window.hide()
    window.deleteLater()
    app.processEvents()
print('Qt startup smoke check passed (no commands executed).')
