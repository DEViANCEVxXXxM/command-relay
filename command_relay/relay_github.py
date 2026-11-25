# SPDX-License-Identifier: Apache-2.0
"""Optional GitHub CLI integration; no shell, token handling or automatic writes."""
from dataclasses import dataclass, asdict
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time


class GitHubError(RuntimeError):
    """Safe diagnostic; never includes raw CLI output or credentials."""


class MergeUnknown(GitHubError):
    """A write may have happened. Refresh before attempting another action."""


_SHA = re.compile(r'[0-9a-f]{40}')
_REPO = re.compile(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}')
_FIELDS = ('number,title,state,isDraft,isCrossRepository,baseRefName,baseRefOid,'
           'headRefName,headRefOid,mergeable,mergeStateStatus,reviewDecision,'
           'statusCheckRollup')


def _repo(value):
    if not isinstance(value, str) or not _REPO.fullmatch(value) or value.split('/')[1] in ('.', '..'):
        raise GitHubError('Expected an explicit github.com owner/repository.')
    return value


def _number(value):
    if type(value) is not int or value <= 0:
        raise GitHubError('Invalid pull request number.')
    return value


def _sha(value):
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise GitHubError('Missing or invalid commit SHA.')
    return value


def _label(value, limit=300):
    if not isinstance(value, str) or not value or len(value) > limit or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise GitHubError('Invalid or oversized GitHub display field.')
    return value


@dataclass(frozen=True)
class Check:
    name: str
    state: str


@dataclass(frozen=True)
class PullRequest:
    repo: str
    number: int
    title: str
    base: str
    head: str
    base_sha: str
    head_sha: str
    state: str
    checks: tuple[Check, ...]
    blockers: tuple[str, ...]

    @property
    def ready(self):
        return not self.blockers


def parse_pr(repo, number, data, repo_data):
    """Conservative readiness: all reported checks acceptable, server CLEAN.

    Does not infer required checks from names or claim server permission to merge.
    Missing/ambiguous states are blockers; fork PRs are outside this first scope.
    """
    _repo(repo); _number(number)
    if not isinstance(data, dict) or data.get('number') != number:
        raise GitHubError('Unexpected pull request response.')
    if not isinstance(repo_data, dict) or str(repo_data.get('full_name', '')).lower() != repo.lower():
        raise GitHubError('Unexpected repository response.')
    blockers = []
    if data.get('state') != 'OPEN': blockers.append('PR is not open.')
    if data.get('isDraft') is not False: blockers.append('PR is draft or draft state is unknown.')
    if data.get('isCrossRepository') is not False: blockers.append('Fork or unknown head repository.')
    if data.get('mergeable') != 'MERGEABLE' or data.get('mergeStateStatus') != 'CLEAN':
        blockers.append('GitHub does not report a clean, mergeable PR.')
    if data.get('reviewDecision') not in ('APPROVED', ''):
        blockers.append('Review decision is blocking or unknown.')
    if repo_data.get('allow_squash_merge') is not True:
        blockers.append('Squash merge is disabled or unknown.')
    permissions = repo_data.get('permissions')
    if not isinstance(permissions, dict) or permissions.get('push') is not True:
        blockers.append('Write permission is missing or unknown.')
    checks = []
    rollup = data.get('statusCheckRollup')
    if not isinstance(rollup, list) or not rollup or len(rollup) > 500:
        blockers.append('Check results are missing or exceed the supported limit.')
    else:
        for item in rollup:
            if not isinstance(item, dict):
                blockers.append('Malformed check result.'); continue
            kind = item.get('__typename')
            if kind == 'CheckRun':
                name = item.get('name'); status = item.get('status')
                state = item.get('conclusion') if status == 'COMPLETED' else 'PENDING'
                allowed = ('SUCCESS', 'NEUTRAL', 'SKIPPED')
            elif kind == 'StatusContext':
                name = item.get('context'); state = item.get('state'); allowed = ('SUCCESS',)
            else:
                blockers.append('Unknown check type.'); continue
            if state not in allowed:
                blockers.append('At least one check is pending, failed or unknown.')
            checks.append(Check(_label(name), _label(state or 'UNKNOWN', 40)))
        if not any(c.state == 'SUCCESS' for c in checks):
            blockers.append('No successful check reported.')
    base = _label(data.get('baseRefName')); head = _label(data.get('headRefName'))
    if base == head: blockers.append('Head and base branch are identical.')
    return PullRequest(repo, number, _label(data.get('title'), 500), base, head,
                       _sha(data.get('baseRefOid')), _sha(data.get('headRefOid')),
                       _label(data.get('state'), 40), tuple(sorted(checks, key=lambda c: (c.name, c.state))),
                       tuple(dict.fromkeys(blockers)))


def workspace_repo(workspace):
    """Read a single explicit GitHub origin without exposing credentials."""
    try:
        result = subprocess.run(['git', '-C', str(workspace), 'config', '--get-all', 'remote.origin.url'],
                                capture_output=True, encoding='utf-8', timeout=5, shell=False)
        lines = result.stdout.splitlines()
    except (OSError, UnicodeError, subprocess.TimeoutExpired):
        raise GitHubError('Could not read workspace origin; enter owner/repository.') from None
    if result.returncode or len(lines) != 1:
        raise GitHubError('Expected one GitHub origin; enter owner/repository.')
    match = re.fullmatch(r'(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)([^/]+/[^/]+?)(?:\.git)?/?', lines[0], re.I)
    if not match:
        raise GitHubError('Origin is not a supported GitHub URL; enter owner/repository.')
    return _repo(match.group(1))


def status_packet(pr, observed_at, *, merge_sha=None, outcome='observed'):
    """Bounded export, never include CLI output, credentials or workspace paths."""
    from .relay_privacy import protect_packet
    if merge_sha is not None:
        _sha(merge_sha)
    return protect_packet({'schema': 'command-relay/github-pr-status-v1',
                           'observed_at_utc': observed_at, 'pr': {**asdict(pr), 'checks': [asdict(c) for c in pr.checks], 'blockers': list(pr.blockers)},
                           'ready_at_observation': pr.ready, 'merge_outcome': outcome,
                           'verified_merge_sha': merge_sha,
                           'note': 'Snapshot only; server rules apply. Review before sharing.'})


class GitHubClient:
    def __init__(self, repo):
        self.repo = _repo(repo)
        executable = shutil.which('gh')
        if not executable:
            raise GitHubError('GitHub CLI is not on PATH.')
        self.executable = str(Path(executable).resolve())

    def _json(self, *args, payload=None):
        env = os.environ.copy()
        env.update(GH_PROMPT_DISABLED='1', GH_NO_UPDATE_NOTIFIER='1', NO_COLOR='1', GH_HOST='github.com')
        # Do not permit environment debug logging or a repository override.
        for key in ('GH_DEBUG', 'GH_REPO', 'DEBUG'):
            env.pop(key, None)
        try:
            p = subprocess.run([self.executable, *args], input=json.dumps(payload) if payload is not None else '',
                               capture_output=True, encoding='utf-8', errors='strict', timeout=30,
                               env=env, cwd=Path.home(), shell=False)
            if p.returncode or len(p.stdout) > 2_000_000:
                raise GitHubError('GitHub CLI request failed or response exceeded the limit; check access and refresh.')
            return json.loads(p.stdout)
        except (OSError, UnicodeError, subprocess.TimeoutExpired, ValueError):
            raise GitHubError('GitHub CLI unavailable, timed out or returned invalid data.') from None

    def _api(self, suffix='', method='GET', payload=None):
        args = ['api', '--hostname', 'github.com', '--method', method, 'repos/' + self.repo + suffix]
        if payload is not None: args += ['--input', '-']
        return self._json(*args, payload=payload)

    def list_open(self):
        rows = self._json('pr', 'list', '--repo', 'github.com/' + self.repo, '--state', 'open',
                          '--limit', '100', '--json', 'number,title')
        if not isinstance(rows, list) or len(rows) > 100:
            raise GitHubError('Unexpected pull request list.')
        result = tuple((_number(r.get('number')), _label(r.get('title'), 500))
                       for r in rows if isinstance(r, dict))
        if len(result) != len(rows) or len({n for n, _ in result}) != len(result):
            raise GitHubError('Malformed pull request list.')
        return result

    def inspect(self, number):
        _number(number)
        repo_data = self._api()
        data = self._json('pr', 'view', str(number), '--repo', 'github.com/' + self.repo, '--json', _FIELDS)
        return parse_pr(self.repo, number, data, repo_data)

    def squash_merge(self, reviewed, *, confirmed=False):
        """Call only after explicit human confirmation of this exact snapshot.

        No retry, auto-merge, admin bypass or branch deletion. GitHub enforces
        server rules; the REST SHA condition protects against head changes.
        Base/check status can still change after inspection; server rules apply.
        """
        return self._squash_merge(reviewed, confirmed=confirmed)

    def _squash_merge(self, reviewed, *, confirmed=False, guard=None):
        if confirmed is not True or not isinstance(reviewed, PullRequest) or reviewed.repo != self.repo or not reviewed.ready:
            raise GitHubError('Merge not confirmed or reviewed snapshot is not ready.')
        fresh = self.inspect(reviewed.number)
        if fresh != reviewed or not fresh.ready:
            raise GitHubError('PR changed or is no longer ready; review again.')
        path = '/pulls/' + str(fresh.number)
        if guard is not None:
            guard()  # Last local policy check before the remote write.
        try:
            result = self._api(path + '/merge', 'PUT', {'sha': fresh.head_sha, 'merge_method': 'squash'})
            if not isinstance(result, dict) or result.get('merged') is not True:
                raise GitHubError('Merge not confirmed by GitHub.')
            merged_sha = _sha(result.get('sha'))
            verified = self._api(path)
            if (not isinstance(verified, dict) or verified.get('number') != fresh.number or verified.get('merged') is not True
                or verified.get('merge_commit_sha') != merged_sha or (verified.get('head') or {}).get('sha') != fresh.head_sha
                or (verified.get('base') or {}).get('ref') != fresh.base
                or str(((verified.get('base') or {}).get('repo') or {}).get('full_name', '')).lower() != self.repo.lower()):
                raise GitHubError('Merged state not independently verified.')
        except (GitHubError, AttributeError, TypeError):
            raise MergeUnknown('Merge outcome unknown or denied. Refresh PR state before any retry; no branch cleanup attempted.') from None
        return merged_sha

    def _require_automation_merge(self, workspace):
        from .relay_permissions import allowed, read_automation_settings
        if not allowed(read_automation_settings(), 'squash_merge',
                       workspace=workspace, repository=self.repo):
            raise GitHubError('Automatic squash merge is disabled for this workspace and repository.')
        if workspace_repo(workspace).lower() != self.repo.lower():
            raise GitHubError('Workspace origin no longer matches the authorized repository.')

    def wait_and_merge(self, number, *, head, head_sha, base, base_sha, required_checks,
                       workspace=None, confirmed=False, timeout=600, interval=15, progress=None):
        """One pinned automatic merge: explicit task review AND scoped opt-in.

        Re-read policy and origin before polling, during polling, and immediately
        before the write. Manual squash_merge remains a separate reviewed action.
        Local checks cannot atomically pin external settings or GitHub state.
        """
        if confirmed is not True:
            raise GitHubError('Task-level squash merge was not explicitly authorized.')
        def guard():
            self._require_automation_merge(workspace)
        ready = self._wait_for_ci(number, head=head, head_sha=head_sha, base=base,
                                 base_sha=base_sha, required_checks=required_checks,
                                 timeout=timeout, interval=interval, progress=progress, guard=guard)
        return self._squash_merge(ready, confirmed=True, guard=guard)

    def wait_for_ci(self, number, *, head, head_sha, base, base_sha, required_checks,
                    timeout=600, interval=15, progress=None):
        """Read-only bounded wait for an exact ready PR; never authorizes a write."""
        return self._wait_for_ci(number, head=head, head_sha=head_sha, base=base,
                                 base_sha=base_sha, required_checks=required_checks,
                                 timeout=timeout, interval=interval, progress=progress)

    def _wait_for_ci(self, number, *, head, head_sha, base, base_sha, required_checks,
                     timeout, interval, progress, guard=None):
        _number(number); _label(head); _label(base); _sha(head_sha); _sha(base_sha)
        if head == base or head_sha == base_sha:
            raise GitHubError('Expected distinct head and base.')
        if (not isinstance(required_checks, (list, tuple)) or not required_checks or
                len(required_checks) > 500):
            raise GitHubError('Expected an explicit nonempty check-name list.')
        names = {_label(name) for name in required_checks}
        if len(names) != len(required_checks):
            raise GitHubError('Expected unique required check names.')
        if type(timeout) is not int or not 30 <= timeout <= 1800 or type(interval) is not int or not 5 <= interval <= 60:
            raise GitHubError('Invalid CI polling budget or interval.')
        if progress is not None and not callable(progress):
            raise GitHubError('Invalid progress callback.')
        if guard is not None:
            guard()
        deadline = time.monotonic() + timeout
        transient = {'GitHub does not report a clean, mergeable PR.',
                     'At least one check is pending, failed or unknown.',
                     'No successful check reported.',
                     'Check results are missing or exceed the supported limit.'}
        waiting = {'PENDING', 'EXPECTED', 'IN_PROGRESS', 'QUEUED', 'WAITING', 'REQUESTED', 'UNKNOWN'}
        while time.monotonic() < deadline:
            if guard is not None:
                guard()
            pr = self.inspect(number)
            if (pr.repo, pr.number, pr.head, pr.head_sha, pr.base, pr.base_sha) != (self.repo, number, head, head_sha, base, base_sha):
                raise GitHubError('PR identity, head or base changed; review a new task.')
            if pr.state != 'OPEN':
                raise GitHubError('PR is no longer open; inspect its state before any new task.')
            if set(pr.blockers) - transient:
                raise GitHubError('PR has a non-waitable blocker; review its current state.')
            if any(c.state not in waiting | {'SUCCESS', 'NEUTRAL', 'SKIPPED'} for c in pr.checks):
                raise GitHubError('CI has failed or returned an unrecognized conclusion; no merge attempted.')
            if any(c.name in names and c.state in {'NEUTRAL', 'SKIPPED'} for c in pr.checks):
                raise GitHubError('An explicitly required check did not succeed; no merge attempted.')
            successes = {c.name for c in pr.checks if c.state == 'SUCCESS'}
            ready = pr.ready and names <= successes and not any(c.state in waiting for c in pr.checks)
            if progress is not None:
                progress('CI_READY' if ready else 'WAITING_FOR_CI', len(names & successes), len(names))
            if ready and time.monotonic() < deadline:
                return pr
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(interval, remaining))
        raise GitHubError('CI polling deadline elapsed; no merge attempted.')
