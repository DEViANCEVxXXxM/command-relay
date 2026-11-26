# SPDX-License-Identifier: Apache-2.0
import json, unittest
from unittest.mock import patch
from command_relay.relay_privacy import inspect_script, protect_packet, protect_text, MASK
from command_relay.relay_core import result_packet, prepare, sha

class PrivacyTests(unittest.TestCase):
    def test_smoke_unchanged(self):
        text='COUNT=15\nRELAY_PASS=True\n{"Passed":3,"Failed":0}\n'
        packet={'output':text,'assertions':{'status':'PASS','checks':[{'key':'Failed','last':0}]},'report_sha256_utf8':'a'*64}
        out=protect_packet(packet,text)
        self.assertEqual(out['privacy']['status'],'no_matches')
        self.assertEqual(out['output'],text)
        self.assertEqual(out['assertions'],packet['assertions'])
    def test_assignments_and_aliases(self):
        value='dummy-not-a-real-password'
        raw=f'PASSWORD={value}\nCopied: {value}\n{{"api_key":"fake-secret-value-123"}}\n'
        out=protect_packet({'output':raw,'comparison':{'before':value},'evidence':{'examples':[value]}},raw)
        encoded=json.dumps(out)
        self.assertNotIn(value,encoded);self.assertNotIn('fake-secret-value-123',encoded)
        self.assertIn('PASSWORD='+MASK,out['output']);self.assertEqual(out['privacy']['status'],'redacted')
    def test_secret_metric(self):
        raw='API_KEY=fixture-dummy-key\n'
        pkt={'output':raw,'assertions':{'status':'PASS','checks':[{'key':'API_KEY','equals':'fixture-dummy-key','last':'fixture-dummy-key','status':'PASS'}]},'comparison':{'metrics':[{'key':'API_KEY','before':'older-dummy-value','after':'fixture-dummy-key'}]}}
        out=protect_packet(pkt,raw);encoded=json.dumps(out)
        self.assertNotIn('fixture-dummy-key',encoded);self.assertNotIn('older-dummy-value',encoded)
        self.assertEqual(out['assertions']['status'],'PASS')
    def test_headers_url_key(self):
        raw='Authorization: Bearer demo-placeholder-abc\nCookie: a=fakecookie; b=fakeother\nhttps://dummyuser:dummypass@example.invalid/path\n-----BEGIN PRIVATE KEY-----\nfictional-key-material\n-----END PRIVATE KEY-----\nCOUNT=1\n'
        out,n=protect_text(raw)
        for v in ('demo-placeholder-abc','fakecookie','fakeother','dummypass','fictional-key-material'):self.assertNotIn(v,out)
        self.assertIn('COUNT=1',out);self.assertGreaterEqual(n,4)
    def test_token_shape(self):
        fake='ghp_'+'X'*36
        out,n=protect_text('Example '+fake)
        self.assertNotIn(fake,out);self.assertEqual(n,1)
    def test_original_hash_and_verdict(self):
        text='COMMAND RELAY REPORT\nStarted: 2026-11-25T07:00:00\nCommand file: test.json\n\n@step 01 — Check\nPASSWORD=fictional-pass-1234\n@step END\nProcess exit code: 0\nCancelled: False\nFinished: 2026-11-25T07:00:01\n'
        packet=result_packet(text,'test.txt');out=protect_packet(packet,text)
        self.assertEqual(out['report_sha256_utf8'],sha(text.encode()))
        self.assertEqual(out['original_lines'],packet['original_lines']);self.assertEqual(out['view'],'full');self.assertNotIn('fictional-pass-1234',out['output']);self.assertIn('fictional-pass-1234',packet['output'])
    def test_omitted_line_alias(self):
        secret='demo-example-password'
        out=protect_packet({'output':'Artifact name '+secret},'PASSWORD='+secret+'\n')
        self.assertNotIn(secret,out['output'])
    def test_session_tool_nested(self):
        pkt={'runs':[{'checks':[{'key':'TOKEN','equals':'not-real-secret-1','last':'not-real-secret-1'}]}],'fields':{'stage / PASSWORD':{'last':'not-real-secret-2'}}}
        out=json.dumps(protect_packet(pkt));self.assertNotIn('not-real-secret-1',out);self.assertNotIn('not-real-secret-2',out)
    def test_scan_limit(self):
        with patch('command_relay.relay_privacy.MAX_SOURCE',1):
            out=protect_packet({'output':'PASSWORD=abc123456'},'long input')
            self.assertTrue(out['privacy']['source_scan_limited']);self.assertNotIn('abc123456',out['output'])
    def test_quoted_values(self):
        text='{"password":"fictional secret with spaces"}\nPASSWORD=\'fictional other value\'\n'
        out,n=protect_text(text);self.assertNotIn('fictional',out);self.assertEqual(json.loads(out.splitlines()[0])['password'],MASK)
    def test_workflow_reference_standalone(self):
        for line in ('    GH_TOKEN: ${{ github.token }}',
                     'API_KEY: "${{ secrets.EXAMPLE_KEY }}"',
                     "PASSWORD: '${{secrets.EXAMPLE_PASSWORD}}'", 'token: ${{github.token}}'):
            for ending in ('', '\n', '\r\n'):
                raw=line+ending
                self.assertEqual(protect_text(raw), (raw, 0))
                out=protect_packet({'output':raw},raw)
                self.assertEqual(out['output'],raw)
                self.assertEqual(out['privacy']['status'],'no_matches')
    def test_workflow_reference_does_not_exempt_mixed_values(self):
        for value in ('"${{ github.token }} literal-fixture-secret"',
                      '"${{ secrets.EXAMPLE || \x27literal-fixture-secret\x27 }}"',
                      '"literal-fixture-secret ${{ github.token }}"'):
            raw='GH_TOKEN: '+value
            out,n=protect_text(raw)
            self.assertNotIn('literal-fixture-secret',out)
            self.assertGreater(n,0)
        for raw in ('GH_TOKEN: ${{ github.token }} # comment',
                    'GH_TOKEN: ${{ github.token }}extra', 'TOKEN=${{ github.token }}',
                    'GH_TOKEN: ${{ vars.EXAMPLE }}'):
            self.assertGreater(protect_text(raw)[1],0)
    def test_workflow_reference_other_masking_rules_remain_active(self):
        token='ghp_'+'X'*36
        raw='GH_TOKEN: ${{ secrets.'+token+' }}\nAuthorization: ${{ github.token }}\n'
        out,n=protect_text(raw)
        self.assertNotIn(token,out)
        self.assertIn('Authorization: '+MASK,out)
        self.assertGreaterEqual(n,2)
    def test_workflow_reference_real_assignment_and_alias(self):
        secret='fixture-real-value-123'
        reference='GH_TOKEN: ${{ github.token }}'
        source=reference+'\nGH_TOKEN: '+secret+'\n'
        out=protect_packet({'output':reference+'\nCopied '+secret},source)
        self.assertIn(reference,out['output'])
        self.assertNotIn(secret,out['output'])
    def test_workflow_reference_structured_secret_not_exempt(self):
        reference='${{ github.token }}'
        out=protect_packet({'token':reference,'checks':[{'key':'API_KEY','last':reference}]})
        self.assertEqual(out['token'],MASK)
        self.assertEqual(out['checks'][0]['last'],MASK)
    def test_already_masked(self):
        self.assertEqual(protect_text('PASSWORD=[REDACTED]')[0],'PASSWORD=[REDACTED]')
    def test_no_value_disclosure_in_warning(self):
        result=inspect_script('Remove-Item -Recurse -LiteralPath "dummy-secret-path"')
        self.assertEqual(result['level'],'high');self.assertNotIn('dummy-secret-path',json.dumps(result))
    def test_inspector_ordinary(self):
        self.assertEqual(inspect_script(prepare('@step Test\nWrite-Output "COUNT=15"\nexit 0'))['level'],'none')
        self.assertEqual(inspect_script('# Remove-Item -Recurse\nGet-ChildItem')['level'],'none')
    def test_inspector_effects(self):
        self.assertEqual(inspect_script('git ls-remote https://example.invalid')['level'],'review')
        self.assertEqual(inspect_script('Set-Content -LiteralPath a -Value b')['level'],'review')
        self.assertEqual(inspect_script('Remove-Item -LiteralPath temp.txt')['level'],'review')
    def test_inspector_high(self):
        for script in ('git reset --hard','Remove-Item -Recurse path','Invoke-Expression $text','Set-ExecutionPolicy Restricted'):
            self.assertEqual(inspect_script(script)['level'],'high',script)
    def test_inspector_indirect_git(self):
        for script, label in (
            ("run('git', 'push', 'origin', BRANCH)", 'Network or remote Git operation'),
            ('subprocess.run(["git", "commit", "-m", title])', 'File or repository changes'),
            ("git('tag', '-a', tag)", 'File or repository changes'),
            ('git tag -a v4.0.3', 'File or repository changes'),
        ):
            result=inspect_script(script)
            self.assertEqual(result['level'],'review',script)
            self.assertIn(label,[m['label'] for m in result['matches']])
    def test_inspector_indirect_high(self):
        for script in ("run('git', 'reset', '--hard')", 'subprocess.run(["git", "push", "--force-with-lease"])', "git('clean', '-fd')"):
            self.assertEqual(inspect_script(script)['level'],'high',script)
    def test_inspector_github_cli(self):
        for script in ('gh pr create --title title', "gh('api', endpoint)", "run('gh.exe', 'issue', 'create')"):
            result=inspect_script(script)
            self.assertEqual(result['level'],'review',script)
            self.assertIn('GitHub CLI operation',[m['label'] for m in result['matches']])
    def test_inspector_external_process(self):
        for script in ('subprocess.run(args, check=True)', 'subprocess.check_output(\n    args)', 'os.system(command)', 'Start-Process -FilePath tool'):
            self.assertEqual(inspect_script(script)['level'],'review',script)
        self.assertEqual(inspect_script('git status\ngh --version\n# subprocess.run(args)')['level'],'none')
    def test_inspector_grouped_and_bounded(self):
        result=inspect_script("git push origin main\nrun('git', 'push', branch)\n"*8)
        matches=[m for m in result['matches'] if m['label']=='Network or remote Git operation']
        self.assertEqual(len(matches),1)
        self.assertEqual(matches[0]['lines'],[1,2,3,4,5])
        self.assertNotIn('origin main',json.dumps(result))
    def test_inspector_bound(self):
        with patch('command_relay.relay_privacy.MAX_SCRIPT',1):
            self.assertTrue(inspect_script('abcdef')['scan_limited']);self.assertEqual(inspect_script('abcdef')['level'],'review')


class SafetyInspectionTests(unittest.TestCase):
    def test_extended_risk_and_no_disclosure(self):
        from command_relay.relay_privacy import safety_inspect
        for command in ('Restart-Computer', 'Remove-Partition', 'Set-Acl', 'reg.exe delete sample', 'Invoke-Command $x', 'shutil.rmtree(dummy)'):
            result=safety_inspect(command+' # confidential-fixture')
            self.assertEqual(result['level'],'high',command)
            self.assertNotIn('confidential-fixture',json.dumps(result))
        self.assertEqual(safety_inspect('Write-Output 1')['level'],'none')
    def test_incomplete_scan_pauses(self):
        from command_relay.relay_privacy import safety_inspect
        with patch('command_relay.relay_privacy.MAX_SCRIPT',1):
            result=safety_inspect('Write-Output 1')
        self.assertEqual(result['level'],'high');self.assertTrue(result['scan_limited'])
        self.assertIn('Incomplete safety inspection',[m['label'] for m in result['matches']])
