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
        obj=SimpleNamespace(running=False,stop_inflight=False,copy_busy=True,detail=Mock())
        ns['run'](obj);ns['run_git'](obj,'Git status');self.assertEqual(obj.detail.setText.call_count,2)

if __name__=='__main__':unittest.main()
