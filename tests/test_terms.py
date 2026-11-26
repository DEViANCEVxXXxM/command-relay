# SPDX-License-Identifier: Apache-2.0
import tempfile
import unittest
from pathlib import Path

from command_relay.relay_terms import disclaimer_text, saved_language, startup_language, tr
from unittest.mock import Mock

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

    def test_locale_notice_uses_complete_original_sections(self):
        full = disclaimer_text(ROOT)
        english, russian = full.split('\n## English\n', 1)[1].split('\n## Русский\n', 1)
        self.assertEqual(disclaimer_text(ROOT, 'en'), english.strip())
        self.assertEqual(disclaimer_text(ROOT, 'ru'), russian.strip())
        self.assertNotEqual(tr('terms_agree', 'en'), tr('terms_agree', 'ru'))
        self.assertEqual(tr('terms_agree', 'unknown'), tr('terms_agree', 'en'))
        with self.assertRaises(ValueError):
            disclaimer_text(ROOT, 'unknown')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'DISCLAIMER.md').write_text('## English\nIncomplete', encoding='utf-8')
            with self.assertRaises(ValueError):
                disclaimer_text(root, 'ru')

    def test_first_run_selection_and_consent_before_persist(self):
        for setting in ({}, {'language': 'unknown'}, {'language': []}):
            with self.subTest(setting=setting):
                self.assertIsNone(saved_language(setting))
                choose, confirm, persist = Mock(return_value='ru'), Mock(return_value=True), Mock()
                self.assertEqual(startup_language(setting, choose, confirm, persist), 'ru')
                choose.assert_called_once_with()
                confirm.assert_called_once_with('ru')
                persist.assert_called_once_with('ru')
        for chosen, accepted in ((None, True), ('unknown', True), ('ru', False)):
            persist = Mock()
            self.assertIsNone(startup_language({}, Mock(return_value=chosen), Mock(return_value=accepted), persist))
            persist.assert_not_called()

    def test_saved_locale_skips_chooser_but_never_skips_notice(self):
        choose, persist = Mock(), Mock()
        for accepted in (False, True):
            confirm = Mock(return_value=accepted)
            self.assertEqual(startup_language({'language': 'en'}, choose, confirm, persist), 'en' if accepted else None)
            confirm.assert_called_once_with('en')
        choose.assert_not_called()
        persist.assert_not_called()
        with self.assertRaises(OSError):
            startup_language({}, Mock(return_value='en'), Mock(return_value=True), Mock(side_effect=OSError('write denied')))
