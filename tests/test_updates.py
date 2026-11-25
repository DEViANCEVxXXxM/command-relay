# SPDX-License-Identifier: Apache-2.0
import copy
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
