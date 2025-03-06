from unittest import TestCase

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
            'services/monitors.json', status=200, json=self._monitor('two', True, '')
        )
        main('local', False)

    def test_missing_version(self):
        self.mock_url('__version__', status=500)
        self.mock_url('__heartbeat__', status=200, json=self._monitor('one', True, ''))
        self.mock_url(
            'services/monitors.json', status=200, json=self._monitor('two', True, '')
        )

        with self.assertRaisesRegex(ValueError, 'Error fetching version data'):
            main('local', False)

    def test_invalid_version(self):
        self.mock_url('__version__', status=200, body='{not valid json')
        self.mock_url('__heartbeat__', status=200, json=self._monitor('one', True, ''))
        self.mock_url(
            'services/monitors.json', status=200, json=self._monitor('two', True, '')
        )

        with self.assertRaisesRegex(ValueError, 'Error fetching version data'):
            main('local', False)

    def test_missing_heartbeat(self):
        self.mock_url('__heartbeat__', status=500)
        self.mock_url('__version__', status=200, json={'version': '1.0.0'})
        self.mock_url(
            'services/monitors.json', status=200, json=self._monitor('two', True, '')
        )

        with self.assertRaisesRegex(ValueError, 'Error fetching heartbeat data'):
            main('local', False)

    def test_failing_heartbeat(self):
        failing_monitor = self._monitor('fail', False, 'Service is down')
        success_monitor = self._monitor('success', True, '')
        self.mock_url('__heartbeat__', status=200, json=failing_monitor)
        self.mock_url('__version__', status=200, json={'version': '1.0.0'})
        self.mock_url('services/monitors.json', status=200, json=success_monitor)

        with self.assertRaisesRegex(ValueError, r'Some monitors are failing.*fail'):
            main('local', False)

    def test_missing_monitors(self):
        self.mock_url('services/monitors.json', status=500)
        self.mock_url('__version__', status=200, json={'version': '1.0.0'})
        self.mock_url('__heartbeat__', status=200, json=self._monitor('one', True, ''))

        with self.assertRaisesRegex(ValueError, 'Error fetching monitors data'):
            main('local', False)

    def test_failing_monitors(self):
        failing_monitor = self._monitor('fail', False, 'Service is down')
        success_monitor = self._monitor('success', True, '')
        self.mock_url('services/monitors.json', status=200, json=failing_monitor)
        self.mock_url('__version__', status=200, json={'version': '1.0.0'})
        self.mock_url('__heartbeat__', status=200, json=success_monitor)

        with self.assertRaisesRegex(ValueError, r'Some monitors are failing.*fail'):
            main('local', False)
