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
    def test_inspector_bound(self):
        with patch('command_relay.relay_privacy.MAX_SCRIPT',1):
            self.assertTrue(inspect_script('abcdef')['scan_limited']);self.assertEqual(inspect_script('abcdef')['level'],'review')
