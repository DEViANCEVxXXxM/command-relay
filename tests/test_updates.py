# SPDX-License-Identifier: Apache-2.0
import copy
import hashlib
import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from command_relay import relay_updates as u


def release(version='4.10.0'):
    stem = f'command-relay-v{version}-windows'
    return {'id': 1, 'tag_name': 'v' + version, 'draft': False, 'prerelease': False,
            'assets': [{'id': i, 'name': stem + ext, 'state': 'uploaded', 'size': 99,
                        'digest': 'sha256:' + 'a' * 64}
                       for i, ext in enumerate(('.zip', '.sha256'), 2)]}


class Response(io.BytesIO):
    status = 200
    def geturl(self):
        return u.LATEST_API


class UpdateTests(unittest.TestCase):
    def test_numeric_comparison(self):
        for latest, current, expected in [('4.10.0', '4.9.0', True), ('4.2.0', '4.2.0', False),
                                          ('4.1.9', '4.2.0', False), ('5.0.0', '4.99.99', True)]:
            with self.subTest(latest=latest, current=current):
                self.assertEqual(u.parse_latest(release(latest), current).available, expected)

    def test_release_url_is_constructed(self):
        data = release()
        data['html_url'] = 'https://untrusted.invalid/'
        data['assets'][0]['browser_download_url'] = 'https://untrusted.invalid/file'
        result = u.parse_latest(data)
        self.assertEqual(result.release_url, 'https://github.com/' + u.REPOSITORY + '/releases/tag/v4.10.0')
        self.assertEqual(result.archive.asset_id, 2)

    def test_reject_bad_versions(self):
        for tag in ('4.2.0', 'v04.2.0', 'v4.2.0-rc1', 'v4.2', 'v4.2.0\n', 'v9999999.0.0'):
            with self.subTest(tag=tag), self.assertRaises(u.UpdateError):
                u.parse_latest(dict(release(), tag_name=tag))
        with self.assertRaises(u.UpdateError):
            u.parse_latest(release(), '4.2')

    def test_reject_draft_prerelease_and_invalid_release_id(self):
        for changes in ({'draft': True}, {'prerelease': True}, {'draft': None}, {'id': True}, {'id': 0}):
            with self.subTest(changes=changes), self.assertRaises(u.UpdateError):
                u.parse_latest(dict(release(), **changes))

    def test_missing_and_duplicate_assets(self):
        data = release()
        for assets in ([], data['assets'][:1], data['assets'] + [data['assets'][0]], [None]):
            with self.subTest(assets=assets), self.assertRaises(u.UpdateError):
                u.parse_latest(dict(data, assets=assets))

    def test_bad_asset_metadata(self):
        for changes in ({'id': True}, {'id': 3}, {'size': 0}, {'state': 'new'}, {'digest': 'bad'}):
            data = copy.deepcopy(release())
            data['assets'][0].update(changes)
            with self.subTest(changes=changes), self.assertRaises(u.UpdateError):
                u.parse_latest(data)

    def test_missing_digest_is_not_a_trust_claim(self):
        data = release()
        data['assets'][0].pop('digest')
        self.assertIsNone(u.parse_latest(data).archive.digest)

    @patch.object(u, 'build_opener')
    def test_fixed_endpoint_get_and_no_auth(self, opener):
        opener.return_value.open.return_value = Response(json.dumps(release()).encode())
        self.assertTrue(u.check_latest('4.2.0').available)
        args, kwargs = opener.return_value.open.call_args
        req = args[0]
        self.assertEqual(req.full_url, u.LATEST_API)
        self.assertEqual(req.get_method(), 'GET')
        self.assertNotIn('Authorization', req.headers)
        self.assertEqual(kwargs, {'timeout': u.SOCKET_TIMEOUT})
        self.assertIsInstance(opener.call_args.args[0], u._NoRedirect)

    def test_redirect_rejected(self):
        with self.assertRaises(u.UpdateError):
            u._NoRedirect().redirect_request(None, None, 302, '', {}, 'https://untrusted.invalid')

    @patch.object(u, 'build_opener')
    def test_bad_responses(self, opener):
        for raw in (b'\xff', b'not json', b'{"id":1,"id":2}', b'x' * (u.MAX_RESPONSE + 1)):
            opener.return_value.open.return_value = Response(raw)
            with self.subTest(length=len(raw)), self.assertRaises(u.UpdateError):
                u.check_latest()

    @patch.object(u, 'build_opener')
    def test_network_errors_safe(self, opener):
        for exc in (URLError('private URL'), TimeoutError('private path'), HTTPError(u.LATEST_API, 403, 'private', {}, None)):
            opener.return_value.open.side_effect = exc
            with self.assertRaises(u.UpdateError) as ctx:
                u.check_latest()
            self.assertNotIn('private', str(ctx.exception))


class AssetResponse(io.BytesIO):
    status = 200
    def __init__(self, data, url='https://release-assets.githubusercontent.com/example'):
        super().__init__(data)
        self.url = url

    def geturl(self):
        return self.url


class DownloadTests(unittest.TestCase):
    def fixture(self, checksum=None):
        import hashlib
        data = release()
        archive = b'example archive bytes'
        digest = hashlib.sha256(archive).hexdigest()
        if checksum is None:
            checksum = (digest + '  ' + data['assets'][0]['name'] + '\n').encode('ascii')
        for asset, content in zip(data['assets'], (archive, checksum)):
            asset.update(size=len(content), digest='sha256:' + hashlib.sha256(content).hexdigest())
        return u.parse_latest(data, '4.2.0'), archive, checksum

    @patch.object(u, 'build_opener')
    def test_download_and_exact_fixed_urls(self, opener):
        info, archive, checksum = self.fixture()
        opener.return_value.open.side_effect = [AssetResponse(checksum), AssetResponse(archive)]
        result = u.download_update(info)
        self.assertEqual(result.archive, archive)
        self.assertEqual(result.sha256, info.archive.digest[7:])
        self.assertEqual(result.info, info)
        for call, asset in zip(opener.return_value.open.call_args_list, (info.checksum, info.archive)):
            req = call.args[0]
            self.assertEqual(req.full_url, 'https://github.com/' + u.REPOSITORY + '/releases/download/v4.10.0/' + asset.name)
            self.assertEqual(req.get_method(), 'GET')
            self.assertNotIn('Authorization', req.headers)
            self.assertEqual(call.kwargs, {'timeout': u.SOCKET_TIMEOUT})
        self.assertEqual(opener.return_value.open.call_count, 2)

    @patch.object(u, 'build_opener')
    def test_no_network_for_invalid_metadata_or_downgrade(self, opener):
        from dataclasses import replace
        info, _, _ = self.fixture()
        for candidate in (replace(info, current=info.latest), replace(info, current='5.0.0'),
                          replace(info, release_id=True), replace(info, archive=replace(info.archive, size=u.MAX_ARCHIVE+1)),
                          replace(info, checksum=replace(info.checksum, size=u.MAX_CHECKSUM+1)),
                          replace(info, archive=replace(info.archive, digest=None)),
                          replace(info, checksum=replace(info.checksum, digest=None)),
                          replace(info, archive=replace(info.archive, name='../bad.zip')),
                          replace(info, checksum=replace(info.checksum, asset_id=info.archive.asset_id))):
            with self.subTest(candidate=candidate), self.assertRaises(u.UpdateError):
                u.download_update(candidate)
        opener.assert_not_called()

    @patch.object(u, 'build_opener')
    def test_checksum_file_must_match_exactly_before_archive_download(self, opener):
        for checksum in (b'0'*64+b'  wrong.zip\n', b'bad', b'0'*64+b'  command-relay-v4.10.0-windows.zip\n'):
            info, _, content = self.fixture(checksum)
            opener.return_value.open.reset_mock()
            opener.return_value.open.return_value = AssetResponse(content)
            with self.assertRaisesRegex(u.UpdateError, 'checksum file'):
                u.download_update(info)
            self.assertEqual(opener.return_value.open.call_count, 1)

    @patch.object(u, 'build_opener')
    def test_truncated_or_oversized_archive(self, opener):
        info, archive, checksum = self.fixture()
        for altered in (archive[:-1], archive+b'extra'):
            opener.return_value.open.side_effect = [AssetResponse(checksum), AssetResponse(altered)]
            with self.assertRaisesRegex(u.UpdateError, 'size differs'):
                u.download_update(info)

    @patch.object(u, 'build_opener')
    def test_corrupt_archive_same_length(self, opener):
        info, archive, checksum = self.fixture()
        opener.return_value.open.side_effect = [AssetResponse(checksum), AssetResponse(b'x'*len(archive))]
        with self.assertRaisesRegex(u.UpdateError, 'digest differs'):
            u.download_update(info)

    @patch.object(u, 'build_opener')
    def test_corrupt_checksum_same_length(self, opener):
        info, _, checksum = self.fixture()
        opener.return_value.open.return_value = AssetResponse(b'x'*len(checksum))
        with self.assertRaisesRegex(u.UpdateError, 'digest differs'):
            u.download_update(info)
        self.assertEqual(opener.return_value.open.call_count, 1)

    def test_redirect_allowlist(self):
        from urllib.request import Request
        handler = u._AssetRedirect()
        req = Request('https://github.com/example', headers={'User-Agent': 'Command-Relay/4.2.0'})
        for url in ('https://release-assets.githubusercontent.com/path?token=abc',
                    'https://objects.githubusercontent.com/path'):
            self.assertEqual(handler.redirect_request(req, None, 302, '', {}, url).full_url, url)
        for url in ('http://release-assets.githubusercontent.com/path', 'https://github.com/other',
                    'https://release-assets.githubusercontent.com.evil.invalid/path',
                    'https://user@release-assets.githubusercontent.com/path',
                    'https://release-assets.githubusercontent.com:444/path',
                    'https://objects.githubusercontent.com/path#fragment', 'file:///tmp/file'):
            with self.subTest(url=url), self.assertRaises(u.UpdateError):
                handler.redirect_request(req, None, 302, '', {}, url)

    @patch.object(u, 'build_opener')
    def test_reject_unexpected_final_url_or_status(self, opener):
        info, _, checksum = self.fixture()
        bad_url = AssetResponse(checksum, 'https://untrusted.invalid/path')
        bad_status = AssetResponse(checksum)
        bad_status.status = 206
        for response in (bad_url, bad_status):
            opener.return_value.open.return_value = response
            with self.assertRaisesRegex(u.UpdateError, 'Unexpected release asset response'):
                u.download_update(info)

    @patch.object(u, 'build_opener')
    def test_network_failure_does_not_leak_redirect_url(self, opener):
        info, _, _ = self.fixture()
        from http.client import IncompleteRead
        for exc in (URLError('private signed URL'), IncompleteRead(b'private', 2)):
            opener.return_value.open.side_effect = exc
            with self.assertRaises(u.UpdateError) as ctx:
                u.download_update(info)
            self.assertNotIn('private', str(ctx.exception))


class PackageTests(unittest.TestCase):
    def package(self, entries, compression=None):
        import hashlib
        import zipfile
        import warnings
        from dataclasses import replace
        info, _, _ = DownloadTests().fixture()
        buf = io.BytesIO()
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            with zipfile.ZipFile(buf, 'w') as z:
                for name, data, mode in entries:
                    item = zipfile.ZipInfo('command-relay-v4.10.0-windows/' + name)
                    item.create_system = 3
                    item.external_attr = mode << 16
                    z.writestr(item, data, compress_type=compression or zipfile.ZIP_STORED)
        raw = buf.getvalue()
        digest = hashlib.sha256(raw).hexdigest()
        info = replace(info, archive=replace(info.archive, size=len(raw), digest='sha256:'+digest))
        return u.DownloadedUpdate(info, raw, digest)

    def manifest(self, **files):
        import hashlib
        return {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}

    def test_exact_package(self):
        import zipfile
        entries = [('Start.pyw', b'start', 0o100644), ('command_relay/core.py', b'code', 0o100644)]
        manifest = self.manifest(**{'Start.pyw': b'start', 'command_relay/core.py': b'code'})
        for method in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            self.assertEqual(u.inspect_package(self.package(entries, method), manifest), tuple(sorted(manifest)))

    def test_reject_unexpected_paths(self):
        for name in ('../Start.pyw', '/Start.pyw', 'C:/Start.pyw', 'a\\Start.pyw', 'START.pyw', 'settings.json'):
            with self.subTest(name=name), self.assertRaises(u.UpdateError):
                u.inspect_package(self.package([(name, b'x', 0o100644)]), self.manifest(**{'Start.pyw': b'x'}))

    def test_reject_unsafe_manifest(self):
        p = self.package([('Start.pyw', b'x', 0o100644)])
        for name in ('../x', 'C:/x', 'a\\b', '/x', 'aux.txt', 'x/COM1.py', 'trailing.', 'a//b', 'a:b', 'a b', 'x\x00y'):
            with self.subTest(name=name), self.assertRaises(u.UpdateError):
                u.inspect_package(p, self.manifest(**{name: b'x'}))
        for names in (('a', 'A'), ('a', 'A/b')):
            with self.assertRaises(u.UpdateError):
                u.inspect_package(p, self.manifest(**dict.fromkeys(names, b'x')))

    def test_reject_duplicate_and_missing_members(self):
        p = self.package([('a', b'x', 0o100644), ('a', b'x', 0o100644)])
        with self.assertRaises(u.UpdateError):
            u.inspect_package(p, self.manifest(a=b'x', b=b'x'))
        with self.assertRaises(u.UpdateError):
            u.inspect_package(p, self.manifest(a=b'x'))

    def test_reject_special_members(self):
        for mode in (0o120777, 0o040755, 0o010644, 0o060644):
            with self.subTest(mode=mode), self.assertRaises(u.UpdateError):
                u.inspect_package(self.package([('a', b'x', mode)]), self.manifest(a=b'x'))

    def test_reject_member_hash_mismatch(self):
        with self.assertRaisesRegex(u.UpdateError, 'content differs'):
            u.inspect_package(self.package([('a', b'x', 0o100644)]), self.manifest(a=b'y'))

    def test_expanded_limits(self):
        p = self.package([('a', b'abc', 0o100644), ('b', b'def', 0o100644)])
        manifest = self.manifest(a=b'abc', b=b'def')
        for key, limit in (('MAX_MEMBER_BYTES', 2), ('MAX_PACKAGE_BYTES', 5), ('MAX_PACKAGE_FILES', 1)):
            with patch.object(u, key, limit), self.assertRaises(u.UpdateError):
                u.inspect_package(p, manifest)

    def test_recheck_archive_digest_and_malformed_zip(self):
        import hashlib
        from dataclasses import replace
        p = self.package([('a', b'x', 0o100644)])
        with self.assertRaisesRegex(u.UpdateError, 'integrity changed'):
            u.inspect_package(replace(p, sha256='0'*64), self.manifest(a=b'x'))
        raw = b'not a ZIP'
        digest = hashlib.sha256(raw).hexdigest()
        info = replace(p.info, archive=replace(p.info.archive, size=len(raw), digest='sha256:'+digest))
        with self.assertRaisesRegex(u.UpdateError, 'damaged release ZIP'):
            u.inspect_package(u.DownloadedUpdate(info, raw, digest), self.manifest(a=b'x'))


class PublisherSignatureTests(unittest.TestCase):
    def setUp(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        self.key = Ed25519PrivateKey.generate()
        self.pub = self.key.public_key().public_bytes_raw()
        self.package = PackageTests().package([('Start.pyw', b'x', 0o100644)])
        self.manifest = {'schema': u.MANIFEST_SCHEMA, 'repository': u.REPOSITORY,
                         'version': self.package.info.latest,
                         'archive': {'name': self.package.info.archive.name,
                                     'size': len(self.package.archive), 'sha256': self.package.sha256},
                         'files': PackageTests().manifest(**{'Start.pyw': b'x'})}

    def raw(self):
        return json.dumps(self.manifest, sort_keys=True).encode('utf-8')

    def verify(self, raw=None, signature=None):
        raw = self.raw() if raw is None else raw
        signature = self.key.sign(raw) if signature is None else signature
        with patch.object(u, 'PUBLISHER_PUBLIC_KEY', self.pub):
            return u.verify_publisher_package(self.package, raw, signature)

    def test_unprovisioned_key_denies(self):
        raw = self.raw()
        with patch.object(u, 'PUBLISHER_PUBLIC_KEY', None):
            with self.assertRaisesRegex(u.UpdateError, 'not configured'):
                u.verify_publisher_package(self.package, raw, self.key.sign(raw))

    def test_production_pin_fingerprint(self):
        self.assertEqual(len(u.PUBLISHER_PUBLIC_KEY), 32)
        self.assertEqual(hashlib.sha256(u.PUBLISHER_PUBLIC_KEY).hexdigest(),
                         'f3d92fd2e380dcb0640eb087c96a0da699ec66ca35dc902f97559192ead62e99')

    def test_production_pin_rejects_ephemeral_signer(self):
        raw = self.raw()
        with self.assertRaisesRegex(u.UpdateError, 'verification failed'):
            u.verify_publisher_package(self.package, raw, self.key.sign(raw))

    def test_valid_signature(self):
        self.assertEqual(self.verify(), ('Start.pyw',))

    def test_modified_manifest_and_signature(self):
        raw = self.raw()
        signature = self.key.sign(raw)
        for data, sig in ((raw+b' ', signature), (raw, bytes([signature[0]^1])+signature[1:])):
            with self.assertRaises(u.UpdateError):
                self.verify(data, sig)

    def test_wrong_key(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        raw = self.raw()
        with self.assertRaises(u.UpdateError):
            self.verify(raw, Ed25519PrivateKey.generate().sign(raw))

    def test_signed_wrong_identity(self):
        for field, value in [('schema','other'), ('repository','other/repo'), ('version','4.9.0')]:
            old = self.manifest[field]
            self.manifest[field] = value
            with self.assertRaises(u.UpdateError):
                self.verify()
            self.manifest[field] = old

    def test_signed_wrong_archive(self):
        for field, value in [('size',True), ('sha256','0'*64), ('name','other.zip')]:
            old = self.manifest['archive'][field]
            self.manifest['archive'][field] = value
            with self.assertRaises(u.UpdateError):
                self.verify()
            self.manifest['archive'][field] = old

    def test_signed_wrong_file_hash(self):
        self.manifest['files']['Start.pyw'] = '0'*64
        with self.assertRaises(u.UpdateError):
            self.verify()

    def test_invalid_manifest_and_bounds(self):
        for raw in (b'{', b'{"schema":1,"schema":2}', b'[]', b' '* (u.MAX_SIGNED_MANIFEST+1)):
            with self.assertRaises(u.UpdateError):
                self.verify(raw)
        with self.assertRaises(u.UpdateError):
            self.verify(signature=b'bad')

    def test_missing_crypto_denies(self):
        import sys
        raw = self.raw()
        signature = self.key.sign(raw)
        with patch.dict(sys.modules, {'cryptography.exceptions':None}):
            with self.assertRaisesRegex(u.UpdateError, 'unavailable'):
                self.verify(raw, signature)


class SignedDownloadTests(unittest.TestCase):
    def fixture(self, alter_signature=False):
        from dataclasses import replace
        signer = PublisherSignatureTests()
        signer.setUp()
        raw = signer.raw()
        sig = signer.key.sign(raw)
        if alter_signature:
            sig = bytes([sig[0] ^ 1]) + sig[1:]
        download = signer.package
        stem = download.info.archive.name[:-4]
        checksum = (download.sha256 + '  ' + download.info.archive.name + '\n').encode('ascii')
        def asset(name, ident, data):
            return u.ReleaseAsset(name, ident, len(data), 'sha256:' + hashlib.sha256(data).hexdigest())
        info = replace(download.info, checksum=asset(stem+'.sha256', 3, checksum),
                       manifest=asset(stem+'.manifest.json', 4, raw),
                       signature=asset(stem+'.manifest.sig', 5, sig))
        return info, (raw, sig, checksum, download.archive), signer.pub

    def test_discovery_signed_pair(self):
        data = release()
        for i, ext in enumerate(('.manifest.json', '.manifest.sig'), 4):
            data['assets'].append(dict(data['assets'][0], id=i,
                name=data['assets'][0]['name'][:-4]+ext))
        info = u.parse_latest(data)
        self.assertEqual(info.manifest.asset_id, 4)
        self.assertEqual(info.signature.asset_id, 5)
        for assets in (data['assets'][:-1], data['assets']+[data['assets'][-1]],
                       data['assets'][:3]+[dict(data['assets'][3], name=data['assets'][3]['name'].replace('.sig','.json'))]):
            with self.assertRaises(u.UpdateError):
                u.parse_latest(dict(data, assets=assets))
        data['assets'][-1]['id'] = 2
        with self.assertRaises(u.UpdateError):
            u.parse_latest(data)

    @patch.object(u, 'build_opener')
    def test_unsigned_release_discovery_but_no_signed_download(self, opener):
        info, _, _ = DownloadTests().fixture()
        self.assertTrue(info.available)
        self.assertIsNone(info.manifest)
        with self.assertRaises(u.UpdateError):
            u.download_signed_update(info)
        opener.assert_not_called()

    @patch.object(u, 'build_opener')
    def test_signed_download(self, opener):
        info, contents, pub = self.fixture()
        opener.return_value.open.side_effect = [AssetResponse(b) for b in contents]
        with patch.object(u, 'PUBLISHER_PUBLIC_KEY', pub):
            result = u.download_signed_update(info)
            self.assertEqual(u.verify_publisher_package(result.download, result.manifest, result.signature), ('Start.pyw',))
        self.assertEqual(result.download.archive, contents[-1])
        for call, asset in zip(opener.return_value.open.call_args_list,
                               (info.manifest, info.signature, info.checksum, info.archive)):
            self.assertEqual(call.args[0].full_url, info.release_url.replace('/tag/', '/download/')+'/'+asset.name)
        self.assertEqual(opener.return_value.open.call_count, 4)

    @patch.object(u, 'build_opener')
    def test_reject_invalid_signed_metadata_before_network(self, opener):
        from dataclasses import replace
        info, _, _ = self.fixture()
        for bad in (replace(info, manifest=replace(info.manifest, size=u.MAX_SIGNED_MANIFEST+1)),
                    replace(info, signature=replace(info.signature, size=63)),
                    replace(info, signature=replace(info.signature, asset_id=info.archive.asset_id)),
                    replace(info, manifest=replace(info.manifest, digest=None)),
                    replace(info, signature=replace(info.signature, name='other.sig'))):
            with self.assertRaises(u.UpdateError):
                u.download_signed_update(bad)
        opener.assert_not_called()

    @patch.object(u, 'build_opener')
    def test_reject_invalid_signature_even_with_matching_asset_digest(self, opener):
        info, contents, pub = self.fixture(alter_signature=True)
        opener.return_value.open.side_effect = [AssetResponse(b) for b in contents]
        with patch.object(u, 'PUBLISHER_PUBLIC_KEY', pub), self.assertRaisesRegex(u.UpdateError, 'verification failed'):
            u.download_signed_update(info)

    @patch.object(u, 'build_opener')
    def test_reject_tampered_manifest_before_archive_download(self, opener):
        info, contents, _ = self.fixture()
        opener.return_value.open.return_value = AssetResponse(b'x'*len(contents[0]))
        with self.assertRaisesRegex(u.UpdateError, 'digest differs'):
            u.download_signed_update(info)
        self.assertEqual(opener.return_value.open.call_count, 1)


class StagingTests(unittest.TestCase):
    def fixture(self, entries=None):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        entries = entries if entries is not None else [
            ('Start.pyw', b'never executed', 0o100644),
            ('command_relay/relay_version.py', b'VERSION = "4.10.0"\n', 0o100644),
            ('docs/manual.txt', b'guide', 0o100644)]
        from dataclasses import replace
        download = PackageTests().package(entries)
        download = replace(download, info=replace(download.info, current=u.VERSION))
        key = Ed25519PrivateKey.generate()
        manifest = json.dumps({'schema': u.MANIFEST_SCHEMA, 'repository': u.REPOSITORY,
            'version': download.info.latest, 'archive': {'name': download.info.archive.name,
                'size': len(download.archive), 'sha256': download.sha256},
            'files': {name: hashlib.sha256(data).hexdigest() for name, data, _ in entries}},
            sort_keys=True).encode()
        return u.SignedUpdate(download, manifest, key.sign(manifest)), key.public_key().public_bytes_raw()

    def test_stage_exact_files_and_cleanup(self):
        signed, key = self.fixture()
        with patch.object(u, 'PUBLISHER_PUBLIC_KEY', key):
            with u.stage_signed_update(signed) as stage:
                self.assertEqual(stage.version, '4.10.0')
                self.assertEqual(set(stage.files), set(json.loads(signed.manifest)['files']))
                root = stage.directory
                self.assertEqual({p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}, set(stage.files))
                for name, digest in json.loads(signed.manifest)['files'].items():
                    self.assertEqual(hashlib.sha256((root / name).read_bytes()).hexdigest(), digest)
            self.assertFalse(root.exists())

    def test_caller_exception_cleans_scratch(self):
        signed, key = self.fixture()
        with patch.object(u, 'PUBLISHER_PUBLIC_KEY', key), self.assertRaisesRegex(ValueError, 'consumer failure'):
            with u.stage_signed_update(signed) as stage:
                root = stage.directory
                raise ValueError('consumer failure')
        self.assertFalse(root.exists())

    def test_bad_signature_before_disk(self):
        from dataclasses import replace
        signed, key = self.fixture()
        bad = replace(signed, signature=b'0' * 64)
        with patch.object(u, 'PUBLISHER_PUBLIC_KEY', key), patch('tempfile.TemporaryDirectory') as temp:
            with self.assertRaises(u.UpdateError):
                with u.stage_signed_update(bad):
                    self.fail('unverified package staged')
            temp.assert_not_called()

    def test_wrong_running_version_before_disk(self):
        from dataclasses import replace
        signed, key = self.fixture()
        bad = replace(signed, download=replace(signed.download, info=replace(signed.download.info, current='0.0.0')))
        with patch.object(u, 'PUBLISHER_PUBLIC_KEY', key), patch('tempfile.TemporaryDirectory') as temp:
            with self.assertRaisesRegex(u.UpdateError, 'running version'):
                with u.stage_signed_update(bad):
                    self.fail('wrong version staged')
            temp.assert_not_called()

    def test_signed_traversal_before_disk(self):
        signed, key = self.fixture([('../settings.json', b'bad', 0o100644)])
        with patch.object(u, 'PUBLISHER_PUBLIC_KEY', key), patch('tempfile.TemporaryDirectory') as temp:
            with self.assertRaises(u.UpdateError):
                with u.stage_signed_update(signed):
                    self.fail('unsafe path staged')
            temp.assert_not_called()

    def test_write_failure_cleans_scratch(self):
        import tempfile
        from pathlib import Path
        signed, key = self.fixture()
        real_temp = tempfile.TemporaryDirectory
        roots = []
        def capture(*args, **kwargs):
            temp = real_temp(*args, **kwargs)
            roots.append(Path(temp.name))
            return temp
        original_open = Path.open
        def fail_write(path, mode='r', *args, **kwargs):
            if mode == 'xb' and path.name == 'manual.txt':
                raise OSError('simulated disk error')
            return original_open(path, mode, *args, **kwargs)
        with patch.object(u, 'PUBLISHER_PUBLIC_KEY', key), patch('tempfile.TemporaryDirectory', side_effect=capture), patch.object(Path, 'open', fail_write):
            with self.assertRaisesRegex(u.UpdateError, 'Unable to stage'):
                with u.stage_signed_update(signed):
                    self.fail('partial package staged')
        self.assertEqual(len(roots), 1)
        self.assertFalse(roots[0].exists())

    def test_independent_staging_does_not_touch_existing_files(self):
        import tempfile
        from pathlib import Path
        signed, key = self.fixture()
        with tempfile.TemporaryDirectory() as existing, patch.object(u, 'PUBLISHER_PUBLIC_KEY', key):
            sentinel = Path(existing) / 'Start.pyw'
            sentinel.write_bytes(b'current installation')
            with u.stage_signed_update(signed) as first, u.stage_signed_update(signed) as second:
                self.assertNotEqual(first.directory, second.directory)
                self.assertNotEqual(first.directory, Path(existing))
                self.assertEqual(sentinel.read_bytes(), b'current installation')
            self.assertEqual(sentinel.read_bytes(), b'current installation')


class InstallPlanTests(unittest.TestCase):
    def setUp(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        import tempfile
        from pathlib import Path
        self.key = Ed25519PrivateKey.generate()
        self.pin = patch.object(u, 'PUBLISHER_PUBLIC_KEY', self.key.public_key().public_bytes_raw())
        self.pin.start(); self.addCleanup(self.pin.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / 'portable'
        self.root.mkdir()
        self.files = {name: name.encode() for name in u.INSTALL_PROGRAM_FILES}
        self.new_files = dict(self.files, **{'Start.pyw': b'new launcher'})
        for name, data in self.files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        (self.root / 'settings.json').write_bytes(b'preserve me')
        self.old = self.package('4.1.0', u.VERSION, self.files)
        self.new = self.package(u.VERSION, '4.10.0', self.new_files)

    def package(self, current, latest, files):
        from dataclasses import replace
        import zipfile
        info, _, _ = DownloadTests().fixture()
        stem = f'command-relay-v{latest}-windows'
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as archive:
            for name, data in files.items():
                member = zipfile.ZipInfo(stem + '/' + name)
                member.create_system = 3
                member.external_attr = 0o100644 << 16
                archive.writestr(member, data)
        raw = buf.getvalue()
        digest = hashlib.sha256(raw).hexdigest()
        info = replace(info, current=current, latest=latest,
                       archive=replace(info.archive, name=stem+'.zip', size=len(raw), digest='sha256:'+digest),
                       checksum=replace(info.checksum, name=stem+'.sha256'))
        manifest = json.dumps({'schema': u.MANIFEST_SCHEMA, 'repository': u.REPOSITORY,
            'version': latest, 'archive': {'name': info.archive.name, 'size': len(raw), 'sha256': digest},
            'files': {n: hashlib.sha256(d).hexdigest() for n,d in files.items()}}, sort_keys=True).encode()
        return u.SignedUpdate(u.DownloadedUpdate(info, raw, digest), manifest, self.key.sign(manifest))

    def test_plan_read_only(self):
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        plan = u.plan_installation(self.root, self.old, self.new)
        self.assertEqual(plan.replace, ('Start.pyw',))
        self.assertEqual(set(plan.unchanged), set(self.files)-{'Start.pyw'})
        self.assertEqual(before, {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_allowlist_matches_build(self):
        from tools.build_release import RELEASE_FILES
        self.assertEqual(u.INSTALL_PROGRAM_FILES, frozenset(RELEASE_FILES))

    def test_modified_or_missing_file_denied(self):
        path = self.root/'Start.pyw'
        path.write_bytes(b'changed')
        with self.assertRaises(u.UpdateError): u.plan_installation(self.root,self.old,self.new)
        path.unlink()
        with self.assertRaises(u.UpdateError): u.plan_installation(self.root,self.old,self.new)

    def test_git_checkout_denied(self):
        for root in (self.root, self.root.parent):
            marker = root/'.git'
            marker.write_text('gitdir: elsewhere')
            with self.assertRaisesRegex(u.UpdateError,'Git checkout'):
                u.plan_installation(self.root,self.old,self.new)
            marker.unlink()

    def test_signed_user_data_denied(self):
        target = self.package(u.VERSION,'4.10.0',dict(self.new_files, **{'settings.json':b'overwrite'}))
        with self.assertRaisesRegex(u.UpdateError,'layout'):
            u.plan_installation(self.root,self.old,target)
        self.assertEqual((self.root/'settings.json').read_bytes(),b'preserve me')

    def test_bad_signature_denied(self):
        from dataclasses import replace
        for old,new in ((replace(self.old,signature=b'x'*64),self.new),(self.old,replace(self.new,signature=b'x'*64))):
            with self.assertRaises(u.UpdateError): u.plan_installation(self.root,old,new)

    def test_wrong_version_denied(self):
        with self.assertRaises(u.UpdateError): u.plan_installation(self.root,self.new,self.new)

    def test_hardlink_denied(self):
        import os
        path = self.root/'Start.pyw'
        try:
            os.link(path,self.root.parent/'linked')
        except OSError:
            self.skipTest('Hardlinks unavailable')
        with self.assertRaisesRegex(u.UpdateError,'Unsafe installation path'):
            u.plan_installation(self.root,self.old,self.new)

    def test_symlink_denied(self):
        path = self.root/'Start.pyw'
        original = self.root.parent/'original'
        path.rename(original)
        try:
            path.symlink_to(original)
        except OSError:
            self.skipTest('Symlinks unavailable')
        with self.assertRaisesRegex(u.UpdateError,'Unsafe installation path'):
            u.plan_installation(self.root,self.old,self.new)


class InstallRehearsalTests(unittest.TestCase):
    def setUp(self):
        fixture = InstallPlanTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.old = fixture.old
        self.new = fixture.package(u.VERSION, '4.10.0', dict(fixture.new_files, **{'README.md': b'new docs'}))

    def test_success_and_restore(self):
        original = u._verify_rehearsal_tree
        states = []
        def capture(root, files):
            original(root, files)
            states.append((root, (root/'Start.pyw').read_bytes()))
        with patch.object(u, '_verify_rehearsal_tree', side_effect=capture):
            result = u.rehearse_installation(self.old, self.new)
        self.assertEqual(result.replaced, ('README.md', 'Start.pyw'))
        self.assertTrue(result.rollback_verified)
        self.assertEqual([data for _,data in states], [b'new launcher', b'Start.pyw'])
        self.assertTrue(all(not root.exists() for root,_ in states))
        self.assertEqual((self.fixture.root/'Start.pyw').read_bytes(), b'Start.pyw')
        self.assertEqual((self.fixture.root/'settings.json').read_bytes(), b'preserve me')

    def test_failure_after_one_replacement_restores(self):
        original = u._replace_rehearsal_file
        def fail(source, destination, expected, replacement):
            if destination.name == 'Start.pyw' and 'incoming' in source.parts:
                raise OSError('simulated failure')
            original(source, destination, expected, replacement)
        with patch.object(u, '_replace_rehearsal_file', side_effect=fail) as calls:
            with self.assertRaisesRegex(u.UpdateError, 'original tree restored'):
                u.rehearse_installation(self.old, self.new)
        self.assertEqual([call.args[0].parent.name for call in calls.call_args_list], ['incoming','incoming','backup'])

    def test_failure_after_replace_before_readback_restores(self):
        original = u._replace_rehearsal_file
        def fail(source, destination, expected, replacement):
            original(source, destination, expected, replacement)
            if destination.name == 'Start.pyw' and 'incoming' in source.parts:
                raise OSError('simulated post-replace failure')
        with patch.object(u, '_replace_rehearsal_file', side_effect=fail) as calls:
            with self.assertRaisesRegex(u.UpdateError, 'original tree restored'):
                u.rehearse_installation(self.old, self.new)
        self.assertEqual([call.args[0].parent.name for call in calls.call_args_list], ['incoming','incoming','backup','backup'])

    def test_rollback_failure_is_not_success(self):
        original = u._replace_rehearsal_file
        def fail(source, destination, expected, replacement):
            if 'backup' in source.parts:
                raise OSError('simulated rollback failure')
            original(source, destination, expected, replacement)
        with patch.object(u, '_replace_rehearsal_file', side_effect=fail):
            with self.assertRaisesRegex(u.UpdateError, 'rollback could not be verified'):
                u.rehearse_installation(self.old, self.new)

    def test_bad_signature_before_disk(self):
        from dataclasses import replace
        with patch('tempfile.TemporaryDirectory') as scratch:
            with self.assertRaises(u.UpdateError):
                u.rehearse_installation(self.old, replace(self.new, signature=b'x'*64))
            scratch.assert_not_called()

    def test_unapproved_layout_before_disk(self):
        bad = self.fixture.package(u.VERSION, '4.10.0', dict(self.fixture.new_files, **{'settings.json':b'bad'}))
        with patch('tempfile.TemporaryDirectory') as scratch:
            with self.assertRaisesRegex(u.UpdateError, 'layout'):
                u.rehearse_installation(self.old, bad)
            scratch.assert_not_called()

    def test_backup_failure_before_replacement(self):
        original = u._write_rehearsal_file
        def fail(path, data):
            if 'backup' in path.parts:
                raise OSError('simulated backup failure')
            original(path, data)
        with patch.object(u, '_write_rehearsal_file', side_effect=fail), patch.object(u, '_replace_rehearsal_file') as replace_file:
            with self.assertRaisesRegex(u.UpdateError, 'prepare or clean'):
                u.rehearse_installation(self.old, self.new)
            replace_file.assert_not_called()


class RecoveryRehearsalTests(unittest.TestCase):
    def setUp(self):
        from pathlib import Path
        import tempfile
        fixture = InstallPlanTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.old = fixture.old
        self.new = fixture.package(u.VERSION, '4.10.0', dict(fixture.new_files, **{'README.md': b'new docs'}))
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.plan = u._prepare_recovery_rehearsal(self.base, self.old, self.new)
        self.original, self.target, _ = u._recovery_packages(self.old, self.new)

    def apply(self, names):
        for name in names:
            u._replace_rehearsal_file(self.base/'incoming'/name, self.base/'portable'/name,
                                      self.original[name], self.target[name])

    def test_simulated_interruption_and_retry(self):
        result = u.rehearse_interrupted_installation(self.old, self.new)
        self.assertTrue(result.rollback_verified)
        self.assertEqual(result.replaced, ('README.md',))

    def test_before_first_replacement(self):
        self.assertEqual(u._recover_rehearsal(self.base, self.old, self.new), ())

    def test_after_all_replacements(self):
        self.apply(self.plan.replace)
        (self.base/'portable'/'settings.json').write_bytes(b'user data')
        self.assertEqual(u._recover_rehearsal(self.base, self.old, self.new), self.plan.replace)
        self.assertEqual(u._recover_rehearsal(self.base, self.old, self.new), ())
        self.assertEqual((self.base/'portable'/'settings.json').read_bytes(), b'user data')

    def test_unknown_file_denied_before_any_restore(self):
        self.apply(self.plan.replace)
        (self.base/'portable'/'Start.pyw').write_bytes(b'unknown')
        with patch.object(u, '_replace_rehearsal_file') as replace_file:
            with self.assertRaisesRegex(u.UpdateError, 'Unknown recovery'):
                u._recover_rehearsal(self.base, self.old, self.new)
            replace_file.assert_not_called()

    def test_corrupt_backup_denied_before_any_restore(self):
        self.apply(self.plan.replace)
        (self.base/'backup'/'Start.pyw').write_bytes(b'bad')
        with patch.object(u, '_replace_rehearsal_file') as replace_file:
            with self.assertRaisesRegex(u.UpdateError, 'backup differs'):
                u._recover_rehearsal(self.base, self.old, self.new)
            replace_file.assert_not_called()

    def test_tampered_intent_denied(self):
        self.apply(self.plan.replace[:1])
        (self.base/'intent.json').write_bytes(b'{}')
        with self.assertRaisesRegex(u.UpdateError, 'intent differs'):
            u._recover_rehearsal(self.base, self.old, self.new)
        self.assertEqual((self.base/'portable'/'README.md').read_bytes(), b'new docs')

    def test_invalid_signature_denied(self):
        from dataclasses import replace
        with patch.object(u, '_read_recovery_file') as read:
            with self.assertRaises(u.UpdateError):
                u._recover_rehearsal(self.base, self.old, replace(self.new, signature=b'x'*64))
            read.assert_not_called()

    def test_interruption_during_rollback_can_retry(self):
        self.apply(self.plan.replace)
        original = u._replace_rehearsal_file
        def interrupt(source, destination, expected, replacement):
            original(source, destination, expected, replacement)
            raise OSError('simulated interruption after restoration')
        with patch.object(u, '_replace_rehearsal_file', side_effect=interrupt):
            with self.assertRaisesRegex(u.UpdateError, 'Recovery interrupted'):
                u._recover_rehearsal(self.base, self.old, self.new)
        self.assertEqual(u._recover_rehearsal(self.base, self.old, self.new), ('README.md',))
        self.assertEqual(u._recover_rehearsal(self.base, self.old, self.new), ())


# Test-only subprocess protocol. No private key is passed to the child, no
# installed application is touched, and no package code is executed.
_RECOVERY_CHILD = r'''
import json, sys
from pathlib import Path
from unittest.mock import patch
from command_relay import relay_updates as u
payload = json.loads(sys.stdin.readline())
base = Path(payload['base'])
def package(data):
    info = data['info']
    for name in ('archive', 'checksum', 'manifest', 'signature'):
        if info[name] is not None:
            info[name] = u.ReleaseAsset(**info[name])
    download = u.DownloadedUpdate(u.UpdateInfo(**info), bytes.fromhex(data['archive']), data['sha256'])
    return u.SignedUpdate(download, bytes.fromhex(data['manifest']), bytes.fromhex(data['signature']))
old, new = map(package, payload['packages'])
mode = payload['mode']
with patch.object(u, 'PUBLISHER_PUBLIC_KEY', bytes.fromhex(payload['public'])):
    if mode == 'recover':
        print(json.dumps(u._recover_rehearsal(base, old, new)), flush=True)
    else:
        original, target, _ = u._recovery_packages(old, new)
        def halt():
            (base / 'child-ready').write_text('ready', encoding='ascii')
            # Parent must kill this process; EOF is not a successful test.
            sys.stdin.readline()
            raise RuntimeError('Child was not killed')
        if mode == 'rollback':
            replace_file = u._replace_rehearsal_file
            def interrupted(*args):
                replace_file(*args)
                halt()
            with patch.object(u, '_replace_rehearsal_file', side_effect=interrupted):
                u._recover_rehearsal(base, old, new)
        else:
            plan = u._prepare_recovery_rehearsal(base, old, new)
            (base / 'portable' / 'settings.json').write_bytes(b'preserve me')
            if mode == 'replace':
                name = plan.replace[0]
                u._replace_rehearsal_file(base/'incoming'/name, base/'portable'/name,
                                          original[name], target[name])
            elif mode != 'intent':
                raise RuntimeError('Unexpected test mode')
            halt()
'''


class CrossProcessRecoveryTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        fixture = InstallPlanTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.old = fixture.old
        self.new = fixture.package(u.VERSION, '4.10.0', dict(fixture.new_files, **{'README.md': b'new docs'}))
        self.temp = tempfile.TemporaryDirectory(prefix='relay-crash-test-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.public = fixture.key.public_key().public_bytes_raw().hex()
        self.original, self.target, _ = u._recovery_packages(self.old, self.new)

    def payload(self, mode):
        from dataclasses import asdict
        def encode(item):
            return {'info': asdict(item.download.info), 'archive': item.download.archive.hex(),
                    'sha256': item.download.sha256, 'manifest': item.manifest.hex(),
                    'signature': item.signature.hex()}
        return json.dumps({'base': str(self.base), 'mode': mode, 'public': self.public,
                           'packages': [encode(self.old), encode(self.new)]}) + '\n'

    def kill_at_checkpoint(self, mode):
        import subprocess
        import sys
        import time
        marker = self.base / 'child-ready'
        self.assertFalse(marker.exists())
        with subprocess.Popen([sys.executable, '-B', '-c', _RECOVERY_CHILD],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True, encoding='utf-8') as child:
            try:
                child.stdin.write(self.payload(mode))
                child.stdin.flush()
                deadline = time.monotonic() + 30
                while not marker.exists():
                    if child.poll() is not None or time.monotonic() >= deadline:
                        self.fail('Child failed to reach recovery checkpoint')
                    time.sleep(0.02)
                self.assertIsNone(child.poll())
                child.kill()
                child.wait(timeout=15)
                self.assertNotEqual(child.returncode, 0)
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait(timeout=15)
            marker.unlink()

    def recover(self):
        import subprocess
        import sys
        result = subprocess.run([sys.executable, '-B', '-c', _RECOVERY_CHILD],
                                input=self.payload('recover'), text=True, encoding='utf-8',
                                capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return tuple(json.loads(result.stdout))

    def verify_restored(self):
        u._verify_rehearsal_tree(self.base/'portable', self.original)
        self.assertEqual((self.base/'portable'/'settings.json').read_bytes(), b'preserve me')
        self.assertEqual(self.recover(), ())

    def test_kill_after_intent_before_replacement(self):
        self.kill_at_checkpoint('intent')
        self.assertEqual(self.recover(), ())
        self.verify_restored()

    def test_kill_after_replacement(self):
        self.kill_at_checkpoint('replace')
        self.assertEqual((self.base/'portable'/'README.md').read_bytes(), b'new docs')
        self.assertEqual(self.recover(), ('README.md',))
        self.verify_restored()

    def test_kill_during_rollback_then_retry(self):
        plan = u._prepare_recovery_rehearsal(self.base, self.old, self.new)
        (self.base/'portable'/'settings.json').write_bytes(b'preserve me')
        for name in plan.replace:
            u._replace_rehearsal_file(self.base/'incoming'/name, self.base/'portable'/name,
                                      self.original[name], self.target[name])
        self.kill_at_checkpoint('rollback')
        self.assertEqual((self.base/'portable'/'Start.pyw').read_bytes(), self.original['Start.pyw'])
        self.assertEqual((self.base/'portable'/'README.md').read_bytes(), self.target['README.md'])
        self.assertEqual(self.recover(), ('README.md',))
        self.verify_restored()


class InstallationLockTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name).resolve() / 'portable'
        self.root.mkdir()
        self.lock = self.root / u.UPDATE_LOCK_NAME

    def test_release_and_reacquire(self):
        with u.installation_lock(self.root):
            self.assertEqual(self.lock.stat().st_size, 0)
        with u.installation_lock(self.root):
            self.assertTrue(self.lock.is_file())
        self.assertTrue(self.lock.is_file())

    def test_exception_releases_lock(self):
        with self.assertRaisesRegex(RuntimeError, 'caller failed'):
            with u.installation_lock(self.root):
                raise RuntimeError('caller failed')
        with u.installation_lock(self.root):
            pass

    def test_git_checkout_denied(self):
        (self.root.parent / '.git').mkdir()
        with self.assertRaisesRegex(u.UpdateError, 'Git checkout'):
            with u.installation_lock(self.root):
                self.fail('lock acquired')
        self.assertFalse(self.lock.exists())

    def test_existing_nonempty_file_untouched(self):
        self.lock.write_bytes(b'preserve')
        with self.assertRaises(u.UpdateError):
            with u.installation_lock(self.root):
                self.fail('lock acquired')
        self.assertEqual(self.lock.read_bytes(), b'preserve')

    def test_link_denied(self):
        import os
        target = self.root / 'settings.json'
        target.write_bytes(b'')
        try:
            os.link(target, self.lock)
        except OSError:
            self.skipTest('hardlinks unavailable')
        with self.assertRaises(u.UpdateError):
            with u.installation_lock(self.root):
                self.fail('lock acquired')
        self.assertEqual(target.read_bytes(), b'')

    def test_invalid_directory_denied(self):
        with self.assertRaises(u.UpdateError):
            with u.installation_lock(self.root / 'missing'):
                self.fail('lock acquired')
        self.assertFalse(self.lock.exists())

    def test_cross_process_exclusion_and_kill(self):
        import subprocess, sys, time
        ready = self.root / 'ready'
        code = '''
import sys
from pathlib import Path
from command_relay.relay_updates import installation_lock
with installation_lock(Path(sys.argv[1])):
    Path(sys.argv[2]).write_text('ready', encoding='ascii')
    sys.stdin.readline()
'''
        child = subprocess.Popen([sys.executable, '-B', '-c', code, str(self.root), str(ready)],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 15
            while not ready.exists() and child.poll() is None and time.monotonic() < deadline:
                time.sleep(.02)
            self.assertTrue(ready.exists(), 'child failed to acquire lock')
            self.assertIsNone(child.poll())
            with self.assertRaises(u.UpdateError):
                with u.installation_lock(self.root):
                    self.fail('second process acquired lock')
            child.kill()
            child.communicate(timeout=10)
            self.assertNotEqual(child.returncode, 0)
            with u.installation_lock(self.root):
                self.assertTrue(self.lock.exists())
        finally:
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=10)


class StandaloneUpdaterTests(unittest.TestCase):
    def setUp(self):
        fixture = InstallPlanTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.root = fixture.root
        self.original = self.root.parent / 'original'
        self.target = self.root.parent / 'target'
        for folder, package in ((self.original, fixture.old), (self.target, fixture.new)):
            folder.mkdir()
            stem = package.download.info.archive.name[:-4]
            (folder / (stem + '.zip')).write_bytes(package.download.archive)
            (folder / (stem + '.sha256')).write_bytes(
                f'{package.download.sha256}  {stem}.zip\n'.encode('ascii'))
            (folder / (stem + '.manifest.json')).write_bytes(package.manifest)
            (folder / (stem + '.manifest.sig')).write_bytes(package.signature)

    def args(self):
        return ['--inspect', '--root', str(self.root), '--original', str(self.original),
                '--target', str(self.target), '--target-version', '4.10.0']

    def snapshot(self):
        return {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*')
                if p.is_file() and p.name != u.UPDATE_LOCK_NAME}

    def run_child(self, *, ephemeral=True):
        import subprocess
        import sys
        if ephemeral:
            # Test-only injection in the child; the production CLI has no key override.
            code = ('from command_relay import relay_updates as u; '
                    'u.PUBLISHER_PUBLIC_KEY=bytes.fromhex(' + repr(self.fixture.key.public_key().public_bytes_raw().hex())
                    + '); raise SystemExit(u.updater_main())')
            command = [sys.executable, '-B', '-c', code]
        else:
            command = [sys.executable, '-B', '-m', 'command_relay.relay_updates']
        return subprocess.run(command + self.args(), capture_output=True, text=True, timeout=30)

    def test_independent_preflight_and_preservation(self):
        before = self.snapshot()
        result = self.run_child()
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['replace'], ['Start.pyw'])
        self.assertEqual(data['current'], u.VERSION)
        self.assertEqual(data['target'], '4.10.0')
        self.assertFalse(data['installation_authorized'])
        self.assertEqual(before, self.snapshot())
        with u.installation_lock(self.root):
            pass

    def test_busy_installation_denied(self):
        before = self.snapshot()
        with u.installation_lock(self.root):
            result = self.run_child()
            self.assertEqual(result.returncode, 1)
            self.assertIn('lock', result.stderr.lower())
            self.assertFalse(result.stdout)
        self.assertEqual(before, self.snapshot())

    def test_production_cli_rejects_ephemeral_key(self):
        result = self.run_child(ephemeral=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn('signature verification failed', result.stderr)
        self.assertFalse(result.stdout)

    def test_modified_checksum_denied(self):
        next(self.target.glob('*.sha256')).write_bytes(b'bad')
        with self.assertRaisesRegex(u.UpdateError, 'checksum'):
            u.inspect_local_installation(self.root, self.original, self.target, '4.10.0')

    def test_bad_signature_and_missing_asset_denied(self):
        signature = next(self.target.glob('*.sig'))
        signature.write_bytes(b'x'*64)
        with self.assertRaisesRegex(u.UpdateError, 'signature verification failed'):
            u.inspect_local_installation(self.root, self.original, self.target, '4.10.0')
        signature.unlink()
        with self.assertRaises(u.UpdateError):
            u.inspect_local_installation(self.root, self.original, self.target, '4.10.0')

    def test_modified_installation_denied(self):
        (self.root/'Start.pyw').write_bytes(b'changed')
        before = self.snapshot()
        result = self.run_child()
        self.assertEqual(result.returncode, 1)
        self.assertIn('differs from signed package', result.stderr)
        self.assertEqual(before, self.snapshot())

    def test_no_install_mode_or_key_override(self):
        import subprocess
        import sys
        for option in ('--install', '--public-key'):
            result = subprocess.run([sys.executable, '-B', '-m', 'command_relay.relay_updates',
                                     *self.args(), option], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 2)
            self.assertFalse(result.stdout)

    def test_oversized_signature_denied(self):
        next(self.target.glob('*.sig')).write_bytes(b'x'*65)
        with self.assertRaisesRegex(u.UpdateError, 'size limit'):
            u.inspect_local_installation(self.root, self.original, self.target, '4.10.0')

    def test_pending_transaction_denies_preflight_before_loading_packages(self):
        marker = self.root / u.UPDATE_TRANSACTION_NAME
        marker.mkdir()
        (marker / 'intent.json').write_bytes(b'opaque')
        before = self.snapshot()
        with patch.object(u, 'load_local_signed_package') as load:
            with self.assertRaises(u.RecoveryRequired):
                u.inspect_local_installation(self.root, self.original, self.target, '4.10.0')
            load.assert_not_called()
        result = self.run_child()
        self.assertEqual(result.returncode, 1)
        self.assertIn('unfinished update', result.stderr.lower())
        self.assertFalse(result.stdout)
        self.assertEqual(before, self.snapshot())
        with u.installation_lock(self.root):
            pass


class PendingTransactionTests(unittest.TestCase):
    def setUp(self):
        fixture = InstallPlanTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.f = fixture
        self.root = fixture.root
        self.marker = self.root / u.UPDATE_TRANSACTION_NAME
        self.new_files = dict(fixture.new_files, **{'README.md': b'new readme'})
        self.target = fixture.package(u.VERSION, '4.10.0', self.new_files)

    def apply(self):
        return u._apply_pending_update(self.root, self.f.old, self.target)

    def recover(self):
        return u._recover_pending_update(self.root, self.f.old, self.target)

    def assert_tree(self, files):
        for name, data in files.items():
            self.assertEqual((self.root / name).read_bytes(), data, name)
        self.assertEqual((self.root / 'settings.json').read_bytes(), b'preserve me')

    def test_apply_and_recover_existing_tree(self):
        plan = self.apply()
        self.assertEqual(plan.replace, ('README.md', 'Start.pyw'))
        self.assert_tree(self.new_files)
        with self.assertRaises(u.RecoveryRequired):
            with u.startup_installation_guard(self.root):
                self.fail('pending transaction allowed startup')
        self.assertEqual(self.recover(), plan.replace)
        self.assert_tree(self.f.files)
        self.assertEqual(self.recover(), ())
        self.assertTrue(self.marker.is_dir())

    def test_busy_lock_denies_before_marker(self):
        with u.installation_lock(self.root):
            with self.assertRaises(u.UpdateError):
                self.apply()
        self.assertFalse(self.marker.exists())
        self.assert_tree(self.f.files)

    def test_failure_after_replacement_can_recover(self):
        original = u._replace_rehearsal_file
        def interrupted(*args):
            original(*args)
            raise OSError('simulated interruption')
        with patch.object(u, '_replace_rehearsal_file', side_effect=interrupted):
            with self.assertRaises(u.UpdateError):
                self.apply()
        self.assertTrue(self.marker.is_dir())
        self.assertEqual(self.recover(), ('README.md',))
        self.assert_tree(self.f.files)

    def test_corrupt_backup_denies_all_restore(self):
        self.apply()
        (self.marker / 'backup' / 'Start.pyw').write_bytes(b'bad')
        with self.assertRaisesRegex(u.UpdateError, 'backup differs'):
            self.recover()
        self.assert_tree(self.new_files)

    def test_unknown_program_file_denies_all_restore(self):
        self.apply()
        (self.root / 'Start.pyw').write_bytes(b'unknown')
        with self.assertRaisesRegex(u.UpdateError, 'Unknown pending'):
            self.recover()
        self.assertEqual((self.root / 'README.md').read_bytes(), b'new readme')
        self.assertEqual((self.root / 'Start.pyw').read_bytes(), b'unknown')

    def test_unapproved_entry_denies_before_marker(self):
        (self.root / 'command_relay' / 'unexpected.py').write_bytes(b'not executed')
        with self.assertRaisesRegex(u.UpdateError, 'Unexpected entry'):
            self.apply()
        self.assertFalse(self.marker.exists())
        self.assert_tree(self.f.files)

    def test_incomplete_preparation_keeps_gate(self):
        with patch.object(u, '_write_rehearsal_file', side_effect=OSError('disk full')):
            with self.assertRaises(u.UpdateError):
                self.apply()
        self.assertTrue(self.marker.is_dir())
        self.assert_tree(self.f.files)
        with self.assertRaises(u.UpdateError):
            self.recover()
        with self.assertRaises(u.RecoveryRequired):
            with u.startup_installation_guard(self.root):
                self.fail('incomplete transaction allowed startup')

    def test_bad_signature_denies_before_marker(self):
        from dataclasses import replace
        self.target = replace(self.target, signature=b'x'*64)
        with self.assertRaises(u.UpdateError):
            self.apply()
        self.assertFalse(self.marker.exists())
        self.assert_tree(self.f.files)

    def test_pending_marker_denies_second_apply(self):
        self.apply()
        with self.assertRaises(u.RecoveryRequired):
            self.apply()
        self.assert_tree(self.new_files)


class TransactionFinalizationTests(unittest.TestCase):
    def setUp(self):
        fixture = PendingTransactionTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.f = fixture
        self.root = fixture.root
        self.marker = fixture.marker

    def finalize(self, outcome='commit'):
        return u._finalize_pending_update(self.root, self.f.f.old, self.f.target, outcome=outcome)

    def assert_gate(self):
        with self.assertRaises(u.RecoveryRequired):
            with u.startup_installation_guard(self.root):
                self.fail('unverified tree allowed startup')

    def test_commit_archives_evidence_and_releases_gate(self):
        self.f.apply()
        journal = (self.marker / 'intent.json').read_bytes()
        archive = self.finalize()
        self.assertEqual(archive.parent.parent, self.root.parent)
        self.assertFalse(self.marker.exists())
        self.assertEqual((archive / 'intent.json').read_bytes(), journal)
        self.assertEqual((archive / 'backup' / 'README.md').read_bytes(), self.f.f.files['README.md'])
        self.f.assert_tree(self.f.new_files)
        with u.startup_installation_guard(self.root):
            pass

    def test_rollback_archives_evidence_and_releases_gate(self):
        self.f.apply()
        self.f.recover()
        archive = self.finalize('rollback')
        self.assertTrue((archive / 'intent.json').is_file())
        self.assertFalse(self.marker.exists())
        self.f.assert_tree(self.f.f.files)
        with u.startup_installation_guard(self.root):
            pass

    def test_wrong_outcome_denied(self):
        self.f.apply()
        with self.assertRaisesRegex(u.UpdateError, 'tree differs'):
            self.finalize('rollback')
        self.assert_gate()
        self.f.assert_tree(self.f.new_files)

    def test_mixed_tree_denied_for_both_outcomes(self):
        self.f.apply()
        (self.root / 'README.md').write_bytes(self.f.f.files['README.md'])
        for outcome in ('commit', 'rollback'):
            with self.assertRaisesRegex(u.UpdateError, 'tree differs'):
                self.finalize(outcome)
        self.assert_gate()

    def test_corrupt_backup_denies_finalization(self):
        self.f.apply()
        (self.marker / 'backup' / 'README.md').write_bytes(b'corrupt')
        with self.assertRaisesRegex(u.UpdateError, 'backup differs'):
            self.finalize()
        self.assert_gate()

    def test_tampered_intent_denies_finalization(self):
        self.f.apply()
        (self.marker / 'intent.json').write_bytes(b'{}')
        with self.assertRaisesRegex(u.UpdateError, 'intent differs'):
            self.finalize()
        self.assert_gate()

    def test_busy_lock_denies_finalization(self):
        self.f.apply()
        with u.installation_lock(self.root):
            with self.assertRaises(u.UpdateError):
                self.finalize()
        self.assert_gate()

    def test_rename_failure_retains_gate_and_retry_succeeds(self):
        self.f.apply()
        with patch('os.rename', side_effect=OSError('unavailable')):
            with self.assertRaisesRegex(u.UpdateError, 'Finalization unavailable'):
                self.finalize()
        self.assert_gate()
        self.f.assert_tree(self.f.new_files)
        self.assertTrue(self.finalize().is_dir())
        self.assertFalse(self.marker.exists())

    def test_invalid_signature_and_invalid_outcome_denied(self):
        from dataclasses import replace
        self.f.apply()
        with self.assertRaises(u.UpdateError):
            self.finalize('auto')
        self.f.target = replace(self.f.target, signature=b'x'*64)
        with self.assertRaises(u.UpdateError):
            self.finalize()
        self.assert_gate()


class StandaloneTransactionTests(unittest.TestCase):
    def setUp(self):
        self.f = StandaloneUpdaterTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.root = self.f.root
        self.marker = self.root / u.UPDATE_TRANSACTION_NAME
        self.policy = self.root / 'automation-permissions.json'

    def grant(self):
        from command_relay.relay_permissions import with_permission
        self.policy.write_text(json.dumps(with_permission({}, 'update_install', enabled=True)), encoding='utf-8')

    def run_mode(self, action, token=None, tty=True):
        import sys
        stdin = io.StringIO(token or '')
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(stdin, 'isatty', return_value=tty), patch.object(stderr, 'isatty', return_value=tty), \
                patch.object(sys, 'stdin', stdin), patch.object(sys, 'stdout', stdout), patch.object(sys, 'stderr', stderr):
            status = u.updater_main(['--'+action, *self.f.args()[1:]])
        return status, stdout.getvalue(), stderr.getvalue()

    def test_install_confirmed_and_finalized(self):
        self.grant()
        before = self.policy.read_bytes()
        status, output, prompt = self.run_mode('install', 'INSTALL 4.10.0\n')
        self.assertEqual(status, 0, prompt)
        result = json.loads(output)
        self.assertEqual(result['outcome'], 'commit')
        self.assertFalse(result['restart_performed'])
        self.assertFalse(self.marker.exists())
        from pathlib import Path
        self.assertTrue((Path(result['evidence'])/'intent.json').is_file())
        self.assertEqual((self.root/'Start.pyw').read_bytes(), b'new launcher')
        self.assertEqual((self.root/'settings.json').read_bytes(), b'preserve me')
        self.assertEqual(self.policy.read_bytes(), before)

    def test_default_deny_and_cancel(self):
        before = self.f.snapshot()
        status, output, _ = self.run_mode('install', 'INSTALL 4.10.0\n')
        self.assertEqual((status, output), (1, ''))
        self.assertEqual(self.f.snapshot(), before)
        self.grant()
        before = self.f.snapshot()
        for token, tty in (('INSTALL 4.10.0\n', False), ('no\n', True), ('', True)):
            status, output, _ = self.run_mode('install', token, tty)
            self.assertEqual((status, output), (1, ''))
            self.assertEqual(self.f.snapshot(), before)
        self.assertFalse(self.marker.exists())

    def test_permission_revoked_after_confirmation(self):
        self.grant()
        with patch.object(u, '_confirm_update_operation', side_effect=lambda *a: self.policy.write_text('{}')):
            status, _, _ = self.run_mode('install')
        self.assertEqual(status, 1)
        self.assertFalse(self.marker.exists())
        self.assertEqual((self.root/'Start.pyw').read_bytes(), self.f.fixture.files['Start.pyw'])

    def test_policy_lock_and_duplicate_rejected(self):
        self.grant()
        lock = self.root / '.automation-permissions.lock'
        lock.touch()
        self.assertEqual(self.run_mode('install', 'INSTALL 4.10.0\n')[0], 1)
        lock.unlink()
        self.policy.write_text('{"automation_permissions":{},"automation_permissions":{}}')
        self.assertEqual(self.run_mode('install', 'INSTALL 4.10.0\n')[0], 1)
        self.assertFalse(self.marker.exists())

    def test_lock_held_during_confirmation_and_finalization(self):
        self.grant()
        original = u._finalize_pending_update_locked
        def confirm(*args):
            with self.assertRaises(u.UpdateError):
                with u.installation_lock(self.root):
                    self.fail('lock released during confirmation')
        def finalize(*args, **kwargs):
            with self.assertRaises(u.UpdateError):
                with u.installation_lock(self.root):
                    self.fail('lock released before finalization')
            return original(*args, **kwargs)
        with patch.object(u, '_confirm_update_operation', side_effect=confirm), \
                patch.object(u, '_finalize_pending_update_locked', side_effect=finalize):
            self.assertEqual(self.run_mode('install')[0], 0)

    def test_failed_install_then_manual_recovery_without_grant(self):
        self.grant()
        replace = u._replace_rehearsal_file
        def interrupt(*args):
            replace(*args)
            raise OSError('simulated error')
        with patch.object(u, '_replace_rehearsal_file', side_effect=interrupt):
            self.assertEqual(self.run_mode('install', 'INSTALL 4.10.0\n')[0], 1)
        self.assertTrue(self.marker.is_dir())
        self.policy.unlink()
        self.assertEqual(self.run_mode('recover', 'no\n')[0], 1)
        self.assertTrue(self.marker.is_dir())
        status, output, error = self.run_mode('recover', 'RECOVER 4.10.0\n')
        self.assertEqual(status, 0, error)
        self.assertEqual(json.loads(output)['outcome'], 'rollback')
        self.assertFalse(self.marker.exists())
        self.assertEqual((self.root/'Start.pyw').read_bytes(), self.f.fixture.files['Start.pyw'])

    def test_bad_signature_and_busy_denied(self):
        self.grant()
        with u.installation_lock(self.root):
            self.assertEqual(self.run_mode('install', 'INSTALL 4.10.0\n')[0], 1)
        next(self.f.target.glob('*.sig')).write_bytes(b'x'*64)
        self.assertEqual(self.run_mode('install', 'INSTALL 4.10.0\n')[0], 1)
        self.assertFalse(self.marker.exists())

    def test_code_inside_destination_denied(self):
        self.grant()
        with patch.object(u, '__file__', str(self.root/'command_relay'/'relay_updates.py')):
            self.assertEqual(self.run_mode('install', 'INSTALL 4.10.0\n')[0], 1)
        self.assertFalse(self.marker.exists())

    def test_changed_dependencies_denied(self):
        self.grant()
        package = self.f.fixture.package(u.VERSION, '4.10.0', dict(self.f.fixture.new_files,
                                                **{'requirements.txt': b'new requirements'}))
        folder = self.f.target
        stem = package.download.info.archive.name[:-4]
        (folder/(stem+'.zip')).write_bytes(package.download.archive)
        (folder/(stem+'.sha256')).write_bytes(f'{package.download.sha256}  {stem}.zip\n'.encode())
        (folder/(stem+'.manifest.json')).write_bytes(package.manifest)
        (folder/(stem+'.manifest.sig')).write_bytes(package.signature)
        self.assertEqual(self.run_mode('install', 'INSTALL 4.10.0\n')[0], 1)
        self.assertFalse(self.marker.exists())
