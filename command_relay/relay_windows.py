# SPDX-License-Identifier: Apache-2.0
"""Per-window Windows chrome; never modifies system preferences."""
import sys


def colorref(rgb):
    r, g, b = rgb
    return r | (g << 8) | (b << 16)


def apply_neutral_chrome(hwnd):
    """Best effort on Windows 11. Unsupported attributes leave native defaults."""
    if sys.platform != 'win32' or not hwnd:
        return {}
    import ctypes
    from ctypes import wintypes
    try:
        setter = ctypes.WinDLL('dwmapi').DwmSetWindowAttribute
        setter.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        setter.restype = ctypes.c_long
        values = ((20, 1), (34, colorref((51, 51, 51))),
                  (35, colorref((32, 32, 32))), (36, colorref((220, 220, 220))))
        result = {}
        for attr, value in values:
            data = wintypes.DWORD(value)
            result[attr] = setter(hwnd, attr, ctypes.byref(data), ctypes.sizeof(data))
        return result
    except (OSError, AttributeError, ValueError):
        return {}


APP_USER_MODEL_ID = 'CommandRelay.QtWorkbench'

def set_app_identity():
    """Set the process taskbar identity before creating any windows; best effort."""
    if sys.platform != 'win32':
        return False
    import ctypes
    try:
        setter = ctypes.WinDLL('shell32').SetCurrentProcessExplicitAppUserModelID
        setter.argtypes = [ctypes.c_wchar_p]
        setter.restype = ctypes.c_long
        return setter(APP_USER_MODEL_ID) == 0
    except (OSError, AttributeError, ValueError):
        return False
