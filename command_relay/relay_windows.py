# SPDX-License-Identifier: Apache-2.0
"""Per-window Windows chrome; never modifies system preferences."""
import sys


def colorref(rgb):
    r, g, b = rgb
    return r | (g << 8) | (b << 16)


def apply_neutral_chrome(hwnd, theme="dark"):
    """Best effort on Windows 11. Unsupported attributes leave native defaults."""
    if sys.platform != 'win32' or not hwnd:
        return {}
    import ctypes
    from ctypes import wintypes
    try:
        setter = ctypes.WinDLL('dwmapi').DwmSetWindowAttribute
        setter.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        setter.restype = ctypes.c_long
        light = theme == 'light'
        values = ((20, int(not light)), (34, colorref((160, 172, 186) if light else (66, 73, 81))),
                  (35, colorref((243, 245, 247) if light else (24, 26, 30))),
                  (36, colorref((34, 43, 54) if light else (226, 229, 233))))
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
