# SPDX-License-Identifier: Apache-2.0
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest


# Run the real entry point while intercepting only the native Windows dialog.
# A failed assertion must produce a diagnostic, not hang an unattended runner.
LAUNCHER_HARNESS = r"""
import ctypes
from pathlib import Path
import runpy
import sys
from unittest.mock import patch

script = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(script.parent))
if sys.platform == 'win32':
    def show_message(_owner, message, _title, _flags):
        print(message, file=sys.stderr)
        return 1
    with patch.object(ctypes.windll.user32, 'MessageBoxW', side_effect=show_message):
        runpy.run_path(str(script), run_name='__main__')
else:
    runpy.run_path(str(script), run_name='__main__')
"""


class LauncherTests(unittest.TestCase):
    def launch(self, body, *, busy=False, pending=False):
        from contextlib import nullcontext
        from command_relay.relay_updates import installation_lock, UPDATE_TRANSACTION_NAME
        with tempfile.TemporaryDirectory(prefix='relay launcher ') as tmp:
            root = pathlib.Path(tmp)
            shutil.copyfile((pathlib.Path(__file__).resolve().parents[1]).joinpath('Start.pyw'), root / 'Start.pyw')
            package = root / 'command_relay'
            package.mkdir()
            (package / '__init__.py').write_text('', encoding='utf-8')
            source = pathlib.Path(__file__).resolve().parents[1] / 'command_relay'
            for name in ('__main__.py', 'relay_updates.py', 'relay_version.py'):
                shutil.copyfile(source / name, package / name)
            (package / 'relay_qt.py').write_text('def main():\n' + ''.join('    ' + line + '\n' for line in body.splitlines()), encoding='utf-8')
            if busy or pending:
                (root / 'startup.log').write_text('unchanged', encoding='utf-8')
            if pending:
                (root / UPDATE_TRANSACTION_NAME).mkdir()
            with installation_lock(root.resolve()) if busy else nullcontext():
                proc = subprocess.run([sys.executable, '-B', '-c', LAUNCHER_HARNESS, str(root / 'Start.pyw')], cwd=root.parent,
                                      capture_output=True, text=True, timeout=15)
            return proc, (root / 'startup.log').read_text(encoding='utf-8')

    def test_normal_launch(self):
        proc, log = self.launch('import pathlib, sys\nassert pathlib.Path.cwd().samefile(pathlib.Path(__file__).parent.parent)\nprint("hello")\nprint("diagnostic", file=sys.stderr)\nsys.exit(0)\n')
        self.assertEqual(proc.returncode, 0)
        self.assertIn('hello', log)
        self.assertIn('diagnostic', log)
        self.assertEqual(proc.stdout, '')
        self.assertEqual(proc.stderr, '')

    def test_exception_logged(self):
        proc, log = self.launch('raise RuntimeError("launch failure")\n')
        self.assertEqual(proc.returncode, 1)
        self.assertIn('RuntimeError: launch failure', log)
        self.assertIn('Start-Debug.cmd', proc.stderr)

    def test_exit_code_preserved(self):
        proc, log = self.launch('raise SystemExit(7)\n')
        self.assertEqual(proc.returncode, 7)
        self.assertIn('Application exited with: 7', log)

    def test_busy_launcher_preserves_log(self):
        proc, log = self.launch('raise AssertionError("must not run")', busy=True)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(log, 'unchanged')
        self.assertIn('installation is busy', proc.stderr)

    def test_return_code_preserved(self):
        proc, log = self.launch('return 9')
        self.assertEqual(proc.returncode, 9)
        self.assertIn('exited with code 9', proc.stderr)

    def test_pending_transaction_launcher_preserves_log(self):
        proc, log = self.launch('raise AssertionError("must not run")', pending=True)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(log, 'unchanged')
        self.assertIn('unfinished update', proc.stderr)
