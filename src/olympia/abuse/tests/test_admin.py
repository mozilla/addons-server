# -*- coding: utf-8 -*-
from datetime import date

from django.contrib import admin
from django.contrib.messages.storage import (
    default_storage as default_messages_storage)

from django.test import RequestFactory
from django.urls import reverse

from pyquery import PyQuery as pq
from six.moves.urllib_parse import parse_qsl, urlparse

from olympia.abuse.admin import AbuseReportAdmin
from olympia.abuse.models import AbuseReport
from olympia.amo.tests import (
    addon_factory, days_ago, grant_permission, TestCase, user_factory
)


class TestAbuse(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.addon1 = addon_factory(guid='@guid1')
        cls.addon2 = addon_factory(guid='@guid2')
        cls.addon3 = addon_factory(guid='@guid3')
        cls.user = user_factory()
        grant_permission(cls.user, 'Admin:Tools', 'Admin Group')
        grant_permission(cls.user, 'AbuseReports:Edit', 'Abuse Report Triage')
        # Create a few abuse reports.
        AbuseReport.objects.create(
            addon=cls.addon1, guid='@guid1', message='Foo',
            state=AbuseReport.STATES.VALID,
            created=days_ago(98))
        AbuseReport.objects.create(
            addon=cls.addon2, guid='@guid2', message='Bar',
            state=AbuseReport.STATES.VALID)
        AbuseReport.objects.create(
            addon=cls.addon3, guid='@guid3', message='Soap',
            reason=AbuseReport.REASONS.OTHER,
            created=days_ago(100))
        AbuseReport.objects.create(
            addon=cls.addon1, guid='@guid1', message='',
            reporter=user_factory())
        # This is a report for an addon not in the database.
        AbuseReport.objects.create(
            guid='@unknown_guid', addon_name='Mysterious Addon', message='Doo')
        # This is one against a user.
        AbuseReport.objects.create(
            user=user_factory(), message='Eheheheh')

    def setUp(self):
        self.client.login(email=self.user.email)
        self.list_url = reverse('admin:abuse_abusereport_changelist')

    def test_list_no_permission(self):
        user_without_abusereports_edit = user_factory()
        grant_permission(
            user_without_abusereports_edit, 'Admin:Tools', 'Admin Group')
        self.client.login(email=user_without_abusereports_edit.email)
        response = self.client.get(self.list_url)
        assert response.status_code == 403

    def test_list(self):
        with self.assertNumQueries(11):
            # - 2 queries to get the user and their permissions
            # - 2 queries for a count of the total number of items
            #   (duplicated by django itself)
            # - 2 savepoints
            # - 1 to get the abuse reports
            # - 2 to get all add-ons displayed and their translations
            #   (regardless of how many there are, thanks to prefetch_related)
            # - 2 for the date hierarchy
            response = self.client.get(self.list_url, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        expected_length = AbuseReport.objects.count()
        assert doc('#result_list tbody tr').length == expected_length

    def test_search(self):
        response = self.client.get(
            self.list_url, {'q': 'Mysterious'}, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        assert '@unknown_guid' in doc('#result_list').text()

    def test_list_filter_by_type(self):
        response = self.client.get(
            self.list_url, {'type': 'addon'}, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#result_list tbody tr').length == 5
        assert 'Eheheheh' not in doc('#result_list').text()

        response = self.client.get(
            self.list_url, {'type': 'user'}, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#result_list tbody tr').length == 1
        'Eheheheh' in doc('#result_list').text()

        # Type filter should be selected. The rest shouldn't.
        lis = doc('#changelist-filter li.selected')
        assert len(lis) == 5
        assert lis.text().split() == ['Users', 'All', 'All', 'All', 'All']

    def test_filter_by_state(self):
        response = self.client.get(
            self.list_url, {'state__exact': AbuseReport.STATES.VALID},
            follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#result_list tbody tr').length == 2
        result_list_text = doc('#result_list').text()
        'Foo' in result_list_text
        'Bar' in result_list_text

        # State filter should be selected. The rest shouldn't.
        lis = doc('#changelist-filter li.selected')
        assert len(lis) == 5
        assert lis.text().split() == ['All', 'Valid', 'All', 'All', 'All']

    def test_filter_by_reason(self):
        response = self.client.get(
            self.list_url, {'reason__exact': AbuseReport.REASONS.OTHER},
            follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#result_list tbody tr').length == 1
        assert 'Soap' in doc('#result_list').text()

        # Reason filter should be selected. The rest shouldn't.
        lis = doc('#changelist-filter li.selected')
        assert len(lis) == 5
        assert lis.text().split() == ['All', 'All', 'Other', 'All', 'All']

    def test_filter_by_created(self):
        some_time_ago = self.days_ago(97).date()
        even_more_time_ago = self.days_ago(99).date()

        data = {
            'created__gte': even_more_time_ago.isoformat(),
            'created__lte': some_time_ago.isoformat(),
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
        # We've got 5 filters, so usually we'd get 5 selected list items
        # (because of the "All" default choice) but since 'created' is actually
        # 2 fields, and we have submitted both, we now have 6 expected items.
        assert len(lis) == 6
        assert lis.text().split() == [
            'All', 'All', 'All', 'From:', 'To:', 'All'
        ]
        elm = lis.eq(3).find('#id_created__gte')
        assert elm
        assert elm.attr('name') == 'created__gte'
        assert elm.attr('value') == even_more_time_ago.isoformat()
        elm = lis.eq(4).find('#id_created__lte')
        assert elm
        assert elm.attr('name') == 'created__lte'
        assert elm.attr('value') == some_time_ago.isoformat()

    def test_filter_by_created_only_from(self):
        not_long_ago = self.days_ago(2).date()
        data = {
            'created__gte': not_long_ago.isoformat(),
        }
        response = self.client.get(self.list_url, data, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#result_list tbody tr').length == 4
        result_list_text = doc('#result_list').text()
        assert 'Soap' not in result_list_text
        assert 'Foo' not in result_list_text

        # Created filter should be selected. The rest shouldn't.
        lis = doc('#changelist-filter li.selected')
        # We've got 5 filters.
        assert len(lis) == 5
        assert lis.text().split() == [
            'All', 'All', 'All', 'From:', 'All'
        ]
        elm = lis.eq(3).find('#id_created__gte')
        assert elm
        assert elm.attr('name') == 'created__gte'
        assert elm.attr('value') == not_long_ago.isoformat()

    def test_filter_by_created_only_to(self):
        some_time_ago = self.days_ago(97).date()
        data = {
            'created__lte': some_time_ago.isoformat(),
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
        # We've got 5 filters.
        assert len(lis) == 5
        assert lis.text().split() == [
            'All', 'All', 'All', 'To:', 'All'
        ]
        elm = lis.eq(3).find('#id_created__lte')
        assert elm
        assert elm.attr('name') == 'created__lte'
        assert elm.attr('value') == some_time_ago.isoformat()

    def test_filter_by_minimum_reports_count_for_guid(self):
        data = {
            'minimum_reports_count': '2'
        }
        response = self.client.get(self.list_url, data, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#result_list tbody tr').length == 2
        result_list_text = doc('#result_list').text()
        assert 'Soap' not in result_list_text
        assert 'Foo' in result_list_text

        # Minimum reports count filter should be selected. The rest shouldn't.
        lis = doc('#changelist-filter li.selected')
        # We've got 5 filters.
        assert len(lis) == 5
        # There is no label for minimum reports count, so despite having 5 lis
        # we only have 4 things in .text().
        assert lis.text().split() == [
            'All', 'All', 'All', 'All',
        ]
        # The 4th item should contain the input though.
        elm = lis.eq(4).find('#id_minimum_reports_count')
        assert elm
        assert elm.attr('name') == 'minimum_reports_count'
        assert elm.attr('value') == '2'

    def test_combine_complex_filters_and_search(self):
        today = date.today()
        data = {
            'reason__exact': str(AbuseReport.REASONS.OTHER),
            'type': 'addon',
            'q': 'Soap',
            'created__gte': self.days_ago(100).date().isoformat(),
            'created__lte': self.days_ago(97).date().isoformat(),
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
        inputs = [(elm.name, elm.value) for elm in forms.find('input')
                  if elm.name and elm.value != '']
        assert set(inputs) == set(data.items())

        # Same for the 'search' form
        form = doc('#changelist-filter form')
        inputs = [(elm.name, elm.value) for elm in form.find('input')
                  if elm.name and elm.value != '']
        assert set(inputs) == set(data.items())

        # Gather selected filters.
        lis = doc('#changelist-filter li.selected')

        # We've got 5 filters, so usually we'd get 5 selected list items
        # (because of the "All" default choice) but since 'created' is actually
        # 2 fields, and we have submitted both, we now have 6 expected items.
        assert len(lis) == 6
        assert lis.text().split() == [
            'Addons', 'All', 'Other', 'From:', 'To:', 'All'
        ]
        assert lis.eq(3).find('#id_created__gte')
        assert lis.eq(4).find('#id_created__lte')

        # The links used for 'normal' filtering should also contain all active
        # filters even our custom fancy ones. We just look at the selected
        # filters to keep things simple (they should have all parameters in
        # data with the same value just like the forms).
        links = doc('#changelist-filter li.selected a')
        for elm in links:
            parsed_href_query = parse_qsl(urlparse(elm.attrib['href']).query)
            assert set(parsed_href_query) == set(data.items())

    def test_get_actions(self):
        abuse_report_admin = AbuseReportAdmin(AbuseReport, admin.site)
        request = RequestFactory().get('/')
        request.user = user_factory()
        assert list(abuse_report_admin.get_actions(request).keys()) == []

        request.user = self.user
        assert list(
            abuse_report_admin.get_actions(request).keys()) == [
            'mark_as_valid', 'mark_as_suspicious'
        ]

    def test_action_mark_multiple_as_valid(self):
        abuse_report_admin = AbuseReportAdmin(AbuseReport, admin.site)
        request = RequestFactory().get('/')
        request.user = self.user
        request._messages = default_messages_storage(request)
        reports = AbuseReport.objects.filter(
            guid__in=('@guid3', '@unknown_guid'))
        assert reports.count() == 2
        for report in reports.all():
            assert report.state == AbuseReport.STATES.UNTRIAGED
        other_report = AbuseReport.objects.get(guid='@guid1', message='')
        assert other_report.state == AbuseReport.STATES.UNTRIAGED

        abuse_report_admin.mark_as_valid(request, reports)
        for report in reports.all():
            assert report.state == AbuseReport.STATES.VALID

        # Other reports should be unaffected
        assert other_report.reload().state == AbuseReport.STATES.UNTRIAGED

    def test_action_mark_multiple_as_suspicious(self):
        abuse_report_admin = AbuseReportAdmin(AbuseReport, admin.site)
        request = RequestFactory().get('/')
        request.user = self.user
        request._messages = default_messages_storage(request)
        reports = AbuseReport.objects.filter(
            guid__in=('@guid3', '@unknown_guid'))
        assert reports.count() == 2
        for report in reports.all():
            assert report.state == AbuseReport.STATES.UNTRIAGED
        other_report = AbuseReport.objects.get(guid='@guid1', message='')
        assert other_report.state == AbuseReport.STATES.UNTRIAGED

        abuse_report_admin.mark_as_suspicious(request, reports)
        for report in reports.all():
            assert report.state == AbuseReport.STATES.SUSPICIOUS

        # Other reports should be unaffected
        assert other_report.reload().state == AbuseReport.STATES.UNTRIAGED
