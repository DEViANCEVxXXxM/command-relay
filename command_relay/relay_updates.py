# SPDX-License-Identifier: Apache-2.0
"""Official release discovery and bounded integrity checks. Not an installer."""
from dataclasses import dataclass
import hashlib
from http.client import HTTPException
import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .relay_version import VERSION

REPOSITORY = 'DEViANCEVxXXxM/command-relay'
LATEST_API = f'https://api.github.com/repos/{REPOSITORY}/releases/latest'
MAX_RESPONSE = 512 * 1024
SOCKET_TIMEOUT = 10
MAX_ARCHIVE = 16 * 1024 * 1024
MAX_CHECKSUM = 512
_ASSET_HOSTS = frozenset(('release-assets.githubusercontent.com', 'objects.githubusercontent.com'))
_VERSION = re.compile(r'(?:0|[1-9][0-9]{0,5})\.(?:0|[1-9][0-9]{0,5})\.(?:0|[1-9][0-9]{0,5})')
_DIGEST = re.compile(r'sha256:[0-9a-f]{64}')


class UpdateError(RuntimeError):
    """Safe update error; never exposes raw API response or local environment."""


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


@dataclass(frozen=True)
class DownloadedUpdate:
    """Integrity-checked bytes only; not a signature or installation authorization."""
    info: UpdateInfo
    archive: bytes
    sha256: str


def _asset_redirect_url(url):
    try:
        parts = urlsplit(url)
        return (parts.scheme == 'https' and parts.netloc in _ASSET_HOSTS
                and parts.path.startswith('/') and not parts.fragment
                and not any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in url))
    except (ValueError, TypeError):
        return False


class _AssetRedirect(HTTPRedirectHandler):
    max_redirections = 3
    max_repeats = 1

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _asset_redirect_url(newurl):
            raise UpdateError('Unexpected release asset redirect.')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _validate_download(info):
    if not isinstance(info, UpdateInfo) or not info.available:
        raise UpdateError('Expected a newer stable release.')
    if type(info.release_id) is not int or info.release_id <= 0:
        raise UpdateError('Invalid release identity.')
    stem = f'command-relay-v{info.latest}-windows'
    for asset, name, limit in ((info.archive, stem + '.zip', MAX_ARCHIVE),
                               (info.checksum, stem + '.sha256', MAX_CHECKSUM)):
        if (not isinstance(asset, ReleaseAsset) or asset.name != name
                or type(asset.asset_id) is not int or asset.asset_id <= 0
                or type(asset.size) is not int or not 0 < asset.size <= limit
                or not isinstance(asset.digest, str) or not _DIGEST.fullmatch(asset.digest)):
            raise UpdateError('Invalid or incomplete download metadata.')
    if info.archive.asset_id == info.checksum.asset_id:
        raise UpdateError('Duplicate release asset identity.')


def _download_asset(info, asset):
    url = info.release_url.replace('/releases/tag/', '/releases/download/') + '/' + asset.name
    request = Request(url, headers={'User-Agent': 'Command-Relay/' + info.current,
                                    'Accept': 'application/octet-stream'}, method='GET')
    try:
        with build_opener(_AssetRedirect()).open(request, timeout=SOCKET_TIMEOUT) as response:
            final = response.geturl()
            if response.status != 200 or (final != url and not _asset_redirect_url(final)):
                raise UpdateError('Unexpected release asset response.')
            # An extra byte detects oversized data without buffering unbounded responses.
            data = response.read(asset.size + 1)
    except HTTPError as exc:
        raise UpdateError(f'Release asset HTTP error ({exc.code}).') from None
    except (URLError, OSError, EOFError, HTTPException):
        raise UpdateError('Release asset unavailable.') from None
    if len(data) != asset.size:
        raise UpdateError('Release asset size differs from metadata.')
    if 'sha256:' + hashlib.sha256(data).hexdigest() != asset.digest:
        raise UpdateError('Release asset digest differs from metadata.')
    return data


def download_update(info):
    """Explicit, bounded download of a newer release into memory only.

    Check both asset digests and the exact checksum file. No extraction,
    persistence, execution, or authorization to install. GitHub-originated
    digests are integrity evidence, not an independent publisher signature.
    The timeout is per socket operation, not an overall deadline.
    """
    _validate_download(info)
    checksum = _download_asset(info, info.checksum)
    expected = (info.archive.digest.removeprefix('sha256:') + '  ' + info.archive.name).encode('ascii')
    if checksum not in (expected + b'\n', expected + b'\r\n'):
        raise UpdateError('Release checksum file does not match archive metadata.')
    archive = _download_asset(info, info.archive)
    return DownloadedUpdate(info, archive, hashlib.sha256(archive).hexdigest())


# Inspection is deliberately separate from installation or publisher trust.
MAX_PACKAGE_FILES = 256
MAX_MEMBER_BYTES = 8 * 1024 * 1024
MAX_PACKAGE_BYTES = 32 * 1024 * 1024
_PACKAGE_COMPONENT = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}')
_RESERVED_NAMES = frozenset(('CON', 'PRN', 'AUX', 'NUL',
                             *(f'COM{i}' for i in range(10)),
                             *(f'LPT{i}' for i in range(10))))


def _package_path(name):
    if not isinstance(name, str) or len(name) > 240:
        return False
    return all(_PACKAGE_COMPONENT.fullmatch(part) and not part.endswith('.')
               and part.split('.')[0].upper() not in _RESERVED_NAMES
               for part in name.split('/'))


def inspect_package(download, expected_files):
    """Check ZIP membership and content hashes without extracting any files.

    expected_files must be a separately trusted mapping of relative paths to
    lowercase SHA-256 hashes (not data taken from the downloaded ZIP itself).
    Returns a sorted tuple of verified relative paths, not install authority.
    Current format accepts regular files only; no new paths are implicitly trusted.
    """
    import io
    import stat
    import zipfile
    import zlib

    if not isinstance(download, DownloadedUpdate) or not isinstance(download.archive, bytes):
        raise UpdateError('Invalid downloaded package.')
    _validate_download(download.info)
    raw = download.archive
    actual = hashlib.sha256(raw).hexdigest()
    if (len(raw) != download.info.archive.size or actual != download.sha256
            or 'sha256:' + actual != download.info.archive.digest):
        raise UpdateError('Downloaded package integrity changed.')
    if not isinstance(expected_files, dict) or not 0 < len(expected_files) <= MAX_PACKAGE_FILES:
        raise UpdateError('Invalid expected package manifest.')
    expected = dict(expected_files)
    if any(not _package_path(name) or not isinstance(digest, str)
           or not re.fullmatch(r'[0-9a-f]{64}', digest) for name, digest in expected.items()):
        raise UpdateError('Invalid expected package manifest.')
    folded = {name.lower() for name in expected}
    if len(folded) != len(expected) or any(
            '/'.join(name.split('/')[:i]) in folded
            for name in folded for i in range(1, len(name.split('/')))):
        raise UpdateError('Ambiguous expected package paths.')
    prefix = f'command-relay-v{download.info.latest}-windows/'
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = archive.infolist()
            if len(members) != len(expected) or len(members) > MAX_PACKAGE_FILES:
                raise UpdateError('Unexpected package file count.')
            names = set()
            total = 0
            for member in members:
                name = member.filename
                if member.orig_filename != name or not name.startswith(prefix):
                    raise UpdateError('Invalid package member path.')
                relative = name[len(prefix):]
                if relative not in expected or relative in names:
                    raise UpdateError('Unexpected or duplicate package member.')
                names.add(relative)
                if (member.is_dir() or member.create_system != 3
                        or stat.S_IFMT(member.external_attr >> 16) != stat.S_IFREG
                        or member.external_attr & 0x10
                        or member.flag_bits & ~0x800
                        or member.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
                    raise UpdateError('Unsupported package member type.')
                if not 0 <= member.file_size <= MAX_MEMBER_BYTES:
                    raise UpdateError('Package member exceeds size limit.')
                total += member.file_size
                if total > MAX_PACKAGE_BYTES:
                    raise UpdateError('Package exceeds expanded size limit.')
            if names != set(expected):
                raise UpdateError('Package membership differs from manifest.')
            for member in members:
                with archive.open(member, 'r') as stream:
                    data = stream.read(member.file_size + 1)
                if (len(data) != member.file_size or
                        hashlib.sha256(data).hexdigest() != expected[member.filename[len(prefix):]]):
                    raise UpdateError('Package member content differs from manifest.')
    except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError, EOFError, RuntimeError,
            NotImplementedError, ValueError, zlib.error) as exc:
        if isinstance(exc, UpdateError):
            raise
        raise UpdateError('Invalid or damaged release ZIP.') from None
    return tuple(sorted(expected))


# Provision only from an independently reviewed publisher public key. Never
# accept a key supplied by the release, manifest, network, or local settings.
PUBLISHER_PUBLIC_KEY = bytes.fromhex(
    '835cafd70177a9c97c426d1f05b522650d05a16c302380654372da4d0c07389b')
MAX_SIGNED_MANIFEST = 128 * 1024
MANIFEST_SCHEMA = 'command-relay/update-manifest-v1'


def verify_publisher_package(download, manifest_bytes, signature):
    """Verify a detached Ed25519 signature and its exact package binding.

    The publisher key is pinned in the reviewed application source.
    A verified package is not authorization to install or execute it.
    """
    key = PUBLISHER_PUBLIC_KEY
    if not isinstance(key, bytes) or len(key) != 32:
        raise UpdateError('Publisher trust key is not configured.')
    if (not isinstance(manifest_bytes, bytes) or not 0 < len(manifest_bytes) <= MAX_SIGNED_MANIFEST
            or not isinstance(signature, bytes) or len(signature) != 64):
        raise UpdateError('Invalid signed manifest or signature size.')
    try:
        from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except (ImportError, OSError):
        raise UpdateError('Publisher signature verification is unavailable.') from None
    try:
        Ed25519PublicKey.from_public_bytes(key).verify(signature, manifest_bytes)
    except (InvalidSignature, UnsupportedAlgorithm, ValueError):
        raise UpdateError('Publisher signature verification failed.') from None
    try:
        data = json.loads(manifest_bytes.decode('utf-8'), object_pairs_hook=_unique_object)
    except (UnicodeError, ValueError, RecursionError):
        raise UpdateError('Invalid signed manifest JSON.') from None
    if not isinstance(download, DownloadedUpdate):
        raise UpdateError('Invalid downloaded package.')
    _validate_download(download.info)
    if (not isinstance(data, dict) or set(data) != {'schema', 'repository', 'version', 'archive', 'files'}
            or data['schema'] != MANIFEST_SCHEMA or data['repository'] != REPOSITORY
            or data['version'] != download.info.latest):
        raise UpdateError('Signed manifest identity differs.')
    archive = data['archive']
    if (not isinstance(archive, dict) or set(archive) != {'name', 'size', 'sha256'}
            or archive['name'] != download.info.archive.name
            or type(archive['size']) is not int or archive['size'] != download.info.archive.size
            or archive['sha256'] != download.sha256):
        raise UpdateError('Signed archive identity differs.')
    return inspect_package(download, data['files'])
