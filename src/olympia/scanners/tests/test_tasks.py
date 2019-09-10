from unittest import mock

from django.test.utils import override_settings

from olympia.amo.tests import TestCase
from olympia.constants.scanners import CUSTOMS, WAT
from olympia.files.tests.test_models import UploadTest
from olympia.scanners.models import ScannersResult
from olympia.scanners.tasks import run_scanner, run_customs, run_wat


class TestRunScanner(UploadTest, TestCase):
    FAKE_SCANNER = 1
    MOCK_SCANNERS = [(FAKE_SCANNER, 'fake-scanner'), ]
    API_URL = 'http://scanner.example.org'
    API_KEY = 'api-key'

    def create_response(self, ok=True, data=None):
        response = mock.Mock(ok=ok)
        response.json.return_value = data if data else {}
        return response

    @mock.patch('olympia.scanners.tasks.SCANNERS', MOCK_SCANNERS)
    def test_skip_non_xpi_files(self):
        upload = self.get_upload('search.xml')

        run_scanner(
            upload.pk,
            scanner=self.FAKE_SCANNER,
            api_url=self.API_URL,
            api_key=self.API_KEY
        )

        assert len(ScannersResult.objects.all()) == 0

    @override_settings(SCANNER_TIMEOUT=123)
    @mock.patch('olympia.scanners.tasks.SCANNERS', MOCK_SCANNERS)
    @mock.patch('olympia.scanners.tasks.requests.post')
    def test_run_with_mocks(self, requests_mock):
        upload = self.get_upload('webextension.xpi')
        scanner_data = {'some': 'results'}
        requests_mock.return_value = self.create_response(data=scanner_data)
        assert len(ScannersResult.objects.all()) == 0

        run_scanner(
            upload.pk,
            scanner=self.FAKE_SCANNER,
            api_url=self.API_URL,
            api_key=self.API_KEY
        )

        assert requests_mock.called
        requests_mock.assert_called_with(
            url=self.API_URL,
            json={
                'api_key': self.API_KEY,
                'download_url': upload.get_authenticated_download_url(),
            },
            timeout=123
        )
        result = ScannersResult.objects.all()[0]
        assert result.upload == upload
        assert result.scanner == self.FAKE_SCANNER
        assert result.results == scanner_data

    @mock.patch('olympia.scanners.tasks.SCANNERS', MOCK_SCANNERS)
    @mock.patch('olympia.scanners.tasks.requests.post')
    def test_handles_scanner_errors_with_mocks(self, requests_mock):
        upload = self.get_upload('webextension.xpi')
        scanner_data = {'error': 'some error'}
        requests_mock.return_value = self.create_response(data=scanner_data)
        assert len(ScannersResult.objects.all()) == 0

        run_scanner(
            upload.pk,
            scanner=self.FAKE_SCANNER,
            api_url=self.API_URL,
            api_key=self.API_KEY
        )

        assert requests_mock.called
        assert len(ScannersResult.objects.all()) == 0

    def test_run_does_not_raise(self):
        upload = self.get_upload('webextension.xpi')

        # This call should not raise even though there will be an error because
        # `api_url` is `None`.
        run_scanner(
            upload.pk,
            scanner=self.FAKE_SCANNER,
            api_url=None,
            api_key='does-not-matter'
        )

    @mock.patch('olympia.scanners.tasks.SCANNERS', MOCK_SCANNERS)
    @mock.patch('olympia.scanners.tasks.statsd.timer')
    @mock.patch('olympia.scanners.tasks.requests.post')
    def test_calls_statsd_timer(self, requests_mock, timer_mock):
        upload = self.get_upload('webextension.xpi')
        requests_mock.return_value = self.create_response()

        run_scanner(
            upload.pk,
            scanner=self.FAKE_SCANNER,
            api_url=self.API_URL,
            api_key=self.API_KEY
        )

        assert timer_mock.called
        scanner_name = dict(self.MOCK_SCANNERS).get(self.FAKE_SCANNER)
        timer_mock.assert_called_with('devhub.{}'.format(scanner_name))


class TestRunCustoms(TestCase):
    API_URL = 'http://customs.example.org'
    API_KEY = 'some-api-key'

    @override_settings(CUSTOMS_API_URL=API_URL, CUSTOMS_API_KEY=API_KEY)
    @mock.patch('olympia.scanners.tasks.run_scanner')
    def test_calls_run_scanner_with_mock(self, run_scanner_mock):
        upload_pk = 1234

        run_customs(upload_pk)

        assert run_scanner_mock.called
        run_scanner_mock.assert_called_once_with(upload_pk,
                                                 scanner=CUSTOMS,
                                                 api_url=self.API_URL,
                                                 api_key=self.API_KEY)


class TestRunWat(TestCase):
    API_URL = 'http://wat.example.org'
    API_KEY = 'some-api-key'

    @override_settings(WAT_API_URL=API_URL, WAT_API_KEY=API_KEY)
    @mock.patch('olympia.scanners.tasks.run_scanner')
    def test_calls_run_scanner_with_mock(self, run_scanner_mock):
        upload_pk = 1234

        run_wat(upload_pk)

        assert run_scanner_mock.called
        run_scanner_mock.assert_called_once_with(upload_pk,
                                                 scanner=WAT,
                                                 api_url=self.API_URL,
                                                 api_key=self.API_KEY)
