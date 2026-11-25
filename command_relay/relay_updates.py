# SPDX-License-Identifier: Apache-2.0
"""Official release discovery, authenticity checks and isolated staging. Not an installer."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
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
    manifest: ReleaseAsset | None = None
    signature: ReleaseAsset | None = None

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
    manifest_name, signature_name = stem + '.manifest.json', stem + '.manifest.sig'
    manifest = signature = None
    if any(a.get('name') in (manifest_name, signature_name) for a in assets):
        manifest = _asset(assets, manifest_name)
        signature = _asset(assets, signature_name)
        if len({a.asset_id for a in (archive, checksum, manifest, signature)}) != 4:
            raise UpdateError('Duplicate release asset identity.')
    return UpdateInfo(current, latest, release_id, archive, checksum, manifest, signature)


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


@dataclass(frozen=True)
class SignedUpdate:
    """Verified download evidence, not installation authority. Reverify before use."""
    download: DownloadedUpdate
    manifest: bytes
    signature: bytes


def describe_release(info):
    """Presentation only: metadata is never publisher authentication."""
    if not isinstance(info, UpdateInfo):
        raise UpdateError('Invalid release metadata.')
    current, latest = _version(info.current), _version(info.latest)
    availability = ('Newer release available.' if latest > current else
                    'Current version is up to date.' if latest == current else
                    'Published stable release is older than this build.')
    if info.manifest is None or info.signature is None:
        trust = 'Signature assets missing. Signed installation unavailable.'
    else:
        trust = 'Signature assets listed. Publisher signature NOT verified.'
    return availability, trust


def _validate_signed_download(info):
    _validate_download(info)
    stem = f'command-relay-v{info.latest}-windows'
    for asset, name, limit in ((info.manifest, stem + '.manifest.json', MAX_SIGNED_MANIFEST),
                               (info.signature, stem + '.manifest.sig', 64)):
        if (not isinstance(asset, ReleaseAsset) or asset.name != name
                or type(asset.asset_id) is not int or asset.asset_id <= 0
                or type(asset.size) is not int or not 0 < asset.size <= limit
                or not isinstance(asset.digest, str) or not _DIGEST.fullmatch(asset.digest)):
            raise UpdateError('Missing or invalid signed release asset metadata.')
    if info.signature.size != 64:
        raise UpdateError('Invalid detached signature size.')
    if len({a.asset_id for a in (info.archive, info.checksum, info.manifest, info.signature)}) != 4:
        raise UpdateError('Duplicate release asset identity.')


def can_verify_release(info):
    """Metadata eligibility only; no network access or authentication."""
    try:
        _validate_signed_download(info)
        return True
    except UpdateError:
        return False


def verify_release_for_display(info):
    """Authenticate the full download in memory; retain only its digest for display."""
    signed = download_signed_update(info)
    return signed.download.sha256


def download_signed_update(info):
    """Fetch the detached signature and manifest, then verify the exact ZIP.

    No writes, extraction, installation, or execution. All four assets are bounded.
    """
    _validate_signed_download(info)
    manifest = _download_asset(info, info.manifest)
    signature = _download_asset(info, info.signature)
    download = download_update(info)
    verify_publisher_package(download, manifest, signature)
    return SignedUpdate(download, manifest, signature)


@dataclass(frozen=True)
class StagedUpdate:
    """Temporary inspection result, not authorization to replace program files."""
    directory: Path  # valid only inside stage_signed_update context
    version: str
    files: tuple[str, ...]


@contextmanager
def stage_signed_update(signed):
    """Reauthenticate and stage a newer package in a fresh temp directory.

    Never accepts a destination supplied by a package or caller, never extracts
    into an existing application tree, and never executes staged code. No
    installation permission is granted. The directory is removed on context
    exit, including exceptions. A hard process kill may leave scratch files.
    Same-user concurrent modification is outside this boundary; reverify bytes
    again before any future installation. No live installation exists yet.
    """
    import io
    import tempfile
    import zipfile

    if (not isinstance(signed, SignedUpdate)
            or not isinstance(signed.download, DownloadedUpdate)
            or not isinstance(signed.download.info, UpdateInfo)
            or signed.download.info.current != VERSION):
        raise UpdateError('Expected signed update for the running version.')
    download = signed.download
    files = verify_publisher_package(download, signed.manifest, signed.signature)
    expected = json.loads(signed.manifest.decode('utf-8'))['files']
    prefix = f'command-relay-v{download.info.latest}-windows/'
    with tempfile.TemporaryDirectory(prefix='command-relay-stage-') as scratch:
        directory = Path(scratch)
        try:
            with zipfile.ZipFile(io.BytesIO(download.archive)) as archive:
                for name in files:
                    member = archive.getinfo(prefix + name)
                    with archive.open(member) as stream:
                        data = stream.read(member.file_size + 1)
                    if (len(data) != member.file_size or
                            hashlib.sha256(data).hexdigest() != expected[name]):
                        raise UpdateError('Staged package content differs from manifest.')
                    target = directory.joinpath(*name.split('/'))
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with target.open('xb') as output:
                        output.write(data)
                    if (target.stat().st_size != len(data) or
                            hashlib.sha256(target.read_bytes()).hexdigest() != expected[name]):
                        raise UpdateError('Staged file readback differs from manifest.')
        except (OSError, zipfile.BadZipFile, KeyError, EOFError) as exc:
            raise UpdateError('Unable to stage verified update.') from None
        yield StagedUpdate(directory, download.info.latest, files)


# First managed layout: exact portable program files, never user data.
# Future layout changes require a separately reviewed migration.
INSTALL_PROGRAM_FILES = frozenset((
    'CHANGELOG.md',
    'CONTRIBUTING.md',
    'DISCLAIMER.md',
    'LICENSE',
    'NOTICE',
    'README.md',
    'SECURITY.md',
    'Start.cmd',
    'Start.pyw',
    'command_relay/__init__.py',
    'command_relay/__main__.py',
    'command_relay/assets/relay-icon.ico',
    'command_relay/assets/relay-icon.png',
    'command_relay/relay_compare.py',
    'command_relay/relay_core.py',
    'command_relay/relay_export.py',
    'command_relay/relay_features.py',
    'command_relay/relay_github.py',
    'command_relay/relay_github_qt.py',
    'command_relay/relay_intelligence.py',
    'command_relay/relay_permissions.py',
    'command_relay/relay_privacy.py',
    'command_relay/relay_qt.py',
    'command_relay/relay_session.py',
    'command_relay/relay_terms.py',
    'command_relay/relay_updates.py',
    'command_relay/relay_version.py',
    'command_relay/relay_view.py',
    'command_relay/relay_windows.py',
    'docs/COMMAND_RELAY_AI_GUIDE.md',
    'docs/architecture.md',
    'docs/disclaimer.md',
    'docs/github-setup.md',
    'docs/manual.txt',
    'examples/example-ai-task.json',
    'examples/example-privacy-task.json',
    'examples/example.txt',
    'requirements.txt',
    'tools/Start-Debug.cmd',
))


@dataclass(frozen=True)
class InstallPlan:
    """Read-only evidence, not installation authorization or a filesystem lock."""
    root: Path
    current: str
    target: str
    replace: tuple[str, ...]
    unchanged: tuple[str, ...]


def _checked_path(path, *, directory):
    import stat
    info = path.lstat()
    if (stat.S_ISLNK(info.st_mode)
            or getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
            or (directory and not stat.S_ISDIR(info.st_mode))
            or (not directory and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1))):
        raise UpdateError('Unsafe installation path type.')
    return info


def plan_installation(root, installed, target):
    """Authenticate old and new packages and read the exact existing program files.

    No writes, permission grants, process locks, or execution. Requires the
    original signed package for the running version. Unsigned legacy installs
    and changes to the program file layout need a separately reviewed migration.
    Other user files are not traversed or modified. Same-user concurrent changes
    are outside this check; a future installer must revalidate before writes.
    """
    if not all(isinstance(item, SignedUpdate) and isinstance(item.download, DownloadedUpdate)
               and isinstance(item.download.info, UpdateInfo) for item in (installed, target)):
        raise UpdateError('Expected two signed packages.')
    if installed.download.info.latest != VERSION or target.download.info.current != VERSION:
        raise UpdateError('Installation packages differ from the running version.')
    old_files, new_files = (verify_publisher_package(item.download, item.manifest, item.signature)
                            for item in (installed, target))
    if set(old_files) != INSTALL_PROGRAM_FILES or set(new_files) != INSTALL_PROGRAM_FILES:
        raise UpdateError('Unsupported managed program file layout.')
    old_hashes = json.loads(installed.manifest.decode('utf-8'))['files']
    new_hashes = json.loads(target.manifest.decode('utf-8'))['files']
    try:
        root = Path(root)
        if not root.is_absolute() or '..' in root.parts or root.parent == root:
            raise UpdateError('Expected an absolute non-root installation directory.')
        for parent in (*reversed(root.parents), root):
            _checked_path(parent, directory=True)
            try:
                (parent / '.git').lstat()
            except FileNotFoundError:
                pass
            else:
                raise UpdateError('Git checkout cannot be updated.')
        for name in sorted(old_hashes):
            path = root
            parts = name.split('/')
            for i, part in enumerate(parts):
                matches = [entry.name for entry in path.iterdir() if entry.name.casefold() == part.casefold()]
                if matches != [part]:
                    raise UpdateError('Missing or ambiguous installed program path.')
                path = path / part
                info = _checked_path(path, directory=i < len(parts)-1)
            if info.st_size > MAX_MEMBER_BYTES:
                raise UpdateError('Installed program file exceeds size limit.')
            with path.open('rb') as source:
                data = source.read(MAX_MEMBER_BYTES + 1)
            if len(data) != info.st_size or hashlib.sha256(data).hexdigest() != old_hashes[name]:
                raise UpdateError('Installed program file differs from signed package.')
    except (OSError, TypeError, ValueError) as exc:
        if isinstance(exc, UpdateError):
            raise
        raise UpdateError('Unable to inspect installation directory.') from None
    changed = tuple(name for name in sorted(old_hashes) if old_hashes[name] != new_hashes[name])
    unchanged = tuple(name for name in sorted(old_hashes) if old_hashes[name] == new_hashes[name])
    return InstallPlan(root, VERSION, target.download.info.latest, changed, unchanged)


@dataclass(frozen=True)
class InstallRehearsal:
    """Evidence from a disposable installation, never a live install result."""
    current: str
    target: str
    replaced: tuple[str, ...]
    rollback_verified: bool


def _verified_program_bytes(signed):
    import io
    import zipfile
    names = verify_publisher_package(signed.download, signed.manifest, signed.signature)
    if set(names) != INSTALL_PROGRAM_FILES:
        raise UpdateError('Unsupported managed program file layout.')
    hashes = json.loads(signed.manifest.decode('utf-8'))['files']
    prefix = f'command-relay-v{signed.download.info.latest}-windows/'
    with zipfile.ZipFile(io.BytesIO(signed.download.archive)) as archive:
        result = {}
        for name in names:
            with archive.open(prefix + name) as source:
                data = source.read(MAX_MEMBER_BYTES + 1)
            if len(data) > MAX_MEMBER_BYTES or hashlib.sha256(data).hexdigest() != hashes[name]:
                raise UpdateError('Rehearsal package bytes differ from manifest.')
            result[name] = data
    return result


def _write_rehearsal_file(path, data):
    import os
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())
    if path.read_bytes() != data:
        raise UpdateError('Rehearsal file readback differs.')


def _replace_rehearsal_file(source, destination, expected, replacement):
    import os
    _checked_path(source, directory=False)
    _checked_path(destination, directory=False)
    if source.read_bytes() != replacement or destination.read_bytes() != expected:
        raise UpdateError('Rehearsal file changed before replacement.')
    os.replace(source, destination)
    if destination.read_bytes() != replacement:
        raise UpdateError('Rehearsal replacement readback differs.')


def _verify_rehearsal_tree(root, files):
    for name, data in files.items():
        path = root / name
        _checked_path(path, directory=False)
        if path.read_bytes() != data:
            raise UpdateError('Rehearsal program tree differs.')


def rehearse_installation(installed, target):
    """Exercise backup, replacement and rollback on a fresh disposable tree.

    No destination argument, permission grant, live installation, restart, or
    execution. Both archives are authenticated before any disk write. Backups
    are prepared and read back before replacement; rollback restores the full
    signed original tree after success or a handled error. Atomic replacement
    is per file, not atomic across the tree. A hard kill or a failure during
    rollback is not recoverable by this rehearsal; durable recovery, process
    exclusion and real installation authorization are separate future work.
    """
    import tempfile

    if not all(isinstance(item, SignedUpdate) and isinstance(item.download, DownloadedUpdate)
               and isinstance(item.download.info, UpdateInfo) for item in (installed, target)):
        raise UpdateError('Expected two signed packages.')
    if installed.download.info.latest != VERSION or target.download.info.current != VERSION:
        raise UpdateError('Installation packages differ from the running version.')
    old = _verified_program_bytes(installed)
    new = _verified_program_bytes(target)
    try:
        with tempfile.TemporaryDirectory(prefix='command-relay-rehearsal-') as scratch:
            base = Path(scratch).resolve()
            root, backup, incoming = (base / name for name in ('portable', 'backup', 'incoming'))
            root.mkdir()
            for name, data in old.items():
                _write_rehearsal_file(root / name, data)
            plan = plan_installation(root, installed, target)
            # Prepare all backups and replacements before modifying the tree.
            for name in plan.replace:
                _write_rehearsal_file(backup / name, old[name])
                _write_rehearsal_file(incoming / name, new[name])
            failed = False
            try:
                for name in plan.replace:
                    _replace_rehearsal_file(incoming / name, root / name, old[name], new[name])
                _verify_rehearsal_tree(root, new)
            except (OSError, UpdateError):
                failed = True
            # Inspect the actual state, including a replacement that succeeded
            # before an exception was raised. Do not overwrite unknown bytes.
            try:
                for name in reversed(plan.replace):
                    destination = root / name
                    _checked_path(destination, directory=False)
                    actual = destination.read_bytes()
                    if actual == old[name]:
                        continue
                    if actual != new[name]:
                        raise UpdateError('Unknown rehearsal file state.')
                    _replace_rehearsal_file(backup / name, destination, new[name], old[name])
                _verify_rehearsal_tree(root, old)
            except (OSError, UpdateError):
                raise UpdateError('Rehearsal rollback could not be verified.') from None
            if failed:
                raise UpdateError('Rehearsal replacement failed; original tree restored.')
            return InstallRehearsal(plan.current, plan.target, plan.replace, True)
    except OSError:
        raise UpdateError('Unable to prepare or clean rehearsal.') from None


def _recovery_intent(installed, target, old, new):
    """Immutable intent binds both authenticated manifests and the replacement set."""
    return json.dumps({
        'schema': 'command-relay/rehearsal-recovery-v1',
        'current': installed.download.info.latest,
        'target': target.download.info.latest,
        'original_manifest_sha256': hashlib.sha256(installed.manifest).hexdigest(),
        'target_manifest_sha256': hashlib.sha256(target.manifest).hexdigest(),
        'replace': sorted(name for name in old if old[name] != new[name]),
    }, sort_keys=True, separators=(',', ':')).encode('utf-8')


def _recovery_packages(installed, target):
    if not all(isinstance(item, SignedUpdate) and isinstance(item.download, DownloadedUpdate)
               and isinstance(item.download.info, UpdateInfo) for item in (installed, target)):
        raise UpdateError('Expected two signed packages.')
    if installed.download.info.latest != VERSION or target.download.info.current != VERSION:
        raise UpdateError('Recovery packages differ from the running version.')
    old, new = _verified_program_bytes(installed), _verified_program_bytes(target)
    return old, new, _recovery_intent(installed, target, old, new)


def _prepare_recovery_rehearsal(base, installed, target):
    """Private helper for a freshly allocated disposable directory only."""
    old, new, intent = _recovery_packages(installed, target)
    _checked_path(base, directory=True)
    if any(base.iterdir()):
        raise UpdateError('Recovery rehearsal directory is not empty.')
    root, backup, incoming = (base / name for name in ('portable', 'backup', 'incoming'))
    for folder in (root, backup, incoming):
        folder.mkdir()
    for name, data in old.items():
        _write_rehearsal_file(root / name, data)
    plan = plan_installation(root, installed, target)
    for name in plan.replace:
        _write_rehearsal_file(backup / name, old[name])
        _write_rehearsal_file(incoming / name, new[name])
    # Flush the complete intent file before allowing any replacement. Directory
    # entry durability on Windows/power loss is not established by this test.
    _write_rehearsal_file(base / 'intent.json', intent)
    return plan


def _read_recovery_file(base, relative, limit):
    """Reject links, junctions, ambiguous names and oversized files."""
    path = base
    _checked_path(path, directory=True)
    parts = relative.split('/')
    for i, part in enumerate(parts):
        if [p.name for p in path.iterdir() if p.name.casefold() == part.casefold()] != [part]:
            raise UpdateError('Missing or ambiguous recovery path.')
        path = path / part
        info = _checked_path(path, directory=i < len(parts) - 1)
    if info.st_size > limit:
        raise UpdateError('Recovery file exceeds size limit.')
    with path.open('rb') as source:
        data = source.read(limit + 1)
    if len(data) != info.st_size or len(data) > limit:
        raise UpdateError('Recovery file size changed.')
    return data


def _recover_rehearsal(base, installed, target):
    """Reconstruct rollback from disk, not an in-memory progress counter.

    Internal disposable-tree prototype. Requires both original signed packages
    again. The immutable intent is retained for idempotent retries. No live
    destination, process exclusion, or power-loss guarantee.
    """
    old, new, intent = _recovery_packages(installed, target)
    try:
        if _read_recovery_file(base, 'intent.json', len(intent)) != intent:
            raise UpdateError('Recovery intent differs from signed packages.')
        # Preflight the entire tree and every required backup before any write.
        pending = []
        for name in sorted(old):
            actual = _read_recovery_file(base, 'portable/' + name, MAX_MEMBER_BYTES)
            if actual == old[name]:
                continue
            if actual != new[name]:
                raise UpdateError('Unknown recovery file state.')
            if _read_recovery_file(base, 'backup/' + name, MAX_MEMBER_BYTES) != old[name]:
                raise UpdateError('Recovery backup differs from signed original.')
            pending.append(name)
        for name in reversed(pending):
            _replace_rehearsal_file(base / 'backup' / name, base / 'portable' / name,
                                    new[name], old[name])
        for name, data in old.items():
            if _read_recovery_file(base, 'portable/' + name, MAX_MEMBER_BYTES) != data:
                raise UpdateError('Recovery original tree differs.')
        return tuple(pending)
    except OSError:
        raise UpdateError('Recovery interrupted or unavailable; retry requires verification.') from None


def rehearse_interrupted_installation(installed, target):
    """Simulate interruption after one replacement, then independently recover.

    The scratch tree is always disposable. No production destination argument.
    The simulation does not kill an OS process or establish power-loss safety.
    """
    import tempfile
    old, new, _ = _recovery_packages(installed, target)
    try:
        with tempfile.TemporaryDirectory(prefix='command-relay-recovery-') as scratch:
            base = Path(scratch).resolve()
            plan = _prepare_recovery_rehearsal(base, installed, target)
            if plan.replace:
                name = plan.replace[0]
                _replace_rehearsal_file(base / 'incoming' / name, base / 'portable' / name,
                                        old[name], new[name])
            restored = _recover_rehearsal(base, installed, target)
            if restored != plan.replace[:1] or _recover_rehearsal(base, installed, target):
                raise UpdateError('Recovery rehearsal was not idempotent.')
            return InstallRehearsal(plan.current, plan.target, restored, True)
    except OSError:
        raise UpdateError('Unable to complete recovery rehearsal.') from None


UPDATE_LOCK_NAME = '.relay-update.lock'
UPDATE_TRANSACTION_NAME = '.relay-update-transaction'


class RecoveryRequired(UpdateError):
    """A pending or unreadable transaction prevents normal startup."""


def _require_no_pending_transaction(root):
    """Call while holding installation_lock, before normal startup or planning.

    Any reserved name, including a malformed file, link or directory, blocks
    startup. Do not read, execute, remove or trust the marker here. A future
    updater must create the marker before replacing anything and retain it
    until the entire tree has been verified. This is a cooperative gate only.
    """
    try:
        for entry in Path(root).iterdir():
            if entry.name.rstrip(' .').casefold() == UPDATE_TRANSACTION_NAME.casefold():
                raise RecoveryRequired('An unfinished update requires recovery. Preserve the transaction files.')
    except OSError:
        raise RecoveryRequired('Unable to check for an unfinished update. Preserve the installation.') from None


@contextmanager
def installation_lock(root):
    """Nonblocking cooperative OS lock for one portable installation.

    The empty lock file is intentionally retained: unlinking a locked inode
    could create a second, independent lock. The OS releases the lock on exit
    or process termination. This is not an authorization, a sandbox, or a
    defence against a hostile same-user process replacing the directory/file.
    Both the application and updater must eventually hold this same lock for
    their entire critical lifetime. Not wired into startup in this change.
    """
    import os
    fd = None
    locked = False
    try:
        root = Path(root)
        if not root.is_absolute() or '..' in root.parts or root.parent == root:
            raise UpdateError('Expected an absolute non-root installation directory.')
        for parent in (*reversed(root.parents), root):
            _checked_path(parent, directory=True)
            try:
                (parent / '.git').lstat()
            except FileNotFoundError:
                pass
            else:
                raise UpdateError('Git checkout cannot be locked for updates.')
        path = root / UPDATE_LOCK_NAME
        # Check existing name before open; never truncate or write to it.
        try:
            _checked_path(path, directory=False)
        except FileNotFoundError:
            pass
        fd = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_BINARY', 0)
                     | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        info = _checked_path(path, directory=False)
        opened = os.fstat(fd)
        if (not os.path.samestat(info, opened) or opened.st_nlink != 1
                or opened.st_size != 0):
            raise UpdateError('Unsafe update lock file.')
        if os.name == 'nt':
            import msvcrt
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        elif os.name == 'posix':
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        else:
            raise UpdateError('Unsupported installation lock platform.')
        locked = True
        if not os.path.samestat(_checked_path(path, directory=False), os.fstat(fd)):
            raise UpdateError('Update lock identity changed.')
    except (OSError, ValueError, TypeError) as exc:
        if fd is not None:
            os.close(fd)
        raise UpdateError('Installation lock unavailable or already held.') from None
    except BaseException:
        if fd is not None:
            os.close(fd)
        raise
    try:
        yield
    finally:
        # Closing the non-inherited descriptor releases the OS lock. Never
        # delete the file, including on exceptions or lock acquisition failure.
        if locked:
            os.close(fd)


_gui_installation = ContextVar("gui_installation", default=None)


@contextmanager
def startup_installation_guard(root):
    """Guard supported portable launchers; leave source checkouts usable.

    The installer must still refuse any Git checkout. A marker in an ancestor
    is also a checkout exclusion. This is cooperative, not an update grant.
    """
    root = Path(root)
    try:
        if not root.is_absolute() or '..' in root.parts or root.parent == root:
            raise UpdateError('Expected an absolute non-root installation directory.')
        checkout = False
        for parent in (*reversed(root.parents), root):
            _checked_path(parent, directory=True)
            try:
                (parent / '.git').lstat()
            except FileNotFoundError:
                continue
            checkout = True
    except (OSError, ValueError, TypeError):
        raise UpdateError('Unable to inspect startup installation.') from None
    if checkout:
        yield
    else:
        with installation_lock(root):
            _require_no_pending_transaction(root)
            token = _gui_installation.set(root)
            try:
                yield
            finally:
                _gui_installation.reset(token)


def load_local_signed_package(folder, version, *, current):
    """Load four local release files with bounded reads and the pinned key.

    Local asset IDs are placeholders for the existing integrity validator, not
    GitHub identities. The detached publisher signature is the trust anchor.
    No network requests or extraction; caller must separately authorize writes.
    """
    _version(version)
    _version(current)
    if _version(version) <= _version(current):
        raise UpdateError('Expected a newer stable release.')
    try:
        folder = Path(folder)
        if not folder.is_absolute() or '..' in folder.parts or folder.parent == folder:
            raise UpdateError('Expected an absolute package directory.')
        for parent in (*reversed(folder.parents), folder):
            _checked_path(parent, directory=True)
        stem = f'command-relay-v{version}-windows'
        names = [stem + ext for ext in ('.zip', '.sha256', '.manifest.json', '.manifest.sig')]
        blobs = [_read_recovery_file(folder, name, limit) for name, limit in zip(
            names, (MAX_ARCHIVE, MAX_CHECKSUM, MAX_SIGNED_MANIFEST, 64))]
        raw, checksum, manifest, signature = blobs
        digest = hashlib.sha256(raw).hexdigest()
        if checksum != f'{digest}  {names[0]}\n'.encode('ascii'):
            raise UpdateError('Local archive checksum differs.')
        assets = [ReleaseAsset(name, i, len(blob), 'sha256:' + hashlib.sha256(blob).hexdigest())
                  for i, (name, blob) in enumerate(zip(names, blobs), 1)]
        info = UpdateInfo(current, version, 1, *assets)
        signed = SignedUpdate(DownloadedUpdate(info, raw, digest), manifest, signature)
        verify_publisher_package(signed.download, signed.manifest, signed.signature)
        return signed
    except (OSError, ValueError, TypeError):
        raise UpdateError('Unable to read local signed package.') from None


def inspect_local_installation(root, original_folder, target_folder, target_version):
    """Standalone preflight, no replacement, restart or installation grant.

    Hold the portable application lock throughout inspection. The empty lock
    file may be created, but program and user files are never written here.
    The result is only a snapshot; a later installer must revalidate under lock.
    """
    with installation_lock(root):
        _require_no_pending_transaction(root)
        # The original version is already installed; the synthetic comparison
        # baseline permits the existing newer-release validator to check it.
        original = load_local_signed_package(original_folder, VERSION, current='0.0.0')
        target = load_local_signed_package(target_folder, target_version, current=VERSION)
        return plan_installation(root, original, target)


def _check_transaction_layout(root):
    """Conservative prototype: reject unapproved entries in program directories.

    User-data directories are opaque and never traversed. Cache migration and
    other portable layouts are not enabled by this prototype.
    """
    allowed = {}
    for name in INSTALL_PROGRAM_FILES:
        parts = name.split('/')
        for i, part in enumerate(parts):
            allowed.setdefault('/'.join(parts[:i]), set()).add(part)
    user_files = {'settings.json', 'automation-permissions.json', 'startup.log',
                  'startup-timing.json', '.automation-permissions.lock', UPDATE_LOCK_NAME}
    user_dirs = {'reports', 'scripts', UPDATE_TRANSACTION_NAME}
    for relative, names in allowed.items():
        folder = root / relative
        _checked_path(folder, directory=True)
        for entry in folder.iterdir():
            if entry.name in names:
                continue
            if not relative and entry.name in user_files | user_dirs:
                _checked_path(entry, directory=entry.name in user_dirs)
                continue
            raise UpdateError('Unexpected entry in managed installation layout.')


def _pending_intent(installed, target, old, new):
    return _recovery_intent(installed, target, old, new).replace(
        b'command-relay/rehearsal-recovery-v1', b'command-relay/pending-update-v1')


def _apply_pending_update(root, installed, target):
    with installation_lock(root):
        return _apply_pending_update_locked(root, installed, target)


def _apply_pending_update_locked(root, installed, target):
    """Internal transaction prototype; not exposed by the standalone CLI.

    Under the shared lock, verify both packages and the existing tree. Keep
    the marker even after success: a separate finalization step must verify
    the target and release the startup gate. Any failure preserves evidence.
    No permission grant, dependency installation, restart or power-loss claim.
    """
    root = Path(root)
    _require_no_pending_transaction(root)
    old, new, _ = _recovery_packages(installed, target)
    plan = plan_installation(root, installed, target)
    _check_transaction_layout(root)
    marker = root / UPDATE_TRANSACTION_NAME
    try:
        marker.mkdir(mode=0o700)
        for name in plan.replace:
            _write_rehearsal_file(marker / 'backup' / name, old[name])
            _write_rehearsal_file(marker / 'incoming' / name, new[name])
        intent = _pending_intent(installed, target, old, new)
        _write_rehearsal_file(marker / 'intent.json', intent)
        # Recheck the complete original tree and journal before first write.
        plan_installation(root, installed, target)
        _check_transaction_layout(root)
        for name in plan.replace:
            for prefix, data in (('backup/', old[name]), ('incoming/', new[name])):
                if _read_recovery_file(marker, prefix + name, MAX_MEMBER_BYTES) != data:
                    raise UpdateError('Pending transaction staging differs.')
        for name in plan.replace:
            _replace_rehearsal_file(marker / 'incoming' / name, root / name,
                                    old[name], new[name])
        for name, data in new.items():
            if _read_recovery_file(root, name, MAX_MEMBER_BYTES) != data:
                raise UpdateError('Pending target tree differs.')
        return plan
    except OSError:
        raise UpdateError('Pending update interrupted; preserve transaction files.') from None


def _recover_pending_update(root, installed, target):
    with installation_lock(root):
        return _recover_pending_update_locked(root, installed, target)


def _recover_pending_update_locked(root, installed, target):
    """Restore authenticated original files under lock; retain the marker.

    Requires both signed packages and intact backups. Unknown contents or an
    incomplete intent are denied before any restoration. Backups are never
    consumed, so an interrupted restore can be retried. No CLI or finalizer.
    """
    import os
    import tempfile
    root = Path(root)
    old, new, _ = _recovery_packages(installed, target)
    marker = root / UPDATE_TRANSACTION_NAME
    intent = _pending_intent(installed, target, old, new)
    try:
        _check_transaction_layout(root)
        if _read_recovery_file(root, UPDATE_TRANSACTION_NAME + '/intent.json', len(intent)) != intent:
            raise UpdateError('Pending transaction intent differs.')
        pending = []
        for name in sorted(old):
            actual = _read_recovery_file(root, name, MAX_MEMBER_BYTES)
            if actual not in (old[name], new[name]):
                raise UpdateError('Unknown pending program file state.')
            if old[name] != new[name]:
                if _read_recovery_file(marker, 'backup/' + name, MAX_MEMBER_BYTES) != old[name]:
                    raise UpdateError('Pending transaction backup differs.')
                if actual != old[name]:
                    pending.append(name)
        for name in reversed(pending):
            # Unique same-volume restore file; the authenticated backup
            # remains intact even if this process dies after replacement.
            with tempfile.NamedTemporaryFile(dir=marker, prefix='restore-', delete=False) as stream:
                scratch = Path(stream.name)
                stream.write(old[name])
                stream.flush()
                os.fsync(stream.fileno())
            _replace_rehearsal_file(scratch, root / name, new[name], old[name])
        for name, data in old.items():
            if _read_recovery_file(root, name, MAX_MEMBER_BYTES) != data:
                raise UpdateError('Restored original tree differs.')
        return tuple(pending)
    except OSError:
        raise UpdateError('Pending recovery interrupted or unavailable; preserve evidence.') from None


def _finalize_pending_update(root, installed, target, *, outcome):
    with installation_lock(root):
        return _finalize_pending_update_locked(root, installed, target, outcome=outcome)


def _finalize_pending_update_locked(root, installed, target, *, outcome):
    """Release the startup gate only for a complete authenticated tree.

    Keep the journal and backups in a fresh sibling evidence directory. One
    same-volume directory rename removes the marker without partial deletion.
    This internal prototype grants no authority and executes no package code.
    The caller must retain both packages and explicitly choose the outcome.
    """
    import os
    import tempfile
    if outcome not in ('commit', 'rollback'):
        raise UpdateError('Expected explicit commit or rollback outcome.')
    root = Path(root)
    old, new, _ = _recovery_packages(installed, target)
    marker = root / UPDATE_TRANSACTION_NAME
    intent = _pending_intent(installed, target, old, new)
    try:
        _check_transaction_layout(root)
        if _read_recovery_file(root, UPDATE_TRANSACTION_NAME + '/intent.json', len(intent)) != intent:
            raise UpdateError('Pending transaction intent differs.')
        chosen = new if outcome == 'commit' else old
        for name in sorted(chosen):
            if _read_recovery_file(root, name, MAX_MEMBER_BYTES) != chosen[name]:
                raise UpdateError('Selected finalization tree differs.')
            if old[name] != new[name]:
                if _read_recovery_file(marker, 'backup/' + name, MAX_MEMBER_BYTES) != old[name]:
                    raise UpdateError('Pending transaction backup differs.')
        # Do not delete evidence or move it into user-data directories.
        # If the parent is not writable or rename fails, retain the gate.
        _checked_path(root.parent, directory=True)
        evidence = Path(tempfile.mkdtemp(prefix='.relay-update-evidence-', dir=root.parent))
        _checked_path(evidence, directory=True)
        os.rename(marker, evidence / UPDATE_TRANSACTION_NAME)
        return evidence / UPDATE_TRANSACTION_NAME
    except OSError:
        raise UpdateError('Finalization unavailable; inspect transaction and evidence directories.') from None


@dataclass(frozen=True)
class PreparedUpdateHandoff:
    """External signed inputs and original program copy, not launch authority."""
    directory: Path
    updater_root: Path
    original_folder: Path
    target_folder: Path
    plan: InstallPlan
    original_sha256: str
    target_sha256: str


def _write_handoff_package(folder, signed):
    stem = signed.download.info.archive.name[:-4]
    blobs = {'.zip': signed.download.archive,
             '.sha256': f'{signed.download.sha256}  {stem}.zip\n'.encode('ascii'),
             '.manifest.json': signed.manifest, '.manifest.sig': signed.signature}
    folder.mkdir(mode=0o700)
    for extension, data in blobs.items():
        _write_rehearsal_file(folder / (stem + extension), data)


def prepare_update_handoff(root, original, target):
    """Prepare a separate original-version updater and both signed packages.

    No execution, permission mutation, installation or restart. The portable
    tree is only inspected (the cooperative lock file may be created). The
    bundle is retained outside the installation, including on partial failure.
    A later launch must independently authenticate the bundle and its code.
    """
    with installation_lock(root):
        return _prepare_update_handoff_locked(Path(root), original, target)


def _prepare_update_handoff_locked(root, original, target):
    import tempfile
    _require_no_pending_transaction(root)
    old, new, _ = _recovery_packages(original, target)
    plan = plan_installation(root, original, target)
    _check_transaction_layout(root)
    if old['requirements.txt'] != new['requirements.txt']:
        raise UpdateError('Dependency changes require manual installation.')
    try:
        directory = Path(tempfile.mkdtemp(prefix='.relay-update-handoff-', dir=root.parent))
        _checked_path(directory, directory=True)
        updater = directory / 'updater'
        updater.mkdir(mode=0o700)
        for name, data in sorted(old.items()):
            _write_rehearsal_file(updater / name, data)
        original_folder, target_folder = directory / 'original', directory / 'target'
        _write_handoff_package(original_folder, original)
        _write_handoff_package(target_folder, target)
        # Reopen all assets through the same bounded, pinned-key reader used
        # by the standalone updater. Never use unsigned metadata for trust.
        reopened_old = load_local_signed_package(original_folder, VERSION, current='0.0.0')
        reopened_new = load_local_signed_package(target_folder, plan.target, current=VERSION)
        for before, after in ((original, reopened_old), (target, reopened_new)):
            if (before.download.archive, before.manifest, before.signature) != (
                    after.download.archive, after.manifest, after.signature):
                raise UpdateError('Prepared handoff package differs.')
        plan_installation(updater, reopened_old, reopened_new)
        _check_transaction_layout(updater)
        return PreparedUpdateHandoff(directory, updater, original_folder, target_folder, plan,
                                     original.download.sha256, target.download.sha256)
    except OSError:
        raise UpdateError('Unable to prepare external handoff; preserve any partial bundle.') from None


def gui_handoff_available(root):
    """Only the guarded portable GUI on Windows can request a handoff."""
    import os
    return os.name == 'nt' and _gui_installation.get() == Path(root)


def prepare_gui_update_handoff(root, original_folder, target):
    """Called on the guarded GUI thread; no recursive installation lock.

    Retained target bytes are reauthenticated by preparation. The original
    package must be supplied separately; neither a source checkout nor an
    unguarded Qt entry point can prepare an installation handoff.
    """
    root = Path(root)
    if not gui_handoff_available(root):
        raise UpdateError('Portable Windows application startup guard required.')
    _require_no_pending_transaction(root)
    _require_install_permission(root)
    original = load_local_signed_package(original_folder, VERSION, current='0.0.0')
    return _prepare_update_handoff_locked(root, original, target)


def _verify_handoff_launch_locked(handoff, *, action):
    """Authenticate the external code and assets before starting any interpreter."""
    if not isinstance(handoff, PreparedUpdateHandoff) or action not in ('inspect', 'install', 'recover'):
        raise UpdateError('Invalid external handoff or action.')
    root, directory = handoff.plan.root, handoff.directory
    if (directory.parent != root.parent or not directory.name.startswith('.relay-update-handoff-')
            or handoff.updater_root != directory / 'updater'
            or handoff.original_folder != directory / 'original'
            or handoff.target_folder != directory / 'target'):
        raise UpdateError('Unexpected external handoff layout.')
    _checked_path(directory, directory=True)
    if {p.name for p in directory.iterdir()} != {'updater', 'original', 'target'}:
        raise UpdateError('Unexpected entry in external handoff.')
    original = load_local_signed_package(handoff.original_folder, VERSION, current='0.0.0')
    target = load_local_signed_package(handoff.target_folder, handoff.plan.target, current=VERSION)
    if (original.download.sha256, target.download.sha256) != (handoff.original_sha256, handoff.target_sha256):
        raise UpdateError('Handoff package differs from prepared package.')
    old, new, _ = _recovery_packages(original, target)
    if old['requirements.txt'] != new['requirements.txt']:
        raise UpdateError('Dependency changes require manual installation.')
    plan_installation(handoff.updater_root, original, target)
    # A signed file set is insufficient if an extra Python module or bytecode
    # can shadow an import. Deny every extra entry in the executable copy.
    directories = {}
    for name in old:
        parts = name.split('/')
        for i, part in enumerate(parts):
            directories.setdefault('/'.join(parts[:i]), set()).add(part)
    for relative, names in directories.items():
        folder = handoff.updater_root / relative
        _checked_path(folder, directory=True)
        if {entry.name for entry in folder.iterdir()} != names:
            raise UpdateError('Unexpected entry in external updater code.')
    if action == 'recover':
        _check_transaction_layout(root)
        _checked_path(root / UPDATE_TRANSACTION_NAME, directory=True)
        intent = _pending_intent(original, target, old, new)
        if _read_recovery_file(root, UPDATE_TRANSACTION_NAME + '/intent.json', len(intent)) != intent:
            raise UpdateError('Pending transaction intent differs.')
    else:
        _require_no_pending_transaction(root)
        if plan_installation(root, original, target) != handoff.plan:
            raise UpdateError('Installation differs from prepared plan.')
        _check_transaction_layout(root)
        if action == 'install':
            _require_install_permission(root)


def launch_prepared_updater(handoff, *, action):
    """Launch a reauthenticated external updater, after the GUI lock is released.

    Use the current trusted Python runtime (not code in the destination), with
    isolated imports and no shell. The child reacquires the lock, rechecks its
    inputs, and requires interactive consent for writes. Launch is not consent
    or a transaction result. The cooperative check-to-launch gap is not a
    hostile same-user boundary. No automatic restart or GUI shutdown here.
    """
    import os
    import subprocess
    import sys
    if not isinstance(handoff, PreparedUpdateHandoff):
        raise UpdateError('Invalid external handoff.')
    root = handoff.plan.root
    try:
        with installation_lock(root):
            _verify_handoff_launch_locked(handoff, action=action)
            executable = Path(sys.executable)
            if not executable.is_absolute():
                raise UpdateError('Trusted Python executable unavailable.')
            if os.name == 'nt' and executable.name.casefold() == 'pythonw.exe':
                executable = executable.with_name('python.exe')
            # Preserve the invocation path for a virtual environment, while
            # also checking the resolved executable and active runtime prefix.
            resolved = executable.resolve(strict=True)
            if not resolved.is_file():
                raise UpdateError('Trusted Python executable unavailable.')
            runtime_paths = (executable, resolved, Path(sys.prefix).resolve(strict=True))
            if any(runtime.is_relative_to(p.resolve(strict=True))
                   for p in (root, handoff.directory) for runtime in runtime_paths):
                raise UpdateError('Python executable must be outside the installation and handoff.')
            if action != 'inspect' and os.name != 'nt' and not (
                    sys.stdin is not None and sys.stderr is not None
                    and sys.stdin.isatty() and sys.stderr.isatty()):
                raise UpdateError('Interactive terminal required for external updater.')
            # -I ignores PYTHONPATH, user site, and the working directory;
            # add only the authenticated tree explicitly, and do not write pyc.
            bootstrap = ("import sys, runpy; sys.path.insert(0, sys.argv.pop(1)); "
                         "runpy.run_module('command_relay.relay_updates', run_name='__main__')")
            argv = [str(executable), '-I', '-B', '-c', bootstrap, str(handoff.updater_root),
                    '--' + action, '--root', str(root), '--original', str(handoff.original_folder),
                    '--target', str(handoff.target_folder), '--target-version', handoff.plan.target]
        # Do not spawn while holding the lock: the child must acquire it itself.
        # If another application wins the race, the child fails closed.
        return subprocess.Popen(argv, cwd=str(handoff.updater_root), shell=False,
                                close_fds=True, creationflags=(subprocess.CREATE_NEW_CONSOLE
                                    if os.name == 'nt' and action != 'inspect' else 0))
    except (OSError, TypeError, ValueError) as exc:
        raise UpdateError('Unable to launch external updater; preserve the handoff bundle.') from None


def _require_install_permission(root):
    """Read the destination policy, not the standalone copy's policy."""
    from .relay_permissions import KEY, AUDIT_KEY, allowed, audit_history
    try:
        def pending():
            return any(p.name.rstrip(' .').casefold() == '.automation-permissions.lock'
                       for p in root.iterdir())
        if pending():
            raise UpdateError('Update installation permission unavailable.')
        raw = _read_recovery_file(root, 'automation-permissions.json', 1_000_000)
        policy = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_object)
        if (not isinstance(policy, dict) or set(policy) - {KEY, AUDIT_KEY}
                or not allowed(policy, 'update_install')):
            raise UpdateError('Update installation permission not granted.')
        audit_history(policy)
        if pending():
            raise UpdateError('Update installation permission unavailable.')
    except (OSError, ValueError, TypeError, RecursionError):
        raise UpdateError('Update installation permission unavailable.') from None


def _confirm_update_operation(action, root, original, target):
    """Explicit local terminal approval, never read redirected input."""
    import sys
    if not (sys.stdin.isatty() and sys.stderr.isatty()):
        raise UpdateError('Interactive terminal confirmation required.')
    token = f'{action.upper()} {target.download.info.latest}'
    print(f'Installation: {str(root)!r}\nAction: {action}\n'
          f'Original: {original.download.info.latest} {original.download.sha256}\n'
          f'Target: {target.download.info.latest} {target.download.sha256}\n'
          f'Type {token!r} to confirm:', file=sys.stderr, flush=True)
    if sys.stdin.readline(128).rstrip('\r\n') != token:
        raise UpdateError('Update operation not confirmed.')


def _run_local_transaction(root, original_folder, target_folder, target_version, *, action):
    """Manual standalone write coordinator; no restart or permission changes.

    Run from a separately trusted copy of the original version. Hold one
    cooperative lock from inspection and consent through finalization. A
    failure retains evidence for explicitly requested rollback; do not guess
    the outcome or remove an incomplete marker. No power-loss guarantee.
    """
    if action not in ('install', 'recover'):
        raise UpdateError('Unsupported transaction action.')
    root = Path(root)
    with installation_lock(root):
        code = Path(__file__).resolve().parent.parent
        resolved = root.resolve(strict=True)
        if code == resolved or code.is_relative_to(resolved) or resolved.is_relative_to(code):
            raise UpdateError('Run the updater from a separate trusted copy.')
        if action == 'install':
            _require_no_pending_transaction(root)
            _require_install_permission(root)
        original = load_local_signed_package(original_folder, VERSION, current='0.0.0')
        target = load_local_signed_package(target_folder, target_version, current=VERSION)
        old, new, _ = _recovery_packages(original, target)
        if action == 'install':
            plan_installation(root, original, target)
            _check_transaction_layout(root)
            if old['requirements.txt'] != new['requirements.txt']:
                raise UpdateError('Dependency changes require manual installation.')
        _confirm_update_operation(action, root, original, target)
        if action == 'install':
            # Re-read permission after confirmation, immediately before writes.
            _require_install_permission(root)
            _apply_pending_update_locked(root, original, target)
            outcome = 'commit'
        else:
            # Explicit repair is not an automatic installation grant. Permit
            # restoring the signed original even if installation was revoked.
            _recover_pending_update_locked(root, original, target)
            outcome = 'rollback'
        evidence = _finalize_pending_update_locked(root, original, target, outcome=outcome)
        return {'schema': 'command-relay/update-transaction-v1', 'outcome': outcome,
                'version': target_version if outcome == 'commit' else VERSION,
                'evidence': str(evidence), 'restart_performed': False}


def updater_main(argv=None):
    """Standalone updater entry point (no Qt, restart or package execution)."""
    import argparse
    import sys
    parser = argparse.ArgumentParser(description='Inspect or explicitly update a signed portable installation.')
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--inspect', action='store_true', help='Inspect only')
    modes.add_argument('--install', action='store_true', help='Install with permission and terminal confirmation')
    modes.add_argument('--recover', action='store_true', help='Restore signed original with terminal confirmation')
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--original', required=True, type=Path)
    parser.add_argument('--target', required=True, type=Path)
    parser.add_argument('--target-version', required=True)
    args = parser.parse_args(argv)
    try:
        if not args.inspect:
            result = _run_local_transaction(args.root, args.original, args.target,
                                            args.target_version,
                                            action='install' if args.install else 'recover')
            print(json.dumps(result, sort_keys=True))
            return 0
        plan = inspect_local_installation(args.root, args.original, args.target, args.target_version)
    except (UpdateError, OSError, KeyboardInterrupt) as exc:
        print(f'Update operation denied: {exc}' if isinstance(exc, UpdateError) else
              'Update operation interrupted or unavailable; preserve transaction evidence.', file=sys.stderr)
        return 1
    print(json.dumps({'schema': 'command-relay/update-preflight-v1', 'current': plan.current,
                      'target': plan.target, 'replace': list(plan.replace),
                      'unchanged': list(plan.unchanged), 'installation_authorized': False},
                     sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(updater_main())
