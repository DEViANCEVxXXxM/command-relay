# SPDX-License-Identifier: Apache-2.0
"""Console-free GUI entry point. No tasks are executed by the launcher."""
import contextlib
import os
from pathlib import Path
import runpy
import sys
import tempfile
import traceback

ROOT = Path(__file__).resolve().parent


def notify_failure(message):
    if sys.platform == 'win32':
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, 'Command Relay — startup error', 0x10)
            return
        except (AttributeError, OSError):
            pass
    if sys.stderr is not None:
        print(message, file=sys.stderr)


def main():
    try:
        log = (ROOT / 'startup.log').open('w', encoding='utf-8', errors='backslashreplace', buffering=1)
    except OSError:
        try:
            log = tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', errors='backslashreplace', buffering=1,
                                              prefix='command-relay-startup-', suffix='.log', delete=False)
        except OSError:
            notify_failure('Cannot open a startup log. Run tools/Start-Debug.cmd to diagnose the problem.')
            return 1
    code = 0
    with log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
        try:
            os.chdir(ROOT)
            runpy.run_module('command_relay', run_name='__main__')
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
            if code:
                print('Application exited with:', exc.code, file=log)
        except Exception:
            traceback.print_exc(file=log)
            code = 1
    if code:
        notify_failure(f'Command Relay exited with code {code}.\n\nLog: {log.name}\n\nFor interactive diagnostics, run tools/Start-Debug.cmd.')
    return code


if __name__ == '__main__':
    sys.exit(main())
