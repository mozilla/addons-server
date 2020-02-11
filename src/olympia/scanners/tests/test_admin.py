import json
from unittest import mock

from django.conf import settings
from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory
from django.test.utils import override_settings
from django.utils.html import format_html
from django.utils.http import urlencode

from pyquery import PyQuery as pq
from urllib.parse import urljoin, urlparse

from olympia import amo
from olympia.amo.tests import (
    AMOPaths,
    TestCase,
    addon_factory,
    user_factory,
    version_factory,
)
from olympia.amo.urlresolvers import reverse
from olympia.constants.scanners import (
    ABORTING,
    COMPLETED,
    CUSTOMS,
    FALSE_POSITIVE,
    INCONCLUSIVE,
    NEW,
    RUNNING,
    SCHEDULED,
    TRUE_POSITIVE,
    UNKNOWN,
    WAT,
    YARA,
)
from olympia.files.models import FileUpload
from olympia.scanners.admin import (
    MatchesFilter,
    ScannerQueryResultAdmin,
    ScannerResultAdmin,
    ScannerRuleAdmin,
    StateFilter,
    WithVersionFilter,
    _is_safe_url,
)
from olympia.scanners.models import (
    ScannerQueryResult, ScannerQueryRule, ScannerResult, ScannerRule
)


class TestScannerResultAdmin(TestCase):
    def setUp(self):
        super().setUp()

        self.user = user_factory()
        self.grant_permission(self.user, 'Admin:ScannersResultsEdit')
        self.grant_permission(self.user, 'Admin:ScannersResultsView')
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
            ('ml_api', '?scanner__exact=4'),

            ('All', '?has_matched_rules=all'),
            (' With matched rules only', '?'),

            ('All', '?state=all'),
            ('Unknown', '?'),
            ('True positive', '?state=1'),
            ('False positive', '?state=2'),
            ('Inconclusive', '?state=3'),

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

    def test_handle_true_positive_uses_referer_if_available(self):
        # Create one entry with matches
        rule = ScannerRule.objects.create(name='some-rule', scanner=YARA)
        result = ScannerResult(scanner=YARA)
        result.add_yara_result(rule=rule.name)
        result.save()
        assert result.state == UNKNOWN

        referer = '{}/en-US/firefox/previous/page'.format(settings.SITE_URL)
        response = self.client.post(
            reverse(
                'admin:scanners_scannerresult_handletruepositive',
                args=[result.pk],
            ),
            follow=True,
            HTTP_REFERER=referer
        )

        last_url, status_code = response.redirect_chain[-1]
        assert last_url == referer

    def test_handle_true_positive_with_invalid_referer(self):
        # Create one entry with matches
        rule = ScannerRule.objects.create(name='some-rule', scanner=YARA)
        result = ScannerResult(scanner=YARA)
        result.add_yara_result(rule=rule.name)
        result.save()
        assert result.state == UNKNOWN

        referer = '{}/en-US/firefox/previous/page'.format('http://example.org')
        response = self.client.post(
            reverse(
                'admin:scanners_scannerresult_handletruepositive',
                args=[result.pk],
            ),
            follow=True,
            HTTP_REFERER=referer
        )

        last_url, status_code = response.redirect_chain[-1]
        assert last_url == reverse('admin:scanners_scannerresult_changelist')

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

    def test_handle_revert_report_uses_referer_if_available(self):
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

        referer = '{}/en-US/firefox/previous/page'.format(settings.SITE_URL)
        response = self.client.post(
            reverse(
                'admin:scanners_scannerresult_handlerevert', args=[result.pk]
            ),
            follow=True,
            HTTP_REFERER=referer
        )

        last_url, status_code = response.redirect_chain[-1]
        assert last_url == referer

    def test_handle_revert_with_invalid_referer(self):
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

        referer = '{}/en-US/firefox/previous/page'.format('http://example.org')
        response = self.client.post(
            reverse(
                'admin:scanners_scannerresult_handlerevert', args=[result.pk]
            ),
            follow=True,
            HTTP_REFERER=referer
        )

        last_url, status_code = response.redirect_chain[-1]
        assert last_url == reverse('admin:scanners_scannerresult_changelist')

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

    def test_change_page(self):
        upload = FileUpload.objects.create()
        version = addon_factory().current_version
        result = ScannerResult.objects.create(
            scanner=YARA, upload=upload, version=version)
        url = reverse('admin:scanners_scannerresult_change', args=(result.pk,))
        response = self.client.get(url)
        assert response.status_code == 200

    def test_handle_inconclusive(self):
        # Create one entry with matches
        rule = ScannerRule.objects.create(name='some-rule', scanner=YARA)
        result = ScannerResult(scanner=YARA)
        result.add_yara_result(rule=rule.name)
        result.save()
        assert result.state == UNKNOWN

        response = self.client.post(
            reverse(
                'admin:scanners_scannerresult_handleinconclusive',
                args=[result.pk],
            ),
            follow=True,
        )

        result.refresh_from_db()
        assert result.state == INCONCLUSIVE
        html = pq(response.content)
        assert html('#result_list tbody tr').length == 0
        # A confirmation message should also appear.
        assert html('.messagelist .info').length == 1

    def test_handle_inconclusive_uses_referer_if_available(self):
        # Create one entry with matches
        rule = ScannerRule.objects.create(name='some-rule', scanner=YARA)
        result = ScannerResult(scanner=YARA)
        result.add_yara_result(rule=rule.name)
        result.save()

        referer = '{}/en-US/firefox/previous/page'.format(settings.SITE_URL)
        response = self.client.post(
            reverse(
                'admin:scanners_scannerresult_handleinconclusive',
                args=[result.pk],
            ),
            follow=True,
            HTTP_REFERER=referer,
        )

        last_url, status_code = response.redirect_chain[-1]
        assert last_url == referer

    def test_handle_inconclusive_with_invalid_referer(self):
        # Create one entry with matches
        rule = ScannerRule.objects.create(name='some-rule', scanner=YARA)
        result = ScannerResult(scanner=YARA)
        result.add_yara_result(rule=rule.name)
        result.save()

        referer = '{}/en-US/firefox/previous/page'.format('http://example.org')
        response = self.client.post(
            reverse(
                'admin:scanners_scannerresult_handleinconclusive',
                args=[result.pk],
            ),
            follow=True,
            HTTP_REFERER=referer,
        )

        last_url, status_code = response.redirect_chain[-1]
        assert last_url == reverse('admin:scanners_scannerresult_changelist')


class TestScannerRuleAdmin(TestCase):
    def setUp(self):
        super().setUp()

        self.user = user_factory()
        self.grant_permission(self.user, 'Admin:*')
        self.client.login(email=self.user.email)
        self.list_url = reverse('admin:scanners_scannerrule_changelist')
        self.admin = ScannerRuleAdmin(
            model=ScannerRule, admin_site=AdminSite()
        )

    def test_list_view(self):
        ScannerRule.objects.create(name='bar', scanner=YARA)
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
        # Create an extra result that doesn't match the rule we'll be looking
        # at: it shouldn't affect anything.
        ScannerResult.objects.create(scanner=YARA)
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
        assert link.text() == '1'  # Our rule has only one result.

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

    def test_get_fields(self):
        request = RequestFactory().get('/')
        request.user = self.user
        assert 'definition' in self.admin.get_fields(request=request)
        assert ('formatted_definition' not in
                self.admin.get_fields(request=request))

    def test_get_fields_for_non_admins(self):
        user = user_factory()
        self.grant_permission(user, 'Admin:ScannersRulesView')
        request = RequestFactory().get('/')
        request.user = user
        assert 'definition' not in self.admin.get_fields(request=request)
        assert 'formatted_definition' in self.admin.get_fields(request=request)


class TestScannerQueryRuleAdmin(AMOPaths, TestCase):
    def setUp(self):
        super().setUp()

        self.user = user_factory()
        self.grant_permission(self.user, 'Admin:ScannersQueryEdit')
        self.client.login(email=self.user.email)
        self.list_url = reverse('admin:scanners_scannerqueryrule_changelist')

    def test_list_view(self):
        ScannerQueryRule.objects.create(name='bar', scanner=YARA)
        response = self.client.get(self.list_url)
        assert response.status_code == 200

    def test_list_view_is_restricted(self):
        user = user_factory()
        self.grant_permission(user, 'Admin:Curation')
        self.client.login(email=user.email)
        response = self.client.get(self.list_url)
        assert response.status_code == 403

    def test_change_view_contains_link_to_results(self):
        rule = ScannerQueryRule.objects.create(name='bar', scanner=YARA)
        result = ScannerQueryResult(scanner=YARA)
        result.add_yara_result(rule=rule.name)
        result.save()
        ScannerQueryResult.objects.create(scanner=YARA)  # Doesn't match
        url = reverse(
            'admin:scanners_scannerqueryrule_change', args=(rule.pk,))
        response = self.client.get(url)
        assert response.status_code == 200
        doc = pq(response.content)
        link = doc('.field-matched_results_link a')
        assert link
        results_list_url = reverse(
            'admin:scanners_scannerqueryresult_changelist')
        expected_href = (
            f'{results_list_url}?matched_rules__id__exact={rule.pk}'
            f'&has_version=all&state=all&scanner={rule.scanner}'
        )
        assert link.attr('href') == expected_href
        assert link.text() == '1'

    def test_create_view_doesnt_contain_link_to_results(self):
        url = reverse('admin:scanners_scannerqueryrule_add')
        response = self.client.get(url)
        assert response.status_code == 200
        doc = pq(response.content)
        field = doc('.field-matched_results_link')
        assert field
        assert field.text() == 'Matched Results:\n-'
        link = doc('.field-matched_results_link a')
        assert not link

    def test_run_button_in_list_view_for_new_rule(self):
        rule = ScannerQueryRule.objects.create(
            name='bar', scanner=YARA, state=NEW)
        response = self.client.get(self.list_url)
        assert response.status_code == 200
        doc = pq(response.content)
        field = doc('.field-state_with_actions')
        assert field
        assert field.text() == 'New \xa0 Run'
        url = reverse(
            'admin:scanners_scannerqueryrule_handle_run', args=(rule.pk, ))
        button = field.find('button')[0]
        assert button.attrib['formaction'] == url

    def test_abort_button_in_list_view_for_running_rule(self):
        rule = ScannerQueryRule.objects.create(
            name='bar', scanner=YARA, state=RUNNING)
        response = self.client.get(self.list_url)
        assert response.status_code == 200
        doc = pq(response.content)
        field = doc('.field-state_with_actions')
        assert field
        assert field.text() == 'Running \xa0 Abort'
        url = reverse(
            'admin:scanners_scannerqueryrule_handle_abort', args=(rule.pk, ))
        button = field.find('button')[0]
        assert button.attrib['formaction'] == url

    def test_no_button_for_completed_rule_query(self):
        ScannerQueryRule.objects.create(
            name='bar', scanner=YARA, state=COMPLETED)
        response = self.client.get(self.list_url)
        assert response.status_code == 200
        doc = pq(response.content)
        field = doc('.field-state_with_actions')
        assert field
        assert field.text() == 'Completed'
        assert not field.find('button')

    def test_button_in_change_view(self):
        rule = ScannerQueryRule.objects.create(
            name='bar', scanner=YARA, state=RUNNING)
        change_url = reverse(
            'admin:scanners_scannerqueryrule_change', args=(rule.pk,))
        response = self.client.get(change_url)
        assert response.status_code == 200
        doc = pq(response.content)
        field = doc('.field-state_with_actions')
        assert field
        assert field.text() == 'State:\nRunning \xa0 Abort'
        url = reverse(
            'admin:scanners_scannerqueryrule_handle_abort', args=(rule.pk, ))
        button = field.find('button')[0]
        assert button.attrib['formaction'] == url

    def test_no_run_button_in_add_view(self):
        add_url = reverse('admin:scanners_scannerqueryrule_add')
        response = self.client.get(add_url)
        assert response.status_code == 200
        doc = pq(response.content)
        field = doc('.field-state_with_actions')
        assert field
        assert field.text() == 'State:\nNew'
        assert not field.find('button')

    @mock.patch('olympia.scanners.admin.run_yara_query_rule.delay')
    def test_run_action(self, run_yara_query_rule_mock):
        rule = ScannerQueryRule.objects.create(
            name='bar', scanner=YARA, state=NEW)
        response = self.client.post(
            reverse(
                'admin:scanners_scannerqueryrule_handle_run',
                args=[rule.pk],
            ), follow=True
        )
        assert response.status_code == 200
        assert response.redirect_chain == [(self.list_url, 302)]
        assert run_yara_query_rule_mock.call_count == 1
        assert run_yara_query_rule_mock.call_args[0] == (rule.pk,)
        messages = list(response.context['messages'])
        assert len(messages) == 1
        assert f'Rule {rule.pk} has been successfully' in str(messages[0])
        rule.reload()
        assert rule.state == SCHEDULED

    def test_run_action_functional(self):
        version = addon_factory(
            file_kw={'is_webextension': True}).current_version
        self.xpi_copy_over(version.all_files[0], 'webextension.xpi')
        rule = ScannerQueryRule.objects.create(
            name='always_true', scanner=YARA, state=NEW,
            definition='rule always_true { condition: true }')
        response = self.client.post(
            reverse(
                'admin:scanners_scannerqueryrule_handle_run',
                args=[rule.pk],
            ), follow=True
        )
        assert response.status_code == 200
        assert response.redirect_chain == [(self.list_url, 302)]
        messages = list(response.context['messages'])
        assert len(messages) == 1
        assert f'Rule {rule.pk} has been successfully' in str(messages[0])
        rule.reload()
        # We're not mocking the task in this test so it's ran in eager mode
        # directly.
        # We should have gone through SCHEDULED, RUNNING, and then COMPLETED.
        assert rule.state == COMPLETED
        # The rule should have been executed, it should have matched our
        # version.
        assert ScannerQueryResult.objects.count() == 1
        assert ScannerQueryResult.objects.get().version == version

    @mock.patch('olympia.scanners.admin.run_yara_query_rule.delay')
    def test_run_action_wrong_state(self, run_yara_query_rule_mock):
        rule = ScannerQueryRule.objects.create(
            name='bar', scanner=YARA, state=ABORTING)
        response = self.client.post(
            reverse(
                'admin:scanners_scannerqueryrule_handle_run',
                args=[rule.pk],
            ), follow=True
        )
        assert response.status_code == 200
        assert response.redirect_chain == [(self.list_url, 302)]
        assert run_yara_query_rule_mock.call_count == 0
        messages = list(response.context['messages'])
        assert len(messages) == 1
        assert f'Rule {rule.pk} could not be queued' in str(messages[0])
        rule.reload()
        assert rule.state == ABORTING

    def test_run_action_no_permission(self):
        user = user_factory()
        self.grant_permission(user, 'Admin:Curation')
        self.client.login(email=user.email)
        rule = ScannerQueryRule.objects.create(
            name='bar', scanner=YARA, state=NEW)
        response = self.client.post(
            reverse(
                'admin:scanners_scannerqueryrule_handle_run',
                args=[rule.pk],
            ), follow=True
        )
        assert response.status_code == 404

    def test_abort_action(self):
        rule = ScannerQueryRule.objects.create(
            name='bar', scanner=YARA, state=RUNNING)
        response = self.client.post(
            reverse(
                'admin:scanners_scannerqueryrule_handle_abort',
                args=[rule.pk],
            ), follow=True
        )
        assert response.status_code == 200
        assert response.redirect_chain == [(self.list_url, 302)]
        messages = list(response.context['messages'])
        assert len(messages) == 1
        assert f'Rule {rule.pk} is being aborted' in str(messages[0])
        rule.reload()
        assert rule.state == ABORTING

    def test_abort_action_wrong_state(self):
        rule = ScannerQueryRule.objects.create(
            name='bar', scanner=YARA, state=COMPLETED)
        response = self.client.post(
            reverse(
                'admin:scanners_scannerqueryrule_handle_abort',
                args=[rule.pk],
            ), follow=True
        )
        assert response.status_code == 200
        assert response.redirect_chain == [(self.list_url, 302)]
        messages = list(response.context['messages'])
        assert len(messages) == 1
        assert f'Rule {rule.pk} could not be aborted' in str(messages[0])
        assert f'was in "{rule.get_state_display()}" state' in str(messages[0])
        rule.reload()
        assert rule.state == COMPLETED

    def test_abort_action_no_permission(self):
        user = user_factory()
        self.grant_permission(user, 'Admin:Curation')
        self.client.login(email=user.email)
        rule = ScannerQueryRule.objects.create(
            name='bar', scanner=YARA, state=RUNNING)
        response = self.client.post(
            reverse(
                'admin:scanners_scannerqueryrule_handle_abort',
                args=[rule.pk],
            ), follow=True
        )
        assert response.status_code == 404

    def test_cannot_change_non_new_query_rule(self):
        rule = ScannerQueryRule.objects.create(name='bar', scanner=YARA)
        url = reverse(
            'admin:scanners_scannerqueryrule_change', args=(rule.pk,))
        response = self.client.get(url)
        assert response.status_code == 200
        doc = pq(response.content)

        # NEW query rule, it can be modified.
        assert not doc('.field-formatted_definition .readonly')

        # RUNNING query rule, it can not be modified
        rule.update(state=RUNNING)
        response = self.client.get(url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('.field-formatted_definition .readonly')


class TestScannerQueryResultAdmin(TestCase):
    def setUp(self):
        super().setUp()

        self.user = user_factory()
        self.grant_permission(self.user, 'Admin:ScannersQueryEdit')
        self.client.login(email=self.user.email)
        self.list_url = reverse('admin:scanners_scannerqueryresult_changelist')

        self.admin = ScannerQueryResultAdmin(
            model=ScannerQueryResult, admin_site=AdminSite()
        )

    def test_list_view(self):
        rule = ScannerQueryRule.objects.create(name='rule', scanner=YARA)
        result = ScannerQueryResult.objects.create(
            scanner=YARA, version=addon_factory().current_version
        )
        result.add_yara_result(rule=rule.name)
        result.save()
        response = self.client.get(self.list_url)
        assert response.status_code == 200
        html = pq(response.content)
        assert html('.field-formatted_addon').length == 1

    def test_list_view_no_query_permissions(self):
        rule = ScannerQueryRule.objects.create(name='rule', scanner=YARA)
        result = ScannerQueryResult.objects.create(
            scanner=YARA, version=addon_factory().current_version
        )
        result.add_yara_result(rule=rule.name)
        result.save()

        self.user = user_factory()
        # Give the user permission to edit ScannersResults, but not
        # ScannerQueryResults.
        self.grant_permission(self.user, 'Admin:ScannersResultsEdit')
        self.client.login(email=self.user.email)
        response = self.client.get(self.list_url)
        assert response.status_code == 403

    def test_list_view_query_view_permission(self):
        self.user = user_factory()
        self.grant_permission(self.user, 'Admin:ScannersQueryView')
        self.client.login(email=self.user.email)
        self.test_list_view()

    def test_list_filters(self):
        rule_foo = ScannerQueryRule.objects.create(name='foo', scanner=YARA)
        rule_bar = ScannerQueryRule.objects.create(name='bar', scanner=YARA)

        response = self.client.get(self.list_url)
        assert response.status_code == 200
        doc = pq(response.content)
        expected = [
            ('All', '?'),
            ('customs', '?scanner__exact=1'),
            ('wat', '?scanner__exact=2'),
            ('yara', '?scanner__exact=3'),
            ('ml_api', '?scanner__exact=4'),

            ('All', '?has_matched_rules=all'),
            (' With matched rules only', '?'),

            ('All', '?state=all'),
            ('Unknown', '?'),
            ('True positive', '?state=1'),
            ('False positive', '?state=2'),
            ('Inconclusive', '?state=3'),

            ('All', '?'),
            ('bar (yara)', f'?matched_rules__id__exact={rule_bar.pk}'),
            ('foo (yara)', f'?matched_rules__id__exact={rule_foo.pk}'),

            ('All', '?has_version=all'),
            (' With version only', '?'),
        ]
        filters = [
            (x.text, x.attrib['href']) for x in doc('#changelist-filter a')
        ]
        assert filters == expected

    def test_list_filter_matched_rules(self):
        rule_foo = ScannerQueryRule.objects.create(name='foo', scanner=YARA)
        rule_bar = ScannerQueryRule.objects.create(name='bar', scanner=YARA)
        with_foo_match = ScannerQueryResult(scanner=YARA)
        with_foo_match.add_yara_result(rule=rule_foo.name)
        with_foo_match.save()
        with_bar_matches = ScannerQueryResult(scanner=YARA)
        with_bar_matches.add_yara_result(rule=rule_bar.name)
        with_bar_matches.save()

        response = self.client.get(self.list_url, {
            'matched_rules__id__exact': rule_bar.pk,
            WithVersionFilter.parameter_name: 'all',
        })
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#result_list tbody tr').length == 1
        assert doc('.field-formatted_matched_rules').text() == 'bar'

    def test_change_page(self):
        rule = ScannerQueryRule.objects.create(name='darule', scanner=YARA)
        result = ScannerQueryResult.objects.create(
            scanner=YARA, version=addon_factory().current_version)
        result.add_yara_result(rule=rule.name)
        result.save()
        url = reverse(
            'admin:scanners_scannerqueryresult_change', args=(result.pk,))
        response = self.client.get(url)
        assert response.status_code == 200

        rule_url = reverse(
            'admin:scanners_scannerqueryrule_change', args=(rule.pk,))
        doc = pq(response.content)
        link = doc('.field-formatted_matched_rules_with_files td a')
        assert link.text() == 'darule ???'
        assert link.attr('href') == rule_url

    def test_change_view_no_query_permissions(self):
        self.user = user_factory()
        # Give the user permission to edit ScannersResults, but not
        # ScannerQueryResults.
        self.grant_permission(self.user, 'Admin:ScannersResultsEdit')
        self.client.login(email=self.user.email)
        rule = ScannerQueryRule.objects.create(name='darule', scanner=YARA)
        result = ScannerQueryResult.objects.create(
            scanner=YARA, version=addon_factory().current_version)
        result.add_yara_result(rule=rule.name)
        result.save()
        url = reverse(
            'admin:scanners_scannerqueryresult_change', args=(result.pk,))
        response = self.client.get(url)
        assert response.status_code == 403

    def test_change_view_query_view_permission(self):
        self.user = user_factory()
        self.grant_permission(self.user, 'Admin:ScannersQueryView')
        self.client.login(email=self.user.email)
        self.test_change_page()

    def test_formatted_matched_rules_with_files(self):
        version = addon_factory().current_version
        result = ScannerQueryResult.objects.create(
            scanner=YARA, version=version
        )
        rule = ScannerQueryRule.objects.create(name='bar', scanner=YARA)
        filename = 'some/file.js'
        result.add_yara_result(rule=rule.name, meta={'filename': filename})
        result.save()

        rule_url = reverse(
            'admin:scanners_scannerqueryrule_change', args=(rule.pk,))

        external_site_url = 'http://example.org'
        file_id = version.all_files[0].id
        assert file_id is not None
        expect_file_item = '<a href="{}{}">{}</a>'.format(
            external_site_url,
            reverse('files.list', args=[file_id, 'file', filename]),
            filename
        )
        with override_settings(EXTERNAL_SITE_URL=external_site_url):
            content = self.admin.formatted_matched_rules_with_files(result)
        assert expect_file_item in content
        assert rule_url in content


class TestIsSafeUrl(TestCase):
    def test_enforces_https_when_request_is_secure(self):
        request = RequestFactory().get('/', secure=True)
        assert _is_safe_url('https://{}'.format(settings.DOMAIN), request)
        assert not _is_safe_url('http://{}'.format(settings.DOMAIN), request)

    def test_does_not_require_https_when_request_is_not_secure(self):
        request = RequestFactory().get('/', secure=False)
        assert _is_safe_url('https://{}'.format(settings.DOMAIN), request)
        assert _is_safe_url('http://{}'.format(settings.DOMAIN), request)

    def test_allows_domain(self):
        request = RequestFactory().get('/', secure=True)
        assert _is_safe_url('https://{}/foo'.format(settings.DOMAIN), request)
        assert not _is_safe_url('https://not-olympia.dev', request)

    def test_allows_external_site_url(self):
        request = RequestFactory().get('/', secure=True)
        external_domain = urlparse(settings.EXTERNAL_SITE_URL).netloc
        assert _is_safe_url('https://{}/foo'.format(external_domain), request)
