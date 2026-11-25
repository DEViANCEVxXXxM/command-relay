# SPDX-License-Identifier: Apache-2.0
"""Offline release signing from a separately reviewed source checkout."""
import argparse
import getpass
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import warnings
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from command_relay import relay_updates as updates
from command_relay.relay_version import VERSION
from tools.build_release import build, RELEASE_FILES


def create_signed_manifest(archive_path, key):
    """Sign only a ZIP matching the reviewed local release source files.

    No network access, extraction, private key persistence, or publication.
    The caller must independently establish that this checkout is trustworthy.
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    if not isinstance(key, Ed25519PrivateKey):
        raise updates.UpdateError('Expected an Ed25519 private key.')
    pinned = updates.PUBLISHER_PUBLIC_KEY
    public = key.public_key().public_bytes(serialization.Encoding.Raw,
                                           serialization.PublicFormat.Raw)
    if not isinstance(pinned, bytes) or len(pinned) != 32 or public != pinned:
        raise updates.UpdateError('Private key does not match the pinned publisher key.')
    stem = f'command-relay-v{VERSION}-windows'
    archive_path = Path(archive_path)
    if archive_path.name != stem + '.zip':
        raise updates.UpdateError('Archive name differs from the reviewed version.')
    with archive_path.open('rb') as stream:
        raw = stream.read(updates.MAX_ARCHIVE + 1)
    if not 0 < len(raw) <= updates.MAX_ARCHIVE:
        raise updates.UpdateError('Archive exceeds size limit.')
    digest = hashlib.sha256(raw).hexdigest()
    # The synthetic identities are local validation inputs, not GitHub metadata.
    info = updates.UpdateInfo('0.0.0', VERSION, 1,
                              updates.ReleaseAsset(stem + '.zip', 2, len(raw), 'sha256:' + digest),
                              updates.ReleaseAsset(stem + '.sha256', 3, 1, 'sha256:' + '0' * 64))
    downloaded = updates.DownloadedUpdate(info, raw, digest)
    with tempfile.TemporaryDirectory(prefix='relay-sign-reference-') as tmp:
        reference, _ = build(Path(tmp), 'v' + VERSION)
        with zipfile.ZipFile(reference) as local:
            expected = {name: hashlib.sha256(local.read(stem + '/' + name)).hexdigest()
                        for name in RELEASE_FILES}
    updates.inspect_package(downloaded, expected)
    manifest = (json.dumps({'schema': updates.MANIFEST_SCHEMA, 'repository': updates.REPOSITORY,
                            'version': VERSION, 'archive': {'name': archive_path.name,
                            'size': len(raw), 'sha256': digest}, 'files': expected},
                           sort_keys=True, separators=(',', ':'), ensure_ascii=True) + '\n').encode('ascii')
    signature = key.sign(manifest)
    updates.verify_publisher_package(downloaded, manifest, signature)
    return manifest, signature


def main():
    from cryptography.hazmat.primitives.serialization import load_pem_private_key

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--key', type=Path, required=True, help='Encrypted offline Ed25519 PEM')
    parser.add_argument('--out', type=Path, required=True, help='New output directory (must not exist)')
    parser.add_argument('--tag', required=True, help='Exact reviewed release tag')
    args = parser.parse_args()
    if args.tag != 'v' + VERSION or updates.PUBLISHER_PUBLIC_KEY is None:
        parser.error('Wrong tag or publisher key not provisioned.')
    if not sys.stdin.isatty() or not sys.stderr.isatty():
        parser.error('An interactive terminal is required; never use Command Relay to enter the password.')
    if args.out.exists() or args.out.is_symlink():
        parser.error('Output directory must not exist.')
    try:
        with args.key.open('rb') as stream:
            pem = stream.read(16385)
        if len(pem) > 16384 or not pem.startswith(b'-----BEGIN ENCRYPTED PRIVATE KEY-----'):
            raise ValueError('Encrypted PKCS8 PEM required.')
        with warnings.catch_warnings():
            warnings.simplefilter('error', getpass.GetPassWarning)
            password = getpass.getpass('Offline signing key password: ').encode('utf-8')
        key = load_pem_private_key(pem, password=password)
        manifest, signature = create_signed_manifest(args.archive, key)
        args.out.mkdir()  # exclusive; never overwrite an existing output directory
        stem = args.archive.stem
        (args.out / (stem + '.manifest.json')).write_bytes(manifest)
        (args.out / (stem + '.manifest.sig')).write_bytes(signature)
    except (OSError, ValueError, TypeError, updates.UpdateError, getpass.GetPassWarning):
        parser.exit(1, 'Signing failed; do not publish partial output.\n')
    print('Manifest and detached signature created. Review before publishing.')


if __name__ == '__main__':
    main()
