# -*- coding: utf-8 -*-
from datetime import datetime

import django.contrib.messages as django_messages
from django.conf import settings
from django.contrib import admin
from django.test import RequestFactory
from django.test.utils import override_settings

import mock
import pytest
import responses
from pyquery import PyQuery as pq

from olympia.amo.tests import addon_factory, TestCase, user_factory
from olympia.amo.urlresolvers import reverse
from olympia.ratings.models import Rating

from .admin import AkismetAdmin
from .models import AkismetReport
from .tasks import submit_to_akismet


class TestAkismetReportsModel(TestCase):

    def test_create_for_rating(self):
        user = user_factory(homepage='https://spam.spam/')
        addon = addon_factory()
        rating = Rating.objects.create(
            addon=addon, user=user, rating=4, body='spám?',
            ip_address='1.23.45.67')
        ua = 'foo/baa'
        referrer = 'https://mozilla.org/'
        report = AkismetReport.create_for_rating(rating, ua, referrer)

        assert report.rating_instance == rating
        data = report._get_data()
        assert data == {
            'blog': settings.SITE_URL,
            'user_ip': rating.ip_address,
            'user_agent': ua,
            'referrer': referrer,
            'permalink': addon.get_url_path(),
            'comment_type': 'user-review',
            'comment_author': user.username,
            'comment_author_email': user.email,
            'comment_author_url': user.homepage,
            'comment_content': rating.body,
            'comment_date_gmt': rating.modified,
            'comment_post_modified_gmt': addon.last_updated,
            'blog_charset': 'utf-8',
            'is_test': not settings.AKISMET_REAL_SUBMIT,
        }

    def _create_report(self, kws=None):
        defaults = dict(
            comment_type='user-review',
            user_ip='9.8.7.6.5',
            user_agent='Agent Bond',
            referrer='á4565',
            user_name='steve',
            user_email='steve@steve.com',
            user_homepage='http://spam.spam',
            content_link='https://addons.mozilla.org',
            content_modified=datetime.now(),
            comment='spammy McSpam?',
            comment_modified=datetime.now(),
        )
        if kws:
            defaults.update(**kws)
        instance = AkismetReport.objects.create(**defaults)
        return instance

    @responses.activate
    @override_settings(AKISMET_API_KEY=None)
    def test_comment_check(self):
        report = self._create_report()

        url = settings.AKISMET_API_URL.format(
            api_key='none', action='comment-check')
        responses.add(responses.POST, url, json=True)
        responses.add(
            responses.POST, url, json=True,
            headers={'X-akismet-pro-tip': 'discard'})
        # Headers should be ignored on False but add anyway.
        responses.add(
            responses.POST, url, json=False,
            headers={'X-akismet-pro-tip': 'discard'})

        result = report.comment_check()
        assert result == report.result == AkismetReport.MAYBE_SPAM

        result = report.comment_check()
        assert result == report.result == AkismetReport.DEFINITE_SPAM

        result = report.comment_check()
        assert result == report.result == AkismetReport.HAM

    @responses.activate
    @override_settings(AKISMET_API_KEY=None)
    def test_submit_spam(self):
        report = self._create_report()
        url = settings.AKISMET_API_URL.format(
            api_key='none', action='submit-spam')
        responses.add(
            responses.POST, url,
            body='Thanks for making the web a better place.')
        responses.add(responses.POST, url, body='')

        with self.assertRaises(AssertionError):
            # will raise because no result
            report.submit_spam()

        report.update(result=AkismetReport.MAYBE_SPAM)
        with self.assertRaises(AssertionError):
            # will raise because can't submit spam as spam
            report.submit_spam()

        report.update(result=AkismetReport.HAM)
        assert report.submit_spam()

        with self.assertRaises(AssertionError):
            # will raise because already submitted
            report.submit_spam()

        report.update(reported=False)
        assert not report.submit_spam()

    @responses.activate
    @override_settings(AKISMET_API_KEY=None)
    def test_submit_ham(self):
        report = self._create_report()
        url = settings.AKISMET_API_URL.format(
            api_key='none', action='submit-ham')
        responses.add(
            responses.POST, url,
            body='Thanks for making the web a better place.')
        responses.add(responses.POST, url, body='')

        with self.assertRaises(AssertionError):
            # will raise because no result
            report.submit_ham()

        report.update(result=AkismetReport.HAM)
        with self.assertRaises(AssertionError):
            # will raise because can't submit ham as ham
            report.submit_ham()

        report.update(result=AkismetReport.MAYBE_SPAM)
        assert report.submit_ham()

        with self.assertRaises(AssertionError):
            # will raise because already submitted
            report.submit_ham()

        report.update(reported=False)
        assert not report.submit_ham()


class TestAkismetAdmin(TestCase):
    def setUp(self):
        super(TestAkismetAdmin, self).setUp()
        self.list_url = reverse('admin:akismet_akismetreport_changelist')
        self.user = user_factory()
        self.grant_permission(self.user, '*:*')
        self.client.login(email=self.user.email)

    def _add_reports(self):
        user = user_factory(homepage='https://spam.spam/')
        addon = addon_factory()
        rating = Rating.objects.create(
            addon=addon, user=user, rating=4, body=u'spám? noreport',
            ip_address='1.23.45.67')
        ua = 'foo/baa'
        referrer = 'https://mozilla.org/'
        AkismetReport.create_for_rating(rating, ua, referrer).update(
            result=AkismetReport.MAYBE_SPAM)
        AkismetReport.create_for_rating(rating, ua, referrer).update(
            result=AkismetReport.DEFINITE_SPAM)
        AkismetReport.create_for_rating(rating, ua, referrer).update(
            result=AkismetReport.HAM)
        rating.update(body=u'spám? report!')
        AkismetReport.create_for_rating(rating, ua, referrer).update(
            result=AkismetReport.MAYBE_SPAM, reported=True)
        AkismetReport.create_for_rating(rating, ua, referrer).update(
            result=AkismetReport.DEFINITE_SPAM, reported=True)
        AkismetReport.create_for_rating(rating, ua, referrer).update(
            result=AkismetReport.HAM, reported=True)

    def test_filters_display(self):
        response = self.client.get(self.list_url, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc("a[href='?reported_status=ham']").text() == 'Reported Ham'
        assert doc("a[href='?reported_status=spam']").text() == 'Reported Spam'
        assert doc("a[href='?reported_status=unreported']").text() == (
            'Not Reported')

    def test_filter_reported_spam(self):
        self._add_reports()
        response = self.client.get(
            self.list_url + '?reported_status=spam', follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        assert u'noreport' not in response.content.decode('utf-8')
        assert doc(u"td:contains('report!')").length == 2

    def test_filter_reported_ham(self):
        self._add_reports()
        response = self.client.get(
            self.list_url + '?reported_status=ham', follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        assert u'noreport' not in response.content.decode('utf-8')
        assert doc(u"td:contains('report!')").length == 1

    def test_filter_not_reported(self):
        self._add_reports()
        response = self.client.get(
            self.list_url + '?reported_status=unreported', follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        assert u'report!' not in response.content.decode('utf-8')
        assert doc(u"td:contains('noreport')").length == 3

    @mock.patch('olympia.lib.akismet.admin.submit_to_akismet.delay')
    def test_submit_spam(self, submit_to_akismet_mock):
        self._add_reports()
        akismet_admin = AkismetAdmin(AkismetReport, admin.site)
        request = RequestFactory().get('/')
        request.user = self.user
        request._messages = django_messages.storage.default_storage(request)

        akismet_admin.submit_spam(request, AkismetReport.objects.all())
        submit_to_akismet_mock.assert_called()
        ham_report_not_already_submitted = AkismetReport.objects.get(
            reported=False, result=AkismetReport.HAM)
        submit_to_akismet_mock.assert_called_with(
            [ham_report_not_already_submitted.pk], True)
        assert len(django_messages.get_messages(request)) == 1
        for message in django_messages.get_messages(request):
            assert unicode(message) == (
                '1 Ham reports submitted as Spam; 5 reports ignored')

    @mock.patch('olympia.lib.akismet.admin.submit_to_akismet.delay')
    def test_submit_ham(self, submit_to_akismet_mock):
        self._add_reports()
        akismet_admin = AkismetAdmin(AkismetReport, admin.site)
        request = RequestFactory().get('/')
        request.user = self.user
        request._messages = django_messages.storage.default_storage(request)

        akismet_admin.submit_ham(request, AkismetReport.objects.all())
        submit_to_akismet_mock.assert_called()
        spam_reports_not_already_submitted = AkismetReport.objects.filter(
            reported=False, result__in=(
                AkismetReport.MAYBE_SPAM, AkismetReport.DEFINITE_SPAM))
        submit_to_akismet_mock.assert_called_with(
            [r.id for r in spam_reports_not_already_submitted], False)
        assert len(django_messages.get_messages(request)) == 1
        for message in django_messages.get_messages(request):
            assert unicode(message) == (
                '2 Spam reports submitted as Ham; 4 reports ignored')

    def test_submit_spam_button_on_ham_page(self):
        rating = Rating.objects.create(
            addon=addon_factory(), user=user_factory(homepage='https://ham'),
            rating=4, body=u'hám?', ip_address='1.23.45.67')
        report = AkismetReport.create_for_rating(
            rating, 'foo/baa', 'https://mozilla.org/')
        url = reverse(
            'admin:akismet_akismetreport_change', args=(report.pk,)
        )
        response = self.client.get(url, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        # no result means no submit button
        assert not doc('input[name="_selected_action"]')

        report.update(result=AkismetReport.HAM)
        response = self.client.get(url, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        # HAM should show a submit Spam button
        assert doc('input[name="_selected_action"]')
        assert doc('input[name="_selected_action"]').attr['value'] == (
            str(report.id))
        assert doc('input[name="action"]').attr['value'] == 'submit_spam'
        assert doc('input[type="submit"]').attr['value'] == (
            'Submit Spam to Akismet')

        # But not if already submitted
        report.update(reported=True)
        response = self.client.get(url, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        assert not doc('input[name="_selected_action"]')

    def test_submit_ham_button_on_spam_page(self):
        rating = Rating.objects.create(
            addon=addon_factory(), user=user_factory(homepage='https://spam'),
            rating=4, body=u'spám?', ip_address='1.23.45.67')
        report = AkismetReport.create_for_rating(
            rating, 'foo/baa', 'https://mozilla.org/')
        url = reverse(
            'admin:akismet_akismetreport_change', args=(report.pk,)
        )
        response = self.client.get(url, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        # no result means no submit button
        assert not doc('input[name="_selected_action"]')

        report.update(result=AkismetReport.MAYBE_SPAM)
        response = self.client.get(url, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        # HAM should show a submit Spam button
        assert doc('input[name="_selected_action"]')
        assert doc('input[name="_selected_action"]').attr['value'] == (
            str(report.id))
        assert doc('input[name="action"]').attr['value'] == 'submit_ham'
        assert doc('input[type="submit"]').attr['value'] == (
            'Submit Ham to Akismet')

        # Treat DEFINITE the same as MAYBE for submitting
        report.update(result=AkismetReport.DEFINITE_SPAM)
        response = self.client.get(url, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('input[name="_selected_action"]')
        assert doc('input[name="_selected_action"]').attr['value'] == (
            str(report.id))
        assert doc('input[name="action"]').attr['value'] == 'submit_ham'
        assert doc('input[type="submit"]').attr['value'] == (
            'Submit Ham to Akismet')

        # But no submit button if already submitted
        report.update(reported=True)
        response = self.client.get(url, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        assert not doc('input[name="_selected_action"]')


@mock.patch('olympia.lib.akismet.models.AkismetReport.submit_ham')
@mock.patch('olympia.lib.akismet.models.AkismetReport.submit_spam')
@pytest.mark.django_db
def test_submit_to_akismet_task(submit_spam_mock, submit_ham_mock):
    rating = Rating.objects.create(
        addon=addon_factory(), user=user_factory(), rating=4, body='')
    report_a, report_b = (
        AkismetReport.create_for_rating(rating, '', ''),
        AkismetReport.create_for_rating(rating, '', ''))

    submit_to_akismet([report_a.id, report_b.id], True)
    assert submit_spam_mock.call_count == 2

    submit_to_akismet([report_a.id, report_b.id], False)
    assert submit_ham_mock.call_count == 2
