from django.core.files.storage import default_storage as storage

import amo.tests
from mkt.developers.utils import check_upload


class TestCheckUpload(amo.tests.TestCase, amo.tests.AMOPaths):
    # TODO: increase coverage on check_upload.

    def test_not_valid(self):
        with self.assertRaises(ValueError):
            check_upload([], 'graphic', 'image/jpg')

    def test_valid(self):
        with storage.open(self.preview_image()) as f:
            errors, hash = check_upload(f, 'preview', 'image/png')
            assert not errors
