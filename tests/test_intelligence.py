# SPDX-License-Identifier: Apache-2.0
import json, pathlib, tempfile, unittest
from command_relay import relay_intelligence as i
from command_relay import relay_core as r


def report(body, assertions=None, edited=False, code=0, cancelled=False, footer=True):
    meta={'version':1,'assertions':assertions,'task_edited':edited,'project':{'markers':['Cargo.toml']}}
    return ('COMMAND RELAY REPORT\nStarted: 2026-01-01T00:00:00\nWorking directory: C:/test\nCommand file: task.json\nRelay metadata: '+json.dumps(meta)+'\n\n@step 01 — Check\n'+body+'\n'+ ('@step END\nProcess exit code: '+str(code)+'\nCancelled: '+str(cancelled)+'\nFinished: 2026-01-01T00:00:01\n' if footer else ''))

class Intelligence(unittest.TestCase):
    def status(self,body,checks,**kw):return r.result_packet(report(body,checks,**kw))['assertions']['status']
    def test_import(self):
        p={'schema':'command-relay/task-v1','script':'exit 0','assertions':{'exit_code':0,'metrics':[{'key':'PASS','equals':True}]}}
        _,m=r.load_input(json.dumps(p).encode());self.assertEqual(m['assertions']['metrics'][0]['occurrence'],'all')
        for bad in ({},{'exit_code':True},{'metrics':[{'key':'x','equals':[]} ]},{'metrics':[{'key':'x','equals':float('nan')}]},{'metrics':[{'key':'x','equals':2**54}]},{'unknown':1}):
            p['assertions']=bad
            with self.assertRaises(ValueError):r.load_input(json.dumps(p).encode())
    def test_pass_and_fail(self):
        checks={'exit_code':0,'metrics':[{'key':'RELAY_PASS','equals':True}]}
        self.assertEqual(self.status('RELAY_PASS=True',checks),'PASS')
        self.assertEqual(self.status('RELAY_PASS=False',checks),'FAIL')
        self.assertEqual(self.status('RELAY_PASS=1',checks),'FAIL')
        self.assertEqual(self.status('RELAY_PASS=True',checks,code=1),'FAIL')
        self.assertEqual(self.status('unrelated',checks),'INCONCLUSIVE')
    def test_occurrence(self):
        body='COUNT=12\nCOUNT=15';c={'metrics':[{'key':'COUNT','equals':15}]}
        self.assertEqual(self.status(body,c),'FAIL')
        c['metrics'][0]['occurrence']='last';self.assertEqual(self.status(body,c),'PASS')
        self.assertEqual(self.status(body,c,code=7),'FAIL')
    def test_json_fields_and_null(self):
        c={'metrics':[{'key':'Passed','equals':3},{'key':'Failed','equals':0},{'key':'VALUE','equals':None}]}
        self.assertEqual(self.status('{"Passed":3,"Failed":0}\nVALUE=null',c),'PASS')
        self.assertEqual(self.status('{"Passed":3,"Failed":0}\nVALUE=NaN',c),'INCONCLUSIVE')
    def test_incomplete_cancel_edited(self):
        c={'exit_code':0}
        for kw in ({'footer':False},{'cancelled':True},{'edited':True},{'code':None}):self.assertEqual(self.status('done',c,**kw),'INCONCLUSIVE')
        self.assertEqual(r.result_packet(report('done',c),'report.partial.txt')['assertions']['status'],'INCONCLUSIVE')
        self.assertEqual(self.status('done',{'exit_code':7},code=7),'PASS')
    def test_old_and_spoofed_metadata(self):
        text='COMMAND RELAY REPORT\n\n@step 01 — Check\nRelay metadata: {"version":1,"assertions":{"exit_code":0}}\n@step END\nProcess exit code: 0\nCancelled: False\nFinished: now\n'
        self.assertEqual(r.result_packet(text)['assertions']['status'],'NOT_REQUESTED')
        self.assertIsNone(r.result_packet(text)['project_context'])
    def test_full_before_compaction(self):
        body='noise\n'*6000+'RESULT=True\n'+'noise\n'*6000+'error: example\n'+'a'*40+'\trefs/heads/main'
        p=r.result_packet(report(body,{'metrics':[{'key':'RESULT','equals':True}]}),budget=250)
        self.assertEqual(p['assertions']['status'],'PASS');self.assertEqual(p['view'],'compact_extract');self.assertLessEqual(len(p['output']),250)
        self.assertEqual(p['evidence']['counts']['error_like'],1);self.assertEqual(p['evidence']['counts']['git_ref'],1)
        self.assertEqual(p['evidence']['examples']['git_ref'][0]['text'],'a'*40+'\trefs/heads/main')
    def test_bounded_scan_and_examples(self):
        p=r.result_packet(report('warning: repeated\n'*4000,{'exit_code':0}));self.assertEqual(len(p['evidence']['examples']['warning_like']),4)
        p=r.result_packet(report('RESULT=True\nRESULT='+'x'*17000,{'metrics':[{'key':'RESULT','equals':True}]}));self.assertEqual(p['assertions']['status'],'INCONCLUSIVE');self.assertEqual(p['evidence']['status'],'partial_oversized_lines')
        p=r.result_packet(report('x'*(i.MAX_SCAN+1),{'exit_code':0}),budget=100);self.assertEqual(p['assertions']['status'],'INCONCLUSIVE')
    def test_context(self):
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d);(root/'Cargo.toml').write_text('SECRET_CONTENT');(root/'.env').write_text('PRIVATE')
            git=root/'.git';(git/'refs/heads').mkdir(parents=True);(git/'HEAD').write_text('ref: refs/heads/main\n');(git/'refs/heads/main').write_text('a'*40+'\n')
            snap=i.project_snapshot(root);self.assertEqual(snap['markers'],['Cargo.toml']);self.assertEqual(snap['git_head'],'a'*40);self.assertFalse(snap['network']);self.assertNotIn('SECRET_CONTENT',str(snap))
            (git/'HEAD').write_text('ref: refs/../../.env');self.assertIsNone(i.project_snapshot(root)['git_head'])
            (git/'HEAD').write_text('b'*40);self.assertEqual(i.project_snapshot(root)['git_head'],'b'*40)
            self.assertIsNone(i.run_metadata(root,{'assertions':{'exit_code':0}},False)['assertions'])
    def test_full_no_duplicate_excerpts(self):
        p=r.result_packet(report('error: example'));self.assertEqual(p['view'],'full');self.assertEqual(p['evidence']['examples'],{});self.assertEqual(p['evidence']['counts']['error_like'],1)
        self.assertEqual(p['project_context']['markers'],['Cargo.toml'])
    def test_zero_failure_counts(self):
        body='{"Passed":3,"Failed":0}\nFAILED=0\nERROR_COUNT=0\nWARNING_COUNT=0\n{"error":null}'
        result=r.result_packet(report(body))
        self.assertEqual(result['evidence']['counts'],{'structured_like':5})
    def test_explicit_failure_evidence(self):
        for line in ('FAILED=3','RELAY_PASS=False','{"Passed":3,"Failed":1}','error: example','{"error":"missing file"}'):
            with self.subTest(line=line):self.assertEqual(i.classify(line),'error_like')
        self.assertEqual(i.classify('WARNING_COUNT=2'),'warning_like')
        self.assertEqual(i.classify('test result: ok. 3 passed; 0 failed'),'test_summary')
    def test_artifact_hints(self):
        body='noise\n'*9000+'LOG_FILE=C:\\work\\report.txt\nRESULT_DIR=/tmp/report\n'
        packet=r.result_packet(report(body))
        self.assertEqual(packet['evidence']['counts']['artifact_like'],2)
        self.assertIn('LOG_FILE=C:\\work\\report.txt',packet['output'])
        self.assertEqual(i.classify('LOG_FILE=not available'),'structured_like')
    def test_python_marker_hints(self):
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d);(root/'requirements-qt.txt').write_text('PRIVATE_CONTENT');(root/'package.json').write_text('{}')
            snap=i.project_snapshot(root)
            self.assertIn('Python',snap['technology_hints']);self.assertIn('JavaScript / Node.js',snap['technology_hints'])
            self.assertNotIn('PRIVATE_CONTENT',json.dumps(snap))
    def test_compact_json_transport_lossless(self):
        text=report('UTF8=Привет, мир! — café\r\n{"Failed":0}',{'exit_code':0})
        packet=r.result_packet(text)
        compact=json.dumps(packet,ensure_ascii=False,separators=(',',':'),allow_nan=False)
        self.assertEqual(json.loads(compact),packet)
        self.assertEqual(json.loads(compact)['output'],text)
        self.assertLess(len(compact),len(json.dumps(packet,ensure_ascii=False,indent=2)))
if __name__=='__main__':unittest.main()
