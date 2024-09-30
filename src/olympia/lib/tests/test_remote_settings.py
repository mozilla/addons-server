import json
import tempfile
from unittest import mock

from django.conf import settings
from django.test.utils import override_settings

import responses

from olympia.amo.tests import TestCase
from olympia.lib.remote_settings import RemoteSettings


@override_settings(
    BLOCKLIST_REMOTE_SETTINGS_USERNAME='test_username',
    BLOCKLIST_REMOTE_SETTINGS_PASSWORD='test_password',
)
class TestRemoteSettings(TestCase):
    @override_settings(REMOTE_SETTINGS_IS_TEST_SERVER=False)
    def test_bucket_not_altered(self):
        server = RemoteSettings('foo', 'baa')
        assert server.bucket == 'foo'

    def test_publish_record(self):
        server = RemoteSettings('foo', 'baa')
        server._setup_done = True
        assert not server._changes
        responses.add(
            responses.POST,
            settings.REMOTE_SETTINGS_WRITER_URL + 'buckets/foo/collections/baa/records',
            content_type='application/json',
            json={'data': {'id': 'new!'}},
        )

        record = server.publish_record({'something': 'somevalue'})
        assert server._changes
        assert record == {'id': 'new!'}

        url = (
            settings.REMOTE_SETTINGS_WRITER_URL
            + 'buckets/foo/collections/baa/records/an-id'
        )
        responses.add(
            responses.PUT,
            url,
            content_type='application/json',
            json={'data': {'id': 'updated'}},
        )

        record = server.publish_record({'something': 'somevalue'}, 'an-id')
        assert record == {'id': 'updated'}

    @mock.patch('olympia.lib.remote_settings.uuid')
    def test_publish_attachment(self, uuidmock):
        uuidmock.uuid4.return_value = 1234567890
        server = RemoteSettings('foo', 'baa')
        server._setup_done = True
        assert not server._changes
        url = (
            settings.REMOTE_SETTINGS_WRITER_URL
            + 'buckets/foo/collections/baa/records/1234567890/attachment'
        )
        responses.add(responses.POST, url, json={'data': {'id': '1234567890'}})

        with tempfile.TemporaryFile() as attachment:
            record = server.publish_attachment(
                {'something': 'somevalue'}, ('file', attachment)
            )
        assert server._changes
        assert record == {'id': '1234567890'}

        url = (
            settings.REMOTE_SETTINGS_WRITER_URL
            + 'buckets/foo/collections/baa/records/an-id/attachment'
        )
        responses.add(responses.POST, url, json={'data': {'id': 'an-id'}})

        with tempfile.TemporaryFile() as attachment:
            record = server.publish_attachment(
                {'something': 'somevalue'}, ('otherfile', attachment), 'an-id'
            )
        assert record == {'id': 'an-id'}

    def test_delete_record(self):
        server = RemoteSettings('foo', 'baa')
        server._setup_done = True
        assert not server._changes
        url = (
            settings.REMOTE_SETTINGS_WRITER_URL
            + 'buckets/foo/collections/baa/records/an-id'
        )
        responses.add(responses.DELETE, url, content_type='application/json')

        server.delete_record('an-id')
        assert server._changes

    def test_delete_all_records(self):
        server = RemoteSettings('foo', 'baa')
        server._setup_done = True
        assert not server._changes
        url = (
            settings.REMOTE_SETTINGS_WRITER_URL + 'buckets/foo/collections/baa/records'
        )
        responses.add(responses.DELETE, url, content_type='application/json')

        server.delete_all_records()
        assert server._changes

    def test_complete_session(self):
        server = RemoteSettings('foo', 'baa')
        server._setup_done = True
        # should return because nothing to signoff
        server.complete_session()

        server._changes = True
        url = settings.REMOTE_SETTINGS_WRITER_URL + 'buckets/foo/collections/baa'
        responses.add(responses.PATCH, url, content_type='application/json')
        server.complete_session()
        assert not server._changes
        assert (
            responses.calls[0].request.body
            == json.dumps({'data': {'status': 'to-review'}}).encode()
        )

    def test_complete_session_no_signoff(self):
        server = RemoteSettings('foo', 'baa', sign_off_needed=False)
        server._setup_done = True
        # should return because nothing to signoff
        server.complete_session()

        server._changes = True
        url = settings.REMOTE_SETTINGS_WRITER_URL + 'buckets/foo/collections/baa'
        responses.add(responses.PATCH, url, content_type='application/json')
        server.complete_session()
        assert not server._changes
        assert (
            responses.calls[0].request.body
            == json.dumps({'data': {'status': 'to-sign'}}).encode()
        )
