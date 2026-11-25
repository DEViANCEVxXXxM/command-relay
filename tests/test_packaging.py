# SPDX-License-Identifier: Apache-2.0
import hashlib
from pathlib import Path
import tempfile
import unittest
import zipfile

from command_relay.relay_version import VERSION
from tools.build_release import build, RELEASE_FILES


class PackagingTests(unittest.TestCase):
    def test_archive_allowlist_and_reproducibility(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive, checksum = build(root / 'one', f'v{VERSION}')
            second, _ = build(root / 'two')
            self.assertEqual(archive.read_bytes(), second.read_bytes())
            self.assertEqual(checksum.read_text().split()[0], hashlib.sha256(archive.read_bytes()).hexdigest())
            with zipfile.ZipFile(archive) as z:
                self.assertIsNone(z.testzip())
                names = {n.split("/", 1)[1] for n in z.namelist()}
                self.assertEqual(set(RELEASE_FILES), names)
                self.assertTrue({'LICENSE', 'NOTICE', 'DISCLAIMER.md', 'command_relay/relay_terms.py'} <= names)
                for name in ('LICENSE', 'NOTICE', 'DISCLAIMER.md'):
                    entry = next(n for n in z.namelist() if n.endswith('/' + name))
                    self.assertEqual(z.read(entry), (Path(__file__).resolve().parents[1] / name).read_bytes().replace(b'\r\n', b'\n'))
                self.assertNotIn('settings.json', names)

    def test_wrong_tag_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                build(Path(tmp), 'v0.0.0')
