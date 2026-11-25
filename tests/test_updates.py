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
