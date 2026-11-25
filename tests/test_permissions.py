# SPDX-License-Identifier: Apache-2.0
import tempfile
import unittest
from pathlib import Path
from command_relay import relay_permissions as p


class PermissionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.a = Path(self.tmp.name) / 'a'; self.a.mkdir()
        self.b = Path(self.tmp.name) / 'b'; self.b.mkdir()
        self.scope = dict(workspace=self.a, repository='Owner/Repo')

    def test_defaults_and_legacy_settings_deny(self):
        for action in p.ACTIONS:
            scope = self.scope if action in p.GIT_ACTIONS else ({'workspace': self.a} if action in p.WORKSPACE_ACTIONS else {})
            self.assertFalse(p.allowed({}, action, **scope))
            self.assertFalse(p.allowed({'legacy_auto_merge': True}, action, **scope))

    def test_exact_scope_and_action(self):
        s = p.with_permission({}, 'squash_merge', enabled=True, **self.scope)
        self.assertTrue(p.allowed(s, 'squash_merge', **self.scope))
        self.assertTrue(p.allowed(s, 'squash_merge', workspace=self.a, repository='owner/repo'))
        self.assertFalse(p.allowed(s, 'squash_merge', workspace=self.b, repository='owner/repo'))
        self.assertFalse(p.allowed(s, 'squash_merge', workspace=self.a, repository='owner/other'))
        self.assertFalse(p.allowed(s, 'git_push', **self.scope))

    def test_revocation_and_no_mutation(self):
        before = {'dense_output': True}
        s = p.with_permission(before, 'squash_merge', enabled=True, **self.scope)
        revoked = p.with_permission(s, 'squash_merge', enabled=False, **self.scope)
        self.assertEqual(before, {'dense_output': True})
        self.assertTrue(p.allowed(s, 'squash_merge', **self.scope))
        self.assertFalse(p.allowed(revoked, 'squash_merge', **self.scope))
        self.assertTrue(revoked['dense_output'])

    def test_malformed_and_future_policy_fail_closed(self):
        s = p.with_permission({}, 'squash_merge', enabled=True, **self.scope)
        record = s[p.KEY]['grants'][0]
        for policy in (None, True, {'version': True, 'grants': [record]}, {'version': 2, 'grants': [record]}, {'version': 1, 'grants': [record, record]}, {'version': 1, 'grants': [record, {'action': 'unknown'}]}, {'version': 1, 'grants': [record], 'other': True}):
            with self.subTest(policy=policy):
                self.assertFalse(p.allowed({p.KEY: policy}, 'squash_merge', **self.scope))
                with self.assertRaises(ValueError):
                    p.with_permission({p.KEY: policy}, 'squash_merge', enabled=True, **self.scope)

    def test_invalid_scope_and_unknown_action(self):
        for scope in ({'workspace': '.', 'repository': 'owner/repo'}, {'workspace': self.a, 'repository': '*/*'}, {'workspace': self.a / 'missing', 'repository': 'owner/repo'}, {'workspace': self.a, 'repository': 'https://github.com/owner/repo'}, {'workspace': self.a}):
            self.assertFalse(p.allowed({}, 'squash_merge', **scope))
        self.assertFalse(p.allowed({}, 'unknown'))
        with self.assertRaises(ValueError):
            p.with_permission({}, 'squash_merge', enabled=1, **self.scope)

    def test_application_and_workspace_scopes_separate(self):
        s = p.with_permission({}, 'update_install', enabled=True)
        s = p.with_permission(s, 'parallel_run', enabled=True, workspace=self.a)
        self.assertTrue(p.allowed(s, 'update_install'))
        self.assertFalse(p.allowed(s, 'update_install', workspace=self.a))
        self.assertTrue(p.allowed(s, 'parallel_run', workspace=self.a))
        self.assertFalse(p.allowed(s, 'parallel_run', workspace=self.b))
        self.assertFalse(p.allowed(s, 'parallel_run', **self.scope))

    def test_deleted_workspace_denied(self):
        s = p.with_permission({}, 'git_push', enabled=True, **self.scope)
        self.a.rmdir()
        self.assertFalse(p.allowed(s, 'git_push', **self.scope))

    def test_grant_is_idempotent(self):
        s = p.with_permission({}, 'pr_create', enabled=True, **self.scope)
        self.assertEqual(s, p.with_permission(s, 'pr_create', enabled=True, **self.scope))
