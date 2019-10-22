from unittest import mock

import yara

from django.test.utils import override_settings

from olympia import amo
from olympia.amo.tests import TestCase
from olympia.constants.scanners import CUSTOMS, WAT
from olympia.files.tests.test_models import UploadTest
from olympia.scanners.models import ScannerResult
from olympia.scanners.tasks import run_scanner, run_customs, run_wat, run_yara


class TestRunScanner(UploadTest, TestCase):
    FAKE_SCANNER = 1
    MOCK_SCANNERS = {FAKE_SCANNER: 'fake-scanner'}
    API_URL = 'http://scanner.example.org'
    API_KEY = 'api-key'

    def setUp(self):
        super(TestRunScanner, self).setUp()

        self.upload = self.get_upload('webextension.xpi')
        self.results = {
            **amo.VALIDATOR_SKELETON_RESULTS,
            'metadata': {'is_webextension': True},
        }

    def create_response(self, status_code=200, data=None):
        response = mock.Mock(status_code=status_code)
        response.json.return_value = data if data else {}
        return response

    @mock.patch('olympia.scanners.tasks.SCANNERS', MOCK_SCANNERS)
    def test_skip_non_webextensions(self):
        upload = self.get_upload('search.xml')
        results = {
            **amo.VALIDATOR_SKELETON_RESULTS,
            'metadata': {'is_webextension': False},
        }

        returned_results = run_scanner(
            results,
            upload.pk,
            scanner=self.FAKE_SCANNER,
            api_url=self.API_URL,
            api_key=self.API_KEY,
        )

        assert len(ScannerResult.objects.all()) == 0
        assert returned_results == results

    @override_settings(SCANNER_TIMEOUT=123)
    @mock.patch('olympia.scanners.tasks.SCANNERS', MOCK_SCANNERS)
    @mock.patch('olympia.scanners.tasks.statsd.incr')
    @mock.patch('olympia.scanners.tasks.requests.post')
    def test_run_with_mocks(self, requests_mock, incr_mock):
        scanner_data = {'some': 'results'}
        requests_mock.return_value = self.create_response(data=scanner_data)
        assert len(ScannerResult.objects.all()) == 0

        returned_results = run_scanner(
            self.results,
            self.upload.pk,
            scanner=self.FAKE_SCANNER,
            api_url=self.API_URL,
            api_key=self.API_KEY,
        )

        assert requests_mock.called
        requests_mock.assert_called_with(
            url=self.API_URL,
            json={
                'api_key': self.API_KEY,
                'download_url': self.upload.get_authenticated_download_url(),
            },
            timeout=123,
        )
        result = ScannerResult.objects.all()[0]
        assert result.upload == self.upload
        assert result.scanner == self.FAKE_SCANNER
        assert result.results == scanner_data
        scanner_name = self.MOCK_SCANNERS.get(self.FAKE_SCANNER)
        assert incr_mock.called
        incr_mock.assert_called_with('devhub.{}.success'.format(scanner_name))
        assert returned_results == self.results

    @mock.patch('olympia.scanners.tasks.SCANNERS', MOCK_SCANNERS)
    @mock.patch('olympia.scanners.tasks.requests.post')
    def test_handles_scanner_errors_with_mocks(self, requests_mock):
        scanner_data = {'error': 'some error'}
        requests_mock.return_value = self.create_response(data=scanner_data)
        assert len(ScannerResult.objects.all()) == 0

        returned_results = run_scanner(
            self.results,
            self.upload.pk,
            scanner=self.FAKE_SCANNER,
            api_url=self.API_URL,
            api_key=self.API_KEY,
        )

        assert requests_mock.called
        assert len(ScannerResult.objects.all()) == 0
        assert returned_results == self.results

    @mock.patch('olympia.scanners.tasks.SCANNERS', MOCK_SCANNERS)
    @mock.patch('olympia.scanners.tasks.statsd.incr')
    def test_run_does_not_raise(self, incr_mock):
        # This call should not raise even though there will be an error because
        # `api_url` is `None`.
        returned_results = run_scanner(
            self.results,
            self.upload.pk,
            scanner=self.FAKE_SCANNER,
            api_url=None,
            api_key='does-not-matter',
        )

        scanner_name = self.MOCK_SCANNERS.get(self.FAKE_SCANNER)
        assert incr_mock.called
        incr_mock.assert_called_with('devhub.{}.failure'.format(scanner_name))
        assert returned_results == self.results

    @mock.patch('olympia.scanners.tasks.SCANNERS', MOCK_SCANNERS)
    @mock.patch('olympia.scanners.tasks.statsd.timer')
    @mock.patch('olympia.scanners.tasks.requests.post')
    def test_calls_statsd_timer(self, requests_mock, timer_mock):
        requests_mock.return_value = self.create_response()

        returned_results = run_scanner(
            self.results,
            self.upload.pk,
            scanner=self.FAKE_SCANNER,
            api_url=self.API_URL,
            api_key=self.API_KEY,
        )

        assert timer_mock.called
        scanner_name = self.MOCK_SCANNERS.get(self.FAKE_SCANNER)
        timer_mock.assert_called_with('devhub.{}'.format(scanner_name))
        assert returned_results == self.results

    @mock.patch('olympia.scanners.tasks.SCANNERS', MOCK_SCANNERS)
    @mock.patch('olympia.scanners.tasks.requests.post')
    def test_handles_http_errors_with_mock(self, requests_mock):
        requests_mock.return_value = self.create_response(
            status_code=504, data={'message': 'http timeout'}
        )
        assert len(ScannerResult.objects.all()) == 0

        returned_results = run_scanner(
            self.results,
            self.upload.pk,
            scanner=self.FAKE_SCANNER,
            api_url=self.API_URL,
            api_key=self.API_KEY,
        )

        assert requests_mock.called
        assert len(ScannerResult.objects.all()) == 0
        assert returned_results == self.results


class TestRunCustoms(TestCase):
    API_URL = 'http://customs.example.org'
    API_KEY = 'some-api-key'

    def setUp(self):
        super(TestRunCustoms, self).setUp()

        self.upload_pk = 1234
        self.results = {**amo.VALIDATOR_SKELETON_RESULTS}

    @override_settings(CUSTOMS_API_URL=API_URL, CUSTOMS_API_KEY=API_KEY)
    @mock.patch('olympia.scanners.tasks.run_scanner')
    def test_calls_run_scanner_with_mock(self, run_scanner_mock):
        run_scanner_mock.return_value = self.results

        returned_results = run_customs(self.results, self.upload_pk)

        assert run_scanner_mock.called
        run_scanner_mock.assert_called_once_with(
            self.results,
            self.upload_pk,
            scanner=CUSTOMS,
            api_url=self.API_URL,
            api_key=self.API_KEY,
        )
        assert returned_results == self.results

    @override_settings(CUSTOMS_API_URL=API_URL, CUSTOMS_API_KEY=API_KEY)
    @mock.patch('olympia.scanners.tasks.run_scanner')
    def test_does_not_run_when_results_contain_errors(self, run_scanner_mock):
        self.results.update({'errors': 1})

        returned_results = run_customs(self.results, self.upload_pk)

        assert not run_scanner_mock.called
        assert returned_results == self.results


class TestRunWat(TestCase):
    API_URL = 'http://wat.example.org'
    API_KEY = 'some-api-key'

    def setUp(self):
        super(TestRunWat, self).setUp()

        self.upload_pk = 1234
        self.results = {**amo.VALIDATOR_SKELETON_RESULTS}

    @override_settings(WAT_API_URL=API_URL, WAT_API_KEY=API_KEY)
    @mock.patch('olympia.scanners.tasks.run_scanner')
    def test_calls_run_scanner_with_mock(self, run_scanner_mock):
        run_scanner_mock.return_value = self.results

        returned_results = run_wat(self.results, self.upload_pk)

        assert run_scanner_mock.called
        run_scanner_mock.assert_called_once_with(
            self.results,
            self.upload_pk,
            scanner=WAT,
            api_url=self.API_URL,
            api_key=self.API_KEY,
        )
        assert returned_results == self.results

    @override_settings(WAT_API_URL=API_URL, WAT_API_KEY=API_KEY)
    @mock.patch('olympia.scanners.tasks.run_scanner')
    def test_does_not_run_when_results_contain_errors(self, run_scanner_mock):
        self.results.update({'errors': 1})

        returned_results = run_wat(self.results, self.upload_pk)

        assert not run_scanner_mock.called
        assert returned_results == self.results


class TestRunYara(UploadTest, TestCase):
    def setUp(self):
        super(TestRunYara, self).setUp()

        self.upload = self.get_upload('webextension.xpi')
        self.results = {
            **amo.VALIDATOR_SKELETON_RESULTS,
            'metadata': {'is_webextension': True},
        }

    @mock.patch('yara.compile')
    def test_skip_non_webextensions_with_mocks(self, yara_compile_mock):
        upload = self.get_upload('search.xml')
        results = {
            **amo.VALIDATOR_SKELETON_RESULTS,
            'metadata': {'is_webextension': False},
        }

        received_results = run_yara(results, upload.pk)

        assert not yara_compile_mock.called
        # The task should always return the results.
        assert received_results == results

    @mock.patch('olympia.scanners.tasks.statsd.incr')
    def test_run_with_mocks(self, incr_mock):
        assert len(ScannerResult.objects.all()) == 0

        # This compiled rule will match for all files in the xpi.
        rules = yara.compile(source='rule always_true { condition: true }')
        with mock.patch('yara.compile') as yara_compile_mock:
            yara_compile_mock.return_value = rules
            received_results = run_yara(self.results, self.upload.pk)

        assert yara_compile_mock.called
        yara_results = ScannerResult.objects.all()
        assert len(yara_results) == 1
        yara_result = yara_results[0]
        assert yara_result.upload == self.upload
        assert len(yara_result.results) == 2
        assert yara_result.results[0] == {
            'rule': 'always_true',
            'tags': [],
            'meta': {'filename': 'index.js'},
        }
        assert yara_result.results[1] == {
            'rule': 'always_true',
            'tags': [],
            'meta': {'filename': 'manifest.json'},
        }
        assert incr_mock.called
        assert incr_mock.call_count == 2
        incr_mock.assert_has_calls(
            [
                mock.call('devhub.yara.has_matches'),
                mock.call('devhub.yara.success'),
            ]
        )
        # The task should always return the results.
        assert received_results == self.results

    @mock.patch('olympia.scanners.tasks.statsd.incr')
    def test_run_no_matches_with_mocks(self, incr_mock):
        assert len(ScannerResult.objects.all()) == 0

        # This compiled rule will never match.
        rules = yara.compile(source='rule always_false { condition: false }')
        with mock.patch('yara.compile') as yara_compile_mock:
            yara_compile_mock.return_value = rules
            received_results = run_yara(self.results, self.upload.pk)

        yara_result = ScannerResult.objects.all()[0]
        assert yara_result.results == []
        # The task should always return the results.
        assert received_results == self.results
        assert incr_mock.called
        assert incr_mock.call_count == 1
        incr_mock.assert_called_with('devhub.yara.success')

    def test_run_ignores_directories(self):
        upload = self.get_upload('webextension_signed_already.xpi')
        results = {
            **amo.VALIDATOR_SKELETON_RESULTS,
            'metadata': {'is_webextension': True},
        }
        # This compiled rule will match for all files in the xpi.
        rules = yara.compile(source='rule always_true { condition: true }')

        with mock.patch('yara.compile') as yara_compile_mock:
            yara_compile_mock.return_value = rules
            received_results = run_yara(results, upload.pk)

        yara_result = ScannerResult.objects.all()[0]
        assert yara_result.upload == upload
        # The `webextension_signed_already.xpi` fixture file has 1 directory
        # and 3 files.
        assert len(yara_result.results) == 3
        # The task should always return the results.
        assert received_results == results

    @override_settings(YARA_RULES_FILEPATH='unknown/path/to/rules.yar')
    @mock.patch('olympia.scanners.tasks.statsd.incr')
    def test_run_does_not_raise(self, incr_mock):
        # This call should not raise even though there will be an error because
        # YARA_RULES_FILEPATH is configured with a wrong path.
        received_results = run_yara(self.results, self.upload.pk)

        assert incr_mock.called
        incr_mock.assert_called_with('devhub.yara.failure')
        # The task should always return the results.
        assert received_results == self.results

    @mock.patch('olympia.scanners.tasks.statsd.timer')
    def test_calls_statsd_timer(self, timer_mock):
        run_yara(self.results, self.upload.pk)

        assert timer_mock.called
        timer_mock.assert_called_with('devhub.yara')

    @mock.patch('yara.compile')
    def test_does_not_run_when_results_contain_errors(self, yara_compile_mock):
        self.results.update({'errors': 1})
        received_results = run_yara(self.results, self.upload.pk)

        assert not yara_compile_mock.called
        # The task should always return the results.
        assert received_results == self.results
