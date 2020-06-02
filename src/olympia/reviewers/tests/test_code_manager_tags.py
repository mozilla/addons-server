from django.test.utils import override_settings

from olympia.reviewers.templatetags import code_manager
from olympia.amo.tests import TestCase


class TestCodeManagerUrl(TestCase):

    def setUp(self):
        super().setUp()
        self.addon_id = 1
        self.base_version_id = 2
        self.cm_url = 'http://code-manager'
        self.file = 'somefile.js'
        self.version_id = 3

    def test_create_a_browse_url(self):
        with override_settings(CODE_MANAGER_URL=self.cm_url):
            assert code_manager.code_manager_url(
                'browse', self.addon_id, self.version_id) == (
                '{}/en-US/browse/{}/versions/{}/'.format(
                    self.cm_url, self.addon_id, self.version_id)
            )

    def test_create_a_compare_url(self):
        with override_settings(CODE_MANAGER_URL=self.cm_url):
            assert code_manager.code_manager_url(
                'compare', self.addon_id, self.version_id,
                self.base_version_id) == (
                '{}/en-US/compare/{}/versions/{}...{}/'.format(
                    self.cm_url, self.addon_id, self.base_version_id,
                    self.version_id)
            )

    def test_create_a_browse_url_with_file(self):
        with override_settings(CODE_MANAGER_URL=self.cm_url):
            assert code_manager.code_manager_url(
                'browse', self.addon_id, self.version_id, file=self.file) == (
                '{}/en-US/browse/{}/versions/{}/?path={}'.format(
                    self.cm_url, self.addon_id, self.version_id, self.file)
            )

    def test_create_a_compare_url_with_file(self):
        with override_settings(CODE_MANAGER_URL=self.cm_url):
            assert code_manager.code_manager_url(
                'compare', self.addon_id, self.version_id,
                self.base_version_id, self.file) == (
                '{}/en-US/compare/{}/versions/{}...{}/?path={}'.format(
                    self.cm_url, self.addon_id, self.base_version_id,
                    self.version_id, self.file)
            )
