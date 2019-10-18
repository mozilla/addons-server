import json

from django.contrib.admin.sites import AdminSite
from django.utils.html import format_html

from pyquery import PyQuery as pq

from olympia import amo
from olympia.amo.tests import (
    TestCase,
    addon_factory,
    user_factory,
    version_factory,
)
from olympia.amo.urlresolvers import reverse
from olympia.constants.scanners import CUSTOMS, WAT, YARA
from olympia.scanners.admin import (
    MatchesFilter,
    ScannerResultAdmin,
    ScannerRuleAdmin,
)
from olympia.scanners.models import ScannerResult, ScannerRule


class TestScannerResultAdmin(TestCase):
    def setUp(self):
        super().setUp()

        self.user = user_factory()
        self.grant_permission(self.user, 'Admin:Advanced')
        self.client.login(email=self.user.email)
        self.list_url = reverse('admin:scanners_scannerresult_changelist')

        self.admin = ScannerResultAdmin(
            model=ScannerResult, admin_site=AdminSite()
        )

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
            addon=addon, channel=amo.RELEASE_CHANNEL_LISTED
        )
        result = ScannerResult(version=version)

        assert self.admin.formatted_addon(result) == (
            '<a href="{}">{} (version: {})</a>'.format(
                reverse('reviewers.review', args=[addon.slug]),
                addon.name,
                version.id,
            )
        )

    def test_formatted_addon_without_version(self):
        result = ScannerResult(version=None)

        assert self.admin.formatted_addon(result) == '-'

    def test_listed_channel(self):
        version = version_factory(
            addon=addon_factory(), channel=amo.RELEASE_CHANNEL_LISTED
        )
        result = ScannerResult(version=version)

        assert self.admin.channel(result) == 'Listed'

    def test_unlisted_channel(self):
        version = version_factory(
            addon=addon_factory(), channel=amo.RELEASE_CHANNEL_UNLISTED
        )
        result = ScannerResult(version=version)

        assert self.admin.channel(result) == 'Unlisted'

    def test_channel_without_version(self):
        result = ScannerResult(version=None)

        assert self.admin.channel(result) == '-'

    def test_formatted_results(self):
        results = {'some': 'results'}
        result = ScannerResult(results=results)

        assert self.admin.formatted_results(result) == format_html(
            '<pre>{}</pre>', json.dumps(results, indent=2)
        )

    def test_formatted_results_without_results(self):
        result = ScannerResult()

        assert self.admin.formatted_results(result) == '<pre>{}</pre>'

    def test_list_queries(self):
        ScannerResult.objects.create(
            scanner=CUSTOMS, version=addon_factory().current_version
        )
        ScannerResult.objects.create(
            scanner=WAT, version=addon_factory().current_version
        )
        ScannerResult.objects.create(
            scanner=CUSTOMS, version=addon_factory().current_version
        )

        with self.assertNumQueries(9):
            # 9 queries:
            # - 2 transaction savepoints because of tests
            # - 2 user and groups
            # - 2 COUNT(*) on scanners results for pagination and total display
            # - 1 scanners results and versions in one query
            # - 1 all add-ons in one query
            # - 1 all add-ons translations in one query
            response = self.client.get(
                self.list_url, {MatchesFilter.parameter_name: 'all'}
            )
        assert response.status_code == 200
        html = pq(response.content)
        expected_length = ScannerResult.objects.count()
        assert html('#result_list tbody tr').length == expected_length

    def test_formatted_matches(self):
        result = ScannerResult()
        result.add_match(rule='some-rule')

        assert self.admin.formatted_matches(result) == format_html(
            '<pre>{}</pre>', json.dumps(result.matches, indent=4)
        )

    def test_formatted_matches_without_matches(self):
        result = ScannerResult()

        assert self.admin.formatted_matches(result) == '<pre>[]</pre>'

    def test_list_shows_matches_only_by_default(self):
        # Create one entry without matches
        ScannerResult.objects.create(scanner=YARA)
        # Create one entry with matches
        with_matches = ScannerResult(scanner=YARA)
        with_matches.add_match(rule='some-rule')
        with_matches.save()

        response = self.client.get(self.list_url)
        assert response.status_code == 200
        html = pq(response.content)
        assert html('#result_list tbody tr').length == 1

    def test_list_can_show_all_entries(self):
        # Create one entry without matches
        ScannerResult.objects.create(scanner=YARA)
        # Create one entry with matches
        with_matches = ScannerResult(scanner=YARA)
        with_matches.add_match(rule='some-rule')
        with_matches.save()

        response = self.client.get(
            self.list_url, {MatchesFilter.parameter_name: 'all'}
        )
        assert response.status_code == 200
        html = pq(response.content)
        expected_length = ScannerResult.objects.count()
        assert html('#result_list tbody tr').length == expected_length


class TestScannerRuleAdmin(TestCase):
    def setUp(self):
        super().setUp()

        self.user = user_factory()
        self.grant_permission(self.user, 'Admin:Advanced')
        self.client.login(email=self.user.email)
        self.list_url = reverse('admin:scanners_scannerrule_changelist')

        self.admin = ScannerRuleAdmin(
            model=ScannerRule, admin_site=AdminSite()
        )

    def test_list_view(self):
        response = self.client.get(self.list_url)
        assert response.status_code == 200

    def test_list_view_is_restricted(self):
        user = user_factory()
        self.grant_permission(user, 'Admin:Curation')
        self.client.login(email=user.email)
        response = self.client.get(self.list_url)
        assert response.status_code == 403
