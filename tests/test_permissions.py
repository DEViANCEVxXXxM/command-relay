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

    def test_fresh_settings_reject_duplicate_keys_and_invalid_data(self):
        from unittest.mock import patch
        path = Path(self.tmp.name) / 'automation-permissions.json'
        with patch('command_relay.relay_permissions.policy_path', return_value=path):
            self.assertEqual(p.read_automation_settings(), {})
            for content in ('{"automation_permissions":{},"automation_permissions":{}}',
                            '{"a":{"x":1,"x":2}}', 'not-json', '[]', ' ' * 1_000_001):
                path.write_text(content, encoding='utf-8')
                self.assertEqual(p.read_automation_settings(), {})
            path.write_text('{"automation_permissions":{"version":1,"grants":[]}}', encoding='utf-8')
            self.assertEqual(p.read_automation_settings(), {p.KEY: {'version': 1, 'grants': []}})

    def test_policy_isolated_from_legacy_preferences(self):
        import json
        from unittest.mock import patch
        legacy = Path(self.tmp.name) / 'settings.json'
        legacy.write_text(json.dumps(p.with_permission({}, 'squash_merge', enabled=True, **self.scope)), encoding='utf-8')
        with patch('command_relay.relay_core.SETTINGS', legacy):
            self.assertFalse(p.allowed(p.read_automation_settings(), 'squash_merge', **self.scope))
            self.assertEqual(p.policy_snapshot(), {})

    def test_save_revoke_and_stale_snapshot(self):
        from unittest.mock import patch
        path = Path(self.tmp.name) / 'automation-permissions.json'
        with patch.object(p, 'policy_path', return_value=path), patch('command_relay.relay_github.workspace_repo', return_value='owner/repo'):
            grant = p.save_merge_permission({}, enabled=True, **self.scope)
            self.assertEqual(p.policy_snapshot(), grant)
            self.assertTrue(p.allowed(grant, 'squash_merge', **self.scope))
            with self.assertRaises(ValueError):
                p.revoke_all_permissions({})
            revoked = p.save_merge_permission(grant, enabled=False, **self.scope)
            self.assertFalse(p.allowed(p.policy_snapshot(), 'squash_merge', **self.scope))
            with self.assertRaises(ValueError):
                p.save_merge_permission(grant, enabled=True, **self.scope)
            self.assertEqual(p.policy_snapshot(), revoked)

    def test_changed_origin_and_invalid_policy_not_overwritten(self):
        from unittest.mock import patch
        path = Path(self.tmp.name) / 'automation-permissions.json'
        with patch.object(p, 'policy_path', return_value=path), patch('command_relay.relay_github.workspace_repo', return_value='other/repo'):
            with self.assertRaises(ValueError):
                p.save_merge_permission({}, enabled=True, **self.scope)
            self.assertFalse(path.exists())
            path.write_text('invalid', encoding='utf-8')
            with self.assertRaises(ValueError):
                p.revoke_all_permissions({})
            self.assertEqual(path.read_text(), 'invalid')
            self.assertEqual(p.read_automation_settings(), {})

    def test_writer_conflict_and_revoke_all(self):
        from unittest.mock import patch
        path = Path(self.tmp.name) / 'automation-permissions.json'
        lock = path.with_name('.automation-permissions.lock')
        with patch.object(p, 'policy_path', return_value=path), patch('command_relay.relay_github.workspace_repo', return_value='owner/repo'):
            lock.touch()
            with self.assertRaises(FileExistsError):
                p.save_merge_permission({}, enabled=True, **self.scope)
            self.assertTrue(lock.exists())
            lock.unlink()
            grant = p.save_merge_permission({}, enabled=True, **self.scope)
            lock.touch()
            self.assertFalse(p.allowed(p.read_automation_settings(), 'squash_merge', **self.scope))
            lock.unlink()
            p.revoke_all_permissions(grant)
            self.assertFalse(p.allowed(p.policy_snapshot(), 'squash_merge', **self.scope))
            self.assertFalse(lock.exists())

    def test_audit_records_grant_revoke_and_revoke_all(self):
        from unittest.mock import patch
        path = Path(self.tmp.name) / 'automation-permissions.json'
        with patch.object(p, 'policy_path', return_value=path), patch('command_relay.relay_github.workspace_repo', return_value='owner/repo'):
            grant = p.save_merge_permission({}, enabled=True, **self.scope)
            self.assertEqual(p.policy_snapshot(), grant)
            event = p.audit_history(grant)['events'][0]
            self.assertEqual((event['operation'], event['repository'], event['count']), ('grant', 'owner/repo', 1))
            self.assertNotIn(str(self.a), p.audit_text(grant))
            self.assertEqual(p.save_merge_permission(grant, enabled=True, **self.scope), grant)
            revoked = p.save_merge_permission(grant, enabled=False, **self.scope)
            again = p.save_merge_permission(revoked, enabled=True, **self.scope)
            final = p.revoke_all_permissions(again)
            self.assertEqual([e['operation'] for e in p.audit_history(final)['events']], ['grant', 'revoke', 'grant', 'revoke_all'])
            self.assertEqual(p.revoke_all_permissions(final), final)
            self.assertFalse(p.allowed(p.read_automation_settings(), 'squash_merge', **self.scope))

    def test_audit_atomic_failure_keeps_previous_grant_and_history(self):
        from unittest.mock import patch
        path = Path(self.tmp.name) / 'automation-permissions.json'
        with patch.object(p, 'policy_path', return_value=path), patch('command_relay.relay_github.workspace_repo', return_value='owner/repo'):
            grant = p.save_merge_permission({}, enabled=True, **self.scope)
            before = path.read_bytes()
            with patch('command_relay.relay_core.atomic_text', side_effect=OSError('write failed')):
                with self.assertRaises(OSError):
                    p.revoke_all_permissions(grant)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(p.policy_snapshot(), grant)
            self.assertFalse(path.with_name('.automation-permissions.lock').exists())

    def test_audit_bounded_and_legacy_policy(self):
        import json
        from unittest.mock import patch
        path = Path(self.tmp.name) / 'automation-permissions.json'
        legacy = p.with_permission({}, 'squash_merge', enabled=True, **self.scope)
        path.write_text(json.dumps(legacy), encoding='utf-8')
        with patch.object(p, 'policy_path', return_value=path), patch('command_relay.relay_github.workspace_repo', return_value='owner/repo'), patch.object(p, 'MAX_AUDIT_EVENTS', 2):
            self.assertEqual(p.audit_history(p.policy_snapshot())['events'], [])
            self.assertTrue(p.allowed(p.read_automation_settings(), 'squash_merge', **self.scope))
            current = legacy
            for enabled in (False, True, False):
                current = p.save_merge_permission(current, enabled=enabled, **self.scope)
            history = p.audit_history(p.policy_snapshot())
            self.assertEqual(history['dropped'], 1)
            self.assertEqual([e['operation'] for e in history['events']], ['grant', 'revoke'])

    def test_invalid_audit_fails_closed_without_rewriting(self):
        import json
        from unittest.mock import patch
        path = Path(self.tmp.name) / 'automation-permissions.json'
        with patch.object(p, 'policy_path', return_value=path), patch('command_relay.relay_github.workspace_repo', return_value='owner/repo'):
            grant = p.save_merge_permission({}, enabled=True, **self.scope)
            grant[p.AUDIT_KEY]['events'][0]['count'] = True
            path.write_text(json.dumps(grant), encoding='utf-8')
            before = path.read_bytes()
            self.assertFalse(p.allowed(p.read_automation_settings(), 'squash_merge', **self.scope))
            with self.assertRaises(ValueError):
                p.revoke_all_permissions(grant)
            self.assertEqual(path.read_bytes(), before)


class UpdatePermissionTests(unittest.TestCase):
    def setUp(self):
        from unittest.mock import patch
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.path = self.root / 'automation-permissions.json'
        (self.root / 'Start.pyw').touch()
        scope = patch.object(p, 'policy_path', return_value=self.path)
        scope.start(); self.addCleanup(scope.stop)

    def save(self, snapshot, enabled):
        return p.save_update_permission(snapshot, root=self.root, enabled=enabled)

    def test_default_grant_revoke_and_updater_reader(self):
        from command_relay import relay_updates as u
        with self.assertRaises(u.UpdateError): u._require_install_permission(self.root)
        grant = self.save({}, True)
        u._require_install_permission(self.root)
        self.assertEqual(p.policy_snapshot(), grant)
        self.assertEqual(self.save(grant, True), grant)
        revoked = self.save(grant, False)
        self.assertFalse(p.allowed(revoked, 'update_install'))
        with self.assertRaises(u.UpdateError): u._require_install_permission(self.root)
        self.assertEqual([e['operation'] for e in p.audit_history(revoked)['events']],
                         ['grant_update_install', 'revoke_update_install'])
        self.assertIn('this application installation', p.audit_text(revoked))

    def test_preserves_merge_grant_and_revoke_all(self):
        from unittest.mock import patch
        with patch('command_relay.relay_github.workspace_repo', return_value='owner/repo'):
            merge = p.save_merge_permission({}, workspace=self.root, repository='owner/repo', enabled=True)
        both = self.save(merge, True)
        self.assertTrue(p.allowed(both, 'squash_merge', workspace=self.root, repository='owner/repo'))
        self.assertTrue(p.allowed(both, 'update_install'))
        self.assertFalse(p.allowed(p.revoke_all_permissions(both), 'update_install'))

    def test_stale_and_locked_policy_denied(self):
        grant = self.save({}, True)
        before = self.path.read_bytes()
        with self.assertRaises(ValueError): self.save({}, False)
        lock = self.path.with_name('.automation-permissions.lock'); lock.touch()
        with self.assertRaises(FileExistsError): self.save(grant, False)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertTrue(lock.exists())

    def test_wrong_root_checkout_and_pending_denied(self):
        from command_relay import relay_updates as u
        with self.assertRaises(ValueError): p.save_update_permission({}, root=self.root.parent, enabled=True)
        git = self.root / '.git'; git.touch()
        with self.assertRaises(ValueError): self.save({}, True)
        git.unlink()
        (self.root / u.UPDATE_TRANSACTION_NAME).mkdir()
        with self.assertRaises(u.RecoveryRequired): self.save({}, True)
        self.assertFalse(self.path.exists())

    def test_linked_policy_denied(self):
        from command_relay import relay_updates as u
        import os
        other = self.root / 'other.json'; other.write_text('{}')
        try: os.link(other, self.path)
        except OSError as exc: self.skipTest(str(exc))
        with self.assertRaises(u.UpdateError): self.save({}, True)
        self.assertEqual(other.read_text(), '{}')

    def test_atomic_failure_and_invalid_audit(self):
        from unittest.mock import patch
        import json
        grant = self.save({}, True); before = self.path.read_bytes()
        with patch('command_relay.relay_core.atomic_text', side_effect=OSError('write failed')):
            with self.assertRaises(OSError): self.save(grant, False)
        self.assertEqual(self.path.read_bytes(), before)
        grant[p.AUDIT_KEY]['events'][0]['count'] = 2
        self.path.write_text(json.dumps(grant), encoding='utf-8')
        before = self.path.read_bytes()
        with self.assertRaises(ValueError): self.save(grant, False)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse(p.allowed(p.read_automation_settings(), 'update_install'))
