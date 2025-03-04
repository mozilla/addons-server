from unittest import TestCase
import responses


from scripts.health_check import main

class TestHealthCheck(TestCase):
    def _url(self, path: str):
        return f'http://nginx/{path}'

    def test_basic(self):
        """Test happy path returning no failing monitors"""
        responses.add(
            responses.GET,
            self._url('__version__'),
            status=200,
            json={'version': '1.0.0'},
        )
        responses.add(
            responses.GET,
            self._url('__healthcheck__?verbose=true'),
            status=200,
            json={'service': {'state': True, 'status': ''}},
        )
        main('local', False)

    def test_missing_version(self):
        responses.add(
            responses.GET,
            self._url('__version__'),
            status=500,
        )
        responses.add(
            responses.GET,
            self._url('__healthcheck__?verbose=true'),
            status=200,
            json={'service': {'state': True, 'status': ''}},
        )

        with self.assertRaisesRegex(ValueError, 'Error fetching version data'):
            main('local', False)

    def test_invalid_version(self):
        responses.add(
            responses.GET,
            self._url('__version__'),
            status=200,
            body='{not valid json',
        )
        responses.add(
            responses.GET,
            self._url('__healthcheck__?verbose=true'),
            status=200,
            json={'service': {'state': True, 'status': ''}},
        )
        with self.assertRaisesRegex(ValueError, 'Error fetching version data'):
            main('local', False)

    def test_missing_healthcheck(self):
        responses.add(
            responses.GET,
            self._url('__version__'),
            status=200,
            json={'version': '1.0.0'},
        )
        responses.add(
            responses.GET,
            self._url('__healthcheck__?verbose=true'),
            status=500,
        )

        with self.assertRaisesRegex(ValueError, 'Error fetching healthcheck data'):
            main('local', False)

    def test_failing_healthcheck(self):
        responses.add(
            responses.GET,
            self._url('__version__'),
            status=200,
            json={'version': '1.0.0'},
        )
        healthcheck_data = {
            'service': {'state': False, 'status': 'Service is down'}
        }
        responses.add(
            responses.GET,
            self._url('__healthcheck__?verbose=true'),
            status=200,
            json=healthcheck_data,
        )
        with self.assertRaisesRegex(ValueError, f'Some monitors are failing {healthcheck_data}'):
            main('local', False)


