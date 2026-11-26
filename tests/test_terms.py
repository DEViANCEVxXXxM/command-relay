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


class WorkspaceSettingsTests(unittest.TestCase):
    def test_migrate_legacy_modes(self):
        from command_relay.relay_terms import workspace_settings
        for mode in ('casual', 'advanced', None, []):
            settings = {'mode':mode, 'show_sidebar_casual':False, 'language':'ru', 'theme':'light', 'show_sidebar':False}
            self.assertEqual(workspace_settings(settings), {'language':'ru','theme':'light'})
            self.assertIn('mode',settings)
        self.assertEqual(workspace_settings({'mode':'casual','show_sidebar_casual':False,'show_sidebar':True}), {})

    def test_shared_safety_labels_preserve_high_risk_evidence(self):
        from command_relay.relay_terms import safety_labels
        matches = {'matches': [
            {'level':'review','label':'File or repository changes','lines':[1]},
            {'level':'high','label':'Destructive file or disk operation','lines':[3, 8]},
            {'level':'high','label':'Incomplete safety inspection','lines':[]},
        ]}
        for language in ('en','ru'):
            ui = lambda key: tr(key, language)
            self.assertEqual(safety_labels(ui, matches),
                ui('safety_reason_Destructive file or disk operation') + ': 3, 8\n' +
                ui('safety_reason_Incomplete safety inspection'))
            self.assertEqual(safety_labels(ui, {'matches':[]}), '')

    def test_repeat_confirmation_preserves_uncertainty(self):
        from command_relay.relay_terms import repeat_requires_confirmation as needs
        for status in ('no_match','not_applicable'):
            self.assertFalse(needs({'status':status}))
        for verdict in ('PASS','NOT_REQUESTED'):
            self.assertFalse(needs({'status':'matched','verdict':verdict,'process_exit':'0'}))
        for verdict in ('FAIL','INCOMPLETE','CANCELLED','NOT_EVALUATED','INCONCLUSIVE'):
            self.assertTrue(needs({'status':'matched','verdict':verdict,'process_exit':'0'}))
        self.assertTrue(needs({'status':'matched','verdict':'PASS','process_exit':'1'}))
        self.assertTrue(needs({'status':'matched','verdict':'PASS','process_exit':'0','reason':'changed'}))
        for status in ('limited','unavailable','unexpected'):
            self.assertTrue(needs({'status':status}))


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
    def test_registry_preview_activation_with_full_notice(self):
        from command_relay.relay_terms import LOCALE_REGISTRY, LANGUAGES, PREVIEW_LANGUAGES, locale_direction
        self.assertEqual(len(LOCALE_REGISTRY), 17)
        self.assertEqual(set(LANGUAGES), set(LOCALE_REGISTRY))
        self.assertEqual(PREVIEW_LANGUAGES, set(LANGUAGES)-{'en','ru'})
        self.assertEqual(locale_direction('ar'), 'rtl')
        self.assertEqual(locale_direction('ru'), 'ltr')
        self.assertEqual(locale_direction([]), 'ltr')
        for code in PREVIEW_LANGUAGES:
            self.assertEqual(saved_language({'language': code}), code)
            notice = disclaimer_text(ROOT, code)
            self.assertTrue(notice.endswith(disclaimer_text(ROOT,'en')))
            self.assertIn('Apache License 2.0', notice)
            persist = Mock()
            self.assertIsNone(startup_language({}, Mock(return_value=code), Mock(return_value=False), persist))
            persist.assert_not_called()
            self.assertEqual(startup_language({}, Mock(return_value=code), Mock(return_value=True), persist), code)
            persist.assert_called_once_with(code)

    def test_preview_notice_refuses_changed_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'DISCLAIMER.md').write_text(disclaimer_text(ROOT).replace('provided as is','provided as available'), encoding='utf-8')
            with self.assertRaises(ValueError):
                disclaimer_text(root,'de')

    def test_workbench_catalog_and_formatting(self):
        from string import Formatter
        from command_relay.relay_terms import _WORKBENCH
        self.assertGreaterEqual(len(_WORKBENCH), 80)
        for key, (en, ru) in _WORKBENCH.items():
            self.assertEqual(tr(key, 'en'), en)
            self.assertEqual(tr(key, 'ru'), ru)
            self.assertEqual(tr(key, 'unknown-locale'), en)
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


class GitHubDialogCatalogTests(unittest.TestCase):
    def test_github_catalog_placeholders_and_merge_notice(self):
        from string import Formatter
        from command_relay.relay_terms import _GITHUB_MESSAGES
        for key, (en, ru) in _GITHUB_MESSAGES.items():
            self.assertEqual({x[1] for x in Formatter().parse(en)},
                             {x[1] for x in Formatter().parse(ru)}, key)
        data = dict(repo='owner/repo', number=42, title='Raw <title>', head='feat/raw',
                    base='main', head_sha='a'*40, base_sha='b'*40)
        for language in ('en','ru'):
            text = tr('gh_confirm_body', language).format(**data)
            for raw in data.values(): self.assertIn(str(raw), text)
        self.assertIn('повторно', tr('gh_confirm_body','ru'))
        self.assertIn('не подтверждено', tr('gh_merge_unverified','ru'))
        self.assertIn('не гарантирует', tr('gh_mask_warning','ru'))


class ResultLocalizationTests(unittest.TestCase):
    def test_result_catalog_formatting_and_review_semantics(self):
        from string import Formatter
        from command_relay.relay_terms import _RESULT_MESSAGES
        for key, (en, ru) in _RESULT_MESSAGES.items():
            self.assertEqual(tr(key, 'en'), en)
            self.assertEqual(tr(key, 'ru'), ru)
            self.assertEqual({x[1] for x in Formatter().parse(en) if x[1] is not None}, {x[1] for x in Formatter().parse(ru) if x[1] is not None}, key)
        self.assertIn('не запускает', tr('result_queue_notice', 'ru'))
        self.assertIn('автоматической отправки нет', tr('result_mask', 'ru'))
        self.assertEqual(tr('result_filter_1', 'ru'), 'Код выхода 0')
        self.assertNotIn('PASS', tr('result_filter_1', 'ru'))
        self.assertIn('12', tr('result_count', 'ru').format(count=12))


class RuntimeLocalizationTests(unittest.TestCase):
    def test_runtime_messages_preserve_parameters_and_exit_semantics(self):
        from string import Formatter
        from command_relay.relay_terms import _RUNTIME_MESSAGES
        for key, (en, ru) in _RUNTIME_MESSAGES.items():
            self.assertEqual(tr(key, 'en'), en)
            self.assertEqual(tr(key, 'ru'), ru)
            self.assertEqual({x[1] for x in Formatter().parse(en)}, {x[1] for x in Formatter().parse(ru)}, key)
        for language in ('en', 'ru'):
            self.assertIn('PASS', tr('runtime_checks', language).format(verdict='PASS'))
            self.assertIn('17', tr('runtime_exit_failed', language).format(code=17))
            self.assertIn('0', tr('runtime_exit_zero', language))
            self.assertNotIn('PASS', tr('runtime_exit_zero', language))
            self.assertIn('raw.json', tr('runtime_copied', language).format(mode='full', name='raw.json'))
        self.assertIn('без маскирования', tr('runtime_raw_warning', 'ru'))
        self.assertIn('без гарантии', tr('runtime_masked_warning', 'ru'))


class HistoryLocalizationTests(unittest.TestCase):
    def test_history_labels_and_parameters(self):
        from string import Formatter
        from command_relay.relay_terms import _HISTORY_MESSAGES
        for key,(en,ru) in _HISTORY_MESSAGES.items():
            self.assertEqual(tr(key,'en'),en);self.assertEqual(tr(key,'ru'),ru)
            self.assertEqual({x[1] for x in Formatter().parse(en) if x[1] is not None},{x[1] for x in Formatter().parse(ru) if x[1] is not None},key)
        self.assertNotIn('PASS',tr('history_exit_zero','en'))
        self.assertIn('без маскирования',tr('history_raw_question','ru'))


class AIRulesTests(unittest.TestCase):
    def test_distributed_rules_are_compact_and_capability_aware(self):
        from command_relay.relay_terms import ai_rules_text
        text=ai_rules_text(ROOT)
        for phrase in ('command-relay/task-v1','asynchronous or parallel','bounded concurrency','manual queue requires explicit','Never detach','exit 0 alone','Copy session context'):
            self.assertIn(phrase,text)
        self.assertLess(len(text),12000)
        self.assertNotIn('relay-ai-rules:',text)
        self.assertNotEqual(tr('copy_ai_rules','en'),tr('copy_ai_rules','ru'))

    def test_missing_malformed_oversized_guide_fails_closed(self):
        from command_relay.relay_terms import ai_rules_text
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'docs').mkdir();guide=root/'docs'/'COMMAND_RELAY_AI_GUIDE.md'
            with self.assertRaises(FileNotFoundError):ai_rules_text(root)
            for value in ('', '<!-- relay-ai-rules:end -->\n<!-- relay-ai-rules:start -->', '<!-- relay-ai-rules:start -->\n<!-- relay-ai-rules:end -->', 'x'*256001):
                guide.write_text(value,encoding='utf-8')
                with self.assertRaises(ValueError):ai_rules_text(root)
            guide.write_bytes(b'\xff')
            with self.assertRaises(UnicodeError):ai_rules_text(root)


class BatchCatalogTests(unittest.TestCase):
    def test_batch_review_catalog(self):
        from command_relay.relay_terms import _BATCH_MESSAGES, tr
        from string import Formatter
        for key, (en, ru) in _BATCH_MESSAGES.items():
            self.assertEqual(tr(key, 'en'), en)
            self.assertEqual(tr(key, 'ru'), ru)
            self.assertEqual({f for _, f, _, _ in Formatter().parse(en) if f},
                             {f for _, f, _, _ in Formatter().parse(ru) if f})
        self.assertIn('No execution authorized', tr('batch_validated'))


class CanonicalCopyTests(unittest.TestCase):
    def test_all_message_placeholders_match(self):
        from collections import Counter
        from string import Formatter
        from command_relay.relay_terms import _MESSAGES
        for key, en in _MESSAGES['en'].items():
            fields=lambda value: Counter(field for _,field,_,_ in Formatter().parse(value) if field is not None)
            self.assertEqual(fields(en),fields(_MESSAGES['ru'][key]),key)

    def test_review_and_verdict_language(self):
        from command_relay.relay_terms import verdict_text
        self.assertIn('не гарантия безопасности',tr('batch_inspector','ru'))
        self.assertIn('not a safety guarantee',tr('batch_inspector'))
        self.assertIn('Exit code 0 alone does not prove that tests passed.',tr('history_assert_note','en'))
        self.assertIn('Код выхода 0 сам по себе не подтверждает успех проверок.',tr('history_assert_note','ru'))
        self.assertNotEqual(verdict_text('PASS','ru'),verdict_text('FAIL','ru'))
        self.assertEqual(verdict_text('NOT_REQUESTED','ru'),'Проверки не заданы')
        self.assertEqual(verdict_text('UNKNOWN_RAW','ru'),'UNKNOWN_RAW')
        self.assertIn('42',tr('nav_recent_exit','ru').format(code=42))


class LegacyUICopyTests(unittest.TestCase):
    def test_export_modes_and_unknown_raw(self):
        from command_relay.relay_terms import export_mode_text
        for mode in ('ai', 'detailed', 'compact', 'full'):
            self.assertNotEqual(export_mode_text(mode,'ru'), export_mode_text(mode,'en'))
        self.assertIn('без маскирования', export_mode_text('full','ru'))
        self.assertIn('unmasked', export_mode_text('full','en'))
        self.assertEqual(export_mode_text('future-mode','ru'),'future-mode')

    def test_context_dialog_uses_catalog(self):
        import ast
        source=ast.parse((ROOT/'command_relay'/'relay_qt.py').read_text(encoding='utf-8'))
        method=next(n for n in ast.walk(source) if isinstance(n,ast.FunctionDef) and n.name=='ai_context')
        used={n.args[0].value for n in ast.walk(method) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='ui' and n.args and isinstance(n.args[0],ast.Constant)}
        self.assertTrue({'context_title','context_notice','context_diff','context_choose_files','context_add_files','context_remove','context_preview','context_result_title','mode_cancel'} <= used)
        for node in ast.walk(method):
            if isinstance(node,ast.Call) and ast.unparse(node.func).split('.')[-1] in {'QLabel','QCheckBox','setWindowTitle','getOpenFileNames','btn','start_tool'}:
                self.assertFalse(any(isinstance(a,ast.Constant) and isinstance(a.value,str) and a.value.strip() for a in node.args),ast.unparse(node))


class GlobalLocalizationDraftTests(unittest.TestCase):
    def test_draft_coverage_and_bundled_preview(self):
        from command_relay.relay_terms import (draft_catalogs, localization_draft_status,
            LOCALE_REGISTRY, LANGUAGES, _MESSAGES)
        drafts = draft_catalogs()
        self.assertEqual(set(drafts), set(LOCALE_REGISTRY) - {'en','ru'})
        self.assertEqual(len(drafts), 15)
        for code, catalog in drafts.items():
            status = localization_draft_status(code, catalog)
            self.assertEqual(status['translated'], 528)
            self.assertEqual(status['total'], len(_MESSAGES['en']))
            self.assertEqual(status['translated'] + len(status['missing']), status['total'])
            self.assertTrue(status['catalog_complete'])
            self.assertFalse(status['notice_reviewed'])
            self.assertFalse(status['editorial_reviewed'])
            self.assertFalse(status['enabled'])
            self.assertEqual(saved_language({'language': code}), code)
            self.assertEqual(tr('shell_session', code), catalog['shell_session'])
            self.assertEqual(_MESSAGES[code], catalog)
        self.assertEqual(localization_draft_status('ar', drafts['ar'])['direction'], 'rtl')

    def test_draft_validation_and_copy_isolation(self):
        from command_relay.relay_terms import draft_catalogs, localization_draft_status
        for catalog in ({'nav_recent_count':'Reports'}, {'nav_recent_count':'{wrong}'},
                        {'nav_recent_count':'{count}{count}'}, {'nav_recent_count':'{count!r}'},
                        {'unknown':'text'}, {'shell_session':'Unexpected\nline'}, {'shell_session':' '}, {'shell_session':None}):
            with self.subTest(catalog=catalog), self.assertRaises(ValueError):
                localization_draft_status('de', catalog)
        with self.assertRaises(ValueError):
            localization_draft_status('en', {})
        drafts = draft_catalogs()
        drafts['de']['shell_session'] = 'changed'
        self.assertEqual(draft_catalogs()['de']['shell_session'], 'Sitzung')

    def test_even_complete_catalog_is_not_authorized(self):
        from command_relay.relay_terms import _MESSAGES, localization_draft_status
        status = localization_draft_status('de', dict(_MESSAGES['en']))
        self.assertTrue(status['catalog_complete'])
        self.assertFalse(status['enabled'])
        self.assertFalse(status['notice_reviewed'])
        self.assertFalse(status['editorial_reviewed'])
        self.assertEqual(saved_language({'language':'de'}), 'de')
        self.assertNotEqual(tr('shell_session','de'), _MESSAGES['en']['shell_session'])

    def test_expanded_safety_and_handoff_drafts(self):
        from command_relay.relay_terms import draft_catalogs, _MESSAGES, localization_draft_status
        keys = {'safety_gate_notice', 'safety_gate_once', 'batch_inspector',
                'stop_confirm', 'history_assert_note', 'history_raw_question', 'bridge_draft_notice',
                'plan_review', 'terms_agree', 'terms_decline'}
        for code, catalog in draft_catalogs().items():
            with self.subTest(code=code):
                self.assertTrue(keys <= catalog.keys())
                self.assertTrue(all(catalog[k] != _MESSAGES['en'][k] for k in keys))
                self.assertIn('example.org', catalog['bridge_draft_notice'].format(host='example.org', report='example.txt'))
                self.assertFalse(localization_draft_status(code, catalog)['enabled'])


    def test_extended_history_batch_and_skill_drafts(self):
        from command_relay.relay_terms import draft_catalogs, _MESSAGES, localization_draft_status
        keys = set('history_detail history_assert_note history_page_count batch_notice batch_confirm batch_parallel_warning batch_fault skills_notice skills_load_confirm skills_import_confirm bridge_copy_identity bridge_copy_notice bridge_download_denied plan_input context_notice close_busy'.split())
        for code, catalog in draft_catalogs().items():
            with self.subTest(code=code):
                self.assertTrue(keys <= catalog.keys())
                self.assertTrue(all(catalog[k] != _MESSAGES['en'][k] for k in keys))
                self.assertEqual(catalog['history_detail'].count('\n'), 3)
                self.assertEqual(catalog['bridge_copy_identity'].count('\n'), 2)
                self.assertNotIn(r'\n', catalog['history_detail'])
                self.assertIn('TEST-REPORT', catalog['bridge_copy_identity'].format(report='TEST-REPORT', workspace='TEST-WORKSPACE', host='example.org'))
                self.assertFalse(localization_draft_status(code, catalog)['enabled'])


    def test_legacy_tools_update_and_repeat_drafts(self):
        from command_relay.relay_terms import draft_catalogs, _MESSAGES, localization_draft_status
        keys = set('editor_placeholder terminal_accessible update_downloading update_missing_signature update_listed_signature repeat_unknown repeat_report_changed safety_saved safety_update_saved gh_confirm_title gh_readiness_yes result_filter_4 result_count'.split())
        for code, catalog in draft_catalogs().items():
            with self.subTest(code=code):
                self.assertTrue(keys <= catalog.keys())
                self.assertTrue(all(catalog[k] != _MESSAGES['en'][k] for k in keys))
                self.assertIn('42', catalog['result_count'].format(count=42))
                self.assertFalse(localization_draft_status(code, catalog)['enabled'])

    def test_retired_workspace_keys_removed(self):
        from command_relay.relay_terms import _MESSAGES, draft_catalogs
        retired = ['casual_accessible', 'casual_edited', 'casual_empty', 'casual_flow', 'casual_import', 'casual_import_help', 'casual_result', 'casual_result_help', 'casual_review', 'casual_review_help', 'casual_run', 'casual_running_help', 'casual_stage_accessible', 'casual_title_accessible', 'casual_untitled', 'mode_advanced', 'mode_advanced_desc', 'mode_casual', 'mode_casual_desc', 'mode_continue', 'mode_heading', 'mode_safety', 'mode_settings', 'mode_title', 'nav_code', 'nav_intent', 'nav_no_intent', 'nav_output', 'nav_review_notice', 'nav_review_run', 'nav_risk_high', 'nav_risk_none', 'nav_risk_pending', 'nav_risk_review', 'nav_session', 'review_risk_end', 'review_risk_intro']
        for catalog in (*_MESSAGES.values(), *draft_catalogs().values()):
            self.assertTrue(set(retired).isdisjoint(catalog))
            self.assertIn('mode_cancel', catalog)
            self.assertIn('safety_gate_notice', catalog)

    def test_complete_drafts_preserve_notice_boundaries(self):
        from command_relay.relay_terms import _MESSAGES, draft_catalogs, localization_draft_status
        keys = ('copy_tip', 'merge_allow', 'merge_revoke', 'install_allow', 'install_revoke',
                'gh_confirm_body', 'repeat_warning', 'repeat_unknown_warning')
        for code, catalog in draft_catalogs().items():
            self.assertEqual(set(catalog), set(_MESSAGES['en']))
            self.assertTrue(localization_draft_status(code, catalog)['catalog_complete'])
            for key in keys:
                self.assertEqual(catalog[key].count('\n'), _MESSAGES['en'][key].count('\n'))
                self.assertNotEqual(catalog[key], _MESSAGES['en'][key])
            for key in ('merge_allow', 'merge_revoke'):
                text = catalog[key].format(workspace='TEST-WORKSPACE', repository='TEST-REPO')
                self.assertIn('TEST-WORKSPACE\nTEST-REPO', text)
