import json
from contextlib import contextmanager
from json.decoder import JSONDecodeError
from unittest import TestCase
from unittest.mock import MagicMock, call, patch
from urllib.error import HTTPError

from scripts.health_check import main


class TestHealthCheck(TestCase):
    def setUp(self):
        path = patch('urllib.request.urlopen')
        self.mock_urlsopen = path.start()
        self.addCleanup(path.stop)

    def _url(self, path: str):
        return f'http://nginx/{path}'

    @contextmanager
    def mock_urls(self, mocks: tuple[str, int, any]):
        def create_mock_response(request, status, body):
            cm = MagicMock()
            cm.status = status
            # Set headers attribute, needed by HTTPError
            cm.headers = {}
            mock_info = MagicMock()
            mock_info.get_content_charset.return_value = 'utf-8'

            mock_data = MagicMock()
            data = body(request) if callable(body) else body
            if isinstance(data, dict):
                data = json.dumps(data)
            mock_data.decode.return_value = data
            cm.read.return_value = mock_data
            cm.info.return_value = mock_info
            cm.__enter__.return_value = cm

            # If status is not OK, raise HTTPError with the mock response
            if status != 200:
                raise HTTPError(
                    url=request.full_url,
                    code=status,
                    msg=f'Mock HTTP Error {status}',
                    hdrs=mock_info,
                    fp=cm,
                )
            return cm

        def side_effect(request, timeout=None):
            url = request.full_url
            for path, status, body in mocks:
                if url == self._url(path):
                    return create_mock_response(request, status, body)
            raise ValueError(f'Unexpected URL requested: {url}')

        self.mock_urlsopen.side_effect = side_effect

        self.mock_urlsopen.side_effect = side_effect

        yield

    def _monitor(self, name: str, state: bool, status: str):
        return {name: {'state': state, 'status': status}}

    def test_basic(self):
        """Test happy path returning no failing monitors"""
        with self.mock_urls(
            [
                ('__version__', 200, {'version': '1.0.0'}),
                ('services/monitor.json', 200, self._monitor('two', True, '')),
            ]
        ):
            main('container')

    def test_missing_version(self):
        with (
            self.assertRaises(HTTPError),
            self.mock_urls(
                [
                    ('__version__', 503, ''),
                    ('services/monitor.json', 200, self._monitor('two', True, '')),
                ]
            ),
        ):
            main('container')

    def test_invalid_version(self):
        with (
            self.assertRaises(JSONDecodeError),
            self.mock_urls(
                [
                    ('__version__', 200, '{not valid json'),
                    ('services/monitor.json', 200, self._monitor('two', True, '')),
                ]
            ),
        ):
            main('container')

    def test_missing_monitors(self):
        with (
            self.assertRaises(HTTPError),
            self.mock_urls(
                [
                    ('services/monitor.json', 503, ''),
                    ('__version__', 200, {'version': '1.0.0'}),
                ]
            ),
        ):
            main('container')

    def test_failing_monitors(self):
        failing_monitor = self._monitor('fail', False, 'Service is down')
        with self.mock_urls(
            [
                ('services/monitor.json', 200, failing_monitor),
                ('__version__', 200, {'version': '1.0.0'}),
            ]
        ):
            results, has_failures = main('container')
            self.assertTrue(has_failures)

    def test_request_retries(self):
        for status in [502, 503, 504]:
            with self.subTest(status=status):
                count = 0

                def increment_count(request):
                    nonlocal count
                    count += 1
                    return ''

                with (
                    self.assertRaises(HTTPError),
                    self.mock_urls(
                        [
                            ('services/monitor.json', status, ''),
                            ('__version__', status, increment_count),
                        ]
                    ),
                ):
                    # Retry 2 times means we should retry main if successful
                    # and has errors. In this case the request itself is failing
                    # which will be retried 5 times and then raise the error.
                    main('container', retries=2)

                assert count == 5

    @patch('scripts.health_check.main', wraps=main)
    def test_retry_failures(self, mock_main):
        with self.mock_urls(
            [
                ('__version__', 200, {'version': '1.0.0'}),
                (
                    'services/monitor.json',
                    500,
                    self._monitor('fail', False, 'Service is down'),
                ),
            ]
        ):
            main('container', retries=2)

        # Should be called 3 times total - initial call plus 2 retries
        self.assertEqual(mock_main.call_count, 2)

        # Verify retry attempts were made with incrementing attempt numbers
        mock_main.assert_has_calls(
            [call('container', False, 2, 1), call('container', False, 2, 2)]
        )

    def test_retry_unhandled_status(self):
        with (
            self.assertRaises(HTTPError),
            self.mock_urls(
                [
                    ('services/monitor.json', 522, ''),
                    ('__version__', 503, ''),
                ]
            ),
        ):
            main('container', retries=5)
