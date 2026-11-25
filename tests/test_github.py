# SPDX-License-Identifier: Apache-2.0
import copy
import pathlib
import tempfile
import subprocess
import unittest
from unittest.mock import patch, Mock
from command_relay.relay_github import GitHubClient, GitHubError, MergeUnknown, parse_pr

REPO = 'owner/repo'
A, B, C = 'a'*40, 'b'*40, 'c'*40
META = {'full_name': REPO, 'allow_squash_merge': True, 'permissions': {'push': True}}
DATA = {'number': 42, 'title': 'Test', 'baseRefName': 'main', 'headRefName': 'feat/test',
        'baseRefOid': A, 'headRefOid': B, 'state': 'OPEN', 'isDraft': False,
        'isCrossRepository': False, 'mergeable': 'MERGEABLE', 'mergeStateStatus': 'CLEAN',
        'reviewDecision': '', 'statusCheckRollup': [
            {'__typename': 'CheckRun', 'name': 'CI', 'status': 'COMPLETED', 'conclusion': 'SUCCESS'}]}


class GitHubTests(unittest.TestCase):
    def client(self):
        with patch('command_relay.relay_github.shutil.which', return_value='/tools/gh'):
            return GitHubClient(REPO)

    def test_ready_and_legacy_status(self):
        data = copy.deepcopy(DATA)
        data['statusCheckRollup'].append({'__typename': 'StatusContext', 'context': 'legacy', 'state': 'SUCCESS'})
        self.assertTrue(parse_pr(REPO, 42, data, META).ready)

    def test_blocked_states(self):
        for field, value in [('state', 'MERGED'), ('isDraft', True), ('isCrossRepository', True),
                             ('mergeable', 'UNKNOWN'), ('mergeStateStatus', 'BLOCKED'), ('reviewDecision', 'REVIEW_REQUIRED'),
                             ('reviewDecision', None), ('statusCheckRollup', []), ('statusCheckRollup', None)]:
            with self.subTest(field=field, value=value):
                self.assertFalse(parse_pr(REPO, 42, dict(DATA, **{field: value}), META).ready)

    def test_check_failure_pending_unknown(self):
        for state in ('FAILURE', 'CANCELLED', 'ACTION_REQUIRED', 'UNKNOWN', None):
            data = copy.deepcopy(DATA); data['statusCheckRollup'][0]['conclusion'] = state
            self.assertFalse(parse_pr(REPO, 42, data, META).ready)
        data = copy.deepcopy(DATA); data['statusCheckRollup'][0]['status'] = 'IN_PROGRESS'
        self.assertFalse(parse_pr(REPO, 42, data, META).ready)

    def test_permissions_and_repo_identity(self):
        self.assertFalse(parse_pr(REPO, 42, DATA, dict(META, allow_squash_merge=False)).ready)
        self.assertFalse(parse_pr(REPO, 42, DATA, dict(META, permissions={})).ready)
        with self.assertRaises(GitHubError): parse_pr(REPO, 42, DATA, dict(META, full_name='other/repo'))
        with self.assertRaises(GitHubError): parse_pr(REPO, 42, dict(DATA, headRefOid='wrong'), META)

    def test_missing_cli_and_invalid_repo(self):
        with patch('command_relay.relay_github.shutil.which', return_value=None):
            with self.assertRaises(GitHubError): GitHubClient(REPO)
        for repo in ('--help', 'evil.com/a/b', 'owner/..', 'owner/x?y'):
            with self.assertRaises(GitHubError): GitHubClient(repo)

    def test_no_confirmation_no_requests(self):
        client = self.client(); client._api = Mock(); client.inspect = Mock()
        with self.assertRaises(GitHubError): client.squash_merge(parse_pr(REPO, 42, DATA, META))
        client._api.assert_not_called(); client.inspect.assert_not_called()

    def test_stale_head_or_base_or_checks_no_write(self):
        client = self.client(); client._api = Mock()
        reviewed = parse_pr(REPO, 42, DATA, META)
        for changes in ({'headRefOid': C}, {'baseRefOid': C}, {'mergeStateStatus': 'BLOCKED'}):
            client.inspect = Mock(return_value=parse_pr(REPO, 42, dict(DATA, **changes), META))
            with self.assertRaises(GitHubError): client.squash_merge(reviewed, confirmed=True)
        client._api.assert_not_called()

    def test_confirmed_squash_verified_once(self):
        client = self.client(); reviewed = parse_pr(REPO, 42, DATA, META)
        client.inspect = Mock(return_value=reviewed)
        client._api = Mock(side_effect=[{'merged': True, 'sha': C}, {'number': 42, 'merged': True,
                         'merge_commit_sha': C, 'head': {'sha': B}, 'base': {'ref': 'main', 'repo': {'full_name': REPO}}}])
        self.assertEqual(client.squash_merge(reviewed, confirmed=True), C)
        self.assertEqual(client._api.call_count, 2)
        client._api.assert_any_call('/pulls/42/merge', 'PUT', {'sha': B, 'merge_method': 'squash'})
        client._api.assert_any_call('/pulls/42')

    def test_denied_or_lost_response_no_retry(self):
        client = self.client(); reviewed = parse_pr(REPO, 42, DATA, META); client.inspect = Mock(return_value=reviewed)
        for result in (GitHubError('timeout'), {'merged': False}):
            client._api = Mock(side_effect=[result])
            with self.assertRaises(MergeUnknown): client.squash_merge(reviewed, confirmed=True)
            self.assertEqual(client._api.call_count, 1)
        client._api = Mock(side_effect=[{'merged': True, 'sha': C}, {'merged': False}])
        with self.assertRaises(MergeUnknown): client.squash_merge(reviewed, confirmed=True)
        self.assertEqual(client._api.call_count, 2)

    def test_cli_safe_diagnostic(self):
        client = self.client()
        with patch('command_relay.relay_github.subprocess.run', return_value=subprocess.CompletedProcess([], 1, '', 'secret value')) as run:
            with self.assertRaises(GitHubError) as err: client.inspect(42)
            self.assertNotIn('secret value', str(err.exception))
            self.assertFalse(run.call_args.kwargs['shell'])
            self.assertEqual(run.call_args.kwargs['timeout'], 30)
        with patch('command_relay.relay_github.subprocess.run', side_effect=subprocess.TimeoutExpired('gh', 30)):
            with self.assertRaises(GitHubError): client.inspect(42)

    def test_list_open_bounded_and_explicit_repo(self):
        client = self.client(); client._json = Mock(return_value=[{'number': 42, 'title': 'Test'}])
        self.assertEqual(client.list_open(), ((42, 'Test'),))
        client._json.assert_called_once_with('pr', 'list', '--repo', 'github.com/owner/repo', '--state', 'open', '--limit', '100', '--json', 'number,title')
        for invalid in (None, [None], [{'number': 0, 'title': 'Test'}], [{'number': 42, 'title': 'Test'}]*2, [{'number': 42, 'title': 'Test'}]*101):
            client._json.return_value = invalid
            with self.assertRaises(GitHubError): client.list_open()

    def test_workspace_origin_is_explicit_and_never_discloses_credentials(self):
        from command_relay.relay_github import workspace_repo
        for url in ('https://github.com/owner/repo.git', 'git@github.com:owner/repo.git', 'ssh://git@github.com/owner/repo', 'https://github.com/owner/repo/'):
            with patch('command_relay.relay_github.subprocess.run', return_value=subprocess.CompletedProcess([], 0, url+'\n', '')):
                self.assertEqual(workspace_repo('.'), REPO)
        for url in ('https://user:secret@github.com/owner/repo', 'https://evil.example/owner/repo', 'https://github.com/owner/repo\nhttps://github.com/owner/other'):
            with patch('command_relay.relay_github.subprocess.run', return_value=subprocess.CompletedProcess([], 0, url+'\n', '')):
                with self.assertRaises(GitHubError) as err: workspace_repo('.')
                self.assertNotIn('secret', str(err.exception))

    def test_status_packet_masks_nested_check_names_and_title(self):
        from command_relay.relay_github import status_packet
        import json
        secret = 'ghp_' + 'x'*30
        data = copy.deepcopy(DATA); data['title'] = 'token=' + secret
        data['statusCheckRollup'][0]['name'] = 'CI ' + secret
        packet = status_packet(parse_pr(REPO, 42, data, META), '2026-11-25T00:00:00+00:00', merge_sha=C, outcome='verified_merged')
        self.assertEqual(packet['schema'], 'command-relay/github-pr-status-v1')
        self.assertEqual(packet['verified_merge_sha'], C)
        self.assertEqual(packet['merge_outcome'], 'verified_merged')
        self.assertNotIn(secret, json.dumps(packet))
        self.assertEqual(packet['privacy']['status'], 'redacted')


    def automation(self, client, **overrides):
        options = dict(head='feat/test', head_sha=B, base='main', base_sha=A,
                       required_checks=['CI'], confirmed=True, timeout=30, interval=5)
        options.update(overrides)
        with patch.object(client, '_require_automation_merge'):
            return client.wait_and_merge(42, **options)

    def test_automation_requires_authorization_and_valid_policy(self):
        client = self.client(); client.inspect = Mock(); client._squash_merge = Mock()
        for overrides in ({'confirmed': False}, {'required_checks': []}, {'required_checks': ['CI', 'CI']},
                          {'timeout': 0}, {'interval': 0}, {'head_sha': 'bad'}):
            with self.assertRaises(GitHubError): self.automation(client, **overrides)
        client.inspect.assert_not_called(); client._squash_merge.assert_not_called()

    def test_automation_waits_then_merges_once(self):
        client = self.client(); pending = copy.deepcopy(DATA)
        pending['statusCheckRollup'][0]['status'] = 'IN_PROGRESS'
        ready = parse_pr(REPO, 42, DATA, META)
        client.inspect = Mock(side_effect=[parse_pr(REPO, 42, pending, META), ready])
        client._squash_merge = Mock(return_value=C); progress = Mock()
        with patch('command_relay.relay_github.time.sleep') as sleep:
            self.assertEqual(self.automation(client, progress=progress), C)
        sleep.assert_called_once(); client._squash_merge.assert_called_once()
        self.assertEqual(client._squash_merge.call_args.args, (ready,))
        self.assertTrue(client._squash_merge.call_args.kwargs['confirmed'])
        self.assertEqual([call.args for call in progress.call_args_list], [('WAITING_FOR_CI', 0, 1), ('CI_READY', 1, 1)])

    def test_automation_stops_on_changed_identity_or_closed_pr(self):
        client = self.client(); client._squash_merge = Mock()
        for changes in ({'headRefOid': C}, {'baseRefOid': C}, {'headRefName': 'other'},
                        {'baseRefName': 'other'}, {'state': 'MERGED'}, {'isDraft': True},
                        {'isCrossRepository': True}, {'reviewDecision': 'REVIEW_REQUIRED'}):
            client.inspect = Mock(return_value=parse_pr(REPO, 42, dict(DATA, **changes), META))
            with self.assertRaises(GitHubError): self.automation(client)
        client._squash_merge.assert_not_called()

    def test_automation_stops_on_failed_or_skipped_required_check(self):
        client = self.client(); client._squash_merge = Mock()
        for state in ('FAILURE', 'CANCELLED', 'ACTION_REQUIRED', 'NEUTRAL', 'SKIPPED'):
            data = copy.deepcopy(DATA); data['statusCheckRollup'][0]['conclusion'] = state
            client.inspect = Mock(return_value=parse_pr(REPO, 42, data, META))
            with self.assertRaises(GitHubError): self.automation(client)
        client._squash_merge.assert_not_called()

    def test_automation_missing_expected_check_never_merges(self):
        client = self.client(); client.inspect = Mock(return_value=parse_pr(REPO, 42, DATA, META)); client._squash_merge = Mock()
        with patch('command_relay.relay_github.time.monotonic', side_effect=[0, 0, 30, 30]):
            with self.assertRaisesRegex(GitHubError, 'deadline'): self.automation(client, required_checks=['not present'])
        client._squash_merge.assert_not_called()

    def test_automation_deadline_even_if_ready_after_poll(self):
        client = self.client(); client.inspect = Mock(return_value=parse_pr(REPO, 42, DATA, META)); client._squash_merge = Mock()
        with patch('command_relay.relay_github.time.monotonic', side_effect=[0, 0, 31, 31]):
            with self.assertRaisesRegex(GitHubError, 'deadline'): self.automation(client)
        client._squash_merge.assert_not_called()

    def test_automation_never_retries_unknown_merge(self):
        client = self.client(); client.inspect = Mock(return_value=parse_pr(REPO, 42, DATA, META))
        client._squash_merge = Mock(side_effect=MergeUnknown('unknown'))
        with self.assertRaises(MergeUnknown): self.automation(client)
        client.inspect.assert_called_once(); client._squash_merge.assert_called_once()


    def test_read_only_wait_without_opt_in(self):
        client = self.client(); ready = parse_pr(REPO, 42, DATA, META)
        client.inspect = Mock(return_value=ready); client._api = Mock()
        self.assertEqual(client.wait_for_ci(42, head='feat/test', head_sha=B, base='main',
                                           base_sha=A, required_checks=['CI']), ready)
        client._api.assert_not_called()

    def test_automatic_merge_denied_without_scoped_permission(self):
        client = self.client(); client.inspect = Mock(); client._api = Mock()
        with tempfile.TemporaryDirectory() as d, patch('command_relay.relay_core.SETTINGS', pathlib.Path(d)/'missing.json'):
            with self.assertRaisesRegex(GitHubError, 'disabled'):
                client.wait_and_merge(42, head='feat/test', head_sha=B, base='main', base_sha=A,
                                      required_checks=['CI'], confirmed=True, workspace=d)
        client.inspect.assert_not_called(); client._api.assert_not_called()

    def test_automatic_merge_scoped_grant_and_revocation_before_put(self):
        import json
        from command_relay.relay_permissions import with_permission
        client = self.client(); ready = parse_pr(REPO, 42, DATA, META)
        client._api = Mock(); options = dict(head='feat/test', head_sha=B, base='main', base_sha=A,
                                             required_checks=['CI'], confirmed=True)
        with tempfile.TemporaryDirectory() as d:
            settings = pathlib.Path(d)/'settings.json'
            grant = with_permission({}, 'squash_merge', enabled=True, workspace=d, repository=REPO)
            settings.write_text(json.dumps(grant), encoding='utf-8')
            with patch('command_relay.relay_core.SETTINGS', settings), patch('command_relay.relay_github.workspace_repo', return_value=REPO):
                def inspect(number):
                    if client.inspect.call_count == 2:
                        settings.write_text('{}', encoding='utf-8')
                    return ready
                client.inspect = Mock(side_effect=inspect)
                with self.assertRaisesRegex(GitHubError, 'disabled'):
                    client.wait_and_merge(42, workspace=d, **options)
                self.assertEqual(client.inspect.call_count, 2)
                client._api.assert_not_called()
                settings.write_text(json.dumps(grant), encoding='utf-8')
                client.inspect = Mock(return_value=ready)
                client._api = Mock(side_effect=[{'merged': True, 'sha': C}, {'number': 42, 'merged': True,
                    'merge_commit_sha': C, 'head': {'sha': B}, 'base': {'ref': 'main', 'repo': {'full_name': REPO}}}])
                self.assertEqual(client.wait_and_merge(42, workspace=d, **options), C)
                self.assertEqual(client._api.call_count, 2)

    def test_automatic_merge_wrong_origin_denied(self):
        import json
        from command_relay.relay_permissions import with_permission
        client = self.client(); client.inspect = Mock(); client._api = Mock()
        with tempfile.TemporaryDirectory() as d:
            settings = pathlib.Path(d)/'settings.json'
            settings.write_text(json.dumps(with_permission({}, 'squash_merge', enabled=True,
                                workspace=d, repository=REPO)), encoding='utf-8')
            with patch('command_relay.relay_core.SETTINGS', settings), patch('command_relay.relay_github.workspace_repo', return_value='other/repo'):
                with self.assertRaisesRegex(GitHubError, 'origin'):
                    client.wait_and_merge(42, head='feat/test', head_sha=B, base='main', base_sha=A,
                                          required_checks=['CI'], confirmed=True, workspace=d)
        client.inspect.assert_not_called(); client._api.assert_not_called()
