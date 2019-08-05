import json

from unittest import mock

from olympia.amo.tests import TestCase
from olympia.files.tests.test_models import UploadTest
from olympia.scanners.models import ScannersResult
from olympia.scanners.tasks import run_scanner


class TestRunScanner(UploadTest, TestCase):
    FAKE_SCANNER = 1
    MOCK_SCANNERS = [(FAKE_SCANNER, 'fake-scanner'), ]

    @mock.patch('olympia.scanners.tasks.SCANNERS', MOCK_SCANNERS)
    def test_skip_non_xpi_files(self):
        upload = self.get_upload('search.xml')

        run_scanner(
            upload.pk,
            scanner=TestRunScanner.FAKE_SCANNER,
            get_args=lambda upload_path: []
        )

        assert len(ScannersResult.objects.all()) == 0

    @mock.patch('olympia.scanners.tasks.SCANNERS', MOCK_SCANNERS)
    def test_run_success(self):
        upload = self.get_upload('webextension.xpi')
        results = {'some': 'results'}
        assert len(ScannersResult.objects.all()) == 0

        run_scanner(
            upload.pk,
            scanner=TestRunScanner.FAKE_SCANNER,
            get_args=lambda upload_path: ['/bin/echo', json.dumps(results)]
        )

        assert len(ScannersResult.objects.all()) == 1
        result = ScannersResult.objects.all()[0]
        assert result.upload == upload
        assert result.scanner == TestRunScanner.FAKE_SCANNER
        assert result.results == results

    @mock.patch('olympia.scanners.tasks.SCANNERS', MOCK_SCANNERS)
    def test_run_fail(self):
        upload = self.get_upload('webextension.xpi')
        assert len(ScannersResult.objects.all()) == 0

        run_scanner(
            upload.pk,
            scanner=TestRunScanner.FAKE_SCANNER,
            get_args=lambda upload_path: ['/bin/invalid-command']
        )

        assert len(ScannersResult.objects.all()) == 0
