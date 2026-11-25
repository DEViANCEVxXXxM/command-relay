# SPDX-License-Identifier: Apache-2.0
import copy
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
