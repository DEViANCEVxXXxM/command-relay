# SPDX-License-Identifier: Apache-2.0
import tempfile
import unittest
from pathlib import Path

from command_relay.relay_terms import disclaimer_text

ROOT = Path(__file__).resolve().parents[1]


class TermsTests(unittest.TestCase):
    def test_distributed_notice_is_bilingual_and_matches_display(self):
        text = disclaimer_text(ROOT)
        self.assertEqual(text, (ROOT / 'DISCLAIMER.md').read_text(encoding='utf-8').strip())
        for phrase in ('## English', '## Русский', 'AI-generated', 'исполняемых файлов',
                       'I understand and agree', 'Decline and exit', 'Apache License 2.0'):
            self.assertIn(phrase, text)

    def test_missing_notice_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                disclaimer_text(Path(tmp))

    def test_empty_notice_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'DISCLAIMER.md').write_text(' \n', encoding='utf-8')
            with self.assertRaises(ValueError):
                disclaimer_text(root)
