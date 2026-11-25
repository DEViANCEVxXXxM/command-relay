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
