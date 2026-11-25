# SPDX-License-Identifier: Apache-2.0
import unittest, pathlib, tempfile, json, hashlib, subprocess
from command_relay import relay_core as r
class Tests(unittest.TestCase):
    def test_packet(self):
        p=(pathlib.Path(__file__).resolve().parents[1]).joinpath('examples', 'example-ai-task.json');s,m=r.load_input(p.read_bytes());self.assertEqual(m['task_id'],'relay-qt-smoke-40');self.assertIn('RELAY_PASS=True',s);self.assertIn("Write-Output '@step 01 — Session'",r.prepare(s))
    def test_reject_result(self):
        with self.assertRaises(ValueError):r.load_input(b'{"schema":"command-relay/result-v1","output":"hello"}')
    def test_report(self):
        s='COMMAND RELAY REPORT\nStarted: 2026-01-01T01:00:00\nWorking directory: C:\\test\nCommand file: x.txt\nTask ID: test-1\n\n@step 01 — Test\nREGRESSION_PASS=False\n'+('ordinary line\n'*5000)+'\n@step END\nProcess exit code: 0\nCancelled: False\nFinished: 2026-01-01T01:00:01\n';p=r.result_packet(s,'report.txt');self.assertTrue(p['report_complete']);self.assertEqual(p['process_exit'],'0');self.assertFalse(p['cancelled']);self.assertIn('REGRESSION_PASS=False',p['output']);self.assertEqual(p['task_id'],'test-1');self.assertEqual(r.result_packet(s,full=True)['output'],s);self.assertFalse(r.result_packet(s,'x.partial.txt')['report_complete']);self.assertTrue(r.result_packet(s,budget=100)['budget_truncated'])
    def test_short_git_report_regression(self):
        refs='0123456789abcdef0123456789abcdef01234567\trefs/pull/101/head\nfedcba9876543210fedcba9876543210fedcba98\trefs/pull/102/head'
        text='COMMAND RELAY REPORT\nStarted: 2026-11-25T06:29:57\nWorking directory: C:/work/repo\nCommand file: Untitled\n\n@step 01 — Commands\n'+refs+'\n\n@step END\nProcess exit code: 0\nCancelled: False\nFinished: 2026-11-25T06:29:59\n'
        p=r.result_packet(text)
        self.assertEqual(p['view'],'full');self.assertEqual(p['output'],text)
        self.assertEqual(p['omitted_lines'],0);self.assertFalse(p['budget_truncated'])
        self.assertEqual(p['report_sha256_utf8'],r.sha(text.encode('utf-8')))
        self.assertEqual(json.loads(json.dumps(p,ensure_ascii=False))['output'],text)
        self.assertEqual(r.compact_report(text),text)
    def test_budget_boundary_unicode_and_line_endings(self):
        text='Привет😀\r\n\r\n'+'x'*(r.REPORT_CHAR_BUDGET-len('Привет😀\r\n\r\n'))
        self.assertEqual(len(text),r.REPORT_CHAR_BUDGET)
        self.assertEqual(r.result_packet(text)['output'],text)
        p=r.result_packet(text+'!');self.assertEqual(p['view'],'compact_extract')
        self.assertLessEqual(len(p['output']),r.REPORT_CHAR_BUDGET)
        self.assertEqual(r.result_packet(text+'!',full=True,budget=1)['output'],text+'!')
        self.assertEqual(r.result_packet('')['view'],'full')
    def test_long_report_git_and_accounting(self):
        import re
        refs=['a'*40+'\trefs/heads/main','b'*64,'0123abc Fix regression','## main...origin/main','ref: refs/heads/main']
        noise='unstructured data\n\n'*1500
        text='COMMAND RELAY REPORT\n'+noise+'\n'.join(refs)+'\nRESULT=True\n'+noise+'@step END\nProcess exit code: 0\nCancelled: False\nFinished: 2026-01-01T00:00:00\n'
        p=r.result_packet(text)
        self.assertEqual(p['view'],'compact_extract');self.assertFalse(p['budget_truncated'])
        for ref in refs:self.assertIn(ref,p['output'].splitlines())
        self.assertGreater(p['filter_omitted_lines'],0);self.assertEqual(p['budget_omitted_lines'],0)
        marks=sum(map(int,re.findall(r'\[\.\.\. (\d+) lines omitted;',p['output'])))
        self.assertEqual(marks,p['omitted_lines'])
        source=[x for x in p['output'].splitlines()[2:] if not x.startswith('[... ')]
        self.assertEqual(len(source)+marks,p['original_lines'])
    def test_oversized_extract_whole_lines_and_count(self):
        import re
        text='COMMAND RELAY REPORT\n'+''.join(f'VALUE={i:06d} data\n' for i in range(7000))+'GIANT='+'z'*50000+'\n@step END\nProcess exit code: 0\nCancelled: False\nFinished: 2026-01-01T00:00:00\n'
        p=r.result_packet(text)
        self.assertTrue(p['budget_truncated']);self.assertGreater(p['budget_omitted_lines'],0)
        self.assertLessEqual(len(p['output']),r.REPORT_CHAR_BUDGET)
        self.assertIn('Process exit code: 0',p['output']);self.assertIn('VALUE=000000 data',p['output'])
        self.assertNotIn('GIANT=',p['output'])
        marks=sum(map(int,re.findall(r'\[\.\.\. (\d+) lines omitted;',p['output'])))
        source=[x for x in p['output'].splitlines()[2:] if not x.startswith('[... ')]
        self.assertTrue(set(source)<=set(text.splitlines()))
        self.assertEqual(marks,p['omitted_lines']);self.assertEqual(len(source)+marks,p['original_lines'])
        self.assertEqual(p['omitted_lines'],p['filter_omitted_lines']+p['budget_omitted_lines'])
    def test_tiny_budget(self):
        text='X'*100+'\nY\n'
        for budget in (0,1,20,50,100):
            with self.subTest(budget=budget):
                p=r.result_packet(text,budget=budget)
                self.assertLessEqual(len(p['output']),budget)
                self.assertTrue(p['budget_truncated']);self.assertEqual(p['omitted_lines'],2)
    def test_file(self):
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d)/'r.txt';r.atomic_text(p,'Привет');self.assertEqual(r.file_hash(p),hashlib.sha256('Привет'.encode()).hexdigest())
    def test_git(self):
        with tempfile.TemporaryDirectory() as d:
            subprocess.run(['git','init','-q',d],check=True)
            p=subprocess.run(['git',*r.git_args('Git status')],cwd=d,capture_output=True);self.assertEqual(p.returncode,0)
        with self.assertRaises(KeyError):r.git_args('reset --hard')
    def test_copy_modifiers(self):
        for control,shift,expected in [(False,False,'ai'),(False,True,'compact'),(True,False,'full'),(True,True,'full')]:
            with self.subTest(control=control,shift=shift):self.assertEqual(r.copy_mode(control,shift),expected)
    def test_colorref(self):
        from command_relay.relay_windows import colorref
        self.assertEqual(colorref((0x12,0x34,0x56)),0x563412)
        self.assertEqual(colorref((32,32,32)),0x202020)
if __name__=='__main__':unittest.main()
