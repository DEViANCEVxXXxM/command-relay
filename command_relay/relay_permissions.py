# SPDX-License-Identifier: Apache-2.0
"""Fail-closed policy data for future application-owned automation.

Not a sandbox or enforcement by itself. Callers must re-read policy immediately
before a built-in write, verify the actual target, and separately confirm intent.
Policy storage is isolated from ordinary workbench settings.
"""
from datetime import datetime, timezone
import hashlib
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
AUDIT_KEY = "permission_audit"
MAX_AUDIT_EVENTS = 128
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


def audit_history(snapshot):
    """Validate and return bounded local history; legacy policies have none."""
    value = snapshot.get(AUDIT_KEY, {'version': 1, 'dropped': 0, 'events': []})
    if (not isinstance(value, dict) or set(value) != {'version', 'dropped', 'events'}
            or type(value['version']) is not int or value['version'] != 1
            or type(value['dropped']) is not int or not 0 <= value['dropped'] <= 2**63 - 1
            or not isinstance(value['events'], list) or len(value['events']) > MAX_AUDIT_EVENTS):
        raise ValueError('Invalid permission history')
    for e in value['events']:
        if not isinstance(e, dict) or set(e) != {'utc', 'operation', 'repository', 'workspace_sha256', 'count'}:
            raise ValueError('Invalid permission event')
        if not isinstance(e['utc'], str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z', e['utc']):
            raise ValueError('Invalid permission event timestamp')
        datetime.fromisoformat(e['utc'][:-1] + '+00:00')
        if type(e['count']) is not int or not 1 <= e['count'] <= MAX_GRANTS:
            raise ValueError('Invalid permission event count')
        if e['operation'] in ('grant', 'revoke'):
            if (e['count'] != 1 or _repository(e['repository']) != e['repository']
                    or not isinstance(e['workspace_sha256'], str)
                    or not re.fullmatch(r'[0-9a-f]{64}', e['workspace_sha256'])):
                raise ValueError('Invalid permission event scope')
        elif e['operation'] in ('grant_update_install', 'revoke_update_install'):
            if e['count'] != 1 or e['repository'] is not None or e['workspace_sha256'] is not None:
                raise ValueError('Invalid update permission event scope')
        elif e['operation'] != 'revoke_all' or e['repository'] is not None or e['workspace_sha256'] is not None:
            raise ValueError('Invalid permission event operation')
    return value


def _record_change(current, updated, operation):
    old, new = _grants(current), _grants(updated)
    if old == new:
        return current
    changed = new - old if operation in ('grant', 'grant_update_install') else old - new
    if operation in ('revoke_all', 'grant_update_install', 'revoke_update_install'):
        repository, workspace_hash = None, None
    else:
        _, workspace, repository = next(iter(changed))
        workspace_hash = hashlib.sha256(workspace.encode('utf-8', errors='surrogatepass')).hexdigest()
    event = {'utc': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
             'operation': operation, 'repository': repository,
             'workspace_sha256': workspace_hash, 'count': len(changed)}
    history = audit_history(current)
    events = [*history['events'], event]
    updated = {**updated, AUDIT_KEY: {'version': 1,
        'dropped': min(2**63 - 1, history['dropped'] + max(0, len(events) - MAX_AUDIT_EVENTS)),
        'events': events[-MAX_AUDIT_EVENTS:]}}
    audit_history(updated)
    return updated


def audit_text(snapshot):
    """Local read-only display; no report/session export."""
    history = audit_history(snapshot)
    lines = ['Local permission history (latest first; not tamper-proof).',
             f"Older entries discarded: {history['dropped']}", '']
    for e in reversed(history['events']):
        scope = (e['repository'] + ' / workspace ' + e['workspace_sha256'][:12]) if e['repository'] else 'all workspaces'
        if e['operation'] in ('grant_update_install', 'revoke_update_install'):
            scope = 'this application installation'
        lines.append(f"{e['utc']}  {e['operation']}  ({e['count']})  {scope}")
    if not history['events']:
        lines.append('No recorded changes. Existing grants may predate this history.')
    return '\n'.join(lines)


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
    if not isinstance(value, dict) or set(value) - {KEY, AUDIT_KEY}:
        raise ValueError('Invalid policy file')
    _grants(value)
    audit_history(value)
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
    return _save_policy(expected, change, 'grant' if enabled else 'revoke')


def update_permission_scope(root):
    """Resolve the running portable installation, never the selected workspace.

    Only a local policy belonging to this application root is eligible. The
    supported launcher already holds the installation lock during GUI use.
    This does not certify the installed package or authorize an installation.
    """
    from .relay_updates import _checked_path, _require_no_pending_transaction
    root = Path(root)
    if not root.is_absolute() or '..' in root.parts or root.parent == root:
        raise ValueError('Expected absolute installation directory')
    if policy_path() != root / 'automation-permissions.json':
        raise ValueError('Policy does not belong to this installation')
    for parent in (*reversed(root.parents), root):
        _checked_path(parent, directory=True)
        if any(entry.name.rstrip(' .').casefold() == '.git' for entry in parent.iterdir()):
            raise ValueError('Source checkout cannot opt in to installation')
    _checked_path(root / 'Start.pyw', directory=False)
    _require_no_pending_transaction(root)
    for entry in root.iterdir():
        name = entry.name.rstrip(' .').casefold()
        if name in ('automation-permissions.json', '.automation-permissions.lock'):
            if entry.name != name:
                raise ValueError('Unexpected policy filename')
            _checked_path(entry, directory=False)
    return root


def save_update_permission(expected, *, root, enabled):
    """Persist a confirmed application-local grant, never install anything."""
    root = update_permission_scope(root)
    def change(current):
        update_permission_scope(root)
        return with_permission(current, 'update_install', enabled=enabled)
    return _save_policy(expected, change, 'grant_update_install' if enabled else 'revoke_update_install')


def revoke_all_permissions(expected):
    return _save_policy(expected, lambda _: {KEY: {'version': 1, 'grants': []}}, 'revoke_all')


def _save_policy(expected, change, operation):
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
        updated = _record_change(current, updated, operation)
        if updated != current:
            text = json.dumps(updated, ensure_ascii=False, indent=2)
            if len(text) > 1_000_000:
                raise ValueError('Policy file too large')
            atomic_text(path, text)
        return updated
    finally:
        lock.unlink()
