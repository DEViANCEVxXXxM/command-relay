# SPDX-License-Identifier: Apache-2.0
"""Console-free GUI entry point. No tasks are executed by the launcher."""
import contextlib
import os
from pathlib import Path
import sys
# Do not create import caches in the signed portable program tree.
sys.dont_write_bytecode = True
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


def _run_logged_gui():
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
            from command_relay.relay_qt import main as run_gui
            code = run_gui()
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
            if code:
                print('Application exited with:', exc.code, file=log)
        except Exception:
            traceback.print_exc(file=log)
            code = 1
    from command_relay.relay_updates import PreparedUpdateHandoff
    if isinstance(code, PreparedUpdateHandoff):
        return code
    if code:
        notify_failure(f'Command Relay exited with code {code}.\n\nLog: {log.name}\n\nFor interactive diagnostics, run tools/Start-Debug.cmd.')
    return code


def main():
    try:
        from command_relay.__main__ import main as launch
        return launch(_run_logged_gui, notify_failure)
    except Exception:
        notify_failure('Command Relay could not initialize its launcher. Run tools/Start-Debug.cmd for diagnostics.')
        return 1


if __name__ == '__main__':
    sys.exit(main())
