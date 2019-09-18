import json

from django.contrib.admin.sites import AdminSite
from django.utils.html import format_html

from olympia import amo
from olympia.amo.tests import (TestCase, addon_factory, user_factory,
                               version_factory)
from olympia.amo.urlresolvers import reverse
from olympia.scanners.admin import ScannersResultAdmin
from olympia.scanners.models import ScannersResult


class TestScannersResultAdmin(TestCase):
    def setUp(self):
        super().setUp()

        self.user = user_factory()
        self.grant_permission(self.user, 'Admin:Advanced')
        self.client.login(email=self.user.email)
        self.list_url = reverse('admin:scanners_scannersresult_changelist')

        self.admin = ScannersResultAdmin(model=ScannersResult,
                                         admin_site=AdminSite())

    def test_list_view(self):
        response = self.client.get(self.list_url)
        assert response.status_code == 200

    def test_list_view_is_restricted(self):
        user = user_factory()
        self.grant_permission(user, 'Admin:Curation')
        self.client.login(email=user.email)
        response = self.client.get(self.list_url)
        assert response.status_code == 403

    def test_has_add_permission(self):
        assert self.admin.has_add_permission(request=None) is False

    def test_has_delete_permission(self):
        assert self.admin.has_delete_permission(request=None) is False

    def test_has_change_permission(self):
        assert self.admin.has_change_permission(request=None) is False

    def test_formatted_addon(self):
        addon = addon_factory()
        version = version_factory(
            addon=addon,
            channel=amo.RELEASE_CHANNEL_LISTED
        )
        result = ScannersResult(version=version)

        assert self.admin.formatted_addon(result) == (
            '<a href="{}">{} (version: {})</a>'.format(
                reverse('reviewers.review', args=[addon.slug]),
                addon.name,
                version.id
            )
        )

    def test_formatted_addon_without_version(self):
        result = ScannersResult(version=None)

        assert self.admin.formatted_addon(result) == '-'

    def test_listed_channel(self):
        version = version_factory(
            addon=addon_factory(),
            channel=amo.RELEASE_CHANNEL_LISTED
        )
        result = ScannersResult(version=version)

        assert self.admin.channel(result) == 'listed'

    def test_unlisted_channel(self):
        version = version_factory(
            addon=addon_factory(),
            channel=amo.RELEASE_CHANNEL_UNLISTED
        )
        result = ScannersResult(version=version)

        assert self.admin.channel(result) == 'unlisted'

    def test_channel_without_version(self):
        result = ScannersResult(version=None)

        assert self.admin.channel(result) == '-'

    def test_formatted_results(self):
        results = {'some': 'results'}
        result = ScannersResult(results=results)

        assert self.admin.formatted_results(result) == format_html(
            '<pre>{}</pre>',
            json.dumps(results, indent=2)
        )

    def test_formatted_results_without_results(self):
        result = ScannersResult()

        assert self.admin.formatted_results(result) == '<pre>{}</pre>'
