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
    # Discoverable copy alternatives dispatch the same existing modes, without modifier keys.
    assert window.cwd.accessibleName() == 'Working directory'
    assert window.editor.accessibleName() == 'Command editor'
    assert window.output.accessibleName() == 'Read-only terminal output'
    assert window.find_previous.accessibleName() and window.find_next.accessibleName()
    assert window.close_search.accessibleName()
    assert 'RAW, unmasked' in window.copy_raw_action.text()
    with patch.object(window, 'copy_report') as copy, patch.object(window, 'start_process') as start:
        for action, mode in ((window.copy_ai_action, 'ai'), (window.copy_text_action, 'compact'),
                             (window.copy_raw_action, 'full')):
            action.trigger()
            copy.assert_called_with(mode)
        assert copy.call_count == 3
        start.assert_not_called()
    print('Qt workbench accessibility checks passed (named controls and explicit copy modes; no commands executed).')
    from command_relay import relay_permissions as permissions
    import time
    with tempfile.TemporaryDirectory() as tmp, patch.object(permissions, 'policy_path', return_value=Path(tmp)/'automation-permissions.json'), \
            patch('command_relay.relay_github.workspace_repo', return_value='owner/repo'):
        dialog = relay_qt.SafetyDialog(tmp, window)
        def wait_safety():
            deadline = time.monotonic() + 5
            while dialog.busy and time.monotonic() < deadline:
                app.processEvents(); time.sleep(.01)
            assert not dialog.busy
        dialog.refresh(); wait_safety()
        assert not dialog.toggle.isChecked() and dialog.toggle.isEnabled()
        assert not permissions.policy_path().exists()
        dialog.toggle.setChecked(True)
        with patch.object(dialog, 'confirm', return_value=False): dialog.save()
        assert not dialog.toggle.isChecked() and not permissions.policy_path().exists()
        dialog.toggle.setChecked(True)
        with patch.object(dialog, 'confirm', return_value=True): dialog.save(); wait_safety()
        assert dialog.toggle.isChecked()
        assert permissions.allowed(permissions.read_automation_settings(), 'squash_merge', workspace=tmp, repository='owner/repo')
        with patch.object(dialog, 'confirm', return_value=True): dialog.revoke_all(); wait_safety()
        assert not dialog.toggle.isChecked()
        assert not permissions.allowed(permissions.read_automation_settings(), 'squash_merge', workspace=tmp, repository='owner/repo')
        dialog.reject()
    print('Qt safety settings checks passed (default deny, cancel, opt-in, revoke; temporary policy only).')
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
    # Session review uses the selected workspace, never executes a task or auto-copies.
    with tempfile.TemporaryDirectory() as tmp, patch.object(relay_qt, 'REPORTS', Path(tmp)), \
            patch.object(window, 'start_tool') as tool:
        window.cwd.setText(str(root))
        window.review_session_context()
        tool.assert_called_once()
        title, work = tool.call_args.args
        assert title == 'Workspace session context'
        packet = work()
        assert packet['schema'] == 'command-relay/session-v1'
        assert packet['handoff']['latest_report'] is None
        assert packet['current_project']['network'] is False
    print('Qt session review entry point checks passed (local-only preview).')

    # Mock all CLI traffic. Exercise the actual dialog, worker completion and confirmation.
    from command_relay import relay_github_qt
    from command_relay.relay_github import PullRequest, Check, MergeUnknown
    from unittest.mock import Mock
    import time
    snapshot = PullRequest('owner/repo', 42, 'Test', 'main', 'feat/test', 'a'*40, 'b'*40,
                           'OPEN', (Check('CI', 'SUCCESS'),), ())
    client = Mock(); client.list_open.return_value = ((42, 'Test'),)
    client.inspect.return_value = snapshot; client.squash_merge.return_value = 'c'*40
    def wait_worker(dialog):
        deadline = time.monotonic() + 5
        while dialog.busy and time.monotonic() < deadline:
            app.processEvents(); time.sleep(0.01)
        assert not dialog.busy, 'GitHub worker did not complete'
    with patch.object(relay_github_qt, 'GitHubClient', return_value=client):
        dialog = relay_github_qt.GitHubDialog(str(root), window)
        dialog.show(); dialog.repo.setText('owner/repo'); dialog.list_prs(); wait_worker(dialog)
        assert dialog.prs.count() == 1
        dialog.inspect_pr(); wait_worker(dialog)
        assert dialog.merge_button.isEnabled()
        def choose_merge(accept):
            errors = []
            def interact():
                box = QApplication.activeModalWidget()
                try:
                    assert isinstance(box, QMessageBox)
                    assert box.defaultButton() is box.button(QMessageBox.StandardButton.Cancel)
                    assert 'b'*40 in box.text()
                    if accept:
                        next(b for b in box.buttons() if b.text() == 'Squash and merge').click()
                    else: box.defaultButton().click()
                except Exception as exc:
                    errors.append(exc)
                    if box is not None: box.reject()
            QTimer.singleShot(0, interact); dialog.confirm_merge(); wait_worker(dialog)
            assert not errors, errors
        choose_merge(False); client.squash_merge.assert_not_called()
        choose_merge(True); client.squash_merge.assert_called_once_with(snapshot, confirmed=True)
        assert dialog.outcome == 'verified_merged' and dialog.merge_sha == 'c'*40
        assert not dialog.merge_button.isEnabled()
        dialog.inspect_pr(); wait_worker(dialog)
        client.squash_merge.side_effect = MergeUnknown('mocked lost response')
        choose_merge(True); assert dialog.outcome == 'unknown' and not dialog.merge_button.isEnabled()
        assert client.squash_merge.call_count == 2
        dialog.repo.setText('other/repo'); assert dialog.snapshot is None and not dialog.merge_button.isEnabled()
        dialog.reject(); dialog.deleteLater(); app.processEvents()
    print('Qt GitHub PR manager checks passed (mocked list, inspect, cancel, merge and unknown outcome; no network writes).')
    window.hide()
    window.deleteLater()
    app.processEvents()
print('Qt startup smoke check passed (no commands executed).')
