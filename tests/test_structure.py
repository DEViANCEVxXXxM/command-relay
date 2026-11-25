# SPDX-License-Identifier: Apache-2.0
"""Checks for the portable package layout and entry point."""
import runpy
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock, patch

from command_relay import relay_core
from tools.build_release import build

ROOT = Path(__file__).resolve().parents[1]


class StructureTests(unittest.TestCase):
    def test_runtime_paths_preserved(self):
        self.assertEqual(relay_core.ROOT, ROOT)
        self.assertEqual(relay_core.REPORTS, ROOT / 'reports')
        self.assertEqual(relay_core.SETTINGS, ROOT / 'settings.json')
        self.assertEqual(relay_core.ASSETS, ROOT / 'command_relay' / 'assets')
        self.assertFalse(list(ROOT.glob('relay_*.py')))
        self.assertTrue((relay_core.ASSETS / 'relay-icon.ico').is_file())

    def test_entry_point_delegates_and_preserves_exit_status(self):
        fake_qt = ModuleType('command_relay.relay_qt')
        fake_qt.main = Mock(return_value=7)
        with patch.dict(sys.modules, {'command_relay.relay_qt': fake_qt}):
            sys.modules.pop('command_relay.__main__', None)
            with self.assertRaises(SystemExit) as raised:
                runpy.run_module('command_relay', run_name='__main__')
        self.assertEqual(raised.exception.code, 7)
        fake_qt.main.assert_called_once_with()

    def test_extracted_portable_imports(self):
        with tempfile.TemporaryDirectory(prefix='relay portable ') as tmp:
            dest = Path(tmp)
            archive, _ = build(dest)
            with zipfile.ZipFile(archive) as z:
                z.extractall(dest)
            extracted = dest / archive.stem
            code = '''from pathlib import Path
from command_relay import relay_core, relay_compare, relay_export, relay_features, relay_github, relay_intelligence, relay_permissions, relay_privacy, relay_session, relay_updates, relay_view, relay_windows
from command_relay.relay_terms import disclaimer_text
from command_relay.relay_version import VERSION
assert relay_core.ROOT.samefile(Path.cwd()), (relay_core.ROOT, Path.cwd())
assert relay_core.ASSETS.joinpath('relay-icon.png').is_file()
assert disclaimer_text(relay_core.ROOT)
assert relay_core.load_input(Path('examples/example-ai-task.json').read_bytes())[1]['task_id'] == 'relay-qt-smoke-40'
assert VERSION == '4.2.0'
'''
            proc = subprocess.run([sys.executable, '-c', code], cwd=extracted,
                                  capture_output=True, text=True, timeout=15)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertFalse((extracted / 'reports').exists())
            self.assertFalse((extracted / 'settings.json').exists())


class StartupGuardTests(unittest.TestCase):
    def test_portable_lifetime_lock_and_exit_status(self):
        from command_relay import __main__ as launcher
        from command_relay.relay_updates import installation_lock, UpdateError
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            def gui():
                with self.assertRaises(UpdateError):
                    with installation_lock(root):
                        pass
                return 7
            with patch.object(launcher, 'ROOT', root):
                self.assertEqual(launcher.main(gui), 7)
            with installation_lock(root):
                pass

    def test_busy_startup_does_not_invoke_gui(self):
        from command_relay import __main__ as launcher
        from command_relay.relay_updates import installation_lock
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            gui, notify = Mock(), Mock()
            with installation_lock(root), patch.object(launcher, 'ROOT', root):
                self.assertEqual(launcher.main(gui, notify), 1)
            gui.assert_not_called()
            notify.assert_called_once()

    def test_source_checkout_stays_launchable_without_lock(self):
        from command_relay import __main__ as launcher
        from command_relay.relay_updates import installation_lock, UpdateError, UPDATE_LOCK_NAME
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / '.git').mkdir()
            with patch.object(launcher, 'ROOT', root):
                self.assertEqual(launcher.main(lambda: 0), 0)
            self.assertFalse((root / UPDATE_LOCK_NAME).exists())
            with self.assertRaises(UpdateError):
                with installation_lock(root):
                    pass

    def test_callback_exception_releases_lock(self):
        from command_relay import __main__ as launcher
        from command_relay.relay_updates import installation_lock
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            with patch.object(launcher, 'ROOT', root), self.assertRaisesRegex(RuntimeError, 'test failure'):
                launcher.main(Mock(side_effect=RuntimeError('test failure')))
            with installation_lock(root):
                pass

    def test_console_free_launcher_does_not_open_log_when_busy(self):
        from command_relay import __main__ as launcher
        from command_relay.relay_updates import installation_lock
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            log = root / 'startup.log'
            log.write_bytes(b'unchanged')
            entry = runpy.run_path(str(ROOT / 'Start.pyw'))['main']
            notify = Mock()
            with installation_lock(root), patch.object(launcher, 'ROOT', root), patch.dict(entry.__globals__, {'ROOT': root, 'notify_failure': notify}):
                self.assertEqual(entry(), 1)
            self.assertEqual(log.read_bytes(), b'unchanged')
            notify.assert_called_once()


class StartupRecoveryGateTests(unittest.TestCase):
    def test_pending_directory_blocks_gui_and_preserves_files(self):
        from command_relay import __main__ as launcher
        from command_relay.relay_updates import UPDATE_TRANSACTION_NAME, installation_lock
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            marker = root / UPDATE_TRANSACTION_NAME
            marker.mkdir()
            (marker / 'intent.json').write_bytes(b'opaque recovery evidence')
            log = root / 'startup.log'
            log.write_bytes(b'unchanged')
            gui, notify = Mock(), Mock()
            with patch.object(launcher, 'ROOT', root):
                self.assertEqual(launcher.main(gui, notify), 1)
            gui.assert_not_called()
            self.assertIn('unfinished update', notify.call_args.args[0])
            self.assertEqual(log.read_bytes(), b'unchanged')
            self.assertEqual((marker / 'intent.json').read_bytes(), b'opaque recovery evidence')
            with installation_lock(root):
                pass

    def test_wrong_type_and_case_alias_block(self):
        from command_relay.relay_updates import UPDATE_TRANSACTION_NAME, startup_installation_guard, RecoveryRequired
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            marker = root / UPDATE_TRANSACTION_NAME.upper()
            marker.write_bytes(b'not a directory')
            with self.assertRaises(RecoveryRequired):
                with startup_installation_guard(root):
                    self.fail('guard allowed malformed marker')
            self.assertEqual(marker.read_bytes(), b'not a directory')

    def test_marker_link_blocks_without_following(self):
        from command_relay.relay_updates import UPDATE_TRANSACTION_NAME, startup_installation_guard, RecoveryRequired
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            marker = root / UPDATE_TRANSACTION_NAME
            try:
                marker.symlink_to(root / 'missing')
            except (OSError, NotImplementedError):
                self.skipTest('symlink unavailable')
            with self.assertRaises(RecoveryRequired):
                with startup_installation_guard(root):
                    self.fail('guard allowed marker symlink')
            self.assertTrue(marker.is_symlink())

    def test_directory_read_failure_denies_startup(self):
        from command_relay.relay_updates import startup_installation_guard, RecoveryRequired, installation_lock
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            with patch.object(Path, 'iterdir', side_effect=PermissionError('denied')):
                with self.assertRaises(RecoveryRequired):
                    with startup_installation_guard(root):
                        self.fail('guard allowed unreadable recovery state')
            with installation_lock(root):
                pass

    def test_checkout_does_not_consume_marker(self):
        from command_relay.relay_updates import UPDATE_TRANSACTION_NAME, startup_installation_guard, UPDATE_LOCK_NAME
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / '.git').mkdir()
            marker = root / UPDATE_TRANSACTION_NAME
            marker.mkdir()
            with startup_installation_guard(root):
                pass
            self.assertTrue(marker.is_dir())
            self.assertFalse((root / UPDATE_LOCK_NAME).exists())


class GuiHandoffLifecycleTests(unittest.TestCase):
    def test_launch_after_gui_releases_lock(self):
        from command_relay import __main__ as launcher
        from command_relay import relay_updates as u
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            bundle = root.parent / 'unused-test-bundle'
            handoff = u.PreparedUpdateHandoff(bundle, bundle/'updater', bundle/'original', bundle/'target',
                u.InstallPlan(root, u.VERSION, '9.0.0', (), ()), 'a'*64, 'b'*64)
            def gui():
                with self.assertRaises(u.UpdateError), u.installation_lock(root):
                    pass
                return handoff
            def spawn(request, *, action):
                self.assertIs(request, handoff)
                self.assertEqual(action, 'install')
                with u.installation_lock(root):
                    pass
            with patch.object(launcher, 'ROOT', root), patch.object(launcher, 'launch_prepared_updater', side_effect=spawn) as launch:
                self.assertEqual(launcher.main(gui), 0)
                launch.assert_called_once()
                launch.reset_mock()
                self.assertEqual(launcher.main(lambda: 7), 7)
                launch.assert_not_called()

    def test_failed_launch_reports_and_does_not_retry(self):
        from command_relay import __main__ as launcher
        from command_relay import relay_updates as u
        from dataclasses import replace
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            handoff = u.PreparedUpdateHandoff(root, root, root, root,
                u.InstallPlan(root, u.VERSION, '9.0.0', (), ()), 'a'*64, 'b'*64)
            notify = Mock()
            with patch.object(launcher, 'ROOT', root), patch.object(launcher, 'launch_prepared_updater', side_effect=u.UpdateError('failed')) as launch:
                self.assertEqual(launcher.main(lambda: handoff, notify), 1)
                launch.assert_called_once()
                notify.assert_called_once()
                launch.reset_mock()
                other = replace(handoff, plan=replace(handoff.plan, root=root.parent))
                self.assertEqual(launcher.main(lambda: other, notify), 1)
                launch.assert_not_called()
