# SPDX-License-Identifier: Apache-2.0
"""Fail-closed policy data for future application-owned automation.

Not a sandbox or enforcement by itself. Callers must re-read policy immediately
before a built-in write, verify the actual target, and separately confirm intent.
Policy storage is isolated from ordinary workbench settings.
"""
import json
import os
from pathlib import Path
import re

KEY = 'automation_permissions'
GIT_ACTIONS = frozenset({'git_push', 'pr_create', 'squash_merge', 'branch_delete'})
WORKSPACE_ACTIONS = frozenset({'unattended_run', 'parallel_run'})
APPLICATION_ACTIONS = frozenset({'update_install'})
ACTIONS = GIT_ACTIONS | WORKSPACE_ACTIONS | APPLICATION_ACTIONS
MAX_GRANTS = 256
_REPO = re.compile(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}', re.ASCII)


def _repository(value):
    if not isinstance(value, str) or not _REPO.fullmatch(value) or value.split('/')[1] in {'.', '..'}:
        raise ValueError('Expected exact GitHub owner/repository')
    return value.lower()


def _workspace(value):
    if not isinstance(value, (str, os.PathLike)) or not os.path.isabs(value):
        raise ValueError('Expected absolute workspace path')
    path = Path(value).resolve(strict=True)
    if not path.is_dir():
        raise ValueError('Expected existing workspace directory')
    return os.path.normcase(str(path))


def _scope(action, workspace, repository):
    if not isinstance(action, str) or action not in ACTIONS:
        raise ValueError('Unknown automation action')
    if action in APPLICATION_ACTIONS:
        if workspace is not None or repository is not None:
            raise ValueError('Application permission has no workspace or repository')
        return (action, None, None)
    if action in WORKSPACE_ACTIONS and repository is not None:
        raise ValueError('Workspace-only action has no repository')
    return (action, _workspace(workspace), _repository(repository) if action in GIT_ACTIONS else None)


def _grants(settings):
    if not isinstance(settings, dict):
        raise ValueError('Invalid settings')
    policy = settings.get(KEY, {'version': 1, 'grants': []})
    if (not isinstance(policy, dict) or set(policy) != {'version', 'grants'}
            or type(policy['version']) is not int or policy['version'] != 1
            or not isinstance(policy['grants'], list) or len(policy['grants']) > MAX_GRANTS):
        raise ValueError('Invalid automation policy')
    grants = set()
    for item in policy['grants']:
        if not isinstance(item, dict) or set(item) != {'action', 'workspace', 'repository'}:
            raise ValueError('Invalid automation grant')
        a, w, r = item['action'], item['workspace'], item['repository']
        if not isinstance(a, str) or a not in ACTIONS:
            raise ValueError('Unknown automation action')
        if a in APPLICATION_ACTIONS:
            if w is not None or r is not None:
                raise ValueError('Invalid application scope')
        else:
            if (not isinstance(w, str) or not w or '\x00' in w or not os.path.isabs(w)
                    or w != os.path.normcase(os.path.normpath(w))):
                raise ValueError('Invalid workspace scope')
            if a in GIT_ACTIONS:
                if _repository(r) != r:
                    raise ValueError('Invalid repository scope')
            elif r is not None:
                raise ValueError('Invalid workspace-only scope')
        grant = (a, w, r)
        if grant in grants:
            raise ValueError('Duplicate automation grant')
        grants.add(grant)
    return grants


def allowed(settings, action, *, workspace=None, repository=None):
    """Return False on missing, unknown, malformed or unresolvable policy/scope."""
    try:
        return _scope(action, workspace, repository) in _grants(settings)
    except (ValueError, TypeError, OSError, RuntimeError):
        return False


def with_permission(settings, action, *, enabled, workspace=None, repository=None):
    """Return a new settings object after explicit opt-in/revocation; never persist.

    Invalid policy must be reconciled explicitly, not silently migrated or replaced.
    UI confirmation, audit, persistence and runtime enforcement are separate concerns.
    """
    if type(enabled) is not bool:
        raise ValueError('Permission choice must be a boolean')
    grants = _grants(settings)
    scope = _scope(action, workspace, repository)
    if enabled:
        grants.add(scope)
    else:
        grants.discard(scope)
    if len(grants) > MAX_GRANTS:
        raise ValueError('Automation permission limit reached')
    records = [{'action': a, 'workspace': w, 'repository': r}
               for a, w, r in sorted(grants, key=lambda g: tuple(v or '' for v in g))]
    return {**settings, KEY: {'version': 1, 'grants': records}}


def policy_path():
    from .relay_core import SETTINGS
    return SETTINGS.with_name('automation-permissions.json')


def policy_snapshot():
    """Strict read for settings UI; a missing file is an empty policy."""
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate policy key')
            result[key] = value
        return result

    try:
        with policy_path().open('r', encoding='utf-8') as stream:
            text = stream.read(1_000_001)
    except FileNotFoundError:
        return {}
    if len(text) > 1_000_000:
        raise ValueError('Policy file too large')
    value = json.loads(text, object_pairs_hook=unique_pairs)
    if not isinstance(value, dict) or set(value) - {KEY}:
        raise ValueError('Invalid policy file')
    _grants(value)
    return value


def read_automation_settings():
    """Fresh isolated policy; legacy settings.json grants are not imported."""
    try:
        lock = policy_path().with_name('.automation-permissions.lock')
        if lock.exists():
            return {}
        snapshot = policy_snapshot()
        return {} if lock.exists() else snapshot
    except (OSError, ValueError, RecursionError):
        return {}


def merge_scope(workspace):
    from .relay_github import workspace_repo
    path = _workspace(workspace)
    return path, _repository(workspace_repo(path))


def save_merge_permission(expected, *, workspace, repository, enabled):
    """UI caller must separately confirm intent. Reject stale scope or policy."""
    def change(current):
        if merge_scope(workspace) != (_workspace(workspace), _repository(repository)):
            raise ValueError('Workspace origin changed; refresh before saving')
        return with_permission(current, 'squash_merge', enabled=enabled,
                               workspace=workspace, repository=repository)
    return _save_policy(expected, change)


def revoke_all_permissions(expected):
    return _save_policy(expected, lambda _: {KEY: {'version': 1, 'grants': []}})


def _save_policy(expected, change):
    from .relay_core import atomic_text
    path = policy_path()
    lock = path.with_name('.automation-permissions.lock')
    # Exclusive local writer; a crashed writer leaves a fail-closed stale lock.
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.close(fd)
        current = policy_snapshot()
        if current != expected:
            raise ValueError('Policy changed; refresh before saving')
        updated = change(current)
        _grants(updated)
        atomic_text(path, json.dumps(updated, ensure_ascii=False, indent=2))
        return updated
    finally:
        lock.unlink()
