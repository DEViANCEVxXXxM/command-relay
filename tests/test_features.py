# SPDX-License-Identifier: Apache-2.0
import hashlib, json, pathlib, subprocess, tempfile, unittest, zipfile
from command_relay import relay_core as r
from command_relay import relay_features as f

class Features(unittest.TestCase):
    def test_markers(self):
        text='@step Prepare\nWrite-Output "Hello"\n@step End\nexit 0\n'
        self.assertIn("Write-Output '@step 01 — Prepare'",r.prepare(text))
        self.assertIn("@step 01 — Prepare",r.prepare('@step Prepare\n```powershell\nWrite-Output 1\n```'))
    def test_retired_directive_rejected(self):
        for text in ('@nextstep Test', '# @NEXTSTEP Test', '@nextstep Test\n```powershell\nexit 0\n```'):
            with self.subTest(text=text):
                with self.assertRaisesRegex(ValueError,'Use @step'):r.prepare(text)
                with self.assertRaisesRegex(ValueError,'Use @step'):r.load_input(text.encode())
                data=json.dumps({'schema':'command-relay/task-v1','script':text}).encode()
                with self.assertRaisesRegex(ValueError,'Use @step'):r.load_input(data)
    def test_report_not_executable(self):
        with self.assertRaises(ValueError):r.load_input(b'COMMAND RELAY REPORT\n@step END')
    def test_here_string(self):
        s="@step Start\n$x = @'\n@step literal content\n'@\nWrite-Output $x"
        self.assertIn("@'\n@step literal content\n'@",r.prepare(s))
    def test_current_report(self):
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d)/'report-test.txt'
            for marker in ['@step']:
                text=f'COMMAND RELAY REPORT\nStarted: 2026-01-01T00:00:00\nCommand file: test.txt\n{marker} 01 — Test\nRESULT=True\n{marker} END\nProcess exit code: 7\nCancelled: False\nFinished: 2026-01-01T00:00:02\n'
                p.write_text(text,encoding='utf-8');self.assertEqual(r.report_metadata(p)[2:4],('Exit 7','00:00:02'));self.assertTrue(r.result_packet(text)['report_complete']);self.assertIn(marker+' 01',r.compact_report(text))
    def test_old_report_not_interpreted(self):
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d)/'report-old.txt'
            old='COMMAND RELAY REPORT\nStarted: 2026-01-01T00:00:00\n@nextstep END\nProcess exit code: 0\nCancelled: False\nFinished: 2026-01-01T00:00:01\n'
            p.write_text(old,encoding='utf-8')
            self.assertEqual(r.report_metadata(p)[2],'Unknown')
            self.assertFalse(r.result_packet(old)['report_complete'])
            self.assertEqual(r.result_packet(old,full=True)['output'],old)
    def test_literal_old_marker(self):
        s="@step Start\n$x = @'\n@nextstep literal content\n'@\nWrite-Output $x"
        self.assertIn("@'\n@nextstep literal content\n'@",r.prepare(s))
    def test_metrics(self):
        m=f.metrics('@step 01 — Test\nCOUNT=5\nCOUNT=9\n{"Pass":false,"Rows":32}\n@step 02 — Later\nCOUNT=1\n')
        self.assertEqual(m['fields']['01 — Test / COUNT']['last'],9)
        self.assertEqual(m['fields']['01 — Test / COUNT']['count'],2)
        self.assertIs(m['fields']['01 — Test / Pass']['last'],False)
        self.assertEqual(m['fields']['02 — Later / COUNT']['last'],1)
    def test_compare(self):
        with tempfile.TemporaryDirectory() as d:
            a,b=[pathlib.Path(d)/n for n in ('a.txt','b.txt')]
            a.write_text('@step Test\nCOUNT=84\n');b.write_text('@step Test\nCOUNT=0\n')
            self.assertEqual(f.compare_metrics(a,b)['changed_fields'][0]['last_delta'],-84)
    def test_context_and_limit(self):
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d); w=root/'workspace';w.mkdir();p=w/'source.rs';p.write_text('fn main() {}',encoding='utf-8');outside=root/'outside';outside.write_text('data')
            obj=f.context_packet(w,[p]);self.assertEqual(obj['files'][0]['sha256'],hashlib.sha256(p.read_bytes()).hexdigest())
            with self.assertRaises(ValueError):f.context_packet(w,[outside])
            with self.assertRaises(ValueError):f.read_bounded(p,1)
    def test_bundle(self):
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d); p=root/'report.txt';p.write_bytes(b'test\r\n');dest=root/'evidence.zip';result=f.evidence_bundle([p],dest)
            with zipfile.ZipFile(dest) as z:
                m=json.loads(z.read('manifest.json'));a=m['reports'][0];self.assertEqual(hashlib.sha256(z.read(a['file'])).hexdigest(),a['sha256']);self.assertEqual(z.read(a['file']),p.read_bytes());self.assertIsNone(z.testzip())
            with self.assertRaises(ValueError):f.evidence_bundle([p],dest)
    def test_git_dashboard(self):
        with tempfile.TemporaryDirectory() as d:
            subprocess.run(['git','init','-q',d],check=True)
            p=f.git_dashboard(d);self.assertEqual(p['sections'][0]['exit'],0);self.assertFalse(p['network']);self.assertEqual(len(p['sections']),6)
if __name__=='__main__':unittest.main()
