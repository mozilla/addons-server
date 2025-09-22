import uuid
from datetime import date, datetime
from unittest import mock
from urllib.parse import parse_qsl, urlparse

from django.conf import settings
from django.urls import reverse

from pyquery import PyQuery as pq

from olympia import amo
from olympia.abuse.models import AbuseReport, CinderPolicy
from olympia.addons.models import AddonApprovalsCounter
from olympia.amo.tests import (
    TestCase,
    addon_factory,
    collection_factory,
    days_ago,
    grant_permission,
    user_factory,
)
from olympia.ratings.models import Rating
from olympia.reviewers.models import AutoApprovalSummary, ReviewActionReason
from olympia.versions.models import VersionPreview


class TestAbuseReportAdmin(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.addon1 = addon_factory(guid='@guid1', name='Neo')
        cls.addon1.name.__class__.objects.create(
            id=cls.addon1.name_id, locale='fr', localized_string='Elu'
        )
        cls.addon2 = addon_factory(guid='@guid2', name='Owt')
        cls.addon3 = addon_factory(guid='@guid3', name='Eerht')
        cls.user = user_factory(email='someone@mozilla.com')
        grant_permission(cls.user, 'AbuseReports:Edit', 'Abuse Report Triage')
        # Create a few abuse reports.
        cls.report1 = AbuseReport.objects.create(
            addon_name='The One',
            guid=cls.addon1.guid,
            message='Foo',
            created=days_ago(98),
        )
        AbuseReport.objects.create(
            addon_name='The Two',
            guid=cls.addon2.guid,
            message='Bar',
        )
        AbuseReport.objects.create(
            addon_name='The Three',
            guid=cls.addon3.guid,
            message='Soap',
            reason=AbuseReport.REASONS.OTHER,
            created=days_ago(100),
        )
        AbuseReport.objects.create(
            addon_name='The One',
            guid=cls.addon1.guid,
            message='With Addon',
            reporter=user_factory(),
        )
        AbuseReport.objects.create(
            guid=cls.addon1.guid, message='', reporter=user_factory()
        )
        # This is a report for an addon not in the database.
        cls.report2 = AbuseReport.objects.create(
            guid='@unknown_guid', addon_name='Mysterious Addon', message='Doo'
        )
        # This is one against a user.
        cls.report_user = AbuseReport.objects.create(
            user=user_factory(username='malicious_user'), message='Ehehehehe'
        )
        # This is one against a collection.
        cls.report_collection = AbuseReport.objects.create(
            collection=collection_factory(), message='Bad collection!'
        )
        # This is one against a rating.
        cls.report_rating = AbuseReport.objects.create(
            rating=Rating.objects.create(
                addon=cls.addon1, body='ugh!', user=user_factory()
            ),
            message='Bad rating!',
        )

    def setUp(self):
        self.client.force_login(self.user)
        self.list_url = reverse('admin:abuse_abusereport_changelist')

    def test_list_no_permission(self):
        user = user_factory(email='nobody@mozilla.com')
        self.client.force_login(user)
        response = self.client.get(self.list_url)
        assert response.status_code == 403

    def test_list(self):
        with self.assertNumQueries(8):
            # - 2 queries to get the user and their permissions
            # - 1 query for a count of the total number of items
            #     (show_full_result_count=False so we avoid the duplicate)
            # - 2 savepoints
            # - 1 to get the abuse reports
            # - 2 for the date hierarchy
            response = self.client.get(self.list_url, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        expected_length = AbuseReport.objects.count()
        assert doc('#result_list tbody tr').length == expected_length

    def test_list_filter_by_type(self):
        response = self.client.get(self.list_url, {'type': 'addon'}, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#result_list tbody tr').length == 6
        assert 'Ehehehehe' not in doc('#result_list').text()

        response = self.client.get(self.list_url, {'type': 'user'}, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#result_list tbody tr').length == 1
        assert 'Ehehehehe' in doc('#result_list').text()

        # Type filter should be selected. The rest shouldn't.
        lis = doc('#changelist-filter li.selected')
        assert len(lis) == 4
        assert lis.text().split() == ['Users', 'All', 'All', 'All']

        response = self.client.get(self.list_url, {'type': 'collection'}, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#result_list tbody tr').length == 1
        assert 'Ehehehehe' not in doc('#result_list').text()
        assert 'Bad collection!' in doc('#result_list').text()

        response = self.client.get(self.list_url, {'type': 'rating'}, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#result_list tbody tr').length == 1
        assert 'Ehehehehe' not in doc('#result_list').text()
        assert 'Bad rating!' in doc('#result_list').text()

    def test_search_deactivated_if_not_filtering_by_type(self):
        response = self.client.get(self.list_url, {'q': 'Mysterious'}, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        assert not doc('#changelist-search')
        assert doc('#result_list tbody tr').length == AbuseReport.objects.count()

    def test_search_user(self):
        response = self.client.get(
            self.list_url, {'q': 'Ehe', 'type': 'user'}, follow=True
        )
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#changelist-search')
        assert doc('#result_list tbody tr').length == 1
        assert 'Eheheheh' in doc('#result_list').text()

        user = AbuseReport.objects.get(message='Ehehehehe').user
        response = self.client.get(
            self.list_url, {'q': f'{user.email[:3]}*', 'type': 'user'}, follow=True
        )
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#changelist-search')
        assert doc('#result_list tbody tr').length == 1
        assert 'Ehehehehe' in doc('#result_list').text()

        response = self.client.get(
            self.list_url, {'q': str(user.pk), 'type': 'user'}, follow=True
        )
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#changelist-search')
        assert doc('#result_list tbody tr').length == 1
        assert 'Ehehehehe' in doc('#result_list').text()

        response = self.client.get(
            self.list_url, {'q': 'NotGoingToFindAnything', 'type': 'user'}, follow=True
        )
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#changelist-search')
        assert doc('#result_list tbody tr').length == 0
        assert 'Ehehehehe' not in doc('#result_list').text()

    def test_search_collection(self):
        response = self.client.get(
            self.list_url, {'q': 'Bad', 'type': 'collection'}, follow=True
        )
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#changelist-search')
        assert doc('#result_list tbody tr').length == 1
        assert 'Bad collection!' in doc('#result_list').text()

        collection = AbuseReport.objects.get(message='Bad collection!').collection
        response = self.client.get(
            self.list_url, {'q': collection.slug, 'type': 'collection'}, follow=True
        )
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#changelist-search')
        assert doc('#result_list tbody tr').length == 1
        assert 'Bad collection!' in doc('#result_list').text()

        response = self.client.get(
            self.list_url, {'q': 'dfddfdf', 'type': 'collection'}, follow=True
        )
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#changelist-search')
        assert doc('#result_list tbody tr').length == 0
        assert 'Bad collection!' not in doc('#result_list').text()

    def test_search_rating(self):
        response = self.client.get(
            self.list_url, {'q': 'Bad', 'type': 'rating'}, follow=True
        )
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#changelist-search')
        assert doc('#result_list tbody tr').length == 1
        assert 'Bad rating!' in doc('#result_list').text()

        rating = AbuseReport.objects.get(message='Bad rating!').rating
        response = self.client.get(
            self.list_url, {'q': f'{rating.body[:3]}*', 'type': 'rating'}, follow=True
        )
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#changelist-search')
        assert doc('#result_list tbody tr').length == 1
        assert 'Bad rating!' in doc('#result_list').text()

        response = self.client.get(
            self.list_url, {'q': rating.id, 'type': 'rating'}, follow=True
        )
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#changelist-search')
        assert doc('#result_list tbody tr').length == 1
        assert 'Bad rating!' in doc('#result_list').text()

        response = self.client.get(
            self.list_url, {'q': 'dfddfdf', 'type': 'rating'}, follow=True
        )
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#changelist-search')
        assert doc('#result_list tbody tr').length == 0
        assert 'Bad rating!' not in doc('#result_list').text()

    def test_search_addon(self):
        response = self.client.get(
            self.list_url, {'q': 'sterious', 'type': 'addon'}, follow=True
        )
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#changelist-search')
        assert doc('#result_list tbody tr').length == 1
        assert 'Mysterious' in doc('#result_list').text()

        response = self.client.get(
            self.list_url, {'q': str(self.addon1.guid), 'type': 'addon'}, follow=True
        )
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#changelist-search')
        assert doc('#result_list tbody tr').length == 3
        # We're not loading names from the database (no FK to addon anymore).
        assert 'Neo' not in doc('#result_list').text()
        # We're displaying the submitted addon name instead.
        assert 'The One' in doc('#result_list').text()

        response = self.client.get(
            self.list_url, {'q': 'NotGoingToFindAnything', 'type': 'addon'}, follow=True
        )
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#changelist-search')
        assert doc('#result_list tbody tr').length == 0
        assert 'The One' not in doc('#result_list').text()
        assert 'Néo' not in doc('#result_list').text()
        assert 'Mysterious' not in doc('#result_list').text()

    def test_search_multiple_addons(self):
        response = self.client.get(
            self.list_url,
            {'q': f'{self.addon1.guid},{self.addon2.guid}', 'type': 'addon'},
            follow=True,
        )
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#changelist-search')
        assert doc('#result_list tbody tr').length == 4
        assert 'The One' in doc('#result_list').text()
        assert 'The Two' in doc('#result_list').text()

    def test_search_multiple_users(self):
        user1 = AbuseReport.objects.get(message='Ehehehehe').user
        user2 = user_factory(username='second_user')
        AbuseReport.objects.create(user=user2, message='One more')

        response = self.client.get(
            self.list_url,
            {'q': f'{user1.pk},{user2.pk}', 'type': 'user'},
            follow=True,
        )
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#changelist-search')
        assert doc('#result_list tbody tr').length == 2

    def test_filter_by_reason(self):
        response = self.client.get(
            self.list_url, {'reason__exact': AbuseReport.REASONS.OTHER}, follow=True
        )
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#result_list tbody tr').length == 1
        assert 'Soap' in doc('#result_list').text()

        # Reason filter should be selected. The rest shouldn't.
        lis = doc('#changelist-filter li.selected')
        assert len(lis) == 4
        assert lis.text().split() == ['All', 'Other', 'All', 'All']

    def test_filter_by_created(self):
        some_time_ago = self.days_ago(97).date()
        even_more_time_ago = self.days_ago(99).date()

        data = {
            'created__range__gte': even_more_time_ago.isoformat(),
            'created__range__lte': some_time_ago.isoformat(),
        }
        response = self.client.get(self.list_url, data, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#result_list tbody tr').length == 1
        result_list_text = doc('#result_list').text()
        assert 'Soap' not in result_list_text
        assert 'Foo' in result_list_text

        # Created filter should be selected. The rest shouldn't.
        lis = doc('#changelist-filter li.selected')
        # We've got 4 filters, so usually we'd get 5 selected list items
        # (because of the "All" default choice) but since 'created' is actually
        # 2 fields, and we have submitted both, we now have 5 expected items.
        assert len(lis) == 5
        assert lis.text().split() == ['All', 'All', 'From:', 'To:', 'All']
        elm = lis.eq(2).find('#id_created__range__gte')
        assert elm
        assert elm.attr('name') == 'created__range__gte'
        assert elm.attr('value') == even_more_time_ago.isoformat()
        elm = lis.eq(3).find('#id_created__range__lte')
        assert elm
        assert elm.attr('name') == 'created__range__lte'
        assert elm.attr('value') == some_time_ago.isoformat()

    def test_filter_by_created_only_from(self):
        not_long_ago = self.days_ago(2).date()
        data = {
            'created__range__gte': not_long_ago.isoformat(),
        }
        response = self.client.get(self.list_url, data, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#result_list tbody tr').length == 7
        result_list_text = doc('#result_list').text()
        assert 'Soap' not in result_list_text
        assert 'Foo' not in result_list_text

        # Created filter should be selected. The rest shouldn't.
        lis = doc('#changelist-filter li.selected')
        # We've got 4 filters.
        assert len(lis) == 4
        assert lis.text().split() == ['All', 'All', 'From:', 'All']
        elm = lis.eq(2).find('#id_created__range__gte')
        assert elm
        assert elm.attr('name') == 'created__range__gte'
        assert elm.attr('value') == not_long_ago.isoformat()

    def test_filter_by_created_only_to(self):
        some_time_ago = self.days_ago(97).date()
        data = {
            'created__range__lte': some_time_ago.isoformat(),
        }
        response = self.client.get(self.list_url, data, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#result_list tbody tr').length == 2
        result_list_text = doc('#result_list').text()
        assert 'Soap' in result_list_text
        assert 'Foo' in result_list_text

        # Created filter should be selected. The rest shouldn't.
        lis = doc('#changelist-filter li.selected')
        # We've got 4 filters.
        assert len(lis) == 4
        assert lis.text().split() == ['All', 'All', 'To:', 'All']
        elm = lis.eq(2).find('#id_created__range__lte')
        assert elm
        assert elm.attr('name') == 'created__range__lte'
        assert elm.attr('value') == some_time_ago.isoformat()

    def test_filter_by_minimum_reports_count_for_guid(self):
        data = {'minimum_reports_count': '2'}
        response = self.client.get(self.list_url, data, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#result_list tbody tr').length == 3
        result_list_text = doc('#result_list').text()
        assert 'Soap' not in result_list_text
        assert 'Foo' in result_list_text

        # Minimum reports count filter should be selected. The rest shouldn't.
        lis = doc('#changelist-filter li.selected')
        # We've got 4 filters.
        assert len(lis) == 4
        # There is no label for minimum reports count, so despite having 4 lis
        # we only have 3 things in .text().
        assert lis.text().split() == ['All', 'All', 'All']
        # The 4th item should contain the input though.
        elm = lis.eq(3).find('#id_minimum_reports_count')
        assert elm
        assert elm.attr('name') == 'minimum_reports_count'
        assert elm.attr('value') == '2'

    def test_combine_complex_filters_and_search(self):
        today = date.today()
        data = {
            'reason__exact': str(AbuseReport.REASONS.OTHER),
            'type': 'addon',
            'q': 'Soap',
            'created__range__gte': self.days_ago(100).date().isoformat(),
            'created__range__lte': self.days_ago(97).date().isoformat(),
            'modified__day': str(today.day),
            'modified__month': str(today.month),
            'modified__year': str(today.year),
        }
        response = self.client.get(self.list_url, data, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#result_list tbody tr').length == 1

        # Also, the forms we used for the 'created' filters should contain all
        # active filters and search query so that we can combine them.
        forms = doc('#changelist-filter form')
        inputs = [
            (elm.name, elm.value)
            for elm in forms.find('input')
            if elm.name and elm.value != ''
        ]
        assert set(inputs) == set(data.items())

        # Same for the 'search' form
        form = doc('#changelist-filter form')
        inputs = [
            (elm.name, elm.value)
            for elm in form.find('input')
            if elm.name and elm.value != ''
        ]
        assert set(inputs) == set(data.items())

        # Gather selected filters.
        lis = doc('#changelist-filter li.selected')

        # We've got 4 filters, so usually we'd get 4 selected list items
        # (because of the "All" default choice) but since 'created' is actually
        # 2 fields, and we have submitted both, we now have 5 expected items.
        assert len(lis) == 5
        assert lis.text().split() == ['Add-ons', 'Other', 'From:', 'To:', 'All']
        assert lis.eq(2).find('#id_created__range__gte')
        assert lis.eq(3).find('#id_created__range__lte')

        # The links used for 'normal' filtering should also contain all active
        # filters even our custom fancy ones. We just look at the selected
        # filters to keep things simple (they should have all parameters in
        # data with the same value just like the forms).
        links = doc('#changelist-filter li.selected a')
        for elm in links:
            parsed_href_query = parse_qsl(urlparse(elm.attrib['href']).query)
            assert set(parsed_href_query) == set(data.items())

    def test_detail_addon_report(self):
        AddonApprovalsCounter.objects.create(
            addon=self.addon1, last_human_review=datetime.now()
        )
        Rating.objects.create(
            addon=self.addon1, rating=2.0, body='Badd-on', user=user_factory()
        )
        AutoApprovalSummary.objects.create(
            version=self.addon1.current_version, verdict=amo.AUTO_APPROVED
        )
        self.detail_url = reverse(
            'admin:abuse_abusereport_change', args=(self.report1.pk,)
        )
        response = self.client.get(self.detail_url, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        # Full add-on card
        assert doc('.addon-info-and-previews')
        assert 'Neo' in doc('.addon-info-and-previews h2').text()
        assert doc('.addon-info-and-previews .meta-abuse td').text() == '2'
        assert doc('.addon-info-and-previews .meta-rating td').text() == (
            'Rated 2 out of 5 stars 1 review(s)'
        )
        assert doc('.addon-info-and-previews .last-approval-date td').text()
        assert doc('.reports-and-ratings')
        assert doc('.reports-and-ratings h3').eq(0).text() == ('Abuse Reports (2)')
        assert doc('.reports-and-ratings h3').eq(1).text() == ('Bad User Ratings (1)')
        # 'addon-info-and-previews' and 'reports-and-ratings' are coming from a
        # reviewer tools template and shouldn't contain any admin-specific
        # links. It also means that all links in it should be external, in
        # order to work when the admin is on a separate admin-only domain.
        assert len(doc('.addon-info-and-previews a[href]'))
        for link in doc('.addon-info-and-previews a[href]'):
            assert link.attrib['href'].startswith(settings.EXTERNAL_SITE_URL)
        assert len(doc('.reports-and-ratings a[href]'))
        for link in doc('.reports-and-ratings a[href]'):
            assert link.attrib['href'].startswith(settings.EXTERNAL_SITE_URL)
        return response

    def test_detail_static_theme_report(self):
        self.addon1.update(type=amo.ADDON_STATICTHEME)
        VersionPreview.objects.create(version=self.addon1.current_version)
        response = self.test_detail_addon_report()
        doc = pq(response.content)
        assert doc('#addon-theme-previews-wrapper img')

    def test_detail_guid_report(self):
        self.detail_url = reverse(
            'admin:abuse_abusereport_change', args=(self.report2.pk,)
        )
        response = self.client.get(self.detail_url, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        assert not doc('.addon-info-and-previews')
        assert doc('.field-addon_name')
        assert 'Mysterious' in doc('.field-addon_name').text()

    def test_detail_user_report(self):
        self.detail_url = reverse(
            'admin:abuse_abusereport_change', args=(self.report_user.pk,)
        )
        response = self.client.get(self.detail_url, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        assert not doc('.addon-info-and-previews')
        assert not doc('.field-addon_name')
        assert 'malicious_user' in doc('.field-user').text()

    def test_detail_collection_report(self):
        self.detail_url = reverse(
            'admin:abuse_abusereport_change', args=(self.report_collection.pk,)
        )
        response = self.client.get(self.detail_url, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        assert not doc('.addon-info-and-previews')
        assert not doc('.field-addon_name')
        assert (
            str(self.report_collection.collection.name)
            in doc('.field-collection').text()
        )

    def test_detail_rating_report(self):
        self.detail_url = reverse(
            'admin:abuse_abusereport_change', args=(self.report_rating.pk,)
        )
        response = self.client.get(self.detail_url, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        assert not doc('.addon-info-and-previews')
        assert not doc('.field-addon_name')
        assert self.report_rating.rating.body in doc('.field-rating').text()


class TestCinderPolicyAdmin(TestCase):
    def setUp(self):
        self.list_url = reverse('admin:abuse_cinderpolicy_changelist')
        self.sync_cinder_policies_url = reverse('admin:abuse_sync_cinder_policies')

    def login(self, permission='*:*'):
        self.user = user_factory(email='someone@mozilla.com')
        if permission:
            grant_permission(self.user, permission, 'Group')
        self.client.force_login(self.user)

    def _make_list_request(self):
        foo = CinderPolicy.objects.create(name='Foo')
        CinderPolicy.objects.create(name='Bar', parent=foo, uuid=uuid.uuid4())
        zab = CinderPolicy.objects.create(name='Zab', parent=foo, uuid=uuid.uuid4())
        lorem = CinderPolicy.objects.create(name='Lorem', uuid=uuid.uuid4())
        CinderPolicy.objects.create(name='Ipsum', uuid=uuid.uuid4())
        ReviewActionReason.objects.create(
            name='Attached to Zab', cinder_policy=zab, canned_response='.'
        )
        ReviewActionReason.objects.create(
            name='Attached to Lorem', cinder_policy=lorem, canned_response='.'
        )
        ReviewActionReason.objects.create(
            name='Also attached to Lorem', cinder_policy=lorem, canned_response='.'
        )

        with self.assertNumQueries(7):
            # - 2 savepoints (tests)
            # - 2 current user & groups
            # - 1 count cinder policies
            # - 1 cinder policies
            # - 1 review action reasons
            response = self.client.get(self.list_url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert len(doc('#result_list tbody tr')) == CinderPolicy.objects.count()
        assert doc('#result_list td.field-name').text() == 'Foo Ipsum Lorem Bar Zab'
        assert (
            doc('#result_list td.field-linked_review_reasons')[2].text_content()
            == 'Also attached to Lorem\nAttached to Lorem'
        )
        assert doc('#abuse_sync_cinder_policies')
        assert doc('#abuse_sync_cinder_policies')[0].attrib == {
            'formaction': self.sync_cinder_policies_url,
            'formmethod': 'post',
            'type': 'submit',
            'id': 'abuse_sync_cinder_policies',
            'value': 'Sync from Cinder',
        }

    def test_list_no_permission(self):
        self.login(permission=None)
        response = self.client.get(self.list_url)
        assert response.status_code == 403

    def test_list(self):
        self.login()
        self._make_list_request()

    def test_list_with_view_permission(self):
        self.login(permission='CinderPolicies:View')
        self._make_list_request()  # should be the same as with full permissions

    def test_list_order_by_reviewreason(self):
        foo = CinderPolicy.objects.create(name='Foo')
        CinderPolicy.objects.create(name='Bar', parent=foo, uuid=uuid.uuid4())
        zab = CinderPolicy.objects.create(name='Zab', parent=foo, uuid=uuid.uuid4())
        lorem = CinderPolicy.objects.create(name='Lorem', uuid=uuid.uuid4())
        CinderPolicy.objects.create(name='Ipsum', uuid=uuid.uuid4())
        ReviewActionReason.objects.create(
            name='Attached to Zab', cinder_policy=zab, canned_response='.'
        )
        ReviewActionReason.objects.create(
            name='Attached to Lorem', cinder_policy=lorem, canned_response='.'
        )

        self.login()
        with self.assertNumQueries(7):
            # - 2 savepoints (tests)
            # - 2 current user & groups
            # - 1 count cinder policies
            # - 1 cinder policies
            # - 1 review action reasons
            # Linked reason is the 3rd field, so we have to pass o=3 parameter
            # to order on it.
            response = self.client.get(self.list_url, {'o': '3'})
        assert response.status_code == 200
        doc = pq(response.content)
        assert len(doc('#result_list tbody tr')) == CinderPolicy.objects.count()
        assert doc('#result_list td.field-name').text() == 'Foo Ipsum Bar Lorem Zab'
        assert (
            doc('#result_list td.field-linked_review_reasons')[4].text_content()
            == 'Attached to Zab'
        )

    def _make_edit_request(self, expected_status_code):
        policy = CinderPolicy.objects.create(
            name='Bar', uuid=uuid.uuid4(), expose_in_reviewer_tools=False
        )
        detail_url = reverse('admin:abuse_cinderpolicy_change', args=(policy.id,))
        response = self.client.post(
            detail_url, {'expose_in_reviewer_tools': True}, follow=True
        )
        assert response.status_code == expected_status_code
        return policy

    def test_edit_policies(self):
        self.login()
        policy = self._make_edit_request(200)
        assert policy.reload().expose_in_reviewer_tools is True

    def test_edit_policies_cannot_with_no_permission(self):
        self.login(permission=None)
        policy = self._make_edit_request(403)
        assert policy.reload().expose_in_reviewer_tools is False

    def test_edit_policies_cannot_with_view_permission(self):
        self.login(permission='CinderPolicies:View')
        policy = self._make_edit_request(403)
        assert policy.reload().expose_in_reviewer_tools is False

    def test_sync_policies_no_permission(self):
        self.login(permission=None)
        response = self.client.post(self.sync_cinder_policies_url)
        assert response.status_code == 403

    def test_sync_policies_wrong_method(self):
        self.login()
        response = self.client.get(self.sync_cinder_policies_url)
        assert response.status_code == 405

    @mock.patch('olympia.abuse.admin.sync_cinder_policies.delay')
    def _make_sync_policies_request(self, sync_cinder_policies_mock):
        response = self.client.post(self.sync_cinder_policies_url, follow=True)
        assert response.status_code == 200
        assert response.redirect_chain[-1][0].endswith(self.list_url)
        assert response.redirect_chain[-1][1] == 302
        assert sync_cinder_policies_mock.call_count == 1

    def test_sync_policies(self):
        self.login()
        self._make_sync_policies_request()

    def test_sync_policies_with_view_permission(self):
        self.login(permission='CinderPolicies:View')
        self._make_sync_policies_request()
