# SPDX-License-Identifier: Apache-2.0
import pathlib
import struct
import sys
import unittest
from unittest.mock import patch, MagicMock
from command_relay import relay_windows

ROOT = pathlib.Path(__file__).resolve().parents[1]

class IconTests(unittest.TestCase):
    def test_ico_entries(self):
        b = (ROOT/'command_relay'/'assets'/'relay-icon.ico').read_bytes()
        reserved, kind, count = struct.unpack_from('<HHH', b)
        self.assertEqual((reserved, kind, count), (0, 1, 9))
        sizes = []
        for i in range(count):
            w,h,colors,r,planes,bpp,length,offset = struct.unpack_from('<BBBBHHII', b, 6+16*i)
            w,h = w or 256,h or 256
            self.assertEqual(w,h)
            self.assertLessEqual(offset+length,len(b))
            self.assertEqual(b[offset:offset+8],b'\x89PNG\r\n\x1a\n')
            self.assertEqual(struct.unpack_from('>II',b,offset+16),(w,h))
            self.assertEqual(b[offset+25],6) # RGBA PNG
            sizes.append(w)
        self.assertEqual(sizes,[16,20,24,32,40,48,64,128,256])

    def test_non_windows_identity(self):
        with patch.object(sys,'platform','linux'):
            self.assertFalse(relay_windows.set_app_identity())

    def test_windows_identity(self):
        mock=MagicMock();mock.return_value.SetCurrentProcessExplicitAppUserModelID.return_value=0
        with patch.object(sys,'platform','win32'), patch('ctypes.WinDLL',mock,create=True):
            self.assertTrue(relay_windows.set_app_identity())
            mock.return_value.SetCurrentProcessExplicitAppUserModelID.assert_called_once_with('CommandRelay.QtWorkbench')

    def test_windows_identity_unavailable(self):
        with patch.object(sys,'platform','win32'),patch('ctypes.WinDLL',side_effect=OSError,create=True):
            self.assertFalse(relay_windows.set_app_identity())
