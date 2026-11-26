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
class SchedulerTests(unittest.TestCase):
    def task(self, name, deps=(), isolated=False):
        return r.ScheduledTask(name, 'a'*64, deps, isolated)
    def start(self, plan, name):
        return plan.start(name, reviewed_sha256='a'*64, authorized=True)
    def finish(self, plan, attempt, **kwargs):
        return plan.finish(attempt, **{**dict(exit_code=0, report_complete=True, assertions_status='PASS'), **kwargs})
    def test_dependency_validation(self):
        for tasks in ([self.task('a',('a',))], [self.task('a',('b',)),self.task('b',('a',))], [self.task('a',('missing',))], [self.task('a'),self.task('a')], [self.task('a',('b','b')),self.task('b')], [], [self.task(str(i)) for i in range(51)], [r.ScheduledTask('bad id','a'*64)], [r.ScheduledTask('a','x')], [r.ScheduledTask('a','a'*64,[])], [r.ScheduledTask('a','a'*64,(),1)]):
            with self.subTest(tasks=tasks), self.assertRaises(ValueError):r.DependencyScheduler(tasks)
    def test_sequential_default_and_opt_in(self):
        tasks=[self.task('a',isolated=True),self.task('b',isolated=True)]
        for workers in (0,5,True,2):
            with self.assertRaises(ValueError):r.DependencyScheduler(tasks,workers=workers)
        p=r.DependencyScheduler(tasks);self.assertEqual(p.ready(),('a',));a=self.start(p,'a');self.assertEqual(p.ready(),());self.finish(p,a);self.assertEqual(p.ready(),('b',))
    def test_dependencies_and_bounded_parallelism(self):
        p=r.DependencyScheduler([self.task('final',('a','b')),self.task('a',isolated=True),self.task('b',isolated=True),self.task('c',isolated=True)],workers=2,parallel_opt_in=True)
        self.assertEqual(p.ready(),('a','b'));a=self.start(p,'a');b=self.start(p,'b');self.assertEqual(p.ready(),());self.finish(p,a);self.assertEqual(p.ready(),('c',));self.finish(p,b);self.assertEqual(p.ready(),('final',));final=self.start(p,'final');self.assertEqual(p.ready(),());self.finish(p,final);self.assertEqual(p.ready(),('c',))
    def test_exclusive_task_does_not_overlap(self):
        p=r.DependencyScheduler([self.task('a',isolated=True),self.task('exclusive'),self.task('b',isolated=True)],workers=3,parallel_opt_in=True)
        self.assertEqual(p.ready(),('a',));a=self.start(p,'a');self.assertEqual(p.ready(),());self.finish(p,a);self.assertEqual(p.ready(),('exclusive',));e=self.start(p,'exclusive');self.assertEqual(p.ready(),());self.finish(p,e);self.assertEqual(p.ready(),('b',))
    def test_review_and_permission_required(self):
        p=r.DependencyScheduler([self.task('a')]);
        for digest,auth in (('b'*64,True),('a'*64,False),('a'*64,1)):
            with self.assertRaises(ValueError):p.start('a',reviewed_sha256=digest,authorized=auth)
        self.assertEqual(p.snapshot(),{'a':'pending'});self.start(p,'a')
        with self.assertRaises(ValueError):self.start(p,'a')
    def test_failure_and_unknown_propagate(self):
        for evidence,state in ((dict(exit_code=1),'failed'),(dict(assertions_status='FAIL'),'failed'),(dict(assertions_status='NOT_REQUESTED'),'unverified'),(dict(report_complete=False),'unverified'),(dict(exit_code=None),'unverified'),(dict(assertions_status='INCONCLUSIVE'),'unverified')):
            p=r.DependencyScheduler([self.task('c',('b',)),self.task('b',('a',)),self.task('a'),self.task('independent')]);a=self.start(p,'a');self.assertEqual(self.finish(p,a,**evidence),state);self.assertEqual(p.snapshot(),{'c':'blocked','b':'blocked','a':state,'independent':'pending'});self.assertEqual(p.ready(),('independent',))
    def test_cancel_pending_and_running(self):
        p=r.DependencyScheduler([self.task('a',isolated=True),self.task('b',('a',)),self.task('c',isolated=True)],workers=2,parallel_opt_in=True)
        a=self.start(p,'a');self.assertTrue(p.cancel('a'));self.assertEqual(p.snapshot()['a'],'cancelling');self.assertFalse(p.cancel('c'));self.assertEqual(p.ready(),());self.assertEqual(self.finish(p,a),'cancelled');self.assertEqual(p.snapshot(),{'a':'cancelled','b':'blocked','c':'cancelled'})
    def test_cancel_retains_worker_slot(self):
        p=r.DependencyScheduler([self.task('a',isolated=True),self.task('b',isolated=True),self.task('c',isolated=True)],workers=2,parallel_opt_in=True)
        a=self.start(p,'a');b=self.start(p,'b');p.cancel('a');self.assertEqual(p.ready(),());self.finish(p,a);self.assertEqual(p.ready(),('c',));self.finish(p,b)
    def test_stop_and_stale_receipts(self):
        p=r.DependencyScheduler([self.task('a'),self.task('b')]);a=self.start(p,'a');self.assertEqual(p.stop(),(a,));self.assertEqual(p.ready(),());self.assertEqual(p.snapshot()['b'],'cancelled');self.assertEqual(self.finish(p,a),'cancelled')
        with self.assertRaises(ValueError):self.finish(p,a)
        q=r.DependencyScheduler([self.task('a')]);b=self.start(q,'a');self.assertNotEqual(a.token,b.token)
        with self.assertRaises(ValueError):self.finish(q,a)
        with self.assertRaises(ValueError):self.finish(q,b,exit_code=True)
        self.assertEqual(q.snapshot()['a'],'running');self.finish(q,b)
    def test_snapshot_is_copy_and_invalid_receipt_does_not_change_state(self):
        p=r.DependencyScheduler([self.task('a')]);p.snapshot()['a']='succeeded';self.assertEqual(p.snapshot()['a'],'pending');a=self.start(p,'a')
        with self.assertRaises(ValueError):self.finish(p,a,report_complete=1)
        self.assertEqual(p.snapshot()['a'],'running');self.finish(p,a)

class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.reports = self.root / 'reports'; self.reports.mkdir()
        self.work = self.root / 'work'; self.work.mkdir()
        self.handles = {}; self.emit = {}; self.auth = []

    def plan(self, *, parallel=False, assertions=None):
        if assertions is None: assertions = {'exit_code':0,'metrics':[{'key':'RESULT','equals':True}]}
        reviews = [r.DispatchReview.capture(k, k.encode(), self.work, assertions) for k in ('a','b','c')]
        tasks = [r.ScheduledTask(v.task_id,r.sha(v.prepared),('a',) if v.task_id=='c' else (),parallel) for v in reviews]
        self.scheduler = r.DependencyScheduler(tasks,workers=2 if parallel else 1,parallel_opt_in=parallel)
        self.dispatch = r.ExecutionDispatch(self.scheduler,reviews,self.reports)
        return reviews

    class Handle:
        code = None
        def poll(self): return self.code

    def launch(self, attempt, review, emit):
        self.assertEqual(r.sha(review.prepared),attempt.prepared_sha256)
        self.handles[attempt.task_id] = self.Handle();self.emit[attempt.task_id]=emit
        return self.handles[attempt.task_id]

    def authorize(self, review):
        self.auth.append(review.task_id);return True

    def start(self, name):
        return self.dispatch.start(name,authorize=self.authorize,launch=self.launch)

    def complete(self, attempt, code=0, output=b'RESULT=True\n'):
        handle=self.handles[attempt.task_id];handle.code=code
        self.emit[attempt.task_id](output)
        return self.dispatch.complete(attempt,handle=handle,settled=lambda *_:True)

    def test_interleaved_real_processes_and_owned_reports(self):
        import sys
        self.plan(parallel=True)
        def launch(attempt, review, emit):
            child=subprocess.Popen([sys.executable,'-c','import sys; print(sys.argv[1]); print("RESULT=True")',attempt.task_id],cwd=review.workspace,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            self.addCleanup(lambda: child.wait(timeout=10))
            self.handles[attempt.task_id]=child;self.emit[attempt.task_id]=emit
            return child
        a=self.dispatch.start('a',authorize=self.authorize,launch=launch)
        b=self.dispatch.start('b',authorize=self.authorize,launch=launch)
        for attempt in (b,a):
            child=self.handles[attempt.task_id];out,_=child.communicate(timeout=10);self.emit[attempt.task_id](out)
            receipt=self.dispatch.complete(attempt,handle=child,settled=lambda *_:True)
            self.assertEqual(receipt.state,'succeeded');self.assertEqual(receipt.assertions_status,'PASS')
            text=receipt.report_path.read_bytes().decode('utf-8');self.assertEqual(r.sha(text.encode()),receipt.report_sha256)
            text=text.replace('\r\n','\n')
            self.assertEqual(r.report_header_fields(text)['Attempt ID'],attempt.token)
            self.assertIn('\n'+attempt.task_id+'\nRESULT=True',text)
            self.assertNotIn('\n'+('a' if attempt.task_id=='b' else 'b')+'\nRESULT=True',text)
        self.assertEqual(self.scheduler.ready(),('c',));self.assertEqual(len(list(self.reports.iterdir())),2)

    def test_denied_and_changed_workspace(self):
        self.plan();called=[]
        with self.assertRaises(ValueError):self.dispatch.start('a',authorize=lambda _:False,launch=lambda *a:called.append(a))
        self.assertEqual(self.scheduler.snapshot()['a'],'pending');self.assertFalse(called)
        self.work.rename(self.root/'old-work');self.work.mkdir()
        with self.assertRaises(ValueError):self.start('a')
        self.assertEqual(self.scheduler.snapshot()['a'],'pending');self.assertFalse(self.handles)

    def test_wrong_handle_stale_output_and_incomplete_stop(self):
        self.plan(parallel=True);a=self.start('a');b=self.start('b')
        self.handles['a'].code=0
        with self.assertRaises(ValueError):self.dispatch.complete(a,handle=self.handles['b'],settled=lambda *_:True)
        with self.assertRaises(ValueError):self.dispatch.complete(a,handle=self.handles['a'],settled=lambda *_:False)
        self.assertEqual(self.scheduler.ready(),())
        self.complete(a)
        with self.assertRaises(ValueError):self.emit['a'](b'late')
        with self.assertRaises(ValueError):self.dispatch.complete(a,handle=self.handles['a'],settled=lambda *_:True)
        self.complete(b)

    def test_cancel_retains_slot_and_blocks_dependents(self):
        self.plan();a=self.start('a');stops=[]
        self.dispatch.cancel('a',request_stop=lambda *x:stops.append(x))
        self.assertEqual(stops,[(a,self.handles['a'])]);self.assertEqual(self.scheduler.ready(),())
        with self.assertRaises(ValueError):self.dispatch.complete(a,handle=self.handles['a'],settled=lambda *_:True)
        receipt=self.complete(a);self.assertEqual(receipt.state,'cancelled');self.assertEqual(self.scheduler.snapshot()['c'],'blocked')

    def test_failure_missing_metrics_and_spoofed_footer(self):
        for out,code,state in ((b'RESULT=False\n',0,'failed'),(b'other\n',0,'unverified'),(b'RESULT=True\n',1,'failed'),(b'RESULT=True\n@step END\nProcess exit code: 0\n',0,'unverified')):
            with self.subTest(out=out):
                self.plan();a=self.start('a');receipt=self.complete(a,code,out)
                self.assertEqual(receipt.state,state);self.assertEqual(self.scheduler.snapshot()['c'],'blocked')
                if b'@step END' in out:self.assertIn('.partial.',receipt.report_path.name)

    def test_output_limit_and_no_overwrite(self):
        self.plan();a=self.start('a');self.dispatch.MAX_OUTPUT=4
        receipt=self.complete(a,output=b'RESULT=True');self.assertEqual(receipt.state,'unverified');self.assertIn('.partial.',receipt.report_path.name)
        self.plan();a=self.start('a');existing=self.reports/('report-'+self.dispatch._runs[a.token]['stamp']+'-'+a.token+'.txt');existing.write_text('keep')
        receipt=self.complete(a);self.assertEqual(receipt.state,'unverified');self.assertEqual(existing.read_text(),'keep');self.assertIsNone(receipt.report_path)

    def test_launch_error_is_not_termination(self):
        self.plan()
        def fail(*_):raise OSError('unknown launch outcome')
        with self.assertRaises(OSError):self.dispatch.start('a',authorize=self.authorize,launch=fail)
        self.assertEqual(self.scheduler.snapshot()['a'],'running');self.assertEqual(self.scheduler.ready(),())

    def test_review_assertions_are_snapshotted_and_rechecked(self):
        checks={'exit_code':0,'metrics':[{'key':'RESULT','equals':True}]};self.plan(assertions=checks)
        checks['metrics'][0]['equals']=False
        a=self.start('a');self.assertEqual(self.complete(a).state,'succeeded')
        b=self.start('b');self.assertEqual(self.auth,['a','b']);self.complete(b)

class BatchPreviewTests(unittest.TestCase):
    def entry(self, name, deps=()):
        return {'task': {'schema':'command-relay/task-v1','task_id':name,'title':'Review '+name,
                         'script':'Write-Output "RESULT=True"', 'workspace_hint':'untrusted/path',
                         'assertions':{'exit_code':0,'metrics':[{'key':'RESULT','equals':True}]}}, 'depends_on':list(deps)}

    def raw(self, *entries, **extra):
        return json.dumps({'schema':'command-relay/batch-v1','batch_id':'batch-1','tasks':list(entries),**extra}).encode()

    def test_preview_and_legacy_rejection(self):
        data=self.raw(self.entry('a'),self.entry('b',('a',)))
        plan=r.load_batch(data);self.assertEqual(plan.source_sha256,r.sha(data))
        self.assertEqual(plan.items[1].dependencies,('a',));self.assertEqual(plan.items[0].prepared,r.prepare(plan.items[0].script).encode('utf-8-sig'))
        with self.assertRaises(ValueError):r.load_input(data)
        with self.assertRaises(ValueError):r.load_batch(json.dumps(self.entry('a')['task']).encode())

    def test_strict_envelope_and_authority(self):
        a=self.entry('a')
        for raw in (self.raw(a,workers=4),self.raw(a,parallel_opt_in=True),self.raw({**a,'isolated':True}),self.raw({'task':{**a['task'],'authorized':True},'depends_on':[]}),self.raw(),b'{"schema":"x","schema":"command-relay/batch-v1"}',b'{}',b' '* (r.PACKET_LIMIT+1)):
            with self.subTest(raw=raw[:200]), self.assertRaises(ValueError):r.load_batch(raw)

    def test_graph_and_checks(self):
        a=self.entry('a');a['task'].pop('assertions')
        for entries in ((a,), (self.entry('a'),self.entry('a')), (self.entry('a',('missing',)),), (self.entry('a',('b',)),self.entry('b',('a',))), (self.entry('a',('a',)),), (self.entry('a',(1,)),)):
            with self.subTest(entries=entries), self.assertRaises(ValueError):r.load_batch(self.raw(*entries))

    def test_explicit_review_and_default_serial(self):
        plan=r.load_batch(self.raw(self.entry('a'),self.entry('b')))
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):plan.review({'a':d})
            scheduler,reviews=plan.review({'a':d,'b':d})
            self.assertEqual(scheduler.ready(),('a',));self.assertEqual(reviews[0].workspace,str(pathlib.Path(d).resolve()))
            self.assertEqual(scheduler.snapshot(),{'a':'pending','b':'pending'})
            with self.assertRaises(ValueError):scheduler.start('a',reviewed_sha256=r.sha(reviews[0].prepared),authorized=False)

    def test_parallel_review_requires_distinct_roots_and_opt_in(self):
        plan=r.load_batch(self.raw(self.entry('a'),self.entry('b')))
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d);a=root/'a';b=root/'b';a.mkdir();b.mkdir()
            for paths in ({'a':a,'b':a},{'a':root,'b':a}):
                with self.assertRaises(ValueError):plan.review(paths,workers=2,parallel_opt_in=True,isolated_ids=('a','b'))
            with self.assertRaises(ValueError):plan.review({'a':a,'b':b},workers=2,isolated_ids=('a','b'))
            scheduler,_=plan.review({'a':a,'b':b},workers=2,parallel_opt_in=True,isolated_ids=('a','b'))
            self.assertEqual(scheduler.ready(),('a','b'))
            scheduler,_=plan.review({'a':a,'b':b},workers=2,parallel_opt_in=True)
            self.assertEqual(scheduler.ready(),('a',))


class WindowsBackendTests(unittest.TestCase):
    def test_bounded_pipe_delivers_on_controller(self):
        import io, threading
        from command_relay.relay_windows import _BoundedPipe
        pipe=_BoundedPipe(io.BytesIO(b'abcdefghij'),4); pipe.thread.join(2)
        received=[]; main=threading.get_ident()
        self.assertTrue(pipe.pump(lambda b:received.append((threading.get_ident(),b))))
        self.assertEqual(received,[(main,b'abcde')]); self.assertTrue(pipe.pump(lambda b:self.fail('duplicate output')))

    def test_pipe_read_failure_marks_incomplete(self):
        from command_relay.relay_windows import _BoundedPipe
        class Broken:
            def read(self,n): raise OSError('read failed')
            def close(self): pass
        pipe=_BoundedPipe(Broken(),10);pipe.thread.join(2);received=[]
        self.assertTrue(pipe.pump(received.append));self.assertEqual(received,[b'\xff'])

    def test_windows_backend_platform_and_real_job(self):
        import sys,time
        from command_relay.relay_windows import WindowsPowerShellRun
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp); reports=root/'reports';reports.mkdir()
            script=r.prepare("@step Probe\nWrite-Output 'RESULT=True'\nexit 0").encode('utf-8-sig')
            review=r.DispatchReview.capture('probe',script,root,{'exit_code':0,'metrics':[{'key':'RESULT','equals':True}]})
            scheduler=r.DependencyScheduler([r.ScheduledTask('probe',r.sha(script))]);dispatch=r.ExecutionDispatch(scheduler,[review],reports)
            if sys.platform!='win32':
                with self.assertRaises(OSError): dispatch.start('probe',authorize=lambda _:True,launch=WindowsPowerShellRun)
                self.assertEqual(scheduler.snapshot()['probe'],'running');return
            handles=[]
            def launch(*args):
                h=WindowsPowerShellRun(*args);handles.append(h);return h
            attempt=dispatch.start('probe',authorize=lambda _:True,launch=launch);h=handles[0]
            try:
                deadline=time.monotonic()+20
                while time.monotonic()<deadline:
                    if h.poll() is not None and h.settled(attempt,h): break
                    time.sleep(.02)
                receipt=dispatch.complete(attempt,handle=h,settled=h.settled)
                self.assertEqual(receipt.state,'succeeded');self.assertEqual(receipt.assertions_status,'PASS')
            finally:
                if not h.closed:
                    h.cancel(attempt,h);h.process.wait(timeout=10);h.pipe.thread.join(10);h.settled(attempt,h)

    def test_windows_job_cancel_descendant(self):
        import sys,time,subprocess
        from command_relay.relay_windows import _WindowsJob,_GATE_HELPER
        if sys.platform!='win32':
            self.assertIn("sys.stdin.buffer.read(1)",_GATE_HELPER);return
        job=_WindowsJob(); child=None
        try:
            # Trusted test helper creates a descendant only after attachment.
            child=subprocess.Popen([sys.executable,'-I','-S','-c',_GATE_HELPER,sys.executable,'-I','-S','-c','import time; time.sleep(30)'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            job.assign(child);child.stdin.write(b'R');child.stdin.close()
            deadline=time.monotonic()+10
            while job.active()<2 and time.monotonic()<deadline:time.sleep(.02)
            self.assertGreaterEqual(job.active(),2)
            job.terminate();child.wait(timeout=10)
            deadline=time.monotonic()+10
            while job.active() and time.monotonic()<deadline:time.sleep(.02)
            self.assertEqual(job.active(),0)
        finally:
            job.close()
            if child is not None:
                if child.poll() is None:child.kill()
                child.wait(timeout=10);child.stdin.close();child.stdout.close()


class BatchControllerTests(unittest.TestCase):
    class Handle:
        def __init__(self, attempt, review, emit):
            self.attempt=attempt; self.emit=emit; self.code=None; self.done=False; self.stops=0
        def poll(self): return self.code
        def settled(self, attempt, handle): return self.done and attempt==self.attempt and handle is self
        def cancel(self, attempt, handle): self.stops+=1
        def finish(self, code=0, output=b'RESULT=True\n'):
            self.emit(output);self.code=code;self.done=True

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=pathlib.Path(self.tmp.name);self.reports=root/'reports';self.reports.mkdir()
        self.paths={k:root/k for k in ('a','b','c')}
        for p in self.paths.values():p.mkdir()
        self.handles={};self.auth=[]

    def controller(self, *, parallel=False, launch=None):
        helper=BatchPreviewTests();plan=r.load_batch(helper.raw(helper.entry('a'),helper.entry('b'),helper.entry('c',('a','b'))))
        def default(attempt,review,emit):
            h=self.Handle(attempt,review,emit);self.handles[attempt.task_id]=h;return h
        return r.BatchExecutionController(plan,self.paths,self.reports,workers=2 if parallel else 1,
            parallel_opt_in=parallel,isolated_ids=('a','b','c') if parallel else (),launch=launch or default)

    def authorize(self,review):self.auth.append(review.task_id);return True

    def test_poll_inert_and_serial(self):
        c=self.controller();self.assertEqual(c.poll(),());self.assertEqual(self.handles,{})
        self.assertEqual([a.task_id for a in c.start_ready(authorize=self.authorize)],['a'])
        h=self.handles['a'];h.code=0;self.assertEqual(c.poll(),());self.assertEqual(c.snapshot()['states']['a'],'running')
        h.finish();self.assertEqual(c.poll()[0].state,'succeeded');self.assertEqual(c.snapshot()['ready'],('b',))
        self.assertEqual(set(self.handles),{'a'});c.start_ready(authorize=self.authorize);self.handles['b'].finish();c.poll()
        c.start_ready(authorize=self.authorize);self.handles['c'].finish();c.poll()
        self.assertTrue(c.snapshot()['finished']);self.assertEqual(self.auth,['a','b','c'])
        self.assertEqual(len({x.report_path for x in c.snapshot()['receipts'].values()}),3)

    def test_parallel_dependencies_and_failure(self):
        c=self.controller(parallel=True);self.assertEqual(len(c.start_ready(authorize=self.authorize)),2)
        self.handles['b'].finish(output=b'RESULT=False\n');self.assertEqual(c.poll()[0].state,'failed')
        self.assertEqual(c.snapshot()['states']['c'],'blocked');self.handles['a'].finish();c.poll();self.assertTrue(c.snapshot()['finished'])

    def test_denial_halts_no_retry(self):
        c=self.controller(parallel=True)
        self.assertEqual(c.start_ready(authorize=lambda _:False),());self.assertTrue(c.snapshot()['halted'])
        self.assertEqual(c.start_ready(authorize=self.authorize),());self.assertEqual(self.handles,{})
        c.stop();self.assertTrue(c.snapshot()['finished'])

    def test_stop_waits_for_settlement(self):
        c=self.controller(parallel=True);c.start_ready(authorize=self.authorize);c.stop();c.stop()
        self.assertEqual(c.snapshot()['states'],{'a':'cancelling','b':'cancelling','c':'cancelled'})
        self.assertEqual([h.stops for h in self.handles.values()],[1,1]);self.assertFalse(c.snapshot()['finished'])
        for h in self.handles.values():h.finish()
        self.assertEqual([x.state for x in c.poll()],['cancelled','cancelled']);self.assertTrue(c.snapshot()['finished'])

    def test_unknown_launch_retains_slot(self):
        def fail(*args):raise OSError('ambiguous launch')
        c=self.controller(parallel=True,launch=fail);self.assertEqual(c.start_ready(authorize=self.authorize),())
        self.assertEqual(c.snapshot()['states']['a'],'running');self.assertEqual(c.snapshot()['ready'],())
        c.stop();self.assertEqual(c.snapshot()['states']['a'],'cancelling');self.assertFalse(c.snapshot()['finished']);self.assertIn('Unknown process handle',c.snapshot()['faults']['a'])

    def test_poll_fault_halts_but_other_receipt_survives(self):
        c=self.controller(parallel=True);c.start_ready(authorize=self.authorize)
        def fail():raise OSError('poll failure')
        self.handles['a'].poll=fail;self.handles['b'].finish();self.assertEqual(c.poll()[0].attempt.task_id,'b')
        self.assertTrue(c.snapshot()['halted']);self.assertEqual(c.snapshot()['states']['a'],'running');self.assertFalse(c.snapshot()['finished'])

    def test_real_windows_controller(self):
        import sys,time
        from command_relay.relay_windows import WindowsPowerShellRun
        if sys.platform!='win32':
            self.assertTrue(callable(WindowsPowerShellRun));return
        c=self.controller(parallel=True,launch=WindowsPowerShellRun)
        try:
            deadline=time.monotonic()+25
            while not c.snapshot()['finished'] and time.monotonic()<deadline:
                c.start_ready(authorize=self.authorize);c.poll();time.sleep(.02)
                if c.snapshot()['halted']:break
            self.assertEqual(c.snapshot()['states'],{'a':'succeeded','b':'succeeded','c':'succeeded'},c.snapshot()['faults'])
            self.assertEqual(len(c.snapshot()['receipts']),3)
        finally:
            c.stop();deadline=time.monotonic()+10
            while not c.snapshot()['finished'] and time.monotonic()<deadline:c.poll();time.sleep(.02)

if __name__=='__main__':unittest.main()


class BatchArchiveTests(unittest.TestCase):
    Handle = BatchControllerTests.Handle
    setUp = BatchControllerTests.setUp
    controller = BatchControllerTests.controller
    authorize = BatchControllerTests.authorize
    def test_archive_roundtrip(self):
        from command_relay import relay_view as view, relay_session as session, relay_compare as compare, relay_export as export
        c=self.controller(parallel=True);c.start_ready(authorize=self.authorize)
        self.handles['b'].finish(output=b'RESULT=False\n');self.handles['a'].finish()
        receipts={x.attempt.task_id:x for x in c.poll()}
        self.assertEqual(set(receipts),{'a','b'})
        for key, expected in [('a','PASS'),('b','FAIL')]:
            receipt=receipts[key];path=receipt.report_path
            self.assertTrue(session.NAME.fullmatch(path.name));self.assertIn(receipt.attempt.token,path.name)
            raw=path.read_bytes();text=raw.decode();self.assertEqual(r.sha(raw),receipt.report_sha256)
            self.assertEqual(r.report_header_fields(text)['Attempt ID'],receipt.attempt.token)
            self.assertEqual(view.history_assertions(path)[0],expected)
            self.assertEqual(r.report_metadata(path,include_identity=True)[6:],(f'Review {key}',key))
            self.assertEqual(compare.previous_run(self.reports,text)['verdict'],expected)
            packet=json.loads(export.build_ai(path).text)
            self.assertEqual(packet['assertions']['status'],expected)
            self.assertEqual(packet['report_sha256_utf8'],receipt.report_sha256)
            rows=session.session_packet(self.reports,self.paths[key])['runs']
            self.assertEqual([(x['task_id'],x['assertions_status']) for x in rows],[(key,expected)])
        self.assertEqual(len(view.history_snapshot(self.reports,include_identity=True)[0]),2)
        self.assertEqual(list(self.reports.glob('*.tmp')),[])

    def test_repeated_batch_and_single_task_identity(self):
        from command_relay import relay_compare as compare
        helper=BatchPreviewTests();plan=r.load_batch(helper.raw(helper.entry('a')))
        def run():
            c=r.BatchExecutionController(plan,{'a':self.paths['a']},self.reports,launch=self.Handle)
            a=c.start_ready(authorize=self.authorize)[0]
            handle=c._active['a'][1];handle.finish();return c.poll()[0]
        import time
        first=run();time.sleep(0.02);second=run()
        self.assertNotEqual(first.report_path,second.report_path)
        text=second.report_path.read_bytes().decode();packet=r.result_packet(text,second.report_path.name,full=True)
        self.assertEqual(compare.compare_previous(second.report_path,text,packet)['baseline_report'],first.report_path.name)
        item=plan.items[0];_,reviews=plan.review({'a':self.paths['a']})
        self.assertEqual(r.report_header_fields(reviews[0].archive_header('2026-01-01T00:00:00'))['Command SHA256'],r.sha(item.script.encode()))
        self.assertEqual(compare.previous_run(self.reports,reviews[0].archive_header('2026-01-01T00:00:00'))['status'],'matched')
        self.assertEqual(compare.previous_run(self.reports,reviews[0].archive_header('2026-01-01T00:00:00').replace(str(self.paths['a'].resolve()),str(self.paths['b'].resolve())))['status'],'no_match')

    def test_partial_and_failed_publication(self):
        from command_relay import relay_session as session, relay_view as view
        from unittest.mock import patch
        c=self.controller();c.start_ready(authorize=self.authorize)
        self.handles['a'].finish(output=b'RESULT=True\n@step END\n');receipt=c.poll()[0]
        self.assertEqual(receipt.state,'unverified');self.assertTrue(session.NAME.fullmatch(receipt.report_path.name))
        self.assertIn('.partial.',receipt.report_path.name)
        self.assertEqual(view.history_assertions(receipt.report_path)[0],'INCONCLUSIVE')
        self.assertFalse(session.session_packet(self.reports,self.paths['a'])['runs'][0]['report_complete'])
        before=set(self.reports.iterdir());c=self.controller();c.start_ready(authorize=self.authorize);self.handles['a'].finish()
        with patch.object(r,'publish_attempt_report',side_effect=OSError('publication failed')):
            receipt=c.poll()[0]
        self.assertEqual(receipt.state,'unverified');self.assertIsNone(receipt.report_path);self.assertEqual(before,set(self.reports.iterdir()))


class BatchSessionTests(unittest.TestCase):
    Handle = BatchControllerTests.Handle
    setUp = BatchControllerTests.setUp

    def session(self, *, workers=1, repeat=False):
        helper = BatchPreviewTests()
        plan = r.load_batch(helper.raw(helper.entry('a'), helper.entry('b'), helper.entry('c', ('a','b'))))
        _, reviews = plan.review(self.paths, workers=workers, parallel_opt_in=workers>1,
                                 isolated_ids=tuple(self.paths) if workers>1 else ())
        def launch(attempt, review, emit):
            h = self.Handle(attempt, review, emit); self.handles[attempt.task_id] = h
            h.finish(); return h
        if repeat:
            (self.reports/'report-20260101-000000-000000.txt').write_text(reviews[0].archive_header('2026-01-01T00:00:00') + '\n@step END\nProcess exit code: 0\nCancelled: False\nFinished: 2026-01-01T00:00:01\n', encoding='utf-8')
        return r.BatchExecutionSession(plan, self.paths, reviews, self.reports, workers=workers, launch=launch)

    def test_session_parallel_and_single_use(self):
        s = self.session(workers=2); snapshots=[]; s.run(snapshots.append)
        self.assertEqual(set(self.handles), {'a','b','c'})
        self.assertEqual(snapshots[-1]['states'], dict.fromkeys(('a','b','c'),'succeeded'))
        self.assertTrue(snapshots[-1]['finished']); self.assertEqual(len(snapshots[-1]['receipts']),3)
        with self.assertRaises(RuntimeError): s.run(snapshots.append)

    def test_stop_before_admission(self):
        s=self.session(); s.stop(); snapshots=[]; s.run(snapshots.append)
        self.assertEqual(self.handles,{})
        self.assertEqual(snapshots[-1]['states'],dict.fromkeys(('a','b','c'),'cancelled'))

    def test_cancel_pending_blocks_dependants(self):
        s=self.session(); s.cancel('a'); snapshots=[]; s.run(snapshots.append)
        self.assertEqual(set(self.handles),{'b'})
        self.assertEqual(snapshots[-1]['states'],{'a':'cancelled','b':'succeeded','c':'blocked'})

    def test_repeat_halts_without_execution(self):
        s=self.session(repeat=True); snapshots=[]
        def publish(snapshot):
            snapshots.append(snapshot)
            if snapshot['halted'] and not snapshot['finished']: s.stop()
        s.run(publish)
        self.assertEqual(self.handles,{})
        self.assertEqual(snapshots[0]['review_faults']['a']['status'],'matched')
        self.assertTrue(snapshots[-1]['finished'])


class SafetyGateTests(unittest.TestCase):
    def test_exact_one_use_and_workspace_binding(self):
        with tempfile.TemporaryDirectory() as td:
            root=pathlib.Path(td);a=root/'a';b=root/'b';a.mkdir();b.mkdir()
            def review(task,script,where):return r.DispatchReview.capture(task,r.prepare(script).encode('utf-8-sig'),where,None,script=script)
            risky=review('a','Restart-Computer',a)
            self.assertFalse(r.SafetyGate().admit(risky))
            gate=r.SafetyGate((risky,))
            self.assertFalse(gate.admit(review('b','Restart-Computer',a)))
            self.assertFalse(gate.admit(review('a','Stop-Computer',a)))
            self.assertFalse(gate.admit(review('a','Restart-Computer',b)))
            self.assertTrue(gate.admit(risky));self.assertFalse(gate.admit(risky))
            self.assertTrue(gate.admit(review('a','Write-Output 1',a)))
    def test_batch_halts_before_unapproved_launch(self):
        with tempfile.TemporaryDirectory() as td:
            root=pathlib.Path(td);reports=root/'reports';reports.mkdir()
            helper=BatchPreviewTests();entry=helper.entry('a');entry['task']['script']='Restart-Computer'
            plan=r.load_batch(helper.raw(entry,helper.entry('b',('a',))))
            paths={'a':root,'b':root};_,reviews=plan.review(paths)
            launches=[];snapshots=[]
            session=r.BatchExecutionSession(plan,paths,reviews,reports,launch=lambda *args:launches.append(args))
            def publish(snap):
                snapshots.append(snap)
                if snap['halted'] and not snap['finished']:session.stop()
            session.run(publish)
            self.assertFalse(launches);self.assertTrue(snapshots[0]['halted']);self.assertIn('a',snapshots[0]['safety_faults']);self.assertTrue(snapshots[-1]['finished'])
            self.assertFalse(list(reports.iterdir()))
    def test_batch_approval_never_inferred_from_packet(self):
        with tempfile.TemporaryDirectory() as td:
            root=pathlib.Path(td);helper=BatchPreviewTests();entry=helper.entry('a');entry['task']['script']='Restart-Computer';plan=r.load_batch(helper.raw(entry));_,reviews=plan.review({'a':root})
            other=r.DispatchReview.capture('a',r.prepare('Stop-Computer').encode('utf-8-sig'),root,None)
            with self.assertRaises(ValueError):r.BatchExecutionSession(plan,{'a':root},reviews,root,safety_approved=(other,))

    def test_batch_exact_approval_can_admit_once(self):
        with tempfile.TemporaryDirectory() as td:
            root=pathlib.Path(td);reports=root/'reports';reports.mkdir()
            helper=BatchPreviewTests();entry=helper.entry('a');entry['task']['script']='Restart-Computer'
            plan=r.load_batch(helper.raw(entry));paths={'a':root};_,reviews=plan.review(paths)
            launches=[]
            def fake(attempt,review,emit):
                launches.append(review);handle=BatchControllerTests.Handle(attempt,review,emit);handle.finish();return handle
            session=r.BatchExecutionSession(plan,paths,reviews,reports,launch=fake,safety_approved=reviews)
            snapshots=[];session.run(snapshots.append)
            self.assertEqual(launches,list(reviews));self.assertEqual(snapshots[-1]['states'],{'a':'succeeded'})
