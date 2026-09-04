from olympia.amo.tests import TestCase
from olympia.reviewers.templatetags import assay


class TestAssayUrl(TestCase):
    def setUp(self):
        super().setUp()
        self.assay_url = 'vscode://mozilla.assay/review'
        self.addon_guid = '{guid}'
        self.version_string = 'version'
        self.filepath = 'somefile.js'

    def test_create_an_assay_url(self):
        assert assay.assay_url(self.addon_guid, self.version_string) == (
            f'{self.assay_url}/{self.addon_guid}/{self.version_string}'
        )

    def test_create_an_assay_url_with_file(self):
        assert assay.assay_url(self.addon_guid, self.version_string, self.filepath) == (
            f'{self.assay_url}/{self.addon_guid}/{self.version_string}?path={self.filepath}'
        )
