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

    def test_catalog_ids_and_fallback(self):
        from command_relay.relay_terms import _MESSAGES, LANGUAGES
        self.assertEqual(set(_MESSAGES), set(LANGUAGES))
        for catalog in _MESSAGES.values():
            self.assertEqual(set(catalog), set(_MESSAGES['en']))
            self.assertTrue(all(isinstance(value, str) and value.strip() for value in catalog.values()))
        self.assertEqual(tr('reduced_motion', None), 'Reduced motion')
        self.assertEqual(tr('reduced_motion', []), 'Reduced motion')
        self.assertNotEqual(tr('reduced_motion', 'ru'), tr('reduced_motion', 'en'))
        with self.assertRaises(KeyError):
            tr('unknown_message', 'ru')


class WorkspaceModeTests(unittest.TestCase):
    def test_mode_preference_and_cancel(self):
        from command_relay.relay_terms import saved_mode, startup_mode
        for invalid in ({}, {'mode': []}, {'mode': 'unknown'}, {'mode': None}):
            self.assertIsNone(saved_mode(invalid))
            choose = Mock(return_value='casual')
            self.assertEqual(startup_mode(invalid, choose), 'casual')
            choose.assert_called_once_with()
            self.assertIsNone(startup_mode(invalid, Mock(return_value=None)))
        for mode in ('casual', 'advanced'):
            choose = Mock()
            self.assertEqual(startup_mode({'mode': mode}, choose), mode)
            choose.assert_not_called()

    def test_sidebar_preferences_are_independent(self):
        from command_relay.relay_terms import sidebar_preference
        self.assertTrue(sidebar_preference({}, 'advanced'))
        self.assertFalse(sidebar_preference({}, 'casual'))
        settings = {'show_sidebar': False, 'show_sidebar_casual': True}
        self.assertFalse(sidebar_preference(settings, 'advanced'))
        self.assertTrue(sidebar_preference(settings, 'casual'))


class ThemeTests(unittest.TestCase):
    def test_theme_preference_and_tokens(self):
        from command_relay.relay_view import saved_theme, theme_colors
        for invalid in (None, [], {}, 'unknown', 'LIGHT'):
            self.assertEqual(saved_theme({'theme': invalid}), 'dark')
        self.assertEqual(saved_theme({'theme': 'light'}), 'light')
        dark, light = theme_colors('dark'), theme_colors('light')
        self.assertEqual(set(dark), set(light))
        self.assertNotEqual(dark['canvas'], light['canvas'])
        dark['canvas'] = 'invalid'
        self.assertNotEqual(theme_colors('dark')['canvas'], 'invalid')

    def test_theme_text_contrast(self):
        from command_relay.relay_view import THEMES, theme_colors
        def lum(color):
            rgb = [int(color[i:i+2], 16)/255 for i in (1, 3, 5)]
            return sum(w * (v/12.92 if v <= .04045 else ((v+.055)/1.055)**2.4)
                       for w, v in zip((.2126, .7152, .0722), rgb))
        for theme in THEMES:
            c = theme_colors(theme)
            pairs = [(fg, bg) for fg in ('text','muted','info','error','success','warning','metric') for bg in ('canvas','surface')]
            pairs += [('selected_text','selection'), ('on_accent','accent'), ('on_accent','accent_hover'), ('text','raised'), ('text','hover')]
            for fg, bg in pairs:
                a, b = sorted((lum(c[fg]), lum(c[bg])))
                self.assertGreaterEqual((b+.05)/(a+.05), 4.5, (theme, fg, bg))


class LocalizationArchitectureTests(unittest.TestCase):
    def test_registry_does_not_enable_unreviewed_notices(self):
        from command_relay.relay_terms import LOCALE_REGISTRY, LANGUAGES, locale_direction
        self.assertEqual(len(LOCALE_REGISTRY), 17)
        self.assertEqual(set(LANGUAGES), {'en', 'ru'})
        self.assertEqual(locale_direction('ar'), 'rtl')
        self.assertEqual(locale_direction('ru'), 'ltr')
        self.assertEqual(locale_direction([]), 'ltr')
        for code in LOCALE_REGISTRY.keys() - LANGUAGES.keys():
            self.assertIsNone(saved_language({'language': code}))
            with self.assertRaises(ValueError):
                disclaimer_text(ROOT, code)

    def test_workbench_catalog_and_formatting(self):
        from string import Formatter
        from command_relay.relay_terms import _WORKBENCH
        self.assertGreaterEqual(len(_WORKBENCH), 80)
        for key, (en, ru) in _WORKBENCH.items():
            self.assertEqual(tr(key, 'en'), en)
            self.assertEqual(tr(key, 'ru'), ru)
            self.assertEqual(tr(key, 'ar'), en)
            self.assertEqual({x[1] for x in Formatter().parse(en)},
                             {x[1] for x in Formatter().parse(ru)})
        self.assertIn('4.3.0', tr('window_title', 'ru').format(version='4.3.0'))
        self.assertIn('RAW', tr('copy_raw', 'ru'))
        self.assertIn('без маскирования', tr('copy_raw', 'ru'))


class DialogLocalizationTests(unittest.TestCase):
    def test_dialog_catalog_and_scope_placeholders(self):
        from string import Formatter
        from command_relay.relay_terms import _DIALOG_MESSAGES
        for key, (en, ru) in _DIALOG_MESSAGES.items():
            self.assertEqual(tr(key, 'en'), en)
            self.assertEqual(tr(key, 'ru'), ru)
            self.assertEqual({x[1] for x in Formatter().parse(en)},
                             {x[1] for x in Formatter().parse(ru)})
        for lang in ('en', 'ru'):
            for key in ('merge_allow', 'merge_revoke'):
                message = tr(key, lang).format(workspace=r'X:\src\example', repository='owner/repo')
                self.assertIn(r'X:\src\example', message)
                self.assertIn('owner/repo', message)
            for key in ('install_allow', 'install_revoke'):
                self.assertIn(r'X:\relay', tr(key, lang).format(root=r'X:\relay'))

    def test_only_known_presentation_results_are_translated(self):
        from command_relay.relay_terms import _DIALOG_RESULTS, dialog_result_text
        for message, key in _DIALOG_RESULTS.items():
            self.assertEqual(dialog_result_text(message, 'en'), message)
            self.assertEqual(dialog_result_text(message, 'ru'), tr(key, 'ru'))
        for message in ('Unknown error SHA-256=abc', 'Publisher signature: Verified\nraw', 'PASS', 'owner/repo'):
            self.assertEqual(dialog_result_text(message, 'ru'), message)
        self.assertNotEqual(tr('update_verified', 'ru'), tr('update_unverified', 'ru'))
        self.assertIn('НЕ проверена', tr('update_listed_signature', 'ru'))


class CasualFlowTests(unittest.TestCase):
    def test_stage_is_actual_state_not_claim_of_success(self):
        from command_relay.relay_terms import casual_stage
        for values, stage in (((False,False,False),'import'), ((True,False,False),'review'),
                              ((True,True,False),'run'), ((False,True,True),'run'),
                              ((True,False,True),'result')):
            self.assertEqual(casual_stage(*values),stage)

    def test_metadata_is_bounded_and_edits_not_mislabeled(self):
        from command_relay.relay_terms import casual_task_title
        self.assertEqual(casual_task_title({'title':'<b>Task</b>\nName'},'file',has_script=True,edited=False),'<b>Task</b> Name')
        self.assertEqual(len(casual_task_title({'title':'x'*200},'file',has_script=True,edited=False)),100)
        self.assertEqual(casual_task_title({'title':'old'},'file',has_script=True,edited=True,language='ru'),tr('casual_edited','ru'))
        self.assertEqual(casual_task_title({},'file',has_script=False,edited=False),tr('casual_empty'))
