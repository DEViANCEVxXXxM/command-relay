# SPDX-License-Identifier: Apache-2.0
"""Read-only discovery of official stable releases. Not an installer or trust verifier."""
from dataclasses import dataclass
import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .relay_version import VERSION

REPOSITORY = 'DEViANCEVxXXxM/command-relay'
LATEST_API = f'https://api.github.com/repos/{REPOSITORY}/releases/latest'
MAX_RESPONSE = 512 * 1024
SOCKET_TIMEOUT = 10
_VERSION = re.compile(r'(?:0|[1-9][0-9]{0,5})\.(?:0|[1-9][0-9]{0,5})\.(?:0|[1-9][0-9]{0,5})')
_DIGEST = re.compile(r'sha256:[0-9a-f]{64}')


class UpdateError(RuntimeError):
    """Safe discovery error; never exposes raw API response or local environment."""


@dataclass(frozen=True)
class ReleaseAsset:
    name: str
    asset_id: int
    size: int
    digest: str | None


@dataclass(frozen=True)
class UpdateInfo:
    current: str
    latest: str
    release_id: int
    archive: ReleaseAsset
    checksum: ReleaseAsset

    @property
    def available(self):
        return _version(self.latest) > _version(self.current)

    @property
    def release_url(self):
        return f'https://github.com/{REPOSITORY}/releases/tag/v{self.latest}'


def _version(value):
    if not isinstance(value, str) or not _VERSION.fullmatch(value):
        raise UpdateError('Invalid stable release version.')
    return tuple(map(int, value.split('.')))


def _asset(assets, name):
    matches = [a for a in assets if a.get('name') == name]
    if len(matches) != 1:
        raise UpdateError('Missing or ambiguous release asset.')
    a = matches[0]
    asset_id, size, digest = a.get('id'), a.get('size'), a.get('digest')
    if (type(asset_id) is not int or asset_id <= 0 or
            type(size) is not int or size <= 0 or a.get('state') != 'uploaded'):
        raise UpdateError('Invalid release asset metadata.')
    if digest is not None and (not isinstance(digest, str) or not _DIGEST.fullmatch(digest)):
        raise UpdateError('Invalid release asset digest.')
    return ReleaseAsset(name, asset_id, size, digest)


def parse_latest(data, current=VERSION):
    """Validate metadata, not provenance or archive contents. No side effects."""
    _version(current)
    if not isinstance(data, dict) or data.get('draft') is not False or data.get('prerelease') is not False:
        raise UpdateError('Expected a published stable release.')
    tag, release_id, assets = data.get('tag_name'), data.get('id'), data.get('assets')
    if not isinstance(tag, str) or not tag.startswith('v'):
        raise UpdateError('Invalid stable release tag.')
    latest = tag[1:]
    _version(latest)
    if (type(release_id) is not int or release_id <= 0 or not isinstance(assets, list)
            or len(assets) > 100 or any(not isinstance(a, dict) for a in assets)):
        raise UpdateError('Invalid release metadata.')
    stem = f'command-relay-v{latest}-windows'
    archive = _asset(assets, stem + '.zip')
    checksum = _asset(assets, stem + '.sha256')
    if archive.asset_id == checksum.asset_id:
        raise UpdateError('Duplicate release asset identity.')
    return UpdateInfo(current, latest, release_id, archive, checksum)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise UpdateError('Unexpected release API redirect.')


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise UpdateError('Duplicate release metadata field.')
        result[key] = value
    return result


def check_latest(current=VERSION):
    """One unauthenticated HTTPS metadata request, with no download or writes.

    Timeout is a socket timeout, not a total request deadline. Call off the UI
    thread when integrating a user-facing check. No automatic polling yet.
    """
    _version(current)
    request = Request(LATEST_API, headers={
        'Accept': 'application/vnd.github+json',
        'User-Agent': 'Command-Relay/' + current,
        'X-GitHub-Api-Version': '2022-11-28',
    }, method='GET')
    try:
        with build_opener(_NoRedirect()).open(request, timeout=SOCKET_TIMEOUT) as response:
            if response.geturl() != LATEST_API or response.status != 200:
                raise UpdateError('Unexpected release API response.')
            raw = response.read(MAX_RESPONSE + 1)
    except HTTPError as exc:
        raise UpdateError(f'Release API HTTP error ({exc.code}).') from None
    except (URLError, OSError) as exc:
        raise UpdateError('Release API unavailable.') from None
    if len(raw) > MAX_RESPONSE:
        raise UpdateError('Release metadata exceeds size limit.')
    try:
        data = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_object)
    except (UnicodeError, ValueError, RecursionError):
        raise UpdateError('Invalid release metadata JSON.') from None
    return parse_latest(data, current)
