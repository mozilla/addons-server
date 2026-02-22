import json
import re
from unittest.mock import MagicMock, Mock, patch

from django.conf import settings
from django.test.utils import override_settings

import pytest
import responses

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

    @pytest.mark.es_tests
    def test_elastic(self):
        status, elastic_result = monitors.elastic()
        assert status == ''

    @patch('olympia.amo.monitors.get_es', side_effect=Exception('Connection error'))
    def test_elastic_connection_error(self, _):
        status, elastic_result = monitors.elastic()
        assert status == 'Failed to connect to Elasticsearch'
        assert 'Connection error' in elastic_result['exception']

    def test_elastic_status_red(self):
        mock_es = MagicMock()
        mock_es.cluster.health.return_value = {'status': 'red'}
        with patch('olympia.amo.monitors.get_es', return_value=mock_es):
            status, elastic_result = monitors.elastic()
            assert status == 'ES is red'
            assert elastic_result == {'status': 'red'}

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

    @override_settings(ENV='production')
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

    @override_settings(ENV='production')
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

    def test_cinder_success(self):
        url = settings.CINDER_SERVER_URL.replace('/api/v1/', '/health')
        responses.add(responses.GET, url, status=200, body=json.dumps({'http': True}))

        status, signer_result = monitors.cinder()
        assert signer_result is True
        assert status == ''

    def test_cinder_fail(self):
        url = settings.CINDER_SERVER_URL.replace('/api/v1/', '/health')
        responses.add(responses.GET, url, status=500, body=json.dumps({'http': False}))

        status, signer_result = monitors.cinder()
        assert signer_result is False
        assert status == (
            'Failed to chat with cinder: '
            f'500 Server Error: Internal Server Error for url: {url}'
        )

    def test_localdev_web_fail(self):
        responses.add(
            responses.GET,
            'http://nginx/__version__',
            status=500,
        )
        status, _ = monitors.localdev_web()
        assert 'Failed to ping web' in status

    def test_localdev_web_success(self):
        responses.add(
            responses.GET,
            'http://nginx/__version__',
            status=200,
        )
        status, _ = monitors.localdev_web()
        assert status == ''

    def test_celery_worker_failed(self):
        # Create a mock ping object
        mock_ping = MagicMock(return_value=None)
        mock_inspect = MagicMock()
        mock_inspect.ping = mock_ping

        with patch(
            'olympia.amo.monitors.celery.current_app.control.inspect',
            return_value=mock_inspect,
        ):
            status, result = monitors.celery_worker()
            assert result is None
            assert status == 'Celery worker is not connected'

    def test_celery_worker_success(self):
        # Create a mock ping object
        mock_ping = MagicMock(return_value={'celery@localhost': []})
        mock_inspect = MagicMock()
        mock_inspect.ping = mock_ping

        with patch(
            'olympia.amo.monitors.celery.current_app.control.inspect',
            return_value=mock_inspect,
        ):
            status, result = monitors.celery_worker()
            assert status == ''
            assert result is None

    @patch('olympia.amo.monitors.MySQLdb.connect')
    def test_olympia_db_unavailable(self, mock_connect):
        mock_connect.side_effect = Exception('Database is unavailable')
        status, result = monitors.olympia_database()
        assert status == 'Failed to connect to database: Database is unavailable'
        assert result is None

    @patch('olympia.amo.monitors.MySQLdb.connect')
    def test_olympia_db_database_does_not_exist(self, mock_connect):
        # Create a mock connection object
        mock_connection = MagicMock()
        mock_connect.return_value = mock_connection

        # Create a mock result object with num_rows returning 0
        mock_result = MagicMock()
        mock_result.num_rows.return_value = 0
        mock_connection.store_result.return_value = mock_result

        status, result = monitors.olympia_database()
        assert re.match(r'^Database .+ does not exist$', status)
        assert result is None
