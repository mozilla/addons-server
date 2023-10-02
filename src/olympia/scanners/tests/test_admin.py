import json
from datetime import datetime
from unittest import mock
from urllib.parse import urljoin

from django.conf import settings
from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory
from django.test.utils import override_settings
from django.urls import reverse
from django.utils.formats import localize
from django.utils.html import format_html
from django.utils.http import urlencode

from pyquery import PyQuery as pq

from olympia import amo
from olympia.amo.tests import (
    TestCase,
    addon_factory,
    user_factory,
    version_factory,
)
from olympia.constants.scanners import (
    ABORTING,
    COMPLETED,
    CUSTOMS,
    FALSE_POSITIVE,
    INCONCLUSIVE,
    MAD,
    NEW,
    RUNNING,
    SCHEDULED,
    TRUE_POSITIVE,
    UNKNOWN,
    YARA,
)
from olympia.files.models import FileUpload
from olympia.reviewers.templatetags.code_manager import code_manager_url
from olympia.scanners.admin import (
    ExcludeMatchedRulesFilter,
    MatchesFilter,
    ScannerQueryResultAdmin,
    ScannerResultAdmin,
    ScannerRuleAdmin,
    StateFilter,
    WithVersionFilter,
    formatted_matched_rules_with_files_and_data,
)
from olympia.scanners.models import (
    ScannerQueryResult,
    ScannerQueryRule,
    ScannerResult,
    ScannerRule,
)
from olympia.scanners.templatetags.scanners import format_scanners_data
from olympia.versions.models import Version


class TestScannerResultAdmin(TestCase):
    def setUp(self):
        super().setUp()

        self.user = user_factory(email='someone@mozilla.com')
        self.grant_permission(self.user, 'Admin:ScannersResultsEdit')
        self.grant_permission(self.user, 'Admin:ScannersResultsView')
        self.client.force_login(self.user)
        self.list_url = reverse('admin:scanners_scannerresult_changelist')

        self.admin = ScannerResultAdmin(model=ScannerResult, admin_site=AdminSite())

    def test_list_view(self):
        rule = ScannerRule.objects.create(name='rule', scanner=CUSTOMS)
        ScannerResult.objects.create(
            scanner=CUSTOMS,
            version=addon_factory().current_version,
            results={'matchedRules': [rule.name]},
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
            results={'matchedRules': [rule.name]},
        )
        user = user_factory(email='somebodyelse@mozilla.com')
        self.grant_permission(user, 'Admin:ScannersResultsView')
        self.client.force_login(user)
        response = self.client.get(self.list_url)
        assert response.status_code == 200
        html = pq(response.content)
        assert html('.column-result_actions').length == 0

    def test_list_view_is_restricted(self):
        user = user_factory(email='curator@mozilla.com')
        self.grant_permission(user, 'Admin:Curation')
        self.client.force_login(user)
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
        version = version_factory(addon=addon, channel=amo.CHANNEL_LISTED)
        result = ScannerResult(version=version)

        formatted_addon = self.admin.formatted_addon(result)
        assert (
            '<a href="{}">Link to review page</a>'.format(
                urljoin(
                    settings.EXTERNAL_SITE_URL,
                    reverse('reviewers.review', args=['listed', addon.id]),
                ),
            )
            in formatted_addon
        )
        assert f'Name:</td><td>{addon.name}' in formatted_addon
        assert f'Version:</td><td>{version.version}' in formatted_addon
        assert f'Channel:</td><td>{version.get_channel_display()}' in formatted_addon

    def test_formatted_unlisted_addon(self):
        addon = addon_factory()
        version = version_factory(addon=addon, channel=amo.CHANNEL_UNLISTED)
        result = ScannerResult(version=version)

        formatted_addon = self.admin.formatted_addon(result)
        assert (
            '<a href="{}">Link to review page</a>'.format(
                urljoin(
                    settings.EXTERNAL_SITE_URL,
                    reverse('reviewers.review', args=['unlisted', addon.id]),
                ),
            )
            in formatted_addon
        )
        assert f'Name:</td><td>{addon.name}' in formatted_addon
        assert f'Version:</td><td>{version.version}' in formatted_addon
        assert f'Channel:</td><td>{version.get_channel_display()}' in formatted_addon

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
        version = version_factory(addon=addon_factory(), channel=amo.CHANNEL_LISTED)
        result = ScannerResult(version=version)

        assert self.admin.channel(result) == 'Listed'

    def test_unlisted_channel(self):
        version = version_factory(addon=addon_factory(), channel=amo.CHANNEL_UNLISTED)
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

    def test_formatted_created(self):
        created = datetime.now()
        result = ScannerResult(created=created)

        assert self.admin.formatted_created(result) == '-'
        result.version = Version(created=created)

        assert self.admin.formatted_created(result) == created.strftime(
            '%Y-%m-%d %H:%M:%S'
        )

    def test_formatted_matched_rules_with_files(self):
        version = addon_factory().current_version
        result = ScannerResult.objects.create(scanner=YARA, version=version)
        rule = ScannerRule.objects.create(name='bar', scanner=YARA)
        filename = 'some/file.js'
        result.add_yara_result(rule=rule.name, meta={'filename': filename})
        result.save()

        file_id = version.file.id
        assert file_id is not None

        expect_file_item = code_manager_url(
            'browse', version.addon.pk, version.pk, file=filename
        )
        assert expect_file_item in formatted_matched_rules_with_files_and_data(result)

    def test_formatted_matched_rules_with_files_without_version(self):
        result = ScannerResult.objects.create(scanner=YARA)
        rule = ScannerRule.objects.create(name='bar', scanner=YARA)
        filename = 'some/file.js'
        result.add_yara_result(rule=rule.name, meta={'filename': filename})
        result.save()

        # We list the file related to the matched rule...
        assert filename in formatted_matched_rules_with_files_and_data(result)
        # ...but we do not add a link to it because there is no associated
        # version.
        assert '/browse/' not in formatted_matched_rules_with_files_and_data(result)

    def test_formatted_score_for_customs(self):
        result = ScannerResult(score=0.123, scanner=CUSTOMS)

        assert self.admin.formatted_score(result) == '12%'

    def test_formatted_score_for_mad(self):
        result = ScannerResult(score=0.456, scanner=MAD)

        assert self.admin.formatted_score(result) == '46%'

    def test_formatted_score_when_not_available(self):
        result = ScannerResult(score=-1, scanner=MAD)

        assert self.admin.formatted_score(result) == 'n/a'

    def test_list_queries(self):
        ScannerResult.objects.create(
            scanner=CUSTOMS, version=addon_factory().current_version
        )
        deleted_addon = addon_factory(name='a deleted add-on')
        ScannerResult.objects.create(
            scanner=CUSTOMS, version=deleted_addon.current_version
        )
        deleted_addon.delete()

        with self.assertNumQueries(13):
            # 13 queries:
            # - 2 transaction savepoints because of tests
            # - 2 request user and groups
            # - 1 COUNT(*) on scanners results for pagination
            #     (show_full_result_count=False so we avoid the duplicate)
            # - 2 get all available rules for filtering
            # - 1 scanners results and versions in one query
            # - 1 all add-ons in one query
            # - 1 all files in one query
            # - 1 all authors in one query
            # - 1 all add-ons translations in one query
            # - 1 all scanner rules in one query
            response = self.client.get(
                self.list_url, {MatchesFilter.parameter_name: 'all'}
            )
        assert response.status_code == 200
        html = pq(response.content)
        expected_length = ScannerResult.objects.count()
        assert html('#result_list tbody > tr').length == expected_length
        # The name of the deleted add-on should be displayed.
        assert str(deleted_addon.name) in html.text()

    def test_guid_column_is_sortable_in_list(self):
        rule_foo = ScannerRule.objects.create(name='foo', scanner=CUSTOMS)
        ScannerResult.objects.create(
            scanner=CUSTOMS,
            results={'matchedRules': [rule_foo.name]},
            version=version_factory(addon=addon_factory()),
        )

        response = self.client.get(self.list_url)
        doc = pq(response.content)
        assert 'sortable' in doc('.column-guid').attr('class').split(' ')

    def test_list_filters(self):
        rule_bar = ScannerRule.objects.create(name='bar', scanner=YARA)
        rule_hello = ScannerRule.objects.create(
            name='hello', scanner=YARA, pretty_name='Pretty Hello'
        )
        rule_foo = ScannerRule.objects.create(name='foo', scanner=CUSTOMS)

        response = self.client.get(self.list_url)
        assert response.status_code == 200
        doc = pq(response.content)
        expected = [
            ('All', '?'),
            ('customs', '?scanner__exact=1'),
            ('wat', '?scanner__exact=2'),
            ('yara', '?scanner__exact=3'),
            ('mad', '?scanner__exact=4'),
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
            ('Pretty Hello (yara)', f'?matched_rules__id__exact={rule_hello.pk}'),
            ('All', '?has_version=all'),
            (' With version only', '?'),
        ]
        filters = [(x.text, x.attrib['href']) for x in doc('#changelist-filter a')]
        assert filters == expected

        # Exclude rules is a form, needs a separate check.
        expected = [
            ('foo (customs)', str(rule_foo.pk)),
            ('bar (yara)', str(rule_bar.pk)),
            ('Pretty Hello (yara)', str(rule_hello.pk)),
        ]
        filters = [
            (option.text, option.attrib['value'])
            for option in doc('#changelist-filter option')
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

        response = self.client.get(
            self.list_url,
            {
                'matched_rules__id__exact': rule_bar.pk,
                WithVersionFilter.parameter_name: 'all',
            },
        )
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#result_list tbody > tr').length == 1
        assert doc('.field-formatted_matched_rules').text() == (
            'bar (yara), hello (yara)'
        )

    def test_exclude_matched_rules_filter(self):
        rule_bar = ScannerRule.objects.create(name='bar', scanner=YARA)
        rule_hello = ScannerRule.objects.create(name='hello', scanner=YARA)
        rule_foo = ScannerRule.objects.create(name='foo', scanner=CUSTOMS)

        with_bar_and_hello_matches = ScannerResult(scanner=YARA)
        with_bar_and_hello_matches.add_yara_result(rule=rule_bar.name)
        with_bar_and_hello_matches.add_yara_result(rule=rule_hello.name)
        with_bar_and_hello_matches.save()
        with_bar_and_hello_matches.update(created=self.days_ago(3))

        with_foo_match = ScannerResult(
            scanner=CUSTOMS, results={'matchedRules': [rule_foo.name]}
        )
        with_foo_match.save()
        with_foo_match.update(created=self.days_ago(2))

        with_hello_match = ScannerResult(scanner=YARA)
        with_hello_match.add_yara_result(rule=rule_hello.name)
        with_hello_match.save()
        with_hello_match.update(created=self.days_ago(1))

        # Exclude 'bar'. We should get 3 results, because they all match other
        # rules as well, so they wouldn't be excluded.
        response = self.client.get(
            self.list_url,
            {
                ExcludeMatchedRulesFilter.parameter_name: rule_bar.pk,
                WithVersionFilter.parameter_name: 'all',
            },
        )
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#result_list tbody > tr').length == 3
        expected_ids = [
            with_hello_match.pk,
            with_foo_match.pk,
            with_bar_and_hello_matches.pk,
        ]
        ids = list(map(int, doc('#result_list .field-id').text().split(' ')))
        assert ids == expected_ids

        # Exclude 'hello'. with_bar_and_hello_matches should still be present
        # as it matches another rule, but with_hello_match should be absent.
        # with_foo_match should not be affected.
        response = self.client.get(
            self.list_url,
            {
                ExcludeMatchedRulesFilter.parameter_name: rule_hello.pk,
                WithVersionFilter.parameter_name: 'all',
            },
        )
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#result_list tbody > tr').length == 2
        expected_ids = [
            with_foo_match.pk,
            with_bar_and_hello_matches.pk,
        ]
        ids = list(map(int, doc('#result_list .field-id').text().split(' ')))
        assert ids == expected_ids

        # Exclude 'foo'. with_bar_and_hello_matches and with_hello_match should
        # still be present, and with_foo only should be gone as it only matches
        # an excluded rule.
        response = self.client.get(
            self.list_url,
            {
                ExcludeMatchedRulesFilter.parameter_name: rule_foo.pk,
                WithVersionFilter.parameter_name: 'all',
            },
        )
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#result_list tbody > tr').length == 2
        expected_ids = [
            with_hello_match.pk,
            with_bar_and_hello_matches.pk,
        ]
        ids = list(map(int, doc('#result_list .field-id').text().split(' ')))
        assert ids == expected_ids

    def test_multiple_exclude_matched_rules_filter(self):
        rule_bar = ScannerRule.objects.create(name='bar', scanner=YARA)
        rule_hello = ScannerRule.objects.create(name='hello', scanner=YARA)
        rule_foo = ScannerRule.objects.create(name='foo', scanner=CUSTOMS)

        with_bar_and_hello_matches = ScannerResult(scanner=YARA)
        with_bar_and_hello_matches.add_yara_result(rule=rule_bar.name)
        with_bar_and_hello_matches.add_yara_result(rule=rule_hello.name)
        with_bar_and_hello_matches.save()
        with_bar_and_hello_matches.update(created=self.days_ago(3))
        with_foo_match = ScannerResult(
            scanner=CUSTOMS,
            results={'matchedRules': [rule_foo.name]},
        )
        with_foo_match.save()
        with_foo_match.update(created=self.days_ago(2))
        with_hello_match = ScannerResult(scanner=YARA)
        with_hello_match.add_yara_result(rule=rule_hello.name)
        with_hello_match.save()
        with_hello_match.update(created=self.days_ago(1))

        # Exclude 'bar' and 'hello'. One result should be left: with_hello
        # and with_bar_and_hello both only matches rules that have been
        # excluded.
        response = self.client.get(
            self.list_url,
            {
                ExcludeMatchedRulesFilter.parameter_name: [rule_bar.pk, rule_hello.pk],
                WithVersionFilter.parameter_name: 'all',
            },
        )
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#result_list tbody > tr').length == 1
        expected_ids = [
            with_foo_match.pk,
        ]
        ids = list(map(int, doc('#result_list .field-id').text().split(' ')))
        assert ids == expected_ids

        # Repeat with another filter into the mix to test links.
        # Set the state of all results to inconclusive first...
        ScannerResult.objects.update(state=INCONCLUSIVE)
        response = self.client.get(
            self.list_url,
            {
                ExcludeMatchedRulesFilter.parameter_name: [rule_bar.pk, rule_hello.pk],
                WithVersionFilter.parameter_name: 'all',
                StateFilter.parameter_name: INCONCLUSIVE,
            },
        )
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#result_list tbody > tr').length == 1
        expected_ids = [
            with_foo_match.pk,
        ]
        ids = list(map(int, doc('#result_list .field-id').text().split(' ')))
        assert ids == expected_ids

        # Check the links to other filters/form for the exclude rules filter
        # are pre-populated with the current active filters correctly.
        links = [x.attrib['href'] for x in doc('#changelist-filter a')]
        expected = [
            '?',
            f'?exclude_rule={rule_bar.pk}&exclude_rule={rule_hello.pk}&has_version=all'
            '&state=3',
            f'?exclude_rule={rule_bar.pk}&exclude_rule={rule_hello.pk}&has_version=all'
            '&state=3&scanner__exact=1',
            f'?exclude_rule={rule_bar.pk}&exclude_rule={rule_hello.pk}&has_version=all'
            '&state=3&scanner__exact=2',
            f'?exclude_rule={rule_bar.pk}&exclude_rule={rule_hello.pk}&has_version=all'
            '&state=3&scanner__exact=3',
            f'?exclude_rule={rule_bar.pk}&exclude_rule={rule_hello.pk}&has_version=all'
            '&state=3&scanner__exact=4',
            f'?exclude_rule={rule_bar.pk}&exclude_rule={rule_hello.pk}&has_version=all'
            '&state=3&has_matched_rules=all',
            f'?exclude_rule={rule_bar.pk}&exclude_rule={rule_hello.pk}&has_version=all'
            '&state=3',
            f'?exclude_rule={rule_bar.pk}&exclude_rule={rule_hello.pk}&has_version=all'
            '&state=all',
            f'?exclude_rule={rule_bar.pk}&exclude_rule={rule_hello.pk}&has_version=all',
            f'?exclude_rule={rule_bar.pk}&exclude_rule={rule_hello.pk}&has_version=all'
            '&state=1',
            f'?exclude_rule={rule_bar.pk}&exclude_rule={rule_hello.pk}&has_version=all'
            '&state=2',
            f'?exclude_rule={rule_bar.pk}&exclude_rule={rule_hello.pk}&has_version=all'
            '&state=3',
            f'?exclude_rule={rule_bar.pk}&exclude_rule={rule_hello.pk}&has_version=all'
            '&state=3',
            f'?exclude_rule={rule_bar.pk}&exclude_rule={rule_hello.pk}&has_version=all'
            f'&state=3&matched_rules__id__exact={rule_foo.pk}',
            f'?exclude_rule={rule_bar.pk}&exclude_rule={rule_hello.pk}&has_version=all'
            f'&state=3&matched_rules__id__exact={rule_bar.pk}',
            f'?exclude_rule={rule_bar.pk}&exclude_rule={rule_hello.pk}&has_version=all'
            f'&state=3&matched_rules__id__exact={rule_hello.pk}',
            f'?exclude_rule={rule_bar.pk}&exclude_rule={rule_hello.pk}&has_version=all'
            '&state=3',
            f'?exclude_rule={rule_bar.pk}&exclude_rule={rule_hello.pk}&state=3',
        ]
        assert links == expected

        # Check the existing filters are passed as hidden fields in the form...
        hidden = [
            (x.attrib['name'], x.attrib['value'])
            for x in doc('#changelist-filter form input[type=hidden]')
        ]
        expected = [('has_version', 'all'), ('state', '3')]
        assert hidden == expected

        # And finally check that the correct options are selected.
        options = [
            x.attrib['value']
            for x in doc(
                '#changelist-filter form select[name=exclude_rule] option[selected]'
            )
        ]
        expected = [str(rule_bar.pk), str(rule_hello.pk)]
        assert options == expected

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
        assert html('#result_list tbody > tr').length == 1

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
        assert html('#result_list tbody > tr').length == expected_length

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
        assert html('#result_list tbody > tr').length == 0
        # A confirmation message should also appear.
        assert html('.messagelist .info').length == 1

    def test_handle_true_positive_uses_referer_if_available(self):
        # Create one entry with matches
        rule = ScannerRule.objects.create(name='some-rule', scanner=YARA)
        result = ScannerResult(scanner=YARA)
        result.add_yara_result(rule=rule.name)
        result.save()
        assert result.state == UNKNOWN

        referer = f'{settings.SITE_URL}/en-US/firefox/previous/page'
        response = self.client.post(
            reverse(
                'admin:scanners_scannerresult_handletruepositive',
                args=[result.pk],
            ),
            follow=True,
            HTTP_REFERER=referer,
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
            HTTP_REFERER=referer,
        )

        last_url, status_code = response.redirect_chain[-1]
        assert last_url == reverse('admin:scanners_scannerresult_changelist')

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
            ),
            follow=True,
        )

        result.refresh_from_db()
        assert result.state == FALSE_POSITIVE
        # The action should send a redirect.
        last_url, status_code = response.redirect_chain[-1]
        assert status_code == 302
        # The action should redirect to the list view and the default list
        # filters should hide the result (because its state is not UNKNOWN
        # anymore).
        html = pq(response.content)
        assert html('#result_list tbody > tr').length == 0
        # A confirmation message should also appear.
        assert html('.messagelist .info').length == 1

    def test_handle_yara_false_positive_uses_referer_if_available(self):
        # Create one entry with matches
        rule = ScannerRule.objects.create(name='some-rule', scanner=YARA)
        result = ScannerResult(scanner=YARA)
        result.add_yara_result(rule=rule.name)
        result.save()
        assert result.state == UNKNOWN

        referer = f'{settings.SITE_URL}/en-US/firefox/previous/page'
        response = self.client.post(
            reverse(
                'admin:scanners_scannerresult_handlefalsepositive',
                args=[result.pk],
            ),
            follow=True,
            HTTP_REFERER=referer,
        )

        last_url, status_code = response.redirect_chain[-1]
        assert last_url == referer

    def test_handle_yara_false_positive_with_invalid_referer(self):
        # Create one entry with matches
        rule = ScannerRule.objects.create(name='some-rule', scanner=YARA)
        result = ScannerResult(scanner=YARA)
        result.add_yara_result(rule=rule.name)
        result.save()
        assert result.state == UNKNOWN

        referer = '{}/en-US/firefox/previous/page'.format('http://example.org')
        response = self.client.post(
            reverse(
                'admin:scanners_scannerresult_handlefalsepositive',
                args=[result.pk],
            ),
            follow=True,
            HTTP_REFERER=referer,
        )

        last_url, status_code = response.redirect_chain[-1]
        assert last_url == reverse('admin:scanners_scannerresult_changelist')

    @override_settings(CUSTOMS_GIT_REPOSITORY='git/repo')
    def test_handle_customs_false_positive(self):
        # Create one entry with matches
        rule = ScannerRule.objects.create(name='some-rule', scanner=CUSTOMS)
        result = ScannerResult(scanner=CUSTOMS, results={'matchedRules': [rule.name]})
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
        assert urlencode({'labels': 'false positive report'}) in response['Location']
        assert 'Raw+scanner+results' not in response['Location']

    def test_handle_revert_report(self):
        # Create one entry with matches
        rule = ScannerRule.objects.create(name='some-rule', scanner=YARA)
        result = ScannerResult(
            scanner=YARA, version=version_factory(addon=addon_factory())
        )
        result.add_yara_result(rule=rule.name)
        result.state = TRUE_POSITIVE
        result.save()
        assert result.state == TRUE_POSITIVE

        response = self.client.post(
            reverse('admin:scanners_scannerresult_handlerevert', args=[result.pk]),
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
        assert html('#result_list tbody > tr').length == 1
        # A confirmation message should also appear.
        assert html('.messagelist .info').length == 1

    def test_handle_revert_report_uses_referer_if_available(self):
        # Create one entry with matches
        rule = ScannerRule.objects.create(name='some-rule', scanner=YARA)
        result = ScannerResult(
            scanner=YARA, version=version_factory(addon=addon_factory())
        )
        result.add_yara_result(rule=rule.name)
        result.state = TRUE_POSITIVE
        result.save()
        assert result.state == TRUE_POSITIVE

        referer = f'{settings.SITE_URL}/en-US/firefox/previous/page'
        response = self.client.post(
            reverse('admin:scanners_scannerresult_handlerevert', args=[result.pk]),
            follow=True,
            HTTP_REFERER=referer,
        )

        last_url, status_code = response.redirect_chain[-1]
        assert last_url == referer

    def test_handle_revert_with_invalid_referer(self):
        # Create one entry with matches
        rule = ScannerRule.objects.create(name='some-rule', scanner=YARA)
        result = ScannerResult(
            scanner=YARA, version=version_factory(addon=addon_factory())
        )
        result.add_yara_result(rule=rule.name)
        result.state = TRUE_POSITIVE
        result.save()
        assert result.state == TRUE_POSITIVE

        referer = '{}/en-US/firefox/previous/page'.format('http://example.org')
        response = self.client.post(
            reverse('admin:scanners_scannerresult_handlerevert', args=[result.pk]),
            follow=True,
            HTTP_REFERER=referer,
        )

        last_url, status_code = response.redirect_chain[-1]
        assert last_url == reverse('admin:scanners_scannerresult_changelist')

    def test_handle_true_positive_and_non_admin_user(self):
        result = ScannerResult(scanner=CUSTOMS)
        user = user_factory(email='somebodyelse@mozilla.com')
        self.grant_permission(user, 'Admin:ScannersResultsView')
        self.client.force_login(user)
        response = self.client.post(
            reverse(
                'admin:scanners_scannerresult_handletruepositive',
                args=[result.pk],
            )
        )
        assert response.status_code == 404

    def test_handle_false_positive_and_non_admin_user(self):
        result = ScannerResult(scanner=CUSTOMS)
        user = user_factory(email='somebodyelse@mozilla.com')
        self.grant_permission(user, 'Admin:ScannersResultsView')
        self.client.force_login(user)
        response = self.client.post(
            reverse(
                'admin:scanners_scannerresult_handlefalsepositive',
                args=[result.pk],
            )
        )
        assert response.status_code == 404

    def test_handle_revert_report_and_non_admin_user(self):
        result = ScannerResult(scanner=CUSTOMS)
        user = user_factory(email='somebodyelse@mozilla.com')
        self.grant_permission(user, 'Admin:ScannersResultsView')
        self.client.force_login(user)
        response = self.client.post(
            reverse(
                'admin:scanners_scannerresult_handlerevert',
                args=[result.pk],
            )
        )
        assert response.status_code == 404

    def test_change_page(self):
        upload = FileUpload.objects.create(
            user=user_factory(),
            ip_address='1.2.3.4',
            source=amo.UPLOAD_SOURCE_DEVHUB,
            channel=amo.CHANNEL_LISTED,
        )
        version = addon_factory().current_version
        result = ScannerResult.objects.create(
            scanner=YARA, upload=upload, version=version
        )
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
        assert html('#result_list tbody > tr').length == 0
        # A confirmation message should also appear.
        assert html('.messagelist .info').length == 1

    def test_handle_inconclusive_uses_referer_if_available(self):
        # Create one entry with matches
        rule = ScannerRule.objects.create(name='some-rule', scanner=YARA)
        result = ScannerResult(scanner=YARA)
        result.add_yara_result(rule=rule.name)
        result.save()

        referer = f'{settings.SITE_URL}/en-US/firefox/previous/page'
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

        self.user = user_factory(email='someone@mozilla.com')
        self.grant_permission(self.user, 'Admin:*')
        self.client.force_login(self.user)
        self.list_url = reverse('admin:scanners_scannerrule_changelist')
        self.admin = ScannerRuleAdmin(model=ScannerRule, admin_site=AdminSite())

    def test_list_view(self):
        ScannerRule.objects.create(name='bar', scanner=YARA)
        response = self.client.get(self.list_url)
        assert response.status_code == 200

    def test_list_view_is_restricted(self):
        user = user_factory(email='curator@mozilla.com')
        self.grant_permission(user, 'Admin:Curation')
        self.client.force_login(user)
        response = self.client.get(self.list_url)
        assert response.status_code == 403

    def test_change_view_contains_link_to_results(self):
        rule = ScannerRule.objects.create(name='bar', scanner=YARA)
        addon = addon_factory()
        version = addon.current_version
        result = ScannerResult(scanner=YARA, version=version)
        result.add_yara_result(rule=rule.name)
        result.save()
        # Create another version that matches for the same add-on.
        version = version_factory(addon=addon)
        result = ScannerResult(scanner=YARA, version=version)
        result.add_yara_result(rule=rule.name)
        result.save()
        # Create another add-on that has a matching version
        addon = addon_factory()
        result = ScannerResult(scanner=YARA, version=addon.current_version)
        result.add_yara_result(rule=rule.name)
        result.save()
        # Create an extra result on the same add-on that doesn't match the rule
        # we'll be looking at: it shouldn't affect anything.
        ScannerResult.objects.create(scanner=YARA, version=version_factory(addon=addon))
        url = reverse('admin:scanners_scannerrule_change', args=(rule.pk,))
        response = self.client.get(url)
        assert response.status_code == 200
        doc = pq(response.content)
        link = doc('.field-matched_results_link a')
        assert link
        results_list_url = reverse('admin:scanners_scannerresult_changelist')
        expected_href = (
            f'{results_list_url}?matched_rules__id__exact={rule.pk}'
            f'&has_version=all&state=all'
        )
        assert link.attr('href') == expected_href
        assert link.text() == '3 (2 add-ons)'

        link_response = self.client.get(expected_href)
        assert link_response.status_code == 200

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
        assert 'formatted_definition' not in self.admin.get_fields(request=request)

    def test_get_fields_for_non_admins(self):
        user = user_factory(email='somebodyelse@mozilla.com')
        self.grant_permission(user, 'Admin:ScannersRulesView')
        request = RequestFactory().get('/')
        request.user = user
        assert 'definition' not in self.admin.get_fields(request=request)
        assert 'formatted_definition' in self.admin.get_fields(request=request)

    def test_create_form_filters_list_of_scanners(self):
        url = reverse('admin:scanners_scannerrule_add')
        response = self.client.get(url)
        select = pq(response.content)('#id_scanner')
        assert len(select.children()) == 3


class TestScannerQueryRuleAdmin(TestCase):
    def setUp(self):
        super().setUp()

        self.user = user_factory(email='someone@mozilla.com')
        self.grant_permission(self.user, 'Admin:ScannersQueryEdit')
        self.client.force_login(self.user)
        self.list_url = reverse('admin:scanners_scannerqueryrule_changelist')

    def test_list_view(self):
        ScannerQueryRule.objects.create(name='bar', scanner=YARA)
        response = self.client.get(self.list_url)
        assert response.status_code == 200
        doc = pq(response.content)
        classes = set(doc('body')[0].attrib['class'].split())
        expected_classes = {
            'app-scanners',
            'model-scannerqueryrule',
            'change-list',
        }
        assert classes == expected_classes

    def test_list_view_viewer(self):
        self.user.groupuser_set.all().delete()
        self.grant_permission(self.user, 'Admin:ScannersQueryView')
        ScannerQueryRule.objects.create(name='bar', scanner=YARA)
        response = self.client.get(self.list_url)
        assert response.status_code == 200
        doc = pq(response.content)
        classes = set(doc('body')[0].attrib['class'].split())
        expected_classes = {
            'app-scanners',
            'model-scannerqueryrule',
            'change-list',
            'hide-action-buttons',
        }
        assert classes == expected_classes

    def test_list_view_is_restricted(self):
        user = user_factory(email='curator@mozilla.com')
        self.grant_permission(user, 'Admin:Curation')
        self.client.force_login(user)
        response = self.client.get(self.list_url)
        assert response.status_code == 403

    def test_change_view_contains_link_to_results(self):
        rule = ScannerQueryRule.objects.create(name='bar', scanner=YARA)
        addon = addon_factory()
        version = addon.current_version
        result = ScannerQueryResult(scanner=YARA, version=version)
        result.add_yara_result(rule=rule.name)
        result.save()
        # Create another version that matches for the same add-on.
        version = version_factory(addon=addon)
        result = ScannerQueryResult(scanner=YARA, version=version)
        result.add_yara_result(rule=rule.name)
        result.save()
        # Create another add-on that has a matching version
        addon = addon_factory()
        result = ScannerQueryResult(scanner=YARA, version=addon.current_version)
        result.add_yara_result(rule=rule.name)
        result.save()
        url = reverse('admin:scanners_scannerqueryrule_change', args=(rule.pk,))
        response = self.client.get(url)
        assert response.status_code == 200
        doc = pq(response.content)
        classes = set(doc('body')[0].attrib['class'].split())
        expected_classes = {
            'app-scanners',
            'model-scannerqueryrule',
            'change-form',
        }
        assert classes == expected_classes
        link = doc('.field-matched_results_link a')
        assert link
        results_list_url = reverse('admin:scanners_scannerqueryresult_changelist')
        expected_href = f'{results_list_url}?matched_rule__id__exact={rule.pk}'
        assert link.attr('href') == expected_href
        assert link.text() == '3 (2 add-ons)'

        link_response = self.client.get(expected_href)
        assert link_response.status_code == 200

    def test_change_view_viewer(self):
        self.user.groupuser_set.all().delete()
        self.grant_permission(self.user, 'Admin:ScannersQueryView')
        rule = ScannerQueryRule.objects.create(name='bar', scanner=YARA)
        url = reverse('admin:scanners_scannerqueryrule_change', args=(rule.pk,))
        response = self.client.get(url)
        assert response.status_code == 200
        doc = pq(response.content)
        classes = set(doc('body')[0].attrib['class'].split())
        expected_classes = {
            'app-scanners',
            'model-scannerqueryrule',
            'change-form',
            'hide-action-buttons',
        }
        assert classes == expected_classes

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
        rule = ScannerQueryRule.objects.create(name='bar', scanner=YARA, state=NEW)
        response = self.client.get(self.list_url)
        assert response.status_code == 200
        doc = pq(response.content)
        field = doc('.field-state_with_actions')
        assert field
        assert field.text() == 'New \xa0 Run'
        url = reverse('admin:scanners_scannerqueryrule_handle_run', args=(rule.pk,))
        button = field.find('button')[0]
        assert button.attrib['formaction'] == url

    def test_abort_button_in_list_view_for_running_rule(self):
        rule = ScannerQueryRule.objects.create(name='bar', scanner=YARA, state=RUNNING)
        response = self.client.get(self.list_url)
        assert response.status_code == 200
        doc = pq(response.content)
        field = doc('.field-state_with_actions')
        assert field
        assert field.text() == 'Running \xa0 Abort'
        url = reverse('admin:scanners_scannerqueryrule_handle_abort', args=(rule.pk,))
        button = field.find('button')[0]
        assert button.attrib['formaction'] == url

    def test_no_button_for_completed_rule_query(self):
        completed = datetime(2020, 9, 29, 14, 1, 2)
        rule = ScannerQueryRule.objects.create(
            name='bar', scanner=YARA, state=COMPLETED, completed=completed
        )
        response = self.client.get(self.list_url)
        assert response.status_code == 200
        doc = pq(response.content)
        field = doc('.field-state_with_actions')
        assert field
        assert field.text() == f'Completed ({localize(completed)})'
        assert not field.find('button')

        rule.update(completed=None)  # If somehow None (unknown finished time)
        response = self.client.get(self.list_url)
        assert response.status_code == 200
        doc = pq(response.content)
        field = doc('.field-state_with_actions')
        assert field
        assert field.text() == 'Completed'
        assert not field.find('button')

    def test_button_in_change_view(self):
        rule = ScannerQueryRule.objects.create(name='bar', scanner=YARA, state=RUNNING)
        change_url = reverse('admin:scanners_scannerqueryrule_change', args=(rule.pk,))
        response = self.client.get(change_url)
        assert response.status_code == 200
        doc = pq(response.content)
        field = doc('.field-state_with_actions')
        assert field
        assert field.text() == 'State:\nRunning \xa0 Abort'
        url = reverse('admin:scanners_scannerqueryrule_handle_abort', args=(rule.pk,))
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
        rule = ScannerQueryRule.objects.create(name='bar', scanner=YARA, state=NEW)
        response = self.client.post(
            reverse(
                'admin:scanners_scannerqueryrule_handle_run',
                args=[rule.pk],
            ),
            follow=True,
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
            file_kw={'filename': 'webextension.xpi'}
        ).current_version
        rule = ScannerQueryRule.objects.create(
            name='always_true',
            scanner=YARA,
            state=NEW,
            definition='rule always_true { condition: true }',
        )
        response = self.client.post(
            reverse(
                'admin:scanners_scannerqueryrule_handle_run',
                args=[rule.pk],
            ),
            follow=True,
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
        rule = ScannerQueryRule.objects.create(name='bar', scanner=YARA, state=ABORTING)
        response = self.client.post(
            reverse(
                'admin:scanners_scannerqueryrule_handle_run',
                args=[rule.pk],
            ),
            follow=True,
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
        user = user_factory(email='somebodyelse@mozilla.com')
        self.grant_permission(user, 'Admin:ScannersQueryView')
        self.client.force_login(user)
        rule = ScannerQueryRule.objects.create(name='bar', scanner=YARA, state=NEW)
        response = self.client.post(
            reverse(
                'admin:scanners_scannerqueryrule_handle_run',
                args=[rule.pk],
            ),
            follow=True,
        )
        assert response.status_code == 404

    def test_abort_action(self):
        rule = ScannerQueryRule.objects.create(name='bar', scanner=YARA, state=RUNNING)
        response = self.client.post(
            reverse(
                'admin:scanners_scannerqueryrule_handle_abort',
                args=[rule.pk],
            ),
            follow=True,
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
            name='bar', scanner=YARA, state=COMPLETED
        )
        response = self.client.post(
            reverse(
                'admin:scanners_scannerqueryrule_handle_abort',
                args=[rule.pk],
            ),
            follow=True,
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
        user = user_factory(email='somebodyelse@mozilla.com')
        self.grant_permission(user, 'Admin:ScannersQueryView')
        self.client.force_login(user)
        rule = ScannerQueryRule.objects.create(name='bar', scanner=YARA, state=RUNNING)
        response = self.client.post(
            reverse(
                'admin:scanners_scannerqueryrule_handle_abort',
                args=[rule.pk],
            ),
            follow=True,
        )
        assert response.status_code == 404

    def test_cannot_change_non_new_query_rule(self):
        rule = ScannerQueryRule.objects.create(name='bar', scanner=YARA)
        url = reverse('admin:scanners_scannerqueryrule_change', args=(rule.pk,))
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

    def test_delete_rule_that_has_results(self):
        rule = ScannerQueryRule.objects.create(name='bar', scanner=YARA)
        result = ScannerQueryResult(scanner=YARA)
        result.add_yara_result(rule=rule.name)
        result.save()

        url = reverse('admin:scanners_scannerqueryrule_delete', args=(rule.pk,))
        response = self.client.get(url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#content h1').text() == 'Are you sure?'

        url = reverse('admin:scanners_scannerqueryrule_delete', args=(rule.pk,))
        response = self.client.post(url, {'post': 'yes'})
        self.assert3xx(response, self.list_url)

        assert not ScannerQueryRule.objects.filter(pk=rule.pk).exists()
        assert not ScannerQueryResult.objects.filter(pk=result.pk).exists()

    def test_cant_delete_rule_if_insufficient_permissions(self):
        rule = ScannerQueryRule.objects.create(name='bar', scanner=YARA)
        result = ScannerQueryResult(scanner=YARA)
        result.add_yara_result(rule=rule.name)
        result.save()

        url = reverse('admin:scanners_scannerqueryrule_delete', args=(rule.pk,))

        user = user_factory(email='somebodyelse@mozilla.com')
        self.client.force_login(user)
        response = self.client.get(url)
        assert response.status_code == 403
        response = self.client.post(url, {'post': 'yes'})
        assert response.status_code == 403

        self.grant_permission(user, 'Admin:ScannersQueryView')
        response = self.client.get(url)
        assert response.status_code == 403
        response = self.client.post(url, {'post': 'yes'})
        assert response.status_code == 403


class TestScannerQueryResultAdmin(TestCase):
    def setUp(self):
        super().setUp()

        self.user = user_factory(email='someone@mozilla.com')
        self.grant_permission(self.user, 'Admin:ScannersQueryEdit')
        self.client.force_login(self.user)
        self.list_url = reverse('admin:scanners_scannerqueryresult_changelist')

        self.admin = ScannerQueryResultAdmin(
            model=ScannerQueryResult, admin_site=AdminSite()
        )

        self.rule = ScannerQueryRule.objects.create(name='myrule', scanner=YARA)

    def scanner_query_result_factory(self, *args, **kwargs):
        kwargs.setdefault('scanner', YARA)
        result = ScannerQueryResult(*args, **kwargs)
        if 'rule' not in kwargs and 'results' not in kwargs:
            result.add_yara_result(rule=self.rule.name)
        result.save()
        return result

    def test_list_view(self):
        addon = addon_factory()
        addon.update(average_daily_users=999)
        addon.authors.add(user_factory(email='foo@bar.com'))
        addon.authors.add(user_factory(email='bar@foo.com'))
        result = self.scanner_query_result_factory(version=addon.current_version)
        response = self.client.get(self.list_url)
        assert response.status_code == 200
        html = pq(response.content)
        assert html('.field-addon_name').length == 1
        assert html('.field-addon_adi').text() == '999'
        authors = html('.field-authors a')
        assert authors.length == 3
        authors_links = list(
            (a.text, a.attrib['href']) for a in html('.field-authors a')
        )
        # Last link should point to the addons model.
        link_to_addons = authors_links.pop()
        result = sorted(authors_links)
        expected = sorted(
            (
                user.email,
                '%s%s'
                % (
                    settings.EXTERNAL_SITE_URL,
                    reverse('admin:users_userprofile_change', args=(user.pk,)),
                ),
            )
            for user in addon.authors.all()
        )
        assert result == expected
        assert 'Other add-ons' in link_to_addons[0]
        expected_querystring = '?authors__in={}'.format(
            ','.join(str(author.pk) for author in addon.authors.all())
        )
        assert expected_querystring in link_to_addons[1]
        download_link = addon.current_version.file.get_absolute_url(attachment=True)
        assert html('.field-download a')[0].attrib['href'] == download_link
        assert '/icon-no.svg' in html('.field-is_file_signed img')[0].attrib['src']

        addon.versions.all()[0].file.update(is_signed=True)
        response = self.client.get(self.list_url)
        html = pq(response.content)
        assert '/icon-yes.svg' in html('.field-is_file_signed img')[0].attrib['src']

    def test_list_view_no_query_permissions(self):
        self.scanner_query_result_factory(version=addon_factory().current_version)

        self.user = user_factory(email='somebodyelse@mozilla.com')
        # Give the user permission to edit ScannersResults, but not
        # ScannerQueryResults.
        self.grant_permission(self.user, 'Admin:ScannersResultsEdit')
        self.client.force_login(self.user)
        response = self.client.get(self.list_url)
        assert response.status_code == 403

    def test_list_view_query_view_permission(self):
        self.user = user_factory(email='somebodyelse@mozilla.com')
        self.grant_permission(self.user, 'Admin:ScannersQueryView')
        self.client.force_login(self.user)
        self.test_list_view()

    def test_list_filters(self):
        rule_foo = ScannerQueryRule.objects.create(name='foo', scanner=YARA)
        rule_bar = ScannerQueryRule.objects.create(
            name='bar', scanner=YARA, pretty_name='A rule walks into a'
        )

        response = self.client.get(self.list_url)
        assert response.status_code == 200
        doc = pq(response.content)
        expected = [
            ('All', '?'),
            ('foo (yara)', f'?matched_rule__id__exact={rule_foo.pk}'),
            ('myrule (yara)', f'?matched_rule__id__exact={self.rule.pk}'),
            ('A rule walks into a (yara)', f'?matched_rule__id__exact={rule_bar.pk}'),
            ('All', '?'),
            ('Unlisted', '?version__channel__exact=1'),
            ('Listed', '?version__channel__exact=2'),
            ('All', '?'),
            ('Incomplete', '?version__addon__status__exact=0'),
            ('Awaiting Review', '?version__addon__status__exact=3'),
            ('Approved', '?version__addon__status__exact=4'),
            ('Disabled by Mozilla', '?version__addon__status__exact=5'),
            ('Deleted', '?version__addon__status__exact=11'),
            ('All', '?'),
            ('Invisible', '?version__addon__disabled_by_user__exact=1'),
            ('Visible', '?version__addon__disabled_by_user__exact=0'),
            ('All', '?'),
            ('Awaiting Review', '?version__file__status__exact=1'),
            ('Approved', '?version__file__status__exact=4'),
            ('Disabled by Mozilla', '?version__file__status__exact=5'),
            ('All', '?'),
            ('Yes', '?version__file__is_signed__exact=1'),
            ('No', '?version__file__is_signed__exact=0'),
            ('All', '?'),
            ('Yes', '?was_blocked__exact=1'),
            ('No', '?was_blocked__exact=0'),
            ('Unknown', '?was_blocked__isnull=True'),
        ]
        filters = [(x.text, x.attrib['href']) for x in doc('#changelist-filter a')]
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

        response = self.client.get(
            self.list_url,
            {
                'matched_rule__id__exact': rule_bar.pk,
            },
        )
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#result_list tbody > tr').length == 1
        assert doc('.field-formatted_matched_rules').text() == 'bar (yara)'

    def test_list_filter_channel(self):
        addon = addon_factory()
        self.scanner_query_result_factory(version=addon.versions.get())
        unlisted_addon = addon_factory(
            version_kw={'channel': amo.CHANNEL_UNLISTED}, status=amo.STATUS_NULL
        )
        self.scanner_query_result_factory(version=unlisted_addon.versions.get())

        response = self.client.get(
            self.list_url,
            {
                'version__channel__exact': amo.CHANNEL_UNLISTED,
            },
        )
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#result_list tbody > tr').length == 1
        assert doc('.field-guid').text() == unlisted_addon.guid

        response = self.client.get(
            self.list_url,
            {
                'version__channel__exact': amo.CHANNEL_LISTED,
            },
        )
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#result_list tbody > tr').length == 1
        assert doc('.field-guid').text() == addon.guid

    def test_list_filter_addon_status(self):
        incomplete_addon = addon_factory(status=amo.STATUS_NULL)
        self.scanner_query_result_factory(version=incomplete_addon.versions.get())
        deleted_addon = addon_factory(status=amo.STATUS_DELETED)
        self.scanner_query_result_factory(version=deleted_addon.versions.get())

        response = self.client.get(
            self.list_url,
            {
                'version__addon__status__exact': amo.STATUS_NULL,
            },
        )
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#result_list tbody > tr').length == 1
        assert doc('.field-guid').text() == incomplete_addon.guid

        response = self.client.get(
            self.list_url,
            {
                'version__addon__status__exact': amo.STATUS_DELETED,
            },
        )
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#result_list tbody > tr').length == 1
        assert doc('.field-guid').text() == deleted_addon.guid

    def test_list_filter_addon_visibility(self):
        visible_addon = addon_factory()
        self.scanner_query_result_factory(version=visible_addon.versions.get())
        invisible_addon = addon_factory(disabled_by_user=True)
        self.scanner_query_result_factory(version=invisible_addon.versions.get())

        response = self.client.get(
            self.list_url,
            {
                'version__addon__disabled_by_user__exact': '1',
            },
        )
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#result_list tbody > tr').length == 1
        assert doc('.field-guid').text() == invisible_addon.guid

        response = self.client.get(
            self.list_url,
            {
                'version__addon__disabled_by_user__exact': '0',
            },
        )
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#result_list tbody > tr').length == 1
        assert doc('.field-guid').text() == visible_addon.guid

    def test_list_filter_file_status(self):
        addon_disabled_file = addon_factory()
        disabled_file_version = version_factory(
            addon=addon_disabled_file, file_kw={'status': amo.STATUS_DISABLED}
        )
        self.scanner_query_result_factory(version=disabled_file_version)
        addon_approved_file = addon_factory()
        self.scanner_query_result_factory(version=addon_approved_file.versions.get())

        response = self.client.get(
            self.list_url,
            {
                'version__file__status': '5',
            },
        )
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#result_list tbody > tr').length == 1
        assert doc('.field-guid').text() == addon_disabled_file.guid

        response = self.client.get(
            self.list_url,
            {
                'version__file__status': '4',
            },
        )
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#result_list tbody > tr').length == 1
        assert doc('.field-guid').text() == addon_approved_file.guid

    def test_list_filter_file_is_signed(self):
        signed_addon = addon_factory(file_kw={'is_signed': True})
        self.scanner_query_result_factory(version=signed_addon.versions.get())
        unsigned_addon = addon_factory(file_kw={'is_signed': False})
        self.scanner_query_result_factory(version=unsigned_addon.versions.get())

        response = self.client.get(
            self.list_url,
            {
                'version__file__is_signed': '1',
            },
        )
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#result_list tbody > tr').length == 1
        assert doc('.field-guid').text() == signed_addon.guid

        response = self.client.get(
            self.list_url,
            {
                'version__file__is_signed': '0',
            },
        )
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#result_list tbody > tr').length == 1
        assert doc('.field-guid').text() == unsigned_addon.guid

    def test_list_filter_was_blocked(self):
        was_blocked_addon = addon_factory()
        self.scanner_query_result_factory(
            version=was_blocked_addon.versions.get(), was_blocked=True
        )
        was_blocked_unknown_addon = addon_factory()
        self.scanner_query_result_factory(
            version=was_blocked_unknown_addon.versions.get(), was_blocked=None
        )
        was_blocked_false_addon = addon_factory()
        self.scanner_query_result_factory(
            version=was_blocked_false_addon.versions.get(), was_blocked=False
        )

        response = self.client.get(
            self.list_url,
            {
                'was_blocked__exact': '1',
            },
        )
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#result_list tbody > tr').length == 1
        assert doc('.field-guid').text() == was_blocked_addon.guid

        response = self.client.get(
            self.list_url,
            {
                'was_blocked__exact': '0',
            },
        )
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#result_list tbody > tr').length == 1
        assert doc('.field-guid').text() == was_blocked_false_addon.guid

        response = self.client.get(
            self.list_url,
            {
                'was_blocked__isnull': 'True',
            },
        )
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#result_list tbody > tr').length == 1
        assert doc('.field-guid').text() == was_blocked_unknown_addon.guid

    def test_change_page(self):
        result = self.scanner_query_result_factory(
            version=addon_factory().current_version
        )
        url = reverse('admin:scanners_scannerqueryresult_change', args=(result.pk,))
        response = self.client.get(url)
        assert response.status_code == 200

        rule_url = reverse(
            'admin:scanners_scannerqueryrule_change', args=(self.rule.pk,)
        )
        doc = pq(response.content)
        link = doc('.field-formatted_matched_rules_with_files_and_data td a')
        assert link.text() == 'myrule ???'
        assert link.attr('href') == rule_url

        link_response = self.client.get(rule_url)
        assert link_response.status_code == 200

    def test_change_view_no_query_permissions(self):
        self.user = user_factory(email='somebodyelse@mozilla.com')
        # Give the user permission to edit ScannersResults, but not
        # ScannerQueryResults.
        self.grant_permission(self.user, 'Admin:ScannersResultsEdit')
        self.client.force_login(self.user)
        result = self.scanner_query_result_factory(
            version=addon_factory().current_version
        )
        url = reverse('admin:scanners_scannerqueryresult_change', args=(result.pk,))
        response = self.client.get(url)
        assert response.status_code == 403

    def test_change_view_query_view_permission(self):
        self.user = user_factory(email='somebodyelse@mozilla.com')
        self.grant_permission(self.user, 'Admin:ScannersQueryView')
        self.client.force_login(self.user)
        self.test_change_page()

    def test_formatted_matched_rules_with_files(self):
        version = addon_factory().current_version
        result = ScannerQueryResult(scanner=YARA, version=version)
        rule = ScannerQueryRule.objects.create(name='bar', scanner=YARA)
        filename = 'some/file.js'
        result.add_yara_result(rule=rule.name, meta={'filename': filename})
        result.save()

        rule_url = reverse('admin:scanners_scannerqueryrule_change', args=(rule.pk,))

        file_id = version.file.id
        assert file_id is not None
        expect_file_item = code_manager_url(
            'browse', version.addon.pk, version.pk, file=filename
        )
        content = formatted_matched_rules_with_files_and_data(result)
        assert expect_file_item in content
        assert rule_url in content

    def test_matching_filenames_in_changelist(self):
        rule = ScannerQueryRule.objects.create(
            name='foo', scanner=YARA, created=self.days_ago(2)
        )
        result1 = ScannerQueryResult(
            scanner=YARA, version=addon_factory().current_version
        )
        result1.add_yara_result(
            rule=rule.name, meta={'filename': 'some/file/somewhere.js'}
        )
        result1.add_yara_result(
            rule=rule.name, meta={'filename': 'another/file/somewhereelse.js'}
        )
        result1.save()
        result2 = ScannerQueryResult(
            scanner=YARA,
            version=addon_factory().current_version,
            created=self.days_ago(1),
        )
        result2.add_yara_result(
            rule=rule.name, meta={'filename': 'a/file/from/another_addon.js'}
        )
        result2.save()
        response = self.client.get(self.list_url)
        assert response.status_code == 200
        doc = pq(response.content)
        links = doc('.field-matching_filenames a')
        assert len(links) == 3
        expected = [
            code_manager_url(
                'browse',
                result1.version.addon.pk,
                result1.version.pk,
                file='some/file/somewhere.js',
            ),
            code_manager_url(
                'browse',
                result1.version.addon.pk,
                result1.version.pk,
                file='another/file/somewhereelse.js',
            ),
            code_manager_url(
                'browse',
                result2.version.addon.pk,
                result2.version.pk,
                file='a/file/from/another_addon.js',
            ),
        ]
        assert [link.attrib['href'] for link in links] == expected


class FormattedMatchedRulesWithFilesAndData(TestCase):
    def test_display_data(self):
        rule = ScannerRule.objects.create(name='bar', scanner=CUSTOMS)
        data = {
            'scanMap': {
                '__GLOBAL__': {
                    rule.name: {
                        'RULE_HAS_MATCHED': True,
                        'BLAH': [
                            {'ratio': 0.566346, 'thisisfun': ['a', 'b']},
                            {'extensionId': '@flop', 'xaxaxa': False},
                        ],
                    }
                }
            },
            'matchedRules': [rule.name],
        }
        result = ScannerResult.objects.create(pk=42, scanner=CUSTOMS, results=data)
        content = formatted_matched_rules_with_files_and_data(result)
        doc = pq(content)
        assert len(doc('td > ul > li')) == 1
        assert doc('td > ul > li').eq(0).text() == ''

        content = formatted_matched_rules_with_files_and_data(result, display_data=True)
        doc = pq(content)
        assert len(doc('td > ul > li')) == 2
        assert doc('td > ul > li').eq(0).text() == ''
        li = doc('td > ul > li').eq(1)
        assert li.attr('class') == 'extra_data'
        assert li.html().strip() == format_scanners_data(
            result.get_files_and_data_by_matched_rules()[rule.name][0]['data']
        )

    def test_display_scanner(self):
        result = ScannerResult(pk=42, scanner=YARA)
        content = formatted_matched_rules_with_files_and_data(result)
        doc = pq(content)
        assert not doc('caption')

        content = formatted_matched_rules_with_files_and_data(
            result, display_scanner=True
        )
        doc = pq(content)
        assert doc('caption').text() == 'yara'
        assert doc('caption a')[0].attrib['href'] == (
            '/en-US/admin/models/scanners/scannerresult/42/change/'
        )

    def test_limit_to(self):
        result = ScannerResult.objects.create(pk=42, scanner=YARA)
        rule = ScannerRule.objects.create(name='bar', scanner=YARA)
        for i in range(0, 5):
            result.add_yara_result(
                rule=rule.name, meta={'filename': f'somefilename{i}'}
            )
        result.save()
        content = formatted_matched_rules_with_files_and_data(result)
        doc = pq(content)
        assert len(doc('li')) == 5
        assert doc('li')[1].text.strip() == 'somefilename1'

        content = formatted_matched_rules_with_files_and_data(result, limit_to=2)
        doc = pq(content)
        assert len(doc('li')) == 3  # 2 + 1 for the "…and and more 3 files"
        assert doc('li')[1].text.strip() == 'somefilename1'
        assert doc('li')[2].text == '…and 3 more files'
