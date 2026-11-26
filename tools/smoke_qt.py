# SPDX-License-Identifier: Apache-2.0
"""Qt smoke check; real Windows batch tests only with --native-batch."""
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


def native_batch_smoke(parent):
    """Explicit opt-in GUI-to-Job-Object test in disposable Windows directories."""
    import time
    from command_relay import relay_core as core, relay_view as view
    assert sys.platform == 'win32', 'Native batch smoke requires Windows'
    with tempfile.TemporaryDirectory(prefix='relay-native-batch-') as td:
        folder = Path(td)
        def run_case(case, specs, expected, cancelled=False):
            base = folder / case; base.mkdir()
            reports = base / 'reports'
            roots = {}; entries = []
            for key, deps, script in specs:
                workspace = base / key; workspace.mkdir(); roots[key] = str(workspace)
                entries.append({'task': {'schema':'command-relay/task-v1', 'task_id':key,
                    'title':'Native '+key, 'script':script, 'assertions':{'exit_code':0,
                    'metrics':[{'key':'RESULT','equals':True,'occurrence':'all'}]}}, 'depends_on':deps})
            plan = core.load_batch(json.dumps({'schema':'command-relay/batch-v1','batch_id':case,'tasks':entries}).encode())
            dialog = relay_qt.BatchReviewDialog(plan,parent,td)
            dialog.show(); dialog.workspaces = roots; dialog.update_bindings()
            dialog.workers.setCurrentIndex(1); dialog.validate_paths()
            assert dialog.start_button.isEnabled(), dialog.status.text()
            def wait_for(predicate, seconds=20):
                deadline = time.monotonic()+seconds
                while time.monotonic()<deadline:
                    app.processEvents(); dialog.refresh_execution()
                    if predicate(): return
                    time.sleep(.02)
                raise AssertionError((case, dialog.status.text(), dialog.snapshot))
            def states(): return (dialog.snapshot or {}).get('states', {})
            with patch.object(relay_qt,'REPORTS',reports):
                try:
                    with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.No):
                        dialog.start_button.click()
                    assert dialog.session is None and not reports.exists()
                    with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes) as confirm:
                        dialog.start_button.click()
                    assert confirm.call_args.args[-1] == QMessageBox.StandardButton.No
                    assert dialog.session is not None and not dialog.close_button.isEnabled()
                    dialog.reject(); assert not dialog.close_button.isEnabled()
                    wait_for(lambda: states().get('a') == states().get('b') == 'running')
                    assert states().get('c') == 'pending'
                    if cancelled:
                        dialog.table.selectRow(0); assert dialog.cancel_button.isEnabled()
                        dialog.cancel_button.click()
                        wait_for(lambda: states().get('a') == 'cancelled')
                        assert states().get('b') == 'running'
                        assert states().get('c') == 'blocked'
                        dialog.stop_button.click()
                    wait_for(lambda: dialog.close_button.isEnabled(), 30)
                    assert states() == expected, dialog.snapshot
                    assert dialog.snapshot['finished'] and not dialog.worker.is_alive()
                    receipts = dialog.snapshot['receipts']
                    assert set(receipts) == {k for k,v in expected.items() if v != 'blocked'}
                    assert len(list(reports.glob('report-*.txt'))) == len(receipts)
                    assert len({r.attempt.token for r in receipts.values()}) == len(receipts)
                    for key, receipt in receipts.items():
                        assert receipt.state == expected[key] and receipt.report_path.parent == reports.resolve()
                        raw = receipt.report_path.read_bytes(); text = raw.decode('utf-8')
                        assert core.sha(raw) == receipt.report_sha256
                        fields = core.report_header_fields(text)
                        assert fields['Task ID'] == key and fields['Attempt ID'] == receipt.attempt.token
                        assert Path(fields['Working directory']).resolve() == Path(roots[key]).resolve()
                        if not cancelled:
                            assert receipt.exit_code == 0
                            assert view.history_assertions(receipt.report_path)[0] == ('FAIL' if key=='b' else 'PASS')
                            assert 'NATIVE_'+key.upper() in text
                        else:
                            assert 'Cancelled: True' in text
                    if expected['c'] == 'blocked':
                        assert not any('NATIVE_C' in p.read_text(encoding='utf-8') for p in reports.glob('report-*.txt'))
                finally:
                    if dialog.worker is not None and dialog.worker.is_alive():
                        dialog.stop_batch(); dialog.worker.join(timeout=12)
                    dialog.refresh_execution()
                    if dialog.worker is None or not dialog.worker.is_alive():
                        dialog.poll_timer.stop(); dialog.hide(); dialog.deleteLater(); app.processEvents()
        run_case('native-success-failure', [
            ('a', [], 'Start-Sleep -Seconds 2\nWrite-Output "NATIVE_A"\nWrite-Output "RESULT=True"\nexit 0'),
            ('b', [], 'Start-Sleep -Seconds 2\nWrite-Output "NATIVE_B"\nWrite-Output "RESULT=False"\nexit 0'),
            ('c', ['b'], 'Write-Output "NATIVE_C"\nWrite-Output "RESULT=True"\nexit 0'),
            ('d', ['a'], 'Write-Output "NATIVE_D"\nWrite-Output "RESULT=True"\nexit 0'),
        ], {'a':'succeeded','b':'failed','c':'blocked','d':'succeeded'})
        run_case('native-cancel', [
            ('a', [], 'Start-Sleep -Seconds 40\nWrite-Output "RESULT=True"\nexit 0'),
            ('b', [], 'Start-Sleep -Seconds 40\nWrite-Output "RESULT=True"\nexit 0'),
            ('c', ['a'], 'Write-Output "NATIVE_C"\nWrite-Output "RESULT=True"\nexit 0'),
        ], {'a':'cancelled','b':'cancelled','c':'blocked'}, cancelled=True)
    print('NATIVE_BATCH_GUI_PASS=True', flush=True)


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
        # Batch review is inert in both modes, binds only explicitly selected paths.
        from command_relay.relay_core import load_batch
        with tempfile.TemporaryDirectory() as td:
            from PySide6.QtWidgets import QTableWidget
            packet = {'schema':'command-relay/batch-v1','batch_id':'smoke-batch','tasks':[
                {'task':{'schema':'command-relay/task-v1','task_id':key,'title':'Task '+key,
                         'script':'Write-Output "RESULT=True"','workspace_hint':'untrusted-path',
                         'assertions':{'exit_code':0}},'depends_on':deps}
                for key,deps in [('a',[]),('b',['a'])]]}
            path=Path(td)/'batch.json'; path.write_text(json.dumps(packet),encoding='utf-8')
            old_editor=localized.editor.toPlainText(); old_workspace=localized.cwd.text(); errors=[]
            def inspect_batch():
                dialog=QApplication.activeModalWidget()
                try:
                    assert dialog.objectName()=='batchReviewDialog'
                    assert dialog.table.rowCount()==2 and not dialog.validate.isEnabled()
                    assert dialog.script.isReadOnly() and dialog.meta.isReadOnly()
                    dialog.table.selectRow(1); assert dialog.table.item(1,1).text()=='a'
                    assert 'untrusted-path' in dialog.meta.toPlainText() and dialog.workspaces=={}
                    with patch.object(QFileDialog,'getExistingDirectory',return_value=td): dialog.choose_every()
                    assert dialog.validate.isEnabled() and set(dialog.workspaces)=={'a','b'}
                    dialog.validate_paths(); assert dialog.status.text()==tr('batch_validated','ru')
                    with patch.object(QFileDialog,'getExistingDirectory',return_value=''): dialog.choose_one()
                    assert dialog.status.text()==tr('batch_validated','ru')
                    with patch.object(QFileDialog,'getExistingDirectory',return_value=str(Path(td)/'missing')): dialog.choose_one()
                    assert dialog.status.text()==tr('batch_invalidated','ru')
                    dialog.validate_paths(); assert dialog.status.text().startswith(tr('batch_error','ru'))
                except Exception as exc: errors.append(exc)
                finally:
                    if dialog is not None: dialog.reject()
            with patch.object(QFileDialog,'getOpenFileName',return_value=(str(path),'')), patch.object(localized,'start_process') as start, patch('command_relay.relay_windows.WindowsPowerShellRun') as backend:
                QTimer.singleShot(0,inspect_batch);localized.batch_dialog()
                assert not errors,errors;start.assert_not_called();backend.assert_not_called()
            assert localized.editor.toPlainText()==old_editor and localized.cwd.text()==old_workspace
        # Execute the UI path using a trusted fake backend, never a real command.
        import time
        with tempfile.TemporaryDirectory() as td:
            reports=Path(td)/'reports'; reports.mkdir()
            plan=load_batch(json.dumps(packet).encode())
            dialog=relay_qt.BatchReviewDialog(plan,localized,td)
            dialog.workspaces={item.task_id:td for item in plan.items};dialog.update_bindings()
            dialog.workers.setCurrentIndex(1);dialog.validate_paths()
            assert not dialog.start_button.isEnabled() # overlapping roots
            dialog.workers.setCurrentIndex(0);dialog.validate_paths();assert dialog.start_button.isEnabled()
            launches=[]
            class Backend:
                def __init__(self,attempt,review,emit):
                    launches.append(attempt.task_id);self.attempt=attempt;self.emit=emit
                    emit(b'RESULT=True\n')
                def poll(self):return 0
                def settled(self,attempt,handle):return attempt==self.attempt and handle is self
                def cancel(self,attempt,handle):pass
            with patch.object(relay_qt,'REPORTS',reports), patch('command_relay.relay_windows.WindowsPowerShellRun',Backend):
                with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.No):dialog.start_execution()
                assert dialog.session is None and not launches
                with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes):dialog.start_execution()
                assert dialog.session is not None and not dialog.close_button.isEnabled()
                dialog.reject();assert not dialog.close_button.isEnabled()
                deadline=time.monotonic()+8
                while not dialog.close_button.isEnabled() and time.monotonic()<deadline:
                    app.processEvents();dialog.refresh_execution();time.sleep(.01)
                assert dialog.close_button.isEnabled(),dialog.status.text()
                assert launches==['a','b'] and dialog.snapshot['finished']
                assert len(list(reports.glob('report-*.txt')))==2
                assert dialog.table.item(1,3).text()==tr('batch_succeeded','ru')
                dialog.reject()
            assert localized.editor.toPlainText()==old_editor and localized.cwd.text()==old_workspace
        print('Qt batch execution UI checks passed (default deny, overlapping roots, mock dispatch, archive, close guard).')
        if mode == 'advanced' and '--native-batch' in sys.argv:
            native_batch_smoke(localized)
        # Runtime presentation is localized, but the actual report stays unchanged.
        localized.import_data(b'Write-Output "READY"', 'raw.ps1')
        assert localized.detail.text() == tr('runtime_loaded', 'ru')+'raw.ps1'
        assert localized.editor.toPlainText() == 'Write-Output "READY"'
        localized.copy_done(('full', 'raw.txt', 'PASS', 0), 'RAW REPORT\nPASS', None)
        assert QApplication.clipboard().text() == 'RAW REPORT\nPASS'
        assert 'PASS' in localized.detail.text() and 'RAW' in localized.detail.text()
        assert localized.detail.toolTip() == tr('runtime_raw_warning', 'ru')
        assert 'Process exit code:' not in tr('runtime_exit_zero', 'ru')
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
        assert localized.copy_ai_rules_action.text()==tr('copy_ai_rules','ru')
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
    # Static AI rules copy is explicit and separate from session data.
    from command_relay.relay_terms import ai_rules_text
    action=window.copy_ai_rules_action
    assert action in window.more.menu().actions() and action.objectName()=='copy_ai_rules'
    assert action.text()==tr('copy_ai_rules','en')
    before=(window.editor.toPlainText(),window.cwd.text(),window.output.toPlainText())
    clipboard=QApplication.clipboard();old_clip=clipboard.text()
    try:
        clipboard.setText('unchanged until explicit action')
        with patch.object(window,'start_process') as start, patch.object(relay_qt.session,'session_packet') as context:
            action.trigger()
            assert clipboard.text()==ai_rules_text(root)
            assert window.detail.text()==tr('ai_rules_copied','en')
            start.assert_not_called();context.assert_not_called()
        with patch.object(relay_qt,'ai_rules_text',side_effect=OSError('missing')),patch.object(window,'error') as error:
            action.trigger();error.assert_called_once_with(tr('ai_rules_unavailable','en'))
            assert clipboard.text()==ai_rules_text(root)
        window.copy_busy=True
        with patch.object(window,'error') as error,patch.object(relay_qt,'ai_rules_text') as reader:
            action.trigger();error.assert_called_once();reader.assert_not_called()
        window.copy_busy=False
        assert before==(window.editor.toPlainText(),window.cwd.text(),window.output.toPlainText())
    finally:
        window.copy_busy=False;clipboard.setText(old_clip)
    print('Qt Copy AI rules checks passed (explicit static copy, missing guide, busy guard, unchanged workspace).')
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
    # Unknown history is not a confirmed repeat; localize the reason and keep Cancel default.
    old_language=window.ui_language
    window.ui_language='ru'
    try:
        errors=[]
        def interact_limited():
            dialog=QApplication.activeModalWidget()
            try:
                assert isinstance(dialog,QMessageBox)
                assert 'пределами лимита' in dialog.text()
                assert 'не установлено' in dialog.text()
                assert 'Older archive' not in dialog.text()
                assert any(b.text()=='Продолжить запуск' for b in dialog.buttons())
                assert dialog.defaultButton() is dialog.button(QMessageBox.StandardButton.Cancel)
                dialog.defaultButton().click()
            except Exception as exc:
                errors.append(exc)
                if dialog is not None:dialog.reject()
        QTimer.singleShot(0,interact_limited)
        assert not window.confirm_repeat({'status':'limited','reason':'Older archive headers were not checked.', 'reason_key':'repeat_header_limit'})
        assert not errors, errors
    finally:
        window.ui_language=old_language
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
    # Verify Russian presentation while retaining the unchanged session schema.
    with tempfile.TemporaryDirectory() as tmp, patch.object(relay_qt, 'REPORTS', Path(tmp)), \
            patch.object(window, 'start_tool') as tool, patch.object(window, 'ui_language', 'ru'):
        window.review_session_context()
        title, work = tool.call_args.args
        assert title == tr('result_session_title', 'ru')
        assert work()['schema'] == 'command-relay/session-v1'
    # Inspect the real dialog without modifying the task queue or running commands.
    from PySide6.QtWidgets import QComboBox
    def inspect_history(dialog):
        assert dialog.windowTitle() == tr('result_history', 'ru')
        combo = dialog.findChild(QComboBox)
        assert [combo.itemData(i) for i in range(combo.count())] == ['All','Exit 0','Failed','Cancelled','Partial / unknown']
        assert combo.itemText(1) == tr('result_filter_1', 'ru')
        return QDialog.DialogCode.Rejected
    with patch.object(window, 'ui_language', 'ru'), patch.object(QDialog, 'exec', inspect_history), \
            patch.object(relay_qt.threading, 'Thread'):
        window.history()
    # Exercise actual selection/filtering and explicit report actions; no files opened externally.
    from PySide6.QtWidgets import QTableWidget, QLabel, QLineEdit
    from PySide6.QtCore import QItemSelectionModel
    class ImmediateHistoryThread:
        def __init__(self,target,daemon=True):self.target=target
        def start(self):self.target()
    with tempfile.TemporaryDirectory() as tmp:
        folder=Path(tmp);meta=json.dumps({'version':1,'task_intent':{'title':'<b>History title</b>'},'assertions':{'exit_code':0,'metrics':[{'key':'CHECK_PASS','equals':True,'occurrence':'all'}]}})
        for i,value in enumerate(('True','False')):
            (folder/f'report-20261125-01000{i}-000000.txt').write_text('COMMAND RELAY REPORT\nStarted: 2026-11-25T01:00:0'+str(i)+'\nCommand file: task.json\nTask ID: task-'+str(i)+'\nRelay metadata: '+meta+'\n\n@step 01 — Work\nCHECK_PASS='+value+'\n@step END\nProcess exit code: 0\nCancelled: False\nFinished: 2026-11-25T01:00:09\n',encoding='utf-8')
        def inspect_redesigned_history(dialog):
            for _ in range(5):app.processEvents()
            table=dialog.findChild(QTableWidget,'historyRuns');op=dialog.findChild(QPushButton,'historyOpen');copy=dialog.findChild(QPushButton,'historyCopy');compare=dialog.findChild(QPushButton,'historyCompare');more=dialog.findChild(QPushButton,'historyMore')
            detail=dialog.findChild(QLabel,'historyAssertions');heading=dialog.findChild(QLabel,'historyHeading')
            assert table.rowCount()==3 and not table.item(0,0).flags() & Qt.ItemFlag.ItemIsSelectable
            assert table.item(1,1).text()=='<b>History title</b>' and heading.textFormat()==Qt.TextFormat.PlainText
            assert heading.text()=='<b>History title</b>' and 'FAIL (1/2)' in detail.text()
            assert op.isEnabled() and copy.isEnabled() and not compare.isEnabled()
            copy.click();assert copy_mock.call_args.args==('ai',folder/'report-20261125-010001-000000.txt')
            op.click();assert open_mock.call_args.args==(folder/'report-20261125-010001-000000.txt',)
            raw=next(a for a in more.menu().actions() if a.text()==tr('copy_raw','ru'))
            with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.No) as confirm:
                raw.trigger();assert confirm.call_args.args[-1]==QMessageBox.StandardButton.No;assert copy_mock.call_count==1
            table.selectionModel().select(table.model().index(2,0),QItemSelectionModel.SelectionFlag.Select|QItemSelectionModel.SelectionFlag.Rows)
            assert compare.isEnabled() and not op.isEnabled() and not copy.isEnabled() and not raw.isEnabled()
            table.clearSelection();assert not compare.isEnabled() and not copy.isEnabled()
            table.selectRow(2)
            for _ in range(5):app.processEvents()
            assert 'PASS (2/2)' in detail.text()
            assert table.isColumnHidden(3)==(window.mode=='casual')
            search=dialog.findChild(QLineEdit,'historySearch');timer=dialog.findChild(QTimer,'historyFilterTimer')
            search.setText('task-0');timer.stop();timer.timeout.emit();assert table.rowCount()==2 and table.item(1,1).text()=='<b>History title</b>'
            search.setText('not-found');timer.stop();timer.timeout.emit();assert table.rowCount()==0 and not copy.isEnabled() and not compare.isEnabled()
            return QDialog.DialogCode.Rejected
        with patch.object(window,'ui_language','ru'),patch.object(relay_qt,'REPORTS',folder),patch.object(QDialog,'exec',inspect_redesigned_history),patch.object(relay_qt.threading,'Thread',ImmediateHistoryThread),patch.object(window,'open_path') as open_mock,patch.object(window,'copy_report') as copy_mock:
            for mode in ('casual','advanced'):
                copy_mock.reset_mock();open_mock.reset_mock()
                with patch.object(window,'mode',mode):window.history()
        def inspect_paged_history(dialog):
            for _ in range(5):app.processEvents()
            table=dialog.findChild(QTableWidget,'historyRuns');more=dialog.findChild(QPushButton,'historyShowMore')
            search=dialog.findChild(QLineEdit,'historySearch');timer=dialog.findChild(QTimer,'historyFilterTimer')
            assert table.rowCount()==2 and not more.isHidden() and more.isEnabled()
            assert table.selectionModel().selectedRows()[0].row()==1
            more.click();assert table.rowCount()==3 and more.isHidden()
            assert table.selectionModel().selectedRows()[0].row()==1
            search.setText('task-0');timer.stop();timer.timeout.emit()
            assert table.rowCount()==2 and more.isHidden()
            search.clear();timer.stop();timer.timeout.emit()
            assert table.rowCount()==2 and not more.isHidden()
            return QDialog.DialogCode.Rejected
        with patch.object(relay_qt.view,'HISTORY_PAGE_SIZE',1),patch.object(relay_qt,'REPORTS',folder),patch.object(QDialog,'exec',inspect_paged_history),patch.object(relay_qt.threading,'Thread',ImmediateHistoryThread):
            window.history()
    print('Qt redesigned history checks passed (grouping, actual assertions, selection, explicit copy, raw cancel, both modes, progressive rows and full-snapshot search).')
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
    # Russian presentation must not weaken cancellation or alter snapshot metadata.
    client.reset_mock(); client.squash_merge.side_effect = None
    with patch.object(relay_github_qt, 'GitHubClient', return_value=client):
        dialog = relay_github_qt.GitHubDialog(str(root), window, language='ru')
        dialog.show(); dialog.repo.setText('owner/repo'); dialog.list_prs(); wait_worker(dialog)
        dialog.inspect_pr(); wait_worker(dialog)
        assert dialog.windowTitle() == tr('gh_title', 'ru')
        assert dialog.merge_button.text() == tr('gh_merge', 'ru') and dialog.merge_button.isEnabled()
        assert 'owner/repo' in dialog.detail.toPlainText() and 'b'*40 in dialog.detail.toPlainText()
        errors = []
        def cancel_ru_merge():
            box = QApplication.activeModalWidget()
            try:
                assert isinstance(box, QMessageBox)
                assert box.windowTitle() == tr('gh_confirm_title', 'ru')
                assert box.defaultButton() is box.button(QMessageBox.StandardButton.Cancel)
                assert box.defaultButton().text() == tr('gh_cancel', 'ru')
                assert 'b'*40 in box.text() and 'повторно' in box.text()
                box.defaultButton().click()
            except Exception as exc:
                errors.append(exc)
                if box is not None: box.reject()
        QTimer.singleShot(0, cancel_ru_merge); dialog.confirm_merge(); wait_worker(dialog)
        assert not errors, errors
        client.squash_merge.assert_not_called()
        dialog.finished_work('merge', None, 'unknown')
        assert dialog.outcome == 'unknown' and not dialog.merge_button.isEnabled()
        assert dialog.notice.text() == tr('gh_merge_unverified', 'ru')
        dialog.reject(); dialog.deleteLater(); app.processEvents()
    print('Qt Russian GitHub manager checks passed (raw snapshot, cancel default, unknown outcome).')
    print('Qt GitHub PR manager checks passed (mocked list, inspect, cancel, merge and unknown outcome; no network writes).')
    window.hide()
    window.deleteLater()
    app.processEvents()
print('Qt startup smoke check passed (native batch commands explicitly enabled).' if '--native-batch' in sys.argv else 'Qt startup smoke check passed (no commands executed).')
