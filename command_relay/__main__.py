# SPDX-License-Identifier: Apache-2.0
"""Launch the workbench under the portable installation's process lock."""
from contextlib import ExitStack
from pathlib import Path
import sys

from .relay_updates import (PreparedUpdateHandoff, RecoveryRequired, UpdateError,
                            launch_prepared_updater, startup_installation_guard)

ROOT = Path(__file__).resolve().parents[1]


def _run_gui():
    from .relay_qt import main
    return main()


def main(run_gui=None, notify=None):
    """Acquire before importing Qt or touching startup/user files.

    A Git checkout remains a development launch, never an update destination.
    Hold the cooperative lock until the GUI event loop and shutdown return.
    """
    with ExitStack() as stack:
        try:
            stack.enter_context(startup_installation_guard(ROOT))
        except UpdateError as exc:
            if isinstance(exc, RecoveryRequired):
                message = 'Command Relay cannot start: unfinished update or recovery state unavailable. Preserve the installation and transaction files; use verified recovery before retrying.'
            else:
                message = 'Command Relay cannot start: installation is busy or its lock is unavailable. Close the other instance or updater and retry.'
            if notify is not None:
                notify(message)
            elif sys.stderr is not None:
                print(message, file=sys.stderr)
            return 1
        result = (run_gui or _run_gui)()
    # The GUI and any startup log context have returned. Never launch with the
    # parent installation lock held, or treat a nonzero GUI exit as consent.
    if isinstance(result, PreparedUpdateHandoff):
        try:
            if result.plan.root != ROOT:
                raise UpdateError('Update destination differs from application root.')
            launch_prepared_updater(result, action='install')
        except UpdateError:
            message = 'Unable to start the external updater. Preserve the handoff bundle; no successful installation is implied.'
            if notify is not None:
                notify(message)
            elif sys.stderr is not None:
                print(message, file=sys.stderr)
            return 1
        return 0
    return result


if __name__ == "__main__":
    raise SystemExit(main())
