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

class UserSkillTests(unittest.TestCase):
    def manifest(self, **changes):
        return json.dumps(dict(schema=f.SKILL_SCHEMA,id='disk-audit',revision=1,title='Disk audit',description='Inspect files',instructions='Review scope before running.',task={'schema':'command-relay/task-v1','task_id':'audit-1','script':'Write-Output "COUNT=1"','assertions':{'exit_code':0}}) | changes).encode('utf-8')

    def test_inert_manifest_and_template(self):
        skill=f.load_skill(self.manifest())
        self.assertEqual(skill.filename,'skill-disk-audit--v1.json')
        self.assertEqual(r.load_input(skill.task_bytes)[0],'Write-Output "COUNT=1"')
        self.assertEqual(skill.digest,r.sha(skill.raw))
        obj=json.loads(skill.raw);del obj['task']
        self.assertIsNone(f.load_skill(json.dumps(obj).encode()).task_bytes)

    def test_strict_schema(self):
        for raw in (self.manifest(schema='command-relay/skill-v2'),self.manifest(id='../outside'),self.manifest(id='UPPER'),self.manifest(revision=True),self.manifest(revision=0),self.manifest(permissions={'run':True}),self.manifest(python='import os'),self.manifest(task={'schema':'command-relay/result-v1'}),self.manifest(task={'schema':'command-relay/task-v1','task_id':'x','script':'Write-Output 1'}),self.manifest(title=''),self.manifest(instructions='x'*24001),b'{"id":"a","id":"b"}',b'['*2000,b'x'*(f.SKILL_LIMIT+1)):
            with self.subTest(raw=raw[:90]),self.assertRaises(ValueError):f.load_skill(raw)

    def test_revisions_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as td:
            root=pathlib.Path(td).resolve()/'user';store=f.UserSkillStore(root)
            one=store.install(self.manifest());self.assertEqual(store.install(one.raw),one)
            with self.assertRaises(ValueError):store.install(self.manifest(title='Different'))
            two=store.install(self.manifest(revision=2));self.assertEqual(store.read(one.filename).raw,one.raw)
            skills,errors=store.scan();self.assertEqual([x.revision for x in skills],[2,1]);self.assertFalse(errors)
            self.assertEqual(store.read(two.filename).raw,two.raw)

    def test_discovery_and_invalid_files(self):
        with tempfile.TemporaryDirectory() as td:
            store=f.UserSkillStore(pathlib.Path(td).resolve()/'user');folder=store.ensure()
            (folder/'plugin.py').write_text('raise RuntimeError("must not import")')
            (folder/'unrecognized.json').write_bytes(self.manifest())
            (folder/'skill-other--v1.json').write_bytes(self.manifest())
            (folder/'skill-broken--v1.json').write_bytes(b'{')
            skills,errors=store.scan();self.assertFalse(skills);self.assertEqual(len(errors),3)
            with self.assertRaises(ValueError):store.read('../plugin.py')
            self.assertTrue((folder/'plugin.py').exists())

    def test_folder_bound_and_separate_installation(self):
        with tempfile.TemporaryDirectory() as td:
            from unittest.mock import patch
            root=pathlib.Path(td).resolve();profile=root/'profile';install=root/'portable'
            env='LOCALAPPDATA' if __import__('os').name=='nt' else 'XDG_DATA_HOME'
            with patch.dict(__import__('os').environ,{env:str(profile)}):
                store=f.UserSkillStore();self.assertEqual(store.root,profile/'CommandRelay'/'User')
                one=store.install(self.manifest());install.mkdir();(install/'core.txt').write_text('old')
                (install/'core.txt').write_text('new');self.assertEqual(f.UserSkillStore().read(one.filename).raw,one.raw)
                with patch.object(f,'SKILL_COUNT_LIMIT',1):
                    with self.assertRaises(ValueError):store.install(self.manifest(revision=2))
                    (store.folder/'extra.txt').write_text('x')
                    with self.assertRaises(ValueError):store.scan()
                self.assertFalse((install/'skills').exists())

    def test_special_entries_rejected(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as td:
            store=f.UserSkillStore(pathlib.Path(td).resolve()/'user');folder=store.ensure();(folder/'skill-disk-audit--v1.json').mkdir()
            with self.assertRaises(ValueError):store.read('skill-disk-audit--v1.json')
            with patch.object(pathlib.Path,'lstat',return_value=SimpleNamespace(st_mode=0o100644,st_file_attributes=0x400)):
                with self.assertRaises(ValueError):f._checked_skill_path(folder,directory=False)

class BrowserBridgeTests(unittest.TestCase):
    def test_origin_policy(self):
        for url in ('https://Example.org/chat','http://127.0.0.1:1234/','http://[::1]:8080/','http://localhost:9000/'):
            self.assertTrue(f.browser_origin(url))
        self.assertEqual(f.browser_origin('https://EXAMPLE.org:443/path'),('https','example.org',443))
        for url in ('http://example.org','file:///C:/a','javascript:alert(1)','https://user:password@example.org','https://example.org:0','https://example.org:99999','https://exa mple.org','https://example.org\\x','http://localhost.evil.org'):
            with self.subTest(url=url),self.assertRaises(ValueError):f.browser_origin(url)
    def test_download_origin_name_and_size(self):
        page='https://example.org/chat'
        self.assertTrue(f.browser_download_allowed(page,'blob:https://example.org/id','task.json',-1))
        self.assertTrue(f.browser_download_allowed(page,'https://example.org:443/task','task.json',1000000))
        for url,name,size in [('https://other.org/a','task.json',5),('blob:null/id','task.json',5),('https://example.org/a','../task.json',5),('https://example.org/a','task.exe',5),('https://example.org/a','task.json',1000001),('https://example.org/a','task.json',-2)]:
            self.assertFalse(f.browser_download_allowed(page,url,name,size))
    def test_strict_packets_only(self):
        packet={'schema':'command-relay/task-v1','script':'Write-Output 1','task_id':'browser-test','assertions':{'exit_code':0}}
        raw=json.dumps(packet).encode();self.assertEqual(f.browser_task_packet(raw),'command-relay/task-v1')
        for data in (b'Write-Output 1',b'{}',b'[]',b'{bad',b'{"schema":"command-relay/result-v1"}',b'{"schema":"command-relay/task-v1","script":"a","script":"b"}',json.dumps({**packet,'permissions':True}).encode(),b'x'*1000001):
            with self.subTest(data=data[:90]),self.assertRaises(ValueError):f.browser_task_packet(data)
    def test_draft_script_serializes_text_and_denies_invalid_inputs(self):
        nonce='a'*32;url='https://example.org/chat';text='"\\\n</script>\u2028; location.href="https://other.org"'
        script=f.browser_draft_script(url,nonce,text)
        self.assertTrue(script.endswith('(...'+json.dumps([url,nonce,text],ensure_ascii=True)+')'))
        self.assertIn('HTMLTextAreaElement',script);self.assertIn('target.el !== el',script)
        self.assertIn('location.href === url',script);self.assertIn('el.value === \'\'',script)
        self.assertIn('globalThis.__relayDraftTarget = null',script)
        for args in [('file:///tmp/a',nonce,text),(url,'bad',text),(url,nonce,''),(url,nonce,'x'*(f.BROWSER_DRAFT_LIMIT+1))]:
            with self.assertRaises(ValueError):f.browser_draft_script(*args)
    def test_batch_packet(self):
        packet={'schema':'command-relay/task-v1','script':'Write-Output 1','task_id':'a','assertions':{'exit_code':0}}
        batch={'schema':'command-relay/batch-v1','batch_id':'browser-test','tasks':[{'task':packet,'depends_on':[]}]}
        self.assertEqual(f.browser_task_packet(json.dumps(batch).encode()),'command-relay/batch-v1')
        batch['tasks'][0]['depends_on']=['a']
        with self.assertRaises(ValueError):f.browser_task_packet(json.dumps(batch).encode())

class RuntimeDiagnosticsTests(unittest.TestCase):
    def test_read_only_partial_scan_and_limit(self):
        with tempfile.TemporaryDirectory() as td:
            root=pathlib.Path(td);reports=root/'reports';reports.mkdir()
            name='report-20261126-070000-000001.partial.txt';p=reports/name;p.write_bytes(b'partial')
            (reports/'unrelated.txt').write_bytes(b'untouched')
            snapshot=f.runtime_diagnostics(root,reports)
            self.assertEqual(snapshot['archive']['partial_report_names'],[name])
            self.assertEqual(snapshot['archive']['partial_reports_observed'],1)
            self.assertFalse(snapshot['recovery']['automatic_retry']);self.assertTrue(snapshot['workspace_available'])
            limited=f.runtime_diagnostics(root,reports,max_entries=1);self.assertTrue(limited['archive']['scan_limited'])
            self.assertEqual(p.read_bytes(),b'partial');self.assertEqual(len(list(reports.iterdir())),2)
    def test_missing_archive_not_created(self):
        with tempfile.TemporaryDirectory() as td:
            root=pathlib.Path(td);missing=root/'missing';snapshot=f.runtime_diagnostics(root,missing)
            self.assertEqual(snapshot['archive']['status'],'missing');self.assertFalse(missing.exists())


if __name__=='__main__':unittest.main()


class LocalPlanTests(unittest.TestCase):
    @staticmethod
    def packet(*ops, **extra):
        return json.dumps({'schema': f.PLAN_SCHEMA, 'operations': list(ops), **extra}).encode()

    def test_parse_exact_catalog(self):
        data = self.packet(*f.PLAN_OPERATIONS)
        plan = f.load_local_plan(data)
        self.assertEqual(plan.operations, f.PLAN_OPERATIONS)
        self.assertEqual(plan.digest, hashlib.sha256(data).hexdigest())
        with self.assertRaises(ValueError): r.load_input(data)

    def test_reject_unknown_authority(self):
        for data in (self.packet(), self.packet('disk_space', 'disk_space'),
                     self.packet('powershell'), self.packet({'script': 'exit 0'}),
                     self.packet('disk_space', workspace='elsewhere'),
                     self.packet('disk_space', automatic=True),
                     b'{"schema":"command-relay/plan-v1","operations":["disk_space"],"operations":["project_markers"]}',
                     b' '*8193, b'\xff'):
            with self.subTest(data=data[:100]), self.assertRaises(ValueError): f.load_local_plan(data)

    def test_exact_one_use_and_metadata_only(self):
        import threading
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp); (root/'README.md').write_bytes(b'secret contents')
            (root/'nested').mkdir(); (root/'nested'/'hidden').write_text('hidden')
            reviewed=f.ReviewedLocalPlan(self.packet(*f.PLAN_OPERATIONS), root)
            with patch.object(subprocess, 'run', side_effect=AssertionError('no process')):
                result=reviewed.run(threading.Event())
            self.assertEqual(result['status'],'complete');self.assertEqual(result['operations_completed'],3)
            inventory=result['results'][0]['result'];self.assertEqual(inventory['ordinary_files'],1)
            self.assertEqual(inventory['directories'],1);self.assertEqual(inventory['ordinary_file_bytes'],15)
            self.assertTrue(result['results'][2]['result']['ordinary_marker_present']['README.md'])
            self.assertNotIn('secret contents',json.dumps(result));self.assertNotIn('hidden',json.dumps(result))
            with self.assertRaises(ValueError):reviewed.run(threading.Event())

    def test_cancellation_before_first_operation(self):
        import threading
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            reviewed=f.ReviewedLocalPlan(self.packet('disk_space'),tmp)
            cancel=threading.Event();cancel.set()
            with patch.object(f,'_plan_operation') as operation:
                result=reviewed.run(cancel);operation.assert_not_called()
            self.assertEqual(result['status'],'cancelled');self.assertEqual(result['operations_completed'],0)

    def test_cancel_during_step_stops_remaining(self):
        import threading
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            reviewed=f.ReviewedLocalPlan(self.packet('disk_space','project_markers'),tmp);cancel=threading.Event()
            def operation(*args):cancel.set();return {'free_bytes':1}
            with patch.object(f,'_plan_operation',side_effect=operation) as mocked:
                result=reviewed.run(cancel);mocked.assert_called_once()
            self.assertEqual(result['status'],'cancelled');self.assertEqual(result['operations_completed'],0)

    def test_deadline_and_unknown_stop(self):
        import threading
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            reviewed=f.ReviewedLocalPlan(self.packet('disk_space','project_markers'),tmp)
            with patch('time.monotonic',side_effect=[0,16]),patch.object(f,'_plan_operation') as operation:
                self.assertEqual(reviewed.run(threading.Event())['status'],'time_limit');operation.assert_not_called()
            reviewed=f.ReviewedLocalPlan(self.packet('disk_space','project_markers'),tmp)
            with patch.object(f,'_plan_operation',side_effect=OSError('private path')) as operation:
                result=reviewed.run(threading.Event());operation.assert_called_once()
            self.assertEqual(result['status'],'unknown_or_unavailable');self.assertNotIn('private path',json.dumps(result))

    def test_scope_replacement_stops(self):
        import threading
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp)/'root';root.mkdir()
            reviewed=f.ReviewedLocalPlan(self.packet('disk_space'),root)
            root.rename(root.with_name('old'));root.mkdir()
            with patch.object(f,'_plan_operation') as operation:
                result=reviewed.run(threading.Event());operation.assert_not_called()
            self.assertEqual(result['status'],'scope_changed')

    def test_inventory_limit_stops_remaining(self):
        import threading
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp)
            for i in range(4):(root/str(i)).touch()
            reviewed=f.ReviewedLocalPlan(self.packet('workspace_inventory','disk_space'),root)
            with patch.object(f,'PLAN_ENTRY_LIMIT',2):result=reviewed.run(threading.Event())
            self.assertEqual(result['status'],'entry_limit');self.assertEqual(result['operations_completed'],1)
            self.assertEqual(result['results'][0]['result']['entries_observed'],2)
            self.assertTrue(result['results'][0]['result']['scan_limited'])

    def test_reject_relative_and_link_scope(self):
        with self.assertRaises(ValueError): f.ReviewedLocalPlan(self.packet('disk_space'),'relative')
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp);target=root/'target';target.mkdir();link=root/'link'
            from unittest.mock import patch
            # Avoid requiring Windows Developer Mode or elevated symlink privileges.
            if __import__('os').name=='nt':
                with self.assertRaises(ValueError):f.ReviewedLocalPlan(self.packet('disk_space'),r'\\server\share')
            else:
                link.symlink_to(target,target_is_directory=True)
                with self.assertRaises(ValueError):f.ReviewedLocalPlan(self.packet('disk_space'),link)
