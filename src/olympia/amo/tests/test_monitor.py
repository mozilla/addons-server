from django.test.utils import override_settings

from mock import Mock, patch

from olympia.amo.tests import TestCase
from olympia.amo import monitors
import responses


class TestMonitor(TestCase):
    @patch('socket.socket')
    def test_memcache(self, mock_socket):
        mocked_caches = {
            'default': {
                'BACKEND': 'django.core.cache.backends.memcached'
                           '.MemcachedCache',
                'LOCATION': '127.0.0.1:6666'
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
                (cache_info[0], int(cache_info[1])))

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

    @override_settings(TMP_PATH=u'foo')
    def test_path_is_no_bytestring(self):
        status, path_result = monitors.path()
        assert status == 'check main status page for broken perms / values'
        assert path_result[0][3].endswith('should be a bytestring!')

    @override_settings(BROKER_URL="amqp://localhost/test")
    @patch('olympia.amo.monitors.Connection')
    def test_rabbitmq(self, mock_connection):
        status, rabbitmq_results = monitors.rabbitmq()
        assert status == ''
        assert rabbitmq_results[0][1]

    @patch('olympia.amo.monitors.redislib')
    def test_redis(self, mock_redislib):
        mocked_redis_backends = {
            'master': {
                'DB': 0,
                'HOST': 'localhost',
                'OPTIONS': {
                    'socket_timeout': 0.5
                },
                'PASSWORD': None,
                'PORT': 4242
            }
        }
        mocked_redis_info = {
            'redis_build_id': 'not_a_real_redis',
        }
        mock_redislib.Redis.return_value.info = lambda: mocked_redis_info
        with override_settings(REDIS_BACKENDS=mocked_redis_backends):
            status, redis_results = monitors.redis()
        assert status == ''
        assert redis_results == {'master': mocked_redis_info}

    @override_settings(SIGNING_SERVER='http://localhost')
    @responses.activate
    def test_signer(self):
        responses.add(
            responses.GET,
            'http://localhost/status',
            status=200
        )
        status, signer_result = monitors.signer()
        assert status == ''
