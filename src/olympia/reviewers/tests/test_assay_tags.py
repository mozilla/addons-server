from olympia.amo.tests import TestCase
from olympia.reviewers.templatetags import assay


class TestAssayUrl(TestCase):
    def setUp(self):
        super().setUp()
        self.assay_url = 'vscode://mozilla.assay/review'
        self.addon_guid = '{guid}'
        self.version = 'version'
        self.file = 'somefile.js'

    def test_create_an_assay_url(self):
        assert assay.assay_url(self.addon_guid, self.version) == (
            '{}/{}/{}'.format(self.assay_url, self.addon_guid, self.version)
        )

    def test_create_an_assay_url_with_file(self):
        assert assay.assay_url(self.addon_guid, self.version, self.file) == (
            '{}/{}/{}?path={}'.format(
                self.assay_url, self.addon_guid, self.version, self.file
            )
        )
