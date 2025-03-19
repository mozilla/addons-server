from json.decoder import JSONDecodeError
from unittest import TestCase
from unittest.mock import call, patch

import requests
import responses

from scripts.health_check import main


class TestHealthCheck(TestCase):
    def _url(self, path: str):
        return f'http://nginx/{path}'

    def mock_url(self, path: str, **kwargs):
        responses.add(
            responses.GET,
            self._url(path),
            **kwargs,
        )

    def _monitor(self, name: str, state: bool, status: str):
        return {name: {'state': state, 'status': status}}

    def test_basic(self):
        """Test happy path returning no failing monitors"""
        self.mock_url('__version__', status=200, json={'version': '1.0.0'})
        self.mock_url('__heartbeat__', status=200, json=self._monitor('one', True, ''))
        self.mock_url(
            'services/__heartbeat__', status=200, json=self._monitor('two', True, '')
        )
        main('local')

    def test_missing_version(self):
        self.mock_url('__version__', status=500)
        self.mock_url('__heartbeat__', status=200, json=self._monitor('one', True, ''))
        self.mock_url(
            'services/__heartbeat__', status=200, json=self._monitor('two', True, '')
        )

        with self.assertRaises(JSONDecodeError):
            main('local')

    def test_invalid_version(self):
        self.mock_url('__version__', status=200, body='{not valid json')
        self.mock_url('__heartbeat__', status=200, json=self._monitor('one', True, ''))
        self.mock_url(
            'services/__heartbeat__', status=200, json=self._monitor('two', True, '')
        )

        with self.assertRaises(JSONDecodeError):
            main('local')

    def test_missing_heartbeat(self):
        self.mock_url('__heartbeat__', status=500)
        self.mock_url('__version__', status=200, json={'version': '1.0.0'})
        self.mock_url(
            'services/__heartbeat__', status=200, json=self._monitor('two', True, '')
        )

        with self.assertRaises(JSONDecodeError):
            main('local')

    def test_failing_heartbeat(self):
        failing_monitor = self._monitor('fail', False, 'Service is down')
        success_monitor = self._monitor('success', True, '')
        self.mock_url('__heartbeat__', status=200, json=failing_monitor)
        self.mock_url('__version__', status=200, json={'version': '1.0.0'})
        self.mock_url('services/__heartbeat__', status=200, json=success_monitor)

        results, has_failures = main('local')
        self.assertTrue(has_failures)

    def test_missing_monitors(self):
        self.mock_url('services/__heartbeat__', status=500)
        self.mock_url('__version__', status=200, json={'version': '1.0.0'})
        self.mock_url('__heartbeat__', status=200, json=self._monitor('one', True, ''))

        with self.assertRaises(JSONDecodeError):
            main('local')

    def test_failing_monitors(self):
        failing_monitor = self._monitor('fail', False, 'Service is down')
        success_monitor = self._monitor('success', True, '')
        self.mock_url('services/__heartbeat__', status=200, json=failing_monitor)
        self.mock_url('__version__', status=200, json={'version': '1.0.0'})
        self.mock_url('__heartbeat__', status=200, json=success_monitor)

        results, has_failures = main('local')
        self.assertTrue(has_failures)

    def test_request_retries(self):
        count = 0

        def increment_count(request):
            nonlocal count
            count += 1
            return (503, {}, '')

        # Mock the get request to fail with a 503 status
        self.mock_url('__version__', status=503)
        self.mock_url('__heartbeat__', status=503)
        self.mock_url('services/__heartbeat__', status=503)

        responses.add_callback(
            responses.GET,
            self._url('__version__'),
            callback=increment_count,
        )

        with self.assertRaises(requests.exceptions.RequestException):
            main('local', retries=0)

        assert count == 5

    @patch('scripts.health_check.main', wraps=main)
    def test_retry_failures(self, mock_main):
        self.mock_url('__version__', status=200, json={'version': '1.0.0'})
        self.mock_url('__heartbeat__', status=200, json=self._monitor('one', True, ''))
        self.mock_url(
            'services/__heartbeat__',
            json=self._monitor('fail', False, 'Service is down'),
        )

        main('local', retries=2)

        # Should be called 3 times total - initial call plus 2 retries
        self.assertEqual(mock_main.call_count, 2)

        # Verify retry attempts were made with incrementing attempt numbers
        mock_main.assert_has_calls(
            [call('local', False, 2, 1), call('local', False, 2, 2)]
        )
