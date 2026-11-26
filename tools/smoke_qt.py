# SPDX-License-Identifier: Apache-2.0
"""Non-executing Qt smoke check, intended for an isolated CI checkout."""
import os
import json
import tempfile
from pathlib import Path
import sys
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QTimer, Qt, QPoint, QCoreApplication, QEvent
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication, QDialog, QPlainTextEdit, QPushButton, QMessageBox, QFileDialog
from command_relay import relay_qt
from command_relay.relay_version import VERSION
from command_relay.relay_terms import confirm_usage_terms, disclaimer_text, choose_language, tr

app = QApplication([])
root = Path(__file__).resolve().parents[1]

def settle_layout():
    # Nested layout requests may be posted by an earlier layout pass.
    # Match the bounded event processing verified by diagnostic task 041d.
    for _ in range(4):
        QCoreApplication.sendPostedEvents(None, QEvent.Type.LayoutRequest.value)
        app.processEvents()


# Exercise the real modal dialog without opening a workspace or running commands.
for language, action, expected in [('en', 'terms_decline', False), ('ru', 'close', False), ('en', 'terms_agree', True), ('ru', 'terms_agree', True)]:
    errors = []
    def interact():
        dialog = QApplication.activeModalWidget()
        try:
            assert isinstance(dialog, QDialog)
            notice = dialog.findChild(QPlainTextEdit)
            assert notice.isReadOnly()
            assert notice.toPlainText() == disclaimer_text(root, language)
            assert dialog.findChild(QPushButton, 'terms_agree').text() == tr('terms_agree', language)
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
    assert confirm_usage_terms(root, language) == expected
    assert not errors, errors
from PySide6.QtWidgets import QInputDialog, QComboBox
for selected, expected in [('ru', 'ru'), (None, None)]:
    errors = []
    def select():
        dialog = QApplication.activeModalWidget()
        try:
            assert isinstance(dialog, QInputDialog)
            if selected is None:
                dialog.reject()
            else:
                dialog.findChild(QComboBox).setCurrentIndex(1)
                dialog.accept()
        except Exception as exc:
            errors.append(exc)
            if dialog is not None:
                dialog.reject()
    QTimer.singleShot(0, select)
    assert choose_language() == expected
    assert not errors, errors
print('Qt startup locale and disclaimer checks passed (English/Russian, select, cancel, accept, decline, close).')
# Real chooser: cancellation, both modes, and reduced motion (no process/network).
for mode, reduced in ((None, True), ('casual', False), ('advanced', True)):
    errors = []
    def select_mode():
        dialog = QApplication.activeModalWidget()
        try:
            assert dialog.objectName() == 'workspace_mode_dialog'
            from PySide6.QtWidgets import QRadioButton
            if mode is None:
                dialog.reject()
            else:
                dialog.findChild(QRadioButton, 'mode_'+mode).setChecked(True)
                dialog.findChild(QPushButton, 'mode_continue').click()
        except Exception as exc:
            errors.append(exc)
            if dialog is not None: dialog.reject()
    QTimer.singleShot(0, select_mode)
    assert relay_qt.choose_workspace_mode(language='ru', reduced_motion=reduced) == mode
    assert not errors, errors
print('Qt workspace mode chooser passed (both modes, cancellation, reduced motion).')
# Localized workbench is constructed from a saved locale. Keep raw content intact.
for mode in ('casual', 'advanced'):
    with patch.object(relay_qt, 'read_settings', return_value={'language':'ru','mode':mode}), patch.object(relay_qt.App, 'start_initial_restore'):
        localized = relay_qt.App()
        localized.show(); settle_layout()
        assert localized.ui_language == 'ru'
        assert localized.more.text() == tr('more', 'ru')
        assert localized.settings_menu.title() == tr('settings', 'ru')
        assert localized.runbtn.text() == tr('run_short' if mode == 'casual' else 'run_commands', 'ru')
        assert localized.editor.accessibleName() == tr('command_editor', 'ru')
        assert localized.safety_action.isEnabled()
        assert 'без маскирования' in localized.copy_raw_action.text()
        raw = 'Write-Output "COMMANDS / READY"'
        localized.editor.setPlainText(raw); localized.output.setPlainText(raw)
        with patch.object(localized, 'start_process') as start:
            localized.apply_mode('advanced' if mode == 'casual' else 'casual')
            assert localized.editor.toPlainText() == raw and localized.output.toPlainText() == raw
            start.assert_not_called()
        # Verify Russian dialogs without any policy or network access.
        import queue
        safety = relay_qt.SafetyDialog(str(root), localized)
        assert safety.windowTitle() == tr('safety_title', 'ru')
        assert not safety.toggle.isEnabled() and not safety.update_toggle.isEnabled()
        assert safety.toggle.text() == tr('safety_merge', 'ru')
        safety.finish_policy(None, None, 'Local policy loaded. No changes made.')
        assert safety.notice.text() == tr('safety_loaded', 'ru')
        assert not safety.save_button.isEnabled() and not safety.update_save_button.isEnabled()
        errors = []
        def reject_permission():
            dialog = QApplication.activeModalWidget()
            try:
                assert dialog.windowTitle() == tr('safety_confirm', 'ru')
                assert dialog.defaultButton() is dialog.button(QMessageBox.StandardButton.Cancel)
                assert dialog.defaultButton().text() == tr('confirm_cancel', 'ru')
                assert 'owner/repo' in dialog.text()
                dialog.defaultButton().click()
            except Exception as exc:
                errors.append(exc)
                if dialog is not None: dialog.reject()
        QTimer.singleShot(0, reject_permission)
        assert not safety.confirm(tr('merge_allow', 'ru').format(workspace=str(root), repository='owner/repo'))
        assert not errors, errors
        updates_dialog = relay_qt.UpdatesDialog(localized)
        assert updates_dialog.windowTitle() == tr('update_title', 'ru')
        assert updates_dialog.trust.text() == tr('update_unverified', 'ru')
        assert not updates_dialog.verify_button.isEnabled() and not updates_dialog.prepare_button.isEnabled()
        updates_dialog.results = queue.Queue()
        updates_dialog.results.put(('check', None, 'Release check failed. Retry later.', 'Publisher signature: Not verified', None))
        updates_dialog.finish_check()
        assert updates_dialog.status.text() == tr('update_check_failed', 'ru')
        assert updates_dialog.trust.text() == tr('update_unverified', 'ru')
        assert not updates_dialog.prepare_button.isEnabled()
        safety.deleteLater(); updates_dialog.deleteLater()
        localized.initial_restore_pending = False
        localized.deleteLater(); settle_layout()
print('Qt localized workbench and dialog checks passed (Russian labels, both modes, raw content, default-deny permission and unverified update).')
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
    # A hidden outline consumes no scan timer; stale navigation cannot jump.
    window.tabs.setCurrentIndex(0)
    window.set_sidebar_visible(True)
    window.editor.setPlainText('@step First\nWrite-Output 1\n@step Second')
    assert window.outline_dirty and window.outline_timer.isActive() and not window.outline.isEnabled()
    window.refresh_outline()
    assert window.outline.count()==2 and window.outline.isEnabled() and not window.outline_timer.isActive()
    assert window.outline.item(1).data(Qt.ItemDataRole.UserRole)==2
    window.set_sidebar_visible(False)
    window.editor.setPlainText('\n@step New')
    assert window.outline_dirty and not window.outline_timer.isActive()
    window.refresh_outline(); assert window.outline.count()==2
    window.set_sidebar_visible(True); assert window.outline_timer.isActive()
    window.refresh_outline()
    assert window.outline.count()==1 and window.outline.item(0).data(Qt.ItemDataRole.UserRole)==1
    window.jump(window.editor,window.outline.item(0)); assert window.editor.textCursor().blockNumber()==1
    window.editor.clear(); window.refresh_outline()
    # Valid file drag is highlighted; remote/multiple/read-only drops are rejected.
    from PySide6.QtCore import QMimeData, QUrl, QPointF
    from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDropEvent
    def drag(mime):
        return QDragEnterEvent(QPoint(2,2),Qt.DropAction.CopyAction,mime,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier)
    mime=QMimeData(); mime.setUrls([QUrl.fromLocalFile(str(root/'sample.json'))])
    event=drag(mime); window.editor.dragEnterEvent(event)
    assert event.isAccepted() and window.editor.property('fileDropActive') is True
    window.editor.dragLeaveEvent(QDragLeaveEvent()); assert not window.editor.property('fileDropActive')
    for urls in ([QUrl('https://example.invalid/task.json')],[QUrl.fromLocalFile('a'),QUrl.fromLocalFile('b')]):
        bad=QMimeData(); bad.setUrls(urls); event=drag(bad); window.editor.dragEnterEvent(event)
        assert not event.isAccepted() and not window.editor.property('fileDropActive')
    with patch.object(window,'start_process') as start:
        dropped=Mock(); window.editor.fileDropped.connect(dropped)
        # Disconnect the actual load slot for the synthetic event only.
        window.editor.fileDropped.disconnect(window.load)
        try:
            def drop():
                return QDropEvent(QPointF(2,2),Qt.DropAction.CopyAction,mime,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier)
            event=drop();window.editor.dropEvent(event);assert event.isAccepted();dropped.assert_called_once()
            window.editor.setReadOnly(True)
            event=drop();window.editor.dropEvent(event);assert not event.isAccepted();dropped.assert_called_once()
            window.editor.setReadOnly(False);start.assert_not_called()
        finally:
            window.editor.fileDropped.disconnect(dropped); window.editor.fileDropped.connect(window.load)
    print('Qt editor responsiveness checks passed (coalesced outline, hidden sidebar, current offsets, drag feedback, read-only denial).')
    # Settings navigation shares existing controls; no policy mutation or network work.
    assert window.settings_menu.objectName() == 'workbench_settings'
    assert window.settings_menu.menuAction() in window.more.menu().actions()
    assert window.safety_action in window.settings_menu.actions()
    assert window.safety_action not in window.more.menu().actions()
    actions = {a.objectName(): a for a in window.settings_menu.actions() if a.objectName()}
    assert set(actions) == {'settings_safety', 'settings_updates', 'settings_language', 'settings_mode', 'settings_light_theme', 'settings_reduced_motion', 'settings_sidebar', 'settings_wrap', 'settings_dense'}
    assert actions['settings_safety'].isEnabled()
    with patch.object(relay_qt, 'choose_language', return_value=None), patch.object(relay_qt, 'atomic_text') as save:
        actions['settings_language'].trigger()
        save.assert_not_called()
    with patch.object(relay_qt, 'choose_language', return_value='ru'), patch.object(relay_qt, 'atomic_text') as save, patch.object(QMessageBox, 'information'):
        actions['settings_language'].trigger()
        assert json.loads(save.call_args.args[1])['language'] == 'ru'
        assert window.settings['language'] == 'ru'
        assert window.ui_language == 'en' and window.more.text() == 'More'
    window.settings.pop('language', None)
    for name, control in [('settings_wrap', window.wrap), ('settings_dense', window.dense)]:
        action = actions[name]
        initial = control.isChecked()
        assert action.isCheckable() and action.isChecked() == initial
        action.trigger(); assert control.isChecked() != initial
        control.setChecked(initial); assert action.isChecked() == initial
    initial = window.sidebar_action.isChecked()
    window.sidebar_action.trigger(); assert window.tabs.isHidden() == initial
    window.sidebar_action.trigger(); assert window.sidebar_action.isChecked() == initial
    # Switch through Settings, keeping the editor, task inspector, output and safety intact.
    editor, output, inspector = window.editor, window.output, window.inspector_label
    editor.setPlainText('Write-Output test'); output.setPlainText('Existing output')
    with patch.object(relay_qt, 'choose_workspace_mode', return_value=None), patch.object(relay_qt, 'atomic_text') as save:
        actions['settings_mode'].trigger(); save.assert_not_called()
    with patch.object(relay_qt, 'choose_workspace_mode', return_value='casual'), patch.object(relay_qt, 'atomic_text') as save, patch.object(window, 'start_process') as start:
        actions['settings_mode'].trigger(); assert json.loads(save.call_args.args[1])['mode'] == 'casual'
        assert window.mode == 'casual' and window.tabs.isHidden() and window.casual_hint.isVisible()
        assert window.editor is editor and window.output is output and window.inspector_label is inspector
        assert editor.isVisible() and output.isVisible() and window.safety_action.isEnabled()
        assert editor.toPlainText() == 'Write-Output test' and output.toPlainText() == 'Existing output'
        assert window.runbtn.isEnabled(); start.assert_not_called()
    # The Casual card tracks actual state; it is not a separate executor.
    assert window.casual_title.text() == tr('casual_edited')
    assert tr('casual_review') in window.casual_hint.accessibleName()
    with patch.object(window, 'start_process') as start:
        window.set_busy(True)
        assert tr('casual_run') in window.casual_hint.accessibleName()
        window.casual_report_ready=True
        window.set_busy(False)
        assert tr('casual_result') in window.casual_hint.accessibleName()
        assert 'not a test verdict' in window.casual_help.text()
        editor.setPlainText('Write-Output changed')
        assert tr('casual_review') in window.casual_hint.accessibleName()
        editor.setPlainText('Write-Output test')
        start.assert_not_called()
    print('Qt Casual workflow card checks passed (review, running, report, invalidation).')
    window.sidebar_action.trigger(); assert not window.tabs.isHidden()
    window.sidebar_action.trigger(); assert window.tabs.isHidden()
    with patch.object(relay_qt, 'choose_workspace_mode', return_value='advanced'), patch.object(relay_qt, 'atomic_text'):
        actions['settings_mode'].trigger()
        assert window.mode == 'advanced' and not window.tabs.isHidden() and window.casual_hint.isHidden()
    # Theme changes do not rebuild widgets, trigger execution or rewrite raw text.
    theme = actions['settings_light_theme']
    assert relay_qt.current_theme() == 'dark' and not theme.isChecked()
    with patch.object(relay_qt, 'atomic_text') as save, patch.object(window, 'start_process') as start:
        theme.trigger(); settle_layout()
        assert relay_qt.current_theme() == 'light' and window.settings['theme'] == 'light'
        assert json.loads(save.call_args.args[1])['theme'] == 'light'
        assert window.editor is editor and window.output is output and window.inspector_label is inspector
        assert editor.toPlainText() == 'Write-Output test' and output.toPlainText() == 'Existing output'
        assert window.runbtn.isEnabled() and window.safety_action.isEnabled()
        assert window.editor_highlight.tokens == relay_qt.colors()
        assert not window.activity._timer.isActive()
        assert window.editor.palette().color(QPalette.ColorRole.Base).name() == relay_qt.colors()['surface']
        theme.trigger(); settle_layout()
        assert relay_qt.current_theme() == 'dark' and not theme.isChecked()
        start.assert_not_called()
    with patch.object(relay_qt, 'atomic_text', side_effect=OSError('mock write denied')), patch.object(window, 'error') as error:
        theme.trigger(); assert not theme.isChecked() and relay_qt.current_theme() == 'dark'
        error.assert_called_once()
    print('Qt theme checks passed (live switch, persistence, denied write, state and safety).')
    editor.clear(); output.clear()
    print('Qt shared workspace mode checks passed (state, safety, independent sidebar, settings).')
    # Activity and output timers are idle when no commands are running.
    assert not window.timer.isActive() and not window.clock.isActive()
    motion = actions['settings_reduced_motion']
    assert not motion.isChecked() and not window.activity._timer.isActive()
    window.set_busy(True)
    assert window.timer.isActive() and window.clock.isActive()
    assert window.activity._timer.isActive()
    motion.trigger()
    assert window.settings['reduced_motion'] is True and window.activity.isVisible()
    assert not window.activity._timer.isActive()
    motion.trigger()
    assert window.activity._timer.isActive()
    window.hide(); app.processEvents()
    assert not window.activity._timer.isActive()
    window.show(); app.processEvents()
    assert window.activity._timer.isActive()
    window.set_busy(False)
    assert not window.timer.isActive() and not window.clock.isActive()
    assert not window.activity._timer.isActive() and window.activity.isHidden()
    window.set_status('ready', 'READY')
    print('Qt idle timer and reduced motion checks passed (no commands executed).')
    print('Qt settings navigation checks passed (shared preferences and compact menu).')
    from command_relay import relay_updates as updates
    import time
    data = {'id': 1, 'tag_name': 'v4.10.0', 'draft': False, 'prerelease': False,
            'assets': [{'id': i, 'name': 'command-relay-v4.10.0-windows' + ext,
                        'state': 'uploaded', 'size': 64, 'digest': 'sha256:' + 'a' * 64}
                       for i, ext in enumerate(('.zip', '.sha256', '.manifest.json', '.manifest.sig'), 2)]}
    info = updates.parse_latest(data, VERSION)
    unsigned = updates.parse_latest(dict(data, assets=data['assets'][:2]), VERSION)
    signed = Mock(); signed.download.sha256 = 'a'*64
    with patch.object(updates, 'check_latest', side_effect=[info, info, unsigned, updates.UpdateError('mock failure')]) as check, \
            patch.object(updates, 'download_signed_update', side_effect=[updates.UpdateError('bad signature'), signed]) as verify:
        dialog = relay_qt.UpdatesDialog(window)
        dialog.show(); app.processEvents()
        check.assert_not_called(); verify.assert_not_called()
        assert not dialog.verify_button.isEnabled()
        def wait_updates():
            deadline = time.monotonic() + 5
            while dialog.results is not None and time.monotonic() < deadline:
                app.processEvents(); time.sleep(.01)
            assert dialog.results is None and dialog.check_button.isEnabled()
        dialog.check_button.click()
        assert not dialog.check_button.isEnabled() and not dialog.verify_button.isEnabled()
        wait_updates()
        assert 'NOT verified' in dialog.trust.text() and dialog.verify_button.isEnabled()
        verify.assert_not_called()
        dialog.verify_button.click(); wait_updates()
        assert 'failed' in dialog.status.text() and 'Not verified' in dialog.trust.text()
        assert not dialog.digest.text() and dialog.verify_button.isEnabled()
        dialog.verify_button.click(); wait_updates()
        assert dialog.trust.text() == 'Publisher signature: Verified'
        assert 'a'*64 in dialog.digest.text() and not dialog.verify_button.isEnabled()
        assert 'retained' in dialog.status.text() and dialog.signed is signed
        assert not dialog.prepare_button.isEnabled()  # no guarded portable GUI in smoke
        with patch.object(updates, 'gui_handoff_available', return_value=True), \
                patch.object(QFileDialog, 'getExistingDirectory', return_value=str(root)), \
                patch.object(QMessageBox, 'question', side_effect=[QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes]), \
                patch.object(updates, 'prepare_gui_update_handoff', side_effect=updates.UpdateError('mock denied')) as prepare:
            dialog.prepare_installation(); prepare.assert_not_called()
            dialog.prepare_installation(); prepare.assert_called_once_with(root, root, signed)
            assert 'mock denied' in dialog.status.text() and dialog.handoff is None
            assert dialog.signed is signed
        dialog.check_button.click(); wait_updates()
        assert 'NOT verified' in dialog.trust.text() and not dialog.digest.text() and dialog.signed is None
        dialog.check_button.click(); wait_updates()
        assert not dialog.verify_button.isEnabled() and 'missing' in dialog.trust.text()
        dialog.verify(); assert verify.call_count == 2
        dialog.check_button.click(); wait_updates()
        assert 'Unavailable' in dialog.latest.text() and 'failed' in dialog.status.text()
        assert not dialog.verify_button.isEnabled()
        assert check.call_count == 4 and verify.call_count == 2
        assert all(call.args == (info,) for call in verify.call_args_list)
        dialog.reject(); dialog.deleteLater(); app.processEvents()
    # Separate accepted preparation; no real download, disk writes or process.
    dialog = relay_qt.UpdatesDialog(window)
    dialog.signed = signed
    prepared = object()
    with patch.object(updates, 'gui_handoff_available', return_value=True), \
            patch.object(QFileDialog, 'getExistingDirectory', return_value=str(root)), \
            patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes), \
            patch.object(updates, 'prepare_gui_update_handoff', return_value=prepared):
        dialog.prepare_installation()
        assert dialog.result() == QDialog.DialogCode.Accepted and dialog.handoff is prepared
        assert dialog.signed is None
    dialog.deleteLater(); app.processEvents()
    print('Qt updates settings checks passed (explicit metadata lookup, verification success/failure, stale state reset, unsigned denial, prepare cancel/deny/accept; mocked network and preparation).')
    # Reproduce audit 041: long labels, compact window, both layout directions.
    original_size = window.size()
    original_direction = window.layoutDirection()
    original_labels = (window.runbtn.text(), window.more.text())
    try:
        for direction in (Qt.LayoutDirection.LeftToRight, Qt.LayoutDirection.RightToLeft):
            window.setLayoutDirection(direction)
            window.runbtn.setText('▶ Run commands / Erweiterte Befehle ausführen')
            window.more.setText('More / Weitere Einstellungen')
            for width, height in ((850, 560), (1180, 740)):
                window.resize(width, height)
                settle_layout()
                for button in (window.openbtn, window.pastebtn, window.stopbtn, window.runbtn, window.more):
                    assert button.width() >= button.sizeHint().width(), (button.text(), button.width(), button.sizeHint().width())
                    assert window.rect().contains(button.rect().translated(button.mapTo(window, QPoint(0, 0))))
                for row in (window.header_row, window.command_row):
                    a, b = (row.itemAt(i).geometry() for i in range(2))
                    assert not a.intersects(b), (a, b)
                    assert row.geometry().contains(a) and row.geometry().contains(b), (row.geometry(), a, b)
                    if row.geometry().width() < row.sizeHint().width():
                        assert b.top() > a.bottom(), (a, b)
                assert window.width() <= width and window.height() <= height
    finally:
        window.runbtn.setText(original_labels[0])
        window.more.setText(original_labels[1])
        window.setLayoutDirection(original_direction)
        window.resize(original_size)
        settle_layout()
    for row in (window.header_row, window.command_row):
        if row.geometry().width() >= row.sizeHint().width():
            a, b = (row.itemAt(i).geometry() for i in range(2))
            assert a.top() <= b.bottom() and b.top() <= a.bottom(), (a, b)
    print('Qt compact action layout checks passed (long labels, LTR and RTL, adaptive groups).')
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
        assert dialog.history_button.isEnabled()
        assert [e['operation'] for e in permissions.audit_history(dialog.snapshot)['events']] == ['grant', 'revoke_all']
        assert 'revoke_all' in permissions.audit_text(dialog.snapshot)
        dialog.reject()
    print('Qt safety settings checks passed (default deny, cancel, opt-in, revoke; temporary policy only).')
    # The application scope must not depend on a selected Git workspace.
    with tempfile.TemporaryDirectory() as tmp:
        install = Path(tmp).resolve()
        (install / 'Start.pyw').touch()
        with patch.object(relay_qt, 'ROOT', install), patch.object(permissions, 'policy_path', return_value=install/'automation-permissions.json'), \
                patch('command_relay.relay_github.workspace_repo', side_effect=ValueError('no origin')):
            dialog = relay_qt.SafetyDialog(str(install / 'unrelated-workspace'), window)
            dialog.refresh(); wait_safety()
            assert not dialog.toggle.isEnabled()
            assert dialog.update_toggle.isEnabled() and not dialog.update_toggle.isChecked()
            dialog.update_toggle.setChecked(True)
            with patch.object(dialog, 'confirm', return_value=False): dialog.save_update()
            assert not dialog.update_toggle.isChecked() and not permissions.policy_path().exists()
            dialog.update_toggle.setChecked(True)
            with patch.object(dialog, 'confirm', return_value=True): dialog.save_update(); wait_safety()
            assert permissions.allowed(permissions.policy_snapshot(), 'update_install')
            dialog.update_toggle.setChecked(False)
            with patch.object(dialog, 'confirm', return_value=True): dialog.save_update(); wait_safety()
            assert not permissions.allowed(permissions.policy_snapshot(), 'update_install')
            assert [e['operation'] for e in permissions.audit_history(dialog.snapshot)['events']] == ['grant_update_install', 'revoke_update_install']
            (install / '.git').touch()
            dialog.refresh(); wait_safety()
            assert not dialog.update_toggle.isEnabled()
            dialog.reject()
    print('Qt update permission checks passed (application scope, cancel, grant, revoke, source checkout denial; temporary policy only).')
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
