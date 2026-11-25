# SPDX-License-Identifier: Apache-2.0
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from command_relay import relay_updates as u
from tools.build_release import build, RELEASE_FILES
from tools.sign_release import create_signed_manifest


class OfflineSigningTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.archive, _ = build(self.root / 'reference')
        self.key = Ed25519PrivateKey.generate()
        public = self.key.public_key().public_bytes(serialization.Encoding.Raw,
                                                    serialization.PublicFormat.Raw)
        pin = patch.object(u, 'PUBLISHER_PUBLIC_KEY', public)
        pin.start()
        self.addCleanup(pin.stop)

    def test_exact_manifest_and_signature(self):
        manifest, sig = create_signed_manifest(self.archive, self.key)
        self.key.public_key().verify(sig, manifest)
        data = json.loads(manifest)
        self.assertEqual(data['archive']['sha256'], hashlib.sha256(self.archive.read_bytes()).hexdigest())
        self.assertEqual(set(data['files']), set(RELEASE_FILES))
        self.assertEqual((manifest, sig), create_signed_manifest(self.archive, self.key))

    def test_unprovisioned_key(self):
        with patch.object(u, 'PUBLISHER_PUBLIC_KEY', None), self.assertRaises(u.UpdateError):
            create_signed_manifest(self.archive, self.key)

    def test_wrong_key(self):
        with self.assertRaises(u.UpdateError):
            create_signed_manifest(self.archive, Ed25519PrivateKey.generate())

    def test_wrong_archive_name(self):
        with self.assertRaises(u.UpdateError):
            create_signed_manifest(self.root / 'other.zip', self.key)

    def repack(self, tamper=False):
        directory = self.root / 'cloud'
        directory.mkdir()
        target = directory / self.archive.name
        with zipfile.ZipFile(self.archive) as src, zipfile.ZipFile(target, 'w') as dest:
            for i, member in enumerate(src.infolist()):
                content = src.read(member)
                if tamper and i == 0:
                    content += b'changed'
                dest.writestr(member, content, compress_type=zipfile.ZIP_STORED)
        return target

    def test_different_zip_encoding_same_files(self):
        cloud = self.repack()
        self.assertNotEqual(cloud.read_bytes(), self.archive.read_bytes())
        manifest, sig = create_signed_manifest(cloud, self.key)
        self.key.public_key().verify(sig, manifest)
        self.assertEqual(json.loads(manifest)['archive']['sha256'], hashlib.sha256(cloud.read_bytes()).hexdigest())

    def test_modified_file_rejected(self):
        with self.assertRaises(u.UpdateError):
            create_signed_manifest(self.repack(tamper=True), self.key)
