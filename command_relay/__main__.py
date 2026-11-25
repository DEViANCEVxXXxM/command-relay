# SPDX-License-Identifier: Apache-2.0
"""Launch the workbench under the portable installation's process lock."""
from contextlib import ExitStack
from pathlib import Path
import sys

from .relay_updates import UpdateError, startup_installation_guard

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
        except UpdateError:
            message = 'Command Relay cannot start: installation is busy or its lock is unavailable. Close the other instance or updater and retry.'
            if notify is not None:
                notify(message)
            elif sys.stderr is not None:
                print(message, file=sys.stderr)
            return 1
        return (run_gui or _run_gui)()


if __name__ == "__main__":
    raise SystemExit(main())
