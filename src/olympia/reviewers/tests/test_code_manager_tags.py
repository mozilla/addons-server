# -*- coding: utf-8 -*-
from django.test.utils import override_settings

from olympia.reviewers.templatetags import code_manager_tags
from olympia.amo.tests import TestCase


class TestCodeManagerUrl(TestCase):

    def setUp(self):
        self.cm_url = 'http://code-manager'

    def test_create_a_browse_url(self):
        addon_id = 1
        version_id = 2
        with override_settings(CODE_MANAGER_URL=self.cm_url):
            assert code_manager_tags.code_manager_url(
                'browse', addon_id, version_id) == (
                '{}/en-US/browse/{}/versions/{}/'.format(
                    self.cm_url, addon_id, version_id)
            )

    def test_create_a_compare_url(self):
        addon_id = 1
        version_id = 2
        compare_version_id = 3
        with override_settings(CODE_MANAGER_URL=self.cm_url):
            assert code_manager_tags.code_manager_url(
                'compare', addon_id, version_id, compare_version_id) == (
                '{}/en-US/compare/{}/versions/{}...{}/'.format(
                    self.cm_url, addon_id, compare_version_id, version_id)
            )

    def test_create_a_browse_url_with_file(self):
        addon_id = 1
        version_id = 2
        file = 'somefile.js'
        with override_settings(CODE_MANAGER_URL=self.cm_url):
            assert code_manager_tags.code_manager_url(
                'browse', addon_id, version_id, file=file) == (
                '{}/en-US/browse/{}/versions/{}/?path={}'.format(
                    self.cm_url, addon_id, version_id, file)
            )

    def test_create_a_compare_url_with_file(self):
        addon_id = 1
        version_id = 2
        compare_version_id = 3
        file = 'somefile.js'
        with override_settings(CODE_MANAGER_URL=self.cm_url):
            assert code_manager_tags.code_manager_url(
                'compare', addon_id, version_id, compare_version_id, file) == (
                '{}/en-US/compare/{}/versions/{}...{}/?path={}'.format(
                    self.cm_url, addon_id, compare_version_id, version_id,
                    file)
            )
