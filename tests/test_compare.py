# SPDX-License-Identifier: Apache-2.0
import json,pathlib,tempfile,unittest
from unittest.mock import patch
from command_relay import relay_compare as c
from command_relay import relay_intelligence as i
from command_relay.relay_core import result_packet

class CompareTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=pathlib.Path(tmp.name);self.ws=self.root/'workspace';self.ws.mkdir()
    def add(self,n,body='COUNT=15',task='test',workspace=None,script='a',prepared='b',revision='c',edited=False,cancelled=False,partial=False,spec=None):
        p=self.root/f'report-20261125-070000-{n:06d}{".partial" if partial else ""}.txt'
        m={'version':1,'task_edited':edited,'assertions':spec or {'metrics':[{'key':'COUNT','equals':15}]},'project':{'git_head':revision*40}}
        text=f'COMMAND RELAY REPORT\nStarted: 2026-11-25T07:00:00\nWorking directory: {workspace or self.ws}\nCommand file: test.json\nTask ID: {task}\nCommand SHA256: {script*64}\nPrepared script SHA256: {prepared*64}\nRelay metadata: {json.dumps(m)}\n\n@step 01 — Check\n{body}\n'
        if not partial:text+=f'@step END\nProcess exit code: 0\nCancelled: {cancelled}\nFinished: 2026-11-25T07:00:01\n'
        p.write_bytes(text.encode());return p,text
    def compare(self,run):
        p,t=run;return c.compare_previous(p,t,result_packet(t,p.name))
    def test_first_run(self):self.assertEqual(self.compare(self.add(1))['status'],'not_available')
    def test_same_task_delta_and_revision(self):
        p,t=self.add(1,'COUNT=12\nwarning: old');self.add(2,task='other');r=self.compare(self.add(3,revision='d'))
        self.assertEqual(r['status'],'compared');self.assertEqual(r['baseline_report'],p.name);self.assertEqual(r['assertion_status_before'],'FAIL');self.assertEqual(r['assertion_status_after'],'PASS');self.assertEqual(r['metrics'][0]['delta'],3);self.assertTrue(r['git_head_changed']);self.assertEqual(r['heuristic_counts']['warning_like']['delta'],-1);self.assertEqual(p.read_bytes(),t.encode())
    def test_identity_isolation(self):
        for n,kw in enumerate([{'workspace':self.root/'other'},{'task':'other'},{'script':'d'},{'prepared':'e'},{'edited':True},{'spec':{'exit_code':0}}],1):self.add(n,**kw)
        self.assertEqual(self.compare(self.add(7))['status'],'not_available')
    def test_historical_does_not_use_future(self):
        r=self.add(1);self.add(2);self.assertEqual(self.compare(r)['status'],'not_available')
    def test_nearest_cancelled_not_silently_skipped(self):
        self.add(1);p,_=self.add(2,cancelled=True);r=self.compare(self.add(3));self.assertEqual(r['status'],'not_available');self.assertEqual(r['baseline_report'],p.name)
    def test_partial_baseline(self):
        self.add(1,partial=True);self.assertEqual(self.compare(self.add(2))['reason'],'Previous matching run is partial')
    def test_limits(self):
        self.add(1);r=self.add(2)
        with patch.object(c,'MAX_BASELINE_BYTES',1):self.assertIn('scan limit',self.compare(r)['reason'])
        with patch.object(c,'MAX_ENTRIES',1):self.assertIn('directory limit',self.compare(r)['reason'])
    def test_utf8_boundary(self):
        self.add(1,'é'*20000+'\nCOUNT=15');self.assertEqual(self.compare(self.add(2))['status'],'not_available') # oversized line
        self.add(3,('é'*99+'\n')*400+'COUNT=15');self.assertEqual(self.compare(self.add(4))['status'],'compared')
    def test_artifacts_independent_of_compaction(self):
        p,t=self.add(1,'noise\n'*10000+'ARTIFACT=C:\\work\\build.exe\n'+json.dumps({'OUTPUT_FILE':'/tmp/report.txt','Failed':1})+'\nARTIFACT=C:\\work\\build.exe\nSECRET_PATH=/private/secret\nCOUNT=15')
        pkt=result_packet(t,p.name,budget=250);a=pkt['artifacts'];self.assertEqual(a['status'],'reported_only');self.assertEqual([x['path'] for x in a['items']],['C:\\work\\build.exe','/tmp/report.txt']);self.assertFalse(a['limit_reached']);self.assertEqual(pkt['assertions']['status'],'PASS')
    def test_artifact_limit_and_path_validation(self):
        p,t=self.add(1,'\n'.join('ARTIFACT=/tmp/'+str(n) for n in range(20))+'\nCOUNT=15');a=result_packet(t,p.name)['artifacts'];self.assertEqual(len(a['items']),12);self.assertTrue(a['limit_reached']);self.assertEqual(i.artifact_hints('ARTIFACT=https://example.com/file'),[]);self.assertEqual(i.artifact_hints('ARTIFACT=missing'),[])
    def test_artifact_header_excluded(self):
        p,t=self.add(1);t=t.replace('Command file: test.json','Command file: test.json\nARTIFACT=/tmp/header');self.assertEqual(result_packet(t,p.name)['artifacts']['items'],[])

    def test_pre_run_matching_and_latest_verdict(self):
        p,header=self.add(1);self.assertEqual(c.previous_run(self.root,header)['verdict'],'PASS')
        fail,_=self.add(2,'COUNT=0');self.add(3,task='other')
        r=c.previous_run(self.root,header);self.assertEqual((r['report_file'],r['verdict']),(fail.name,'FAIL'))
        self.add(4,cancelled=True);self.assertEqual(c.previous_run(self.root,header)['verdict'],'CANCELLED')
        self.add(5,partial=True);self.assertEqual(c.previous_run(self.root,header)['verdict'],'INCOMPLETE')
    def test_pre_run_identity_isolation(self):
        _,header=self.add(1)
        other=self.root/'empty';other.mkdir()
        self.assertEqual(c.previous_run(other,header)['status'],'no_match')
        for n,kw in enumerate([{'workspace':self.root/'other'},{'task':'other'},{'script':'d'},{'prepared':'e'},{'spec':{'exit_code':0}}],2):
            _,t=self.add(n,**kw)
            (self.root/f'report-20261125-070000-{n:06d}.txt').unlink()
            self.assertEqual(c.previous_run(self.root,t)['status'],'no_match')
        _,t=self.add(7,edited=True);self.assertEqual(c.previous_run(self.root,t)['status'],'not_applicable')
    def test_pre_run_bounded_history(self):
        _,header=self.add(1);self.add(2,task='other')
        with patch.object(c,'MAX_HEADERS',1):self.assertEqual(c.previous_run(self.root,header)['status'],'limited')
        with patch.object(c,'MAX_ENTRIES',1):self.assertEqual(c.previous_run(self.root,header)['status'],'limited')
        with patch.object(c,'MAX_BASELINE_BYTES',1):self.assertEqual(c.previous_run(self.root,header)['verdict'],'NOT_EVALUATED')
        with patch.object(c.os,'scandir',side_effect=PermissionError):self.assertEqual(c.previous_run(self.root,header)['status'],'unavailable')
    def test_pre_run_missing_history(self):
        _,header=self.add(1);self.assertEqual(c.previous_run(self.root/'missing',header)['status'],'no_match')

if __name__=='__main__':unittest.main()
