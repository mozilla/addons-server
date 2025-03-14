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
            'services/__heartbeat__', status=200, json=self._monitor('two', True, '')
        )
        results, _ = main('local', False)

    def test_missing_version(self):
        self.mock_url('__version__', status=500)
        self.mock_url('__heartbeat__', status=200, json=self._monitor('one', True, ''))
        self.mock_url(
            'services/__heartbeat__', status=200, json=self._monitor('two', True, '')
        )

        results, _ = main('local', False)
        self.assertEqual(results['version'], {})

    def test_invalid_version(self):
        self.mock_url('__version__', status=200, body='{not valid json')
        self.mock_url('__heartbeat__', status=200, json=self._monitor('one', True, ''))
        self.mock_url(
            'services/__heartbeat__', status=200, json=self._monitor('two', True, '')
        )

        results, _ = main('local', False)
        self.assertEqual(results['version'], {})

    def test_missing_heartbeat(self):
        self.mock_url('__heartbeat__', status=500)
        self.mock_url('__version__', status=200, json={'version': '1.0.0'})
        self.mock_url(
            'services/__heartbeat__', status=200, json=self._monitor('two', True, '')
        )

        results, _ = main('local', False)
        self.assertEqual(results['heartbeat'], {})

    def test_failing_heartbeat(self):
        failing_monitor = self._monitor('fail', False, 'Service is down')
        success_monitor = self._monitor('success', True, '')
        self.mock_url('__heartbeat__', status=200, json=failing_monitor)
        self.mock_url('__version__', status=200, json={'version': '1.0.0'})
        self.mock_url('services/__heartbeat__', status=200, json=success_monitor)

        results, has_failures = main('local', False)
        self.assertTrue(has_failures)
        # Check for failing monitors
        failing_monitors = []
        for monitor_type, monitor_data in results.items():
            if monitor_type == 'version':
                continue
            for name, details in monitor_data.get('data', {}).items():
                if details.get('state') is False:
                    failing_monitors.append(f'{monitor_type}.{name}')
        self.assertIn('heartbeat.fail', failing_monitors)

    def test_missing_monitors(self):
        self.mock_url('services/__heartbeat__', status=500)
        self.mock_url('__version__', status=200, json={'version': '1.0.0'})
        self.mock_url('__heartbeat__', status=200, json=self._monitor('one', True, ''))

        results, _ = main('local', False)
        self.assertEqual(results['monitors'], {})

    def test_failing_monitors(self):
        failing_monitor = self._monitor('fail', False, 'Service is down')
        success_monitor = self._monitor('success', True, '')
        self.mock_url('services/__heartbeat__', status=200, json=failing_monitor)
        self.mock_url('__version__', status=200, json={'version': '1.0.0'})
        self.mock_url('__heartbeat__', status=200, json=success_monitor)

        results, has_failures = main('local', False)
        self.assertTrue(has_failures)
        # Check for failing monitors
        failing_monitors = []
        for monitor_type, monitor_data in results.items():
            if monitor_type == 'version':
                continue
            for name, details in monitor_data.get('data', {}).items():
                if details.get('state') is False:
                    failing_monitors.append(f'{monitor_type}.{name}')
        self.assertIn('monitors.fail', failing_monitors)
