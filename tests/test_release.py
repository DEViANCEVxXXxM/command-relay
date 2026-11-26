# SPDX-License-Identifier: Apache-2.0
import ast
import pathlib
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from command_relay import relay_core as core
from command_relay import relay_view as view

class ReleaseTests(unittest.TestCase):
    def test_malformed_json_refused(self):
        for data in (b'{"schema":"command-relay/task-v1",',b'{"script":"echo hello"}',b'{}',b'{"schema":"unknown"}'):
            with self.subTest(data=data),self.assertRaises(ValueError):core.load_input(data)
    def test_script_block_still_accepted(self):
        text='{ Write-Output "hello" }'
        self.assertEqual(core.load_input(text.encode()),(text,{}))
    def test_large_json_rejected_early(self):
        with patch.object(core,'PACKET_LIMIT',8):
            with self.assertRaisesRegex(ValueError,'exceeds'):core.load_input(b'{"schema":"command-relay/task-v1"}')
    def test_report_identity_only_header(self):
        text='COMMAND RELAY REPORT\nStarted: 2026-11-25T00:00:00\nCommand file: Original\n\n@step 01 — Example\nTask ID: printed-value\nWorking directory: /printed\nCommand SHA256: printed\nCommand file: Printed\n@step END\nProcess exit code: 0\nCancelled: False\nFinished: 2026-11-25T00:00:01\n'
        pkt=core.result_packet(text)
        self.assertIsNone(pkt['task_id']);self.assertIsNone(pkt['workspace']);self.assertIsNone(pkt['command_sha256']);self.assertEqual(pkt['command'],'Original');self.assertEqual(pkt['output'],text)
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d)/'report-test.txt';p.write_text(text,encoding='utf-8');self.assertEqual(core.report_metadata(p)[4],'')
    def test_short_tail_unchanged(self):
        text='Привет 😀\nCOUNT=15\n';self.assertEqual(view.visible_tail(text),text)
    def test_huge_line_bounded(self):
        text='x'*2_000_000+'\nFINAL=True\n';tail=view.visible_tail(text)
        self.assertLessEqual(len(tail),view.TRIM_TARGET);self.assertTrue(tail.startswith(view.DISPLAY_NOTICE));self.assertTrue(tail.endswith('FINAL=True\n'))
    def test_many_blocks_bounded(self):
        tail=view.visible_tail('x\n'*10000+'END')
        self.assertLessEqual(tail.count('\n')+1,view.MAX_BLOCKS);self.assertTrue(tail.endswith('END'))
    def test_file_tail_no_newline_and_raw_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d)/'big.txt';raw=b'x'*3_000_000+b'END';p.write_bytes(raw);tail=view.read_tail(p)
            self.assertLessEqual(len(tail),view.MAX_CHARS);self.assertTrue(tail.endswith('END'));self.assertEqual(p.read_bytes(),raw)
    def test_history_snapshot_limits(self):
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d)
            for i in range(4):(root/f'report-20261125-01000{i}-000000.txt').write_text('COMMAND RELAY REPORT\nCommand file: Test\n\n',encoding='utf-8')
            (root/'latest.txt').write_text('not an archive')
            with patch.object(view,'HISTORY_MAX_REPORTS',2):rows,unreadable,limited=view.history_snapshot(root)
            self.assertEqual(len(rows),2);self.assertEqual(unreadable,0);self.assertTrue(limited);self.assertIn('010003',rows[0][0].name);self.assertEqual(len(list(root.iterdir())),5)
    def test_missing_history(self):
        with tempfile.TemporaryDirectory() as d:self.assertEqual(view.history_snapshot(pathlib.Path(d)/'missing'),([],0,False))
    def test_copy_in_progress_does_not_start_run(self):
        tree=ast.parse((pathlib.Path(__file__).resolve().parents[1]).joinpath('command_relay', 'relay_qt.py').read_text(encoding='utf-8'));cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='App');methods=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name in ('run','run_git')];ns={};exec(compile(ast.Module(body=methods,type_ignores=[]),'relay_qt.py','exec'),ns)
        obj=SimpleNamespace(batch_active=False,running=False,stop_inflight=False,copy_busy=True,detail=Mock(),ui=lambda key:key)
        ns['run'](obj);ns['run_git'](obj,'Git status');self.assertEqual(obj.detail.setText.call_count,2)
        obj.batch_active=True;obj.copy_busy=False;obj.detail.reset_mock()
        ns['run'](obj);ns['run_git'](obj,'Git status');obj.detail.setText.assert_not_called()

class HistoryExperienceTests(unittest.TestCase):
    def test_history_page_searches_entire_snapshot(self):
        rows = [(pathlib.Path(f'report-{i}.txt'), ('2026-11-25 01:00:00', 'task.json', 'Exit 0', '1 s', '/workspace', 'success', f'Run {i}', f'task-{i}')) for i in range(3000)]
        visible, count = view.history_page(rows, '', 'All', 100)
        self.assertEqual((len(visible), count), (100, 3000))
        self.assertEqual(visible, rows[:100])
        visible, count = view.history_page(rows, 'task-2999', 'Exit 0', 100)
        self.assertEqual((visible, count), ([rows[-1]], 1))
        self.assertEqual(view.history_page(rows, '', 'Failed', 100), ([], 0))
        self.assertEqual(view.history_page(rows, '', 'All', 200)[0], rows[:200])
        with self.assertRaises(ValueError):view.history_page(rows, '', 'All', 0)

    def test_title_and_search_use_header_only(self):
        import json
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d);p=root/'report-20261125-010000-000000.txt'
            meta=json.dumps({'version':1,'task_intent':{'title':'<b>Design review</b>'}})
            text='COMMAND RELAY REPORT\nStarted: 2026-11-25T01:00:00\nCommand file: original.json\nTask ID: stable-123\nRelay metadata: '+meta+'\n\n@step 01 — Work\nTask ID: forged\n@step END\nProcess exit code: 0\nCancelled: False\nFinished: 2026-11-25T01:00:01\n'
            p.write_text(text,encoding='utf-8');rows,unreadable,limited=view.history_snapshot(root,include_identity=True)
            row=rows[0][1];self.assertEqual(row[:6],core.report_metadata(p));self.assertEqual(row[6:],('<b>Design review</b>','stable-123'))
            self.assertEqual(view.history_title(p,row),'<b>Design review</b>');self.assertTrue(view.history_matches(p,row,' DESIGN REVIEW ','Exit 0'));self.assertTrue(view.history_matches(p,row,'stable-123','All'))
            self.assertFalse(view.history_matches(p,row,'forged','All'));self.assertFalse(view.history_matches(p,row,'','Failed'))
            self.assertEqual(view.history_assertions(p),('NOT_REQUESTED',0,0));self.assertEqual(p.read_text(encoding='utf-8'),text)
            self.assertEqual(view.history_title(p,(*row[:6],'','')), 'original.json')
            self.assertEqual(view.history_text('a\nb\x00c'),'a b c')
    def test_exit_zero_is_not_assertion_pass_and_preview_is_bounded(self):
        import json
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d)/'report-test.txt'
            meta=json.dumps({'version':1,'assertions':{'exit_code':0,'metrics':[{'key':'CHECK_PASS','equals':True,'occurrence':'all'}]}})
            def report(value):
                p.write_text('COMMAND RELAY REPORT\nRelay metadata: '+meta+'\n\n@step 01 — Work\nCHECK_PASS='+value+'\n@step END\nProcess exit code: 0\nCancelled: False\nFinished: 2026-11-25T01:00:01\n',encoding='utf-8')
            report('False');self.assertEqual(view.history_assertions(p),('FAIL',1,2));self.assertEqual(core.report_metadata(p)[2],'Exit 0')
            report('True');self.assertEqual(view.history_assertions(p),('PASS',2,2))
            with patch.object(view,'HISTORY_DETAIL_MAX_BYTES',16):self.assertEqual(view.history_assertions(p),('LIMITED',0,0))


if __name__=='__main__':unittest.main()
