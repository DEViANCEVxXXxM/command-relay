# SPDX-License-Identifier: Apache-2.0
"""Fail-closed policy data for future application-owned automation.

Not a sandbox or enforcement by itself. Callers must re-read policy immediately
before a built-in write, verify the actual target, and separately confirm intent.
No settings are written by this module.
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


def read_automation_settings():
    """Read fresh settings for a built-in write; malformed or ambiguous means deny."""
    from .relay_core import SETTINGS

    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate settings key')
            result[key] = value
        return result

    try:
        with SETTINGS.open('r', encoding='utf-8') as stream:
            text = stream.read(1_000_001)
        if len(text) > 1_000_000:
            return {}
        value = json.loads(text, object_pairs_hook=unique_pairs)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, RecursionError):
        return {}
