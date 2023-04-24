import json

from django.conf import settings
from django.test.utils import override_settings

import responses

from unittest.mock import Mock, patch

from olympia.amo import monitors
from olympia.amo.tests import TestCase


class TestMonitor(TestCase):
    @patch('socket.socket')
    def test_memcache(self, mock_socket):
        mocked_caches = {
            'default': {
                'BACKEND': 'django.core.cache.backends.memcached.MemcachedCache',
                'LOCATION': '127.0.0.1:6666',
            }
        }
        cache_info = mocked_caches['default']['LOCATION'].split(':')
        mock_socket_instance = Mock()
        mock_socket.return_value = mock_socket_instance
        with override_settings(CACHES=mocked_caches):
            status, memcache_results = monitors.memcache()
            assert status == ''

            # Expect socket.connect() to be called once, with the cache info.
            connect_call_args = mock_socket_instance.connect.call_args_list
            assert len(connect_call_args) == 1
            mock_socket_instance.connect.assert_called_with(
                (cache_info[0], int(cache_info[1]))
            )

            # Expect memcached_results to contain cache info and then a boolean
            # indicating everything is OK.
            assert len(memcache_results) == 1
            assert list(memcache_results[0][0:2]) == cache_info
            assert memcache_results[0][2]

    def test_libraries(self):
        status, libraries_result = monitors.libraries()
        assert status == ''
        assert libraries_result == [('PIL+JPEG', True, 'Got it!')]

    def test_elastic(self):
        status, elastic_result = monitors.elastic()
        assert status == ''

    @patch('os.path.exists')
    @patch('os.access')
    def test_path(self, mock_exists, mock_access):
        status, path_result = monitors.path()
        assert status == ''

    @override_settings(TMP_PATH='foo')
    def test_path_is_no_bytestring(self):
        status, path_result = monitors.path()
        assert status == 'check main status page for broken perms / values'
        assert path_result[0][3].endswith('should be a bytestring!')

    @override_settings(CELERY_BROKER_URL='amqp://localhost/test')
    @patch('olympia.amo.monitors.Connection')
    def test_rabbitmq(self, mock_connection):
        status, rabbitmq_results = monitors.rabbitmq()
        assert status == ''
        assert rabbitmq_results[0][1]

    def test_signer(self):
        responses.add_passthru(settings.AUTOGRAPH_CONFIG['server_url'])

        status, signer_result = monitors.signer()
        assert status == ''

    def test_database(self):
        with self.assertNumQueries(2):
            status, result = monitors.database()
        assert status == ''
        assert result is None

    def test_remotesettings_success(self):
        responses.add(
            responses.GET,
            f'{settings.REMOTE_SETTINGS_WRITER_URL}__heartbeat__',
            status=200,
            body=json.dumps({'check': True}),
        )
        responses.add(
            responses.GET,
            settings.REMOTE_SETTINGS_WRITER_URL,
            status=200,
            body=json.dumps({'user': {'id': 'account:amo'}}),
        )
        obtained, _ = monitors.remotesettings()
        assert obtained == ''

    def test_remotesettings_bad_credentials(self):
        responses.add(
            responses.GET,
            f'{settings.REMOTE_SETTINGS_WRITER_URL}__heartbeat__',
            status=200,
            body=json.dumps({'check': True}),
        )
        responses.add(
            responses.GET,
            settings.REMOTE_SETTINGS_WRITER_URL,
            status=200,
            body=json.dumps({}),
        )
        obtained, _ = monitors.remotesettings()
        assert 'Invalid credentials' in obtained

    def test_remotesettings_fail(self):
        responses.add(
            responses.GET,
            f'{settings.REMOTE_SETTINGS_WRITER_URL}__heartbeat__',
            status=503,
            body=json.dumps({'check': False}),
        )
        responses.add(
            responses.GET,
            settings.REMOTE_SETTINGS_WRITER_URL,
            status=200,
            body=json.dumps({}),
        )
        obtained, _ = monitors.remotesettings()
        assert '503 Server Error: Service Unavailable' in obtained
