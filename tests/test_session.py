# SPDX-License-Identifier: Apache-2.0
import json, pathlib, tempfile, unittest
from unittest.mock import patch
from command_relay import relay_session as s
from command_relay import relay_intelligence as i
from command_relay.relay_core import result_packet

class SessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=pathlib.Path(self.tmp.name);self.ws=self.root/'project';self.ws.mkdir();self.reports=self.root/'reports';self.reports.mkdir()
    def add(self,n,workspace=None,body='COUNT=15',checks=True,cancel=False,partial=False,edited=False):
        path=self.reports/f'report-20261125-060000-{n:06d}{".partial" if partial else ""}.txt'
        task={'title':'Sample task','purpose':'Validate count','expected':'COUNT=15','assertions':{'exit_code':0,'metrics':[{'key':'COUNT','equals':15}]}}
        meta=i.run_metadata(self.ws,task if checks else {},not edited)
        text=f'COMMAND RELAY REPORT\nStarted: 2026-11-25T06:00:00\nWorking directory: {workspace or self.ws}\nCommand file: example.json\nTask ID: task-{n}\nCommand SHA256: {"a"*64}\nRelay metadata: {json.dumps(meta)}\n\n@step 01 — Check\n{body}\n'
        if not partial:text+=f'@step END\nProcess exit code: 0\nCancelled: {cancel}\nFinished: 2026-11-25T06:00:01\n'
        path.write_bytes(text.encode());return path,text
    def packet(self):return s.session_packet(self.reports,self.ws)
    def test_empty(self):self.assertEqual(self.packet()['runs'],[])
    def test_isolation_order_and_intent(self):
        p,text=self.add(1);self.add(2,self.root/'other',body='PRIVATE_OTHER');self.add(3)
        self.assertEqual([r['task_id'] for r in self.packet()['runs']],['task-3','task-1'])
        r=self.packet()['runs'][1];self.assertEqual(r['assertions_status'],'PASS');self.assertEqual(r['intent']['purpose'],'Validate count');self.assertEqual(r['report_sha256_utf8'],result_packet(text,p.name)['report_sha256_utf8']);self.assertNotIn('PRIVATE_OTHER',json.dumps(self.packet()))
        self.assertNotIn('output',r);self.assertEqual(p.read_bytes(),text.encode())
    def test_selected_workspace_canonical_spelling(self):
        canonical = self.root/'canonical project'; canonical.mkdir()
        self.add(1, workspace=canonical)
        self.add(2, workspace=self.ws)
        self.add(3, workspace=self.root/'unrelated')
        original = pathlib.Path.resolve
        def selected_only(path, *args, **kwargs):
            if path == self.ws:
                return canonical
            self.fail('Historical workspace must not be resolved: '+str(path))
        with patch.object(pathlib.Path, 'resolve', autospec=True, side_effect=selected_only):
            rows = self.packet()['runs']
        self.assertEqual([r['task_id'] for r in rows], ['task-2', 'task-1'])
        self.assertEqual([r['assertions_status'] for r in rows], ['PASS', 'PASS'])
        self.assertIs(pathlib.Path.resolve, original)

    def test_canonical_resolution_failure_preserves_lexical_scope(self):
        self.add(1); self.add(2, workspace=self.root/'unrelated')
        with patch.object(pathlib.Path, 'resolve', side_effect=OSError('unavailable')):
            self.assertEqual([r['task_id'] for r in self.packet()['runs']], ['task-1'])

    def test_statuses(self):
        self.add(1,body='COUNT=12');self.add(2,cancel=True);self.add(3,partial=True);self.add(4,checks=False);self.add(5,edited=True)
        rows=self.packet()['runs'];self.assertEqual([r['assertions_status'] for r in rows],['INCONCLUSIVE','NOT_REQUESTED','INCONCLUSIVE','INCONCLUSIVE','FAIL']);self.assertFalse(rows[2]['report_complete']);self.assertEqual(rows[0]['intent'],{})
    def test_big_report_not_pass(self):
        self.add(1,body='x'*600000+'\nCOUNT=15');r=self.packet()['runs'][0];self.assertEqual(r['analysis'],'header_footer_only');self.assertEqual(r['assertions_status'],'NOT_EVALUATED');self.assertTrue(r['report_complete'])
    def test_limits(self):
        for n in range(20):self.add(n)
        p=self.packet();self.assertEqual(len(p['runs']),12);self.assertTrue(p['limits']['older_candidates_not_checked'])
        with patch.object(s,'MAX_PACKET',2000):
            p=self.packet();self.assertGreater(p['limits']['packet_omitted_runs'],0);self.assertLessEqual(len(json.dumps(p,ensure_ascii=False,separators=(',',':'))),2000)
        with patch.object(s,'MAX_SCAN_BYTES',1):self.assertTrue(all(r['assertions_status']=='NOT_EVALUATED' for r in self.packet()['runs']))
        with patch.object(s,'MAX_HEADERS',2):self.assertEqual(len(self.packet()['runs']),2)
    def test_legacy_and_unrelated_files(self):
        path,text=self.add(1);text='\n'.join(l for l in text.split('\n') if not l.startswith('Relay metadata:'));path.write_bytes(text.encode());(self.reports/'latest.txt').write_bytes(text.encode());(self.reports/'not-a-report.txt').write_bytes(text.encode());rows=self.packet()['runs'];self.assertEqual(len(rows),1);self.assertEqual(rows[0]['intent'],{});self.assertEqual(rows[0]['assertions_status'],'NOT_REQUESTED')
    def test_no_raw_log(self):
        self.add(1,body='PRIVATE_BODY\nCOUNT=15');self.assertNotIn('PRIVATE_BODY',json.dumps(self.packet()));self.assertNotIn('task_intent',result_packet('COMMAND RELAY REPORT\n')['evidence'])
    def test_intent_bounded(self):
        m=i.run_metadata(self.ws,{'title':'x'*4000,'expected':'ok'},True);self.assertEqual(len(m['task_intent']['title']),300);self.assertEqual(i.run_metadata(self.ws,{'title':'x'},False)['task_intent'],{})
    def test_relative_and_fake_header(self):
        p,t=self.add(1,workspace='relative');self.add(2,workspace=self.root/'other',body=f'Working directory: {self.ws}');self.assertEqual(self.packet()['runs'],[])
    def test_actionable_handoff(self):
        self.add(1); self.add(2,body='COUNT=12'); self.add(3,cancel=True)
        self.add(4,partial=True); self.add(5,checks=False)
        packet=self.packet(); rows=packet['runs']
        self.assertEqual([r['continuation']['next_action'] for r in rows], [
            'review_report_and_missing_checks','inspect_partial_effects',
            'inspect_partial_effects','inspect_failure_and_existing_effects','verify_current_state_before_reuse'])
        self.assertEqual(packet['handoff']['latest_report'],rows[0]['report_file'])
        self.assertEqual(sum(packet['handoff']['action_counts'].values()),len(rows))
    def test_current_head_relation(self):
        git=self.ws/'.git';git.mkdir();(git/'HEAD').write_text('a'*40)
        self.add(1);(git/'HEAD').write_text('b'*40);self.add(2)
        packet=self.packet();self.assertEqual(packet['current_project']['git_head'],'b'*40)
        self.assertEqual([r['continuation']['git_head_relation'] for r in packet['runs']],['same_as_run_start','differs_from_run_start'])
        self.assertFalse(packet['current_project']['network'])
    def test_handoff_trim_and_empty(self):
        self.assertEqual(self.packet()['handoff']['latest_report'],None)
        for n in range(12):self.add(n)
        with patch.object(s,'MAX_PACKET',3000):
            p=self.packet();self.assertGreater(p['limits']['packet_omitted_runs'],0)
            self.assertEqual(sum(p['handoff']['action_counts'].values()),len(p['runs']))
            self.assertLessEqual(len(json.dumps(p,ensure_ascii=False,separators=(',',':'))),3000)
    def test_nonzero_exit_and_unscanned_are_not_success(self):
        p,text=self.add(1);p.write_text(text.replace('Process exit code: 0','Process exit code: 1'),encoding='utf-8')
        self.add(2,body='x'*600000)
        self.assertEqual([r['continuation']['next_action'] for r in self.packet()['runs']],['review_report_and_missing_checks','inspect_failure_and_existing_effects'])
    def test_protected_handoff(self):
        from command_relay.relay_privacy import protect_packet
        p,text=self.add(1);p.write_text(text.replace('Validate count','PASSWORD=fictional-handoff-secret'),encoding='utf-8')
        out=json.dumps(protect_packet(self.packet()))
        self.assertNotIn('fictional-handoff-secret',out)
        self.assertIn('verify_current_state_before_reuse',out)
    def test_utf8_header_boundary(self):
        self.add(1,body='é'*40000+'\nCOUNT=15');self.assertEqual(self.packet()['runs'][0]['assertions_status'],'PASS')

if __name__=='__main__':unittest.main()
