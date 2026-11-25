# SPDX-License-Identifier: Apache-2.0
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest


class LauncherTests(unittest.TestCase):
    def launch(self, body):
        with tempfile.TemporaryDirectory(prefix='relay launcher ') as tmp:
            root = pathlib.Path(tmp)
            shutil.copyfile((pathlib.Path(__file__).resolve().parents[1]).joinpath('Start.pyw'), root / 'Start.pyw')
            package = root / 'command_relay'
            package.mkdir()
            (package / '__init__.py').write_text('', encoding='utf-8')
            (package / '__main__.py').write_text(body, encoding='utf-8')
            proc = subprocess.run([sys.executable, str(root / 'Start.pyw')], cwd=root.parent,
                                  capture_output=True, text=True, timeout=15)
            return proc, (root / 'startup.log').read_text(encoding='utf-8')

    def test_normal_launch(self):
        proc, log = self.launch('import pathlib, sys\nassert pathlib.Path.cwd() == pathlib.Path(__file__).parent.parent\nprint("hello")\nprint("diagnostic", file=sys.stderr)\nsys.exit(0)\n')
        self.assertEqual(proc.returncode, 0)
        self.assertIn('hello', log)
        self.assertIn('diagnostic', log)
        self.assertEqual(proc.stdout, '')
        self.assertEqual(proc.stderr, '')

    @unittest.skipIf(sys.platform == 'win32', 'Failure deliberately shows a native dialog on Windows')
    def test_exception_logged(self):
        proc, log = self.launch('raise RuntimeError("launch failure")\n')
        self.assertEqual(proc.returncode, 1)
        self.assertIn('RuntimeError: launch failure', log)
        self.assertIn('Start-Debug.cmd', proc.stderr)

    @unittest.skipIf(sys.platform == 'win32', 'Failure deliberately shows a native dialog on Windows')
    def test_exit_code_preserved(self):
        proc, log = self.launch('raise SystemExit(7)\n')
        self.assertEqual(proc.returncode, 7)
        self.assertIn('Application exited with: 7', log)
