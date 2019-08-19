from olympia.amo.tests import TestCase, addon_factory

from olympia.constants.scanners import CUSTOMS
from olympia.files.models import FileUpload
from olympia.scanners.models import ScannersResult


class TestScannersResult(TestCase):
    def create_file_upload(self):
        addon = addon_factory()
        return FileUpload.objects.create(addon=addon)

    def create_scanners_result(self):
        upload = self.create_file_upload()
        return ScannersResult.objects.create(upload=upload, scanner=CUSTOMS)

    def test_create(self):
        upload = self.create_file_upload()

        result = ScannersResult.objects.create(upload=upload, scanner=CUSTOMS)

        assert result.id is not None
        assert result.upload == upload
        assert result.scanner == CUSTOMS
        assert result.results == {}
        assert result.version is None
