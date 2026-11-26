# SPDX-License-Identifier: Apache-2.0
import ast
import json
import pathlib
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from command_relay import relay_export as ex


class ExportTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=pathlib.Path(tmp.name)
    def report(self,n=1,body='COUNT=15'):
        p=self.root/f'report-20261125-070000-{n:06d}.txt'
        meta={'version':1,'task_edited':False,'assertions':{'metrics':[{'key':'COUNT','equals':15}]},'project':{'git_head':'c'*40}}
        text=f'COMMAND RELAY REPORT\nStarted: 2026-11-25T07:00:00\nWorking directory: {self.root}\nCommand file: test.json\nTask ID: test\nCommand SHA256: {"a"*64}\nPrepared script SHA256: {"b"*64}\nRelay metadata: {json.dumps(meta)}\n\n@step 01 — Check\n{body}\n@step END\nProcess exit code: 0\nCancelled: False\nFinished: 2026-11-25T07:00:01\n'
        p.write_bytes(text.encode());return p
    def test_warm_identical_protected(self):
        self.report(1);p=self.report(2,'COUNT=15\nPASSWORD=fictional-example-secret')
        before=p.read_bytes();cached=ex.build_ai(p,warm=True)
        self.assertTrue(cached.fresh());self.assertEqual(ex.build_copy(p,'ai'),(cached.info,cached.text,None))
        self.assertNotIn('fictional-example-secret',cached.text)
        pkt=json.loads(cached.text);self.assertEqual(pkt['privacy']['status'],'redacted');self.assertEqual(pkt['comparison']['status'],'compared');self.assertEqual(pkt['assertions']['status'],'PASS')
        self.assertEqual(p.read_bytes(),before)
    def test_report_changed(self):
        p=self.report();cached=ex.build_ai(p,warm=True);p.write_bytes(p.read_bytes()+b'changed');self.assertFalse(cached.fresh())
    def test_baseline_changed(self):
        a=self.report();p=self.report(2);cached=ex.build_ai(p,warm=True);a.write_bytes(a.read_bytes()+b'changed');self.assertFalse(cached.fresh())
    def test_archive_changed(self):
        p=self.report();cached=ex.build_ai(p,warm=True);self.report(2);self.assertFalse(cached.fresh())
    def test_archive_changed_with_constant_directory_metadata(self):
        p = self.report()
        original_stamp = ex.stamp
        fixed_directory_stamp = original_stamp(self.root)
        with patch.object(ex, 'stamp', side_effect=lambda path: (
                fixed_directory_stamp if path == self.root else original_stamp(path))):
            cached = ex.build_ai(p, warm=True)
            self.assertIsNotNone(cached)
            self.assertTrue(cached.fresh())
            added = self.report(2)
            self.assertFalse(cached.fresh())
            refreshed = ex.build_ai(p, warm=True)
            self.assertIsNotNone(refreshed)
            self.assertTrue(refreshed.fresh())
            added.unlink()
            self.assertFalse(refreshed.fresh())

    def test_archive_limit_disables_warm_cache_not_explicit_copy(self):
        p = self.report()
        with patch.object(ex, 'MAX_ENTRIES', 1):
            cached = ex.build_ai(p, warm=True)
            self.assertIsNotNone(cached)
            self.report(2)
            self.assertFalse(cached.fresh())
            self.assertIsNone(ex.build_ai(p, warm=True))
            with patch.object(ex, 'archive_stamp', side_effect=AssertionError('explicit copy must not scan for cache reuse')):
                self.assertIsNone(ex.build_copy(p, 'ai')[2])

    def test_missing_report(self):
        p=self.report();cached=ex.build_ai(p,warm=True);p.unlink();self.assertFalse(cached.fresh());self.assertIsNotNone(ex.build_copy(p,'ai')[2])
    def test_warm_limit_explicit_copy(self):
        p=self.report()
        with patch.object(ex,'WARM_MAX_BYTES',10):
            self.assertIsNone(ex.build_ai(p,warm=True));self.assertIsNone(ex.build_copy(p,'ai')[2])
    def test_modes(self):
        p=self.report(body='PASSWORD=fictional-example-secret\nCOUNT=15');raw=p.read_bytes().decode()
        self.assertEqual(ex.build_copy(p,'full')[1],raw);self.assertNotIn('fictional-example-secret',ex.build_copy(p,'compact')[1]);self.assertIsNotNone(ex.build_copy(p,'invalid')[2])
    def test_mask_failure_never_raw(self):
        p=self.report(body='PASSWORD=fictional-example-secret')
        with patch.object(ex,'protect_packet',side_effect=ValueError):
            _,out,error=ex.build_copy(p,'ai');self.assertIsNone(out);self.assertIsNotNone(error)


class WorkflowTests(unittest.TestCase):
    """Execute the actual GUI copy methods against mocks, without requiring Qt."""
    def setUp(self):
        tree=ast.parse((pathlib.Path(__file__).resolve().parents[1]).joinpath('command_relay', 'relay_qt.py').read_text(encoding='utf-8'))
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='App')
        names={'warm_done','copy_report'}
        code=ast.Module(body=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name in names],type_ignores=[])
        ns={};exec(compile(code,'relay_qt.py','exec'),ns)
        from command_relay.relay_terms import tr
        self.app=SimpleNamespace(ui=lambda key: tr(key, 'ru'),current=pathlib.Path('report.txt'),running=False,copy_busy=False,warm_path=None,warm_result=None,warm_waiting=False,detail=Mock(),error=Mock(),copy_done=Mock(),start_copy_worker=Mock())
        self.click=lambda mode='ai':ns['copy_report'](self.app,mode)
        self.done=lambda prepared,path=None:ns['warm_done'](self.app,path or self.app.current,prepared)
        self.prepared=SimpleNamespace(path=self.app.current,fresh=Mock(return_value=True),info=('ai','report.txt','PASS',0),text='protected')
    def test_no_automatic_copy(self):
        self.app.warm_path=self.app.current;self.done(self.prepared);self.app.copy_done.assert_not_called();self.click();self.app.copy_done.assert_called_once_with(self.prepared.info,'protected',None);self.app.start_copy_worker.assert_not_called()
    def test_click_during_preparation(self):
        self.app.warm_path=self.app.current;self.click();self.assertTrue(self.app.warm_waiting);self.app.copy_done.assert_not_called();self.done(self.prepared);self.app.copy_done.assert_called_once()
    def test_preparation_failure_falls_back(self):
        self.app.warm_path=self.app.current;self.click();self.done(None);self.app.start_copy_worker.assert_called_once_with(self.app.current,'ai')
    def test_stale_cache_rebuilt(self):
        self.app.warm_result=self.prepared;self.prepared.fresh.return_value=False;self.click();self.app.start_copy_worker.assert_called_once_with(self.app.current,'ai');self.app.copy_done.assert_not_called()
    def test_raw_copy_does_not_use_ai_cache(self):
        self.app.warm_result=self.prepared;self.click('full');self.app.start_copy_worker.assert_called_once_with(self.app.current,'full')
    def test_old_worker_does_not_replace_new_result(self):
        old=self.app.current;self.app.warm_path=old;self.app.current=pathlib.Path('new.txt');self.app.running=True
        self.done(self.prepared,old);self.assertIsNone(self.app.warm_result);self.assertIsNone(self.app.warm_path);self.app.copy_done.assert_not_called()

if __name__=='__main__':unittest.main()
