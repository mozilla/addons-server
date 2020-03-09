import tempfile
from unittest import mock

from django.conf import settings
from django.test.utils import override_settings

import responses

from olympia.amo.tests import TestCase
from olympia.lib.kinto import KintoServer


@override_settings(
    BLOCKLIST_KINTO_USERNAME='test_username',
    BLOCKLIST_KINTO_PASSWORD='test_password')
class TestKintoServer(TestCase):

    def test_setup_test_server_auth(self):
        server = KintoServer('foo', 'baa')
        responses.add(
            responses.GET,
            settings.KINTO_API_URL,
            content_type='application/json',
            json={'user': {'id': ''}})
        responses.add(
            responses.PUT,
            settings.KINTO_API_URL + 'accounts/test_username',
            content_type='application/json',
            json={'data': {'password': 'test_password'}},
            status=201)
        server.setup_test_server_auth()

        # If repeated then the account should exist the 2nd time
        responses.add(
            responses.GET,
            settings.KINTO_API_URL,
            content_type='application/json',
            json={'user': {'id': 'account:test_username'}})
        server.setup_test_server_auth()

    def test_setup_test_server_collection(self):
        server = KintoServer('foo', 'baa')
        responses.add(
            responses.GET,
            settings.KINTO_API_URL + 'buckets/foo/collections/baa/records',
            content_type='application/json',
            status=403)
        responses.add(
            responses.PUT,
            settings.KINTO_API_URL + 'buckets/foo',
            content_type='application/json')
        responses.add(
            responses.PUT,
            settings.KINTO_API_URL + 'buckets/foo/collections/baa',
            content_type='application/json',
            status=201)
        server.setup_test_server_collection()

        # If repeated then the collection shouldn't 403 a second time
        responses.add(
            responses.GET,
            settings.KINTO_API_URL + 'buckets/foo/collections/baa/records',
            content_type='application/json')
        server.setup_test_server_collection()

    @override_settings(KINTO_API_IS_TEST_SERVER=False)
    def test_setup_not_test_server(self):
        server = KintoServer('foo', 'baa')

        server.setup()  # will just return
        assert server._setup_done
        assert server.bucket == 'foo'

    @override_settings(KINTO_API_IS_TEST_SERVER=True)
    def test_setup(self):
        server = KintoServer('foo', 'baa')
        responses.add(
            responses.GET,
            settings.KINTO_API_URL,
            content_type='application/json',
            json={'user': {'id': 'account:test_username'}})
        records_url = (
            settings.KINTO_API_URL +
            'buckets/foo_test_username/collections/baa/records')
        responses.add(
            responses.GET,
            records_url,
            content_type='application/json')

        server.setup()
        assert server._setup_done
        assert server.bucket == 'foo_test_username'

        server.setup()  # a second time shouldn't make any requests

    def test_publish_record(self):
        server = KintoServer('foo', 'baa')
        server._setup_done = True
        assert not server._needs_signoff
        responses.add(
            responses.POST,
            settings.KINTO_API_URL + 'buckets/foo/collections/baa/records',
            content_type='application/json',
            json={'data': {'id': 'new!'}})

        record = server.publish_record({'something': 'somevalue'})
        assert server._needs_signoff
        assert record == {'id': 'new!'}

        url = (
            settings.KINTO_API_URL +
            'buckets/foo/collections/baa/records/an-id')
        responses.add(
            responses.PUT,
            url,
            content_type='application/json',
            json={'data': {'id': 'updated'}})

        record = server.publish_record({'something': 'somevalue'}, 'an-id')
        assert record == {'id': 'updated'}

    @mock.patch('olympia.lib.kinto.uuid')
    def test_publish_attachment(self, uuidmock):
        uuidmock.uuid4.return_value = 1234567890
        server = KintoServer('foo', 'baa')
        server._setup_done = True
        assert not server._needs_signoff
        url = (
            settings.KINTO_API_URL +
            'buckets/foo/collections/baa/records/1234567890/attachment')
        responses.add(
            responses.POST,
            url,
            json={'data': {'id': '1234567890'}})

        with tempfile.TemporaryFile() as attachment:
            record = server.publish_attachment(
                {'something': 'somevalue'}, ('file', attachment))
        assert server._needs_signoff
        assert record == {'id': '1234567890'}

        url = (
            settings.KINTO_API_URL +
            'buckets/foo/collections/baa/records/an-id/attachment')
        responses.add(
            responses.POST,
            url,
            json={'data': {'id': 'an-id'}})

        with tempfile.TemporaryFile() as attachment:
            record = server.publish_attachment(
                {'something': 'somevalue'}, ('otherfile', attachment), 'an-id')
        assert record == {'id': 'an-id'}

    def test_delete_record(self):
        server = KintoServer('foo', 'baa')
        server._setup_done = True
        assert not server._needs_signoff
        url = (
            settings.KINTO_API_URL +
            'buckets/foo/collections/baa/records/an-id')
        responses.add(
            responses.DELETE,
            url,
            content_type='application/json')

        server.delete_record('an-id')
        assert server._needs_signoff

    def test_signoff(self):
        server = KintoServer('foo', 'baa')
        server._setup_done = True
        # should return because nothing to signoff
        server.signoff_request()

        server._needs_signoff = True
        url = (
            settings.KINTO_API_URL +
            'buckets/foo/collections/baa')
        responses.add(
            responses.PATCH,
            url,
            content_type='application/json')
        server.signoff_request()
        assert not server._needs_signoff
