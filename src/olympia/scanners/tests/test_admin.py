import json

from django.conf import settings
from django.contrib.admin.sites import AdminSite
from django.test.utils import override_settings
from django.utils.html import format_html
from django.utils.http import urlencode

from pyquery import PyQuery as pq
from urllib.parse import urljoin

from olympia import amo
from olympia.amo.tests import (
    TestCase,
    addon_factory,
    user_factory,
    version_factory,
)
from olympia.amo.urlresolvers import reverse
from olympia.constants.scanners import (
    CUSTOMS,
    FALSE_POSITIVE,
    TRUE_POSITIVE,
    UNKNOWN,
    WAT,
    YARA,
)
from olympia.scanners.admin import (
    MatchesFilter,
    ScannerResultAdmin,
    StateFilter,
    WithVersionFilter,
)
from olympia.scanners.models import ScannerResult, ScannerRule


class TestScannerResultAdmin(TestCase):
    def setUp(self):
        super().setUp()

        self.user = user_factory()
        self.grant_permission(self.user, 'Admin:*')
        self.client.login(email=self.user.email)
        self.list_url = reverse('admin:scanners_scannerresult_changelist')

        self.admin = ScannerResultAdmin(
            model=ScannerResult, admin_site=AdminSite()
        )

    def test_list_view(self):
        rule = ScannerRule.objects.create(name='rule', scanner=CUSTOMS)
        ScannerResult.objects.create(
            scanner=CUSTOMS,
            version=addon_factory().current_version,
            results={'matchedRules': [rule.name]}
        )
        response = self.client.get(self.list_url)
        assert response.status_code == 200
        html = pq(response.content)
        assert html('.column-result_actions').length == 1

    def test_list_view_for_non_admins(self):
        rule = ScannerRule.objects.create(name='rule', scanner=CUSTOMS)
        ScannerResult.objects.create(
            scanner=CUSTOMS,
            version=addon_factory().current_version,
            results={'matchedRules': [rule.name]}
        )
        user = user_factory()
        self.grant_permission(user, 'Admin:ScannersResultsView')
        self.client.login(email=user.email)
        response = self.client.get(self.list_url)
        assert response.status_code == 200
        html = pq(response.content)
        assert html('.column-result_actions').length == 0

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

    def test_formatted_listed_addon(self):
        addon = addon_factory()
        version = version_factory(
            addon=addon, channel=amo.RELEASE_CHANNEL_LISTED
        )
        result = ScannerResult(version=version)

        assert self.admin.formatted_addon(result) == (
            '<a href="{}">{} (version: {})</a>'.format(
                urljoin(
                    settings.EXTERNAL_SITE_URL,
                    reverse('reviewers.review', args=['listed', addon.id]),
                ),
                addon.name,
                version.version,
            )
        )

    def test_formatted_unlisted_addon(self):
        addon = addon_factory()
        version = version_factory(
            addon=addon, channel=amo.RELEASE_CHANNEL_UNLISTED
        )
        result = ScannerResult(version=version)

        assert self.admin.formatted_addon(result) == (
            '<a href="{}">{} (version: {})</a>'.format(
                urljoin(
                    settings.EXTERNAL_SITE_URL,
                    reverse('reviewers.review', args=['unlisted', addon.id]),
                ),
                addon.name,
                version.version,
            )
        )

    def test_formatted_addon_without_version(self):
        result = ScannerResult(version=None)

        assert self.admin.formatted_addon(result) == '-'

    def test_guid(self):
        version = version_factory(addon=addon_factory())
        result = ScannerResult(version=version)

        assert self.admin.guid(result) == version.addon.guid

    def test_guid_without_version(self):
        result = ScannerResult(version=None)

        assert self.admin.guid(result) == '-'

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

        assert self.admin.formatted_results(result) == '<pre>[]</pre>'

    def test_formatted_matched_rules_with_files(self):
        version = addon_factory().current_version
        result = ScannerResult.objects.create(
            scanner=YARA, version=version
        )
        rule = ScannerRule.objects.create(name='bar', scanner=YARA)
        filename = 'some/file.js'
        result.add_yara_result(rule=rule.name, meta={'filename': filename})
        result.save()

        external_site_url = 'http://example.org'
        file_id = version.all_files[0].id
        assert file_id is not None
        expect_file_item = '<a href="{}{}">{}</a>'.format(
            external_site_url,
            reverse('files.list', args=[file_id, 'file', filename]),
            filename
        )
        with override_settings(EXTERNAL_SITE_URL=external_site_url):
            assert (expect_file_item in
                    self.admin.formatted_matched_rules_with_files(result))

    def test_formatted_matched_rules_with_files_without_version(self):
        result = ScannerResult.objects.create(scanner=YARA)
        rule = ScannerRule.objects.create(name='bar', scanner=YARA)
        filename = 'some/file.js'
        result.add_yara_result(rule=rule.name, meta={'filename': filename})
        result.save()

        # We list the file related to the matched rule...
        assert (filename in
                self.admin.formatted_matched_rules_with_files(result))
        # ...but we do not add a link to it because there is no associated
        # version.
        assert ('/file/' not in
                self.admin.formatted_matched_rules_with_files(result))

    def test_list_queries(self):
        ScannerResult.objects.create(
            scanner=CUSTOMS, version=addon_factory().current_version
        )
        ScannerResult.objects.create(
            scanner=WAT, version=addon_factory().current_version
        )
        deleted_addon = addon_factory(name='a deleted add-on')
        ScannerResult.objects.create(
            scanner=CUSTOMS, version=deleted_addon.current_version
        )
        deleted_addon.delete()

        with self.assertNumQueries(11):
            # 10 queries:
            # - 2 transaction savepoints because of tests
            # - 2 user and groups
            # - 2 COUNT(*) on scanners results for pagination and total display
            # - 1 get all available rules for filtering
            # - 1 scanners results and versions in one query
            # - 1 all add-ons in one query
            # - 1 all add-ons translations in one query
            # - 1 all scanner rules in one query
            response = self.client.get(
                self.list_url, {MatchesFilter.parameter_name: 'all'}
            )
        assert response.status_code == 200
        html = pq(response.content)
        expected_length = ScannerResult.objects.count()
        assert html('#result_list tbody tr').length == expected_length
        # The name of the deleted add-on should be displayed.
        assert str(deleted_addon.name) in html.text()

    def test_list_filters(self):
        rule_bar = ScannerRule.objects.create(name='bar', scanner=YARA)
        rule_hello = ScannerRule.objects.create(name='hello', scanner=YARA)
        rule_foo = ScannerRule.objects.create(name='foo', scanner=CUSTOMS)

        response = self.client.get(self.list_url)
        assert response.status_code == 200
        doc = pq(response.content)
        expected = [
            ('All', '?'),
            ('customs', '?scanner__exact=1'),
            ('wat', '?scanner__exact=2'),
            ('yara', '?scanner__exact=3'),

            ('All', '?has_matched_rules=all'),
            (' With matched rules only', '?'),

            ('All', '?state=all'),
            ('Unknown', '?'),
            ('True positive', '?state=1'),
            ('False positive', '?state=2'),

            ('All', '?'),
            ('foo (customs)', f'?matched_rules__id__exact={rule_foo.pk}'),
            ('bar (yara)', f'?matched_rules__id__exact={rule_bar.pk}'),
            ('hello (yara)', f'?matched_rules__id__exact={rule_hello.pk}'),

            ('All', '?has_version=all'),
            (' With version only', '?'),
        ]
        filters = [
            (x.text, x.attrib['href']) for x in doc('#changelist-filter a')
        ]
        assert filters == expected

    def test_list_filter_matched_rules(self):
        rule_bar = ScannerRule.objects.create(name='bar', scanner=YARA)
        rule_hello = ScannerRule.objects.create(name='hello', scanner=YARA)
        rule_foo = ScannerRule.objects.create(name='foo', scanner=CUSTOMS)
        with_bar_matches = ScannerResult(scanner=YARA)
        with_bar_matches.add_yara_result(rule=rule_bar.name)
        with_bar_matches.add_yara_result(rule=rule_hello.name)
        with_bar_matches.save()
        ScannerResult.objects.create(
            scanner=CUSTOMS, results={'matchedRules': [rule_foo.name]}
        )
        with_hello_match = ScannerResult(scanner=YARA)
        with_hello_match.add_yara_result(rule=rule_hello.name)

        response = self.client.get(self.list_url, {
            'matched_rules__id__exact': rule_bar.pk,
            WithVersionFilter.parameter_name: 'all',
        })
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#result_list tbody tr').length == 1
        assert doc('.field-formatted_matched_rules').text() == 'bar, hello'

    def test_list_default(self):
        # Create one entry without matches, it will not be shown by default
        ScannerResult.objects.create(
            scanner=YARA,
            version=version_factory(addon=addon_factory()),
        )
        # Create one entry with matches, it will be shown by default
        rule = ScannerRule.objects.create(name='some-rule', scanner=YARA)
        with_matches = ScannerResult(
            scanner=YARA,
            version=version_factory(addon=addon_factory()),
        )
        with_matches.add_yara_result(rule=rule.name)
        with_matches.save()
        # Create a false positive, it will not be shown by default
        false_positive = ScannerResult(
            scanner=YARA,
            state=FALSE_POSITIVE,
            version=version_factory(addon=addon_factory()),
        )
        false_positive.add_yara_result(rule=rule.name)
        false_positive.save()
        # Create an entry without a version, it will not be shown by default
        without_version = ScannerResult(scanner=YARA)
        without_version.add_yara_result(rule=rule.name)
        without_version.save()

        response = self.client.get(self.list_url)
        assert response.status_code == 200
        html = pq(response.content)
        assert html('#result_list tbody tr').length == 1

    def test_list_can_show_all_entries(self):
        # Create one entry without matches
        ScannerResult.objects.create(scanner=YARA)
        # Create one entry with matches
        rule = ScannerRule.objects.create(name='some-rule', scanner=YARA)
        with_matches = ScannerResult(scanner=YARA)
        with_matches.add_yara_result(rule=rule.name)
        with_matches.save()
        # Create a false positive
        false_positive = ScannerResult(scanner=YARA, state=FALSE_POSITIVE)
        false_positive.add_yara_result(rule=rule.name)
        false_positive.save()
        # Create an entry without a version
        without_version = ScannerResult(scanner=YARA)
        without_version.add_yara_result(rule=rule.name)
        without_version.save()

        response = self.client.get(
            self.list_url,
            {
                MatchesFilter.parameter_name: 'all',
                StateFilter.parameter_name: 'all',
                WithVersionFilter.parameter_name: 'all',
            },
        )
        assert response.status_code == 200
        html = pq(response.content)
        expected_length = ScannerResult.objects.count()
        assert html('#result_list tbody tr').length == expected_length

    def test_handle_true_positive(self):
        # Create one entry with matches
        rule = ScannerRule.objects.create(name='some-rule', scanner=YARA)
        result = ScannerResult(scanner=YARA)
        result.add_yara_result(rule=rule.name)
        result.save()
        assert result.state == UNKNOWN

        response = self.client.post(
            reverse(
                'admin:scanners_scannerresult_handletruepositive',
                args=[result.pk],
            ),
            follow=True,
        )

        result.refresh_from_db()
        assert result.state == TRUE_POSITIVE
        # The action should send a redirect.
        last_url, status_code = response.redirect_chain[-1]
        assert status_code == 302
        # The action should redirect to the list view and the default list
        # filters should hide the result (because its state is not UNKNOWN
        # anymore).
        html = pq(response.content)
        assert html('#result_list tbody tr').length == 0
        # A confirmation message should also appear.
        assert html('.messagelist .info').length == 1

    @override_settings(YARA_GIT_REPOSITORY='git/repo')
    def test_handle_yara_false_positive(self):
        # Create one entry with matches
        rule = ScannerRule.objects.create(name='some-rule', scanner=YARA)
        result = ScannerResult(scanner=YARA)
        result.add_yara_result(rule=rule.name)
        result.save()
        assert result.state == UNKNOWN

        response = self.client.post(
            reverse(
                'admin:scanners_scannerresult_handlefalsepositive',
                args=[result.pk],
            )
        )

        result.refresh_from_db()
        assert result.state == FALSE_POSITIVE
        # This action should send a redirect to GitHub.
        assert response.status_code == 302
        # We create a GitHub issue draft by passing some query parameters to
        # GitHub.
        assert response['Location'].startswith(
            'https://github.com/git/repo/issues/new?'
        )
        assert (
            urlencode(
                {
                    'title': 'False positive report for '
                    'ScannerResult {}'.format(result.pk)
                }
            )
            in response['Location']
        )
        assert urlencode({'body': '### Report'}) in response['Location']
        assert (
            urlencode({'labels': 'false positive report'})
            in response['Location']
        )
        assert 'Raw+scanner+results' in response['Location']

    @override_settings(CUSTOMS_GIT_REPOSITORY='git/repo')
    def test_handle_customs_false_positive(self):
        # Create one entry with matches
        rule = ScannerRule.objects.create(name='some-rule', scanner=CUSTOMS)
        result = ScannerResult(
            scanner=CUSTOMS, results={'matchedRules': [rule.name]}
        )
        result.save()
        assert result.state == UNKNOWN

        response = self.client.post(
            reverse(
                'admin:scanners_scannerresult_handlefalsepositive',
                args=[result.pk],
            )
        )

        result.refresh_from_db()
        assert result.state == FALSE_POSITIVE
        # This action should send a redirect to GitHub.
        assert response.status_code == 302
        assert 'Raw+scanner+results' not in response['Location']

    def test_handle_revert_report(self):
        # Create one entry with matches
        rule = ScannerRule.objects.create(name='some-rule', scanner=YARA)
        result = ScannerResult(
            scanner=YARA,
            version=version_factory(addon=addon_factory())
        )
        result.add_yara_result(rule=rule.name)
        result.state = TRUE_POSITIVE
        result.save()
        assert result.state == TRUE_POSITIVE

        response = self.client.post(
            reverse(
                'admin:scanners_scannerresult_handlerevert', args=[result.pk]
            ),
            follow=True,
        )

        result.refresh_from_db()
        assert result.state == UNKNOWN
        # The action should send a redirect.
        last_url, status_code = response.redirect_chain[-1]
        assert status_code == 302
        # The action should redirect to the list view and the default list
        # filters should show the result (because its state is UNKNOWN again).
        html = pq(response.content)
        assert html('#result_list tbody tr').length == 1
        # A confirmation message should also appear.
        assert html('.messagelist .info').length == 1

    def test_handle_true_positive_and_non_admin_user(self):
        result = ScannerResult(scanner=CUSTOMS)
        user = user_factory()
        self.grant_permission(user, 'Admin:ScannersResultsView')
        self.client.login(email=user.email)
        response = self.client.post(
            reverse(
                'admin:scanners_scannerresult_handletruepositive',
                args=[result.pk],
            )
        )
        assert response.status_code == 404

    def test_handle_false_positive_and_non_admin_user(self):
        result = ScannerResult(scanner=CUSTOMS)
        user = user_factory()
        self.grant_permission(user, 'Admin:ScannersResultsView')
        self.client.login(email=user.email)
        response = self.client.post(
            reverse(
                'admin:scanners_scannerresult_handlefalsepositive',
                args=[result.pk],
            )
        )
        assert response.status_code == 404

    def test_handle_revert_report_and_non_admin_user(self):
        result = ScannerResult(scanner=CUSTOMS)
        user = user_factory()
        self.grant_permission(user, 'Admin:ScannersResultsView')
        self.client.login(email=user.email)
        response = self.client.post(
            reverse(
                'admin:scanners_scannerresult_handlerevert',
                args=[result.pk],
            )
        )
        assert response.status_code == 404


class TestScannerRuleAdmin(TestCase):
    def setUp(self):
        super().setUp()

        self.user = user_factory()
        self.grant_permission(self.user, 'Admin:*')
        self.client.login(email=self.user.email)
        self.list_url = reverse('admin:scanners_scannerrule_changelist')

    def test_list_view(self):
        response = self.client.get(self.list_url)
        assert response.status_code == 200

    def test_list_view_is_restricted(self):
        user = user_factory()
        self.grant_permission(user, 'Admin:Curation')
        self.client.login(email=user.email)
        response = self.client.get(self.list_url)
        assert response.status_code == 403

    def test_change_view_contains_link_to_results(self):
        rule = ScannerRule.objects.create(name='bar', scanner=YARA)
        result = ScannerResult(scanner=YARA)
        result.add_yara_result(rule=rule.name)
        result.save()
        ScannerResult.objects.create(scanner=YARA)  # Doesn't match
        url = reverse('admin:scanners_scannerrule_change', args=(rule.pk,))
        response = self.client.get(url)
        assert response.status_code == 200
        doc = pq(response.content)
        link = doc('.field-matched_results_link a')
        assert link
        results_list_url = reverse('admin:scanners_scannerresult_changelist')
        expected_href = (
            f'{results_list_url}?matched_rules__id__exact={rule.pk}'
            f'&has_version=all&state=all&scanner={rule.scanner}'
        )
        assert link.attr('href') == expected_href
        assert link.text() == '1'

    def test_create_view_doesnt_contain_link_to_results(self):
        url = reverse('admin:scanners_scannerrule_add')
        response = self.client.get(url)
        assert response.status_code == 200
        doc = pq(response.content)
        field = doc('.field-matched_results_link')
        assert field
        assert field.text() == 'Matched Results:\n-'
        link = doc('.field-matched_results_link a')
        assert not link
