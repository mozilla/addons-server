# -*- coding: utf-8 -*-
import json
import os
import time
import urlparse

from collections import OrderedDict
from datetime import datetime, timedelta

from django.conf import settings
from django.core import mail
from django.core.cache import cache
from django.core.files import temp
from django.core.files.base import File as DjangoFile
from django.template import defaultfilters
from django.test.utils import override_settings

import mock

from freezegun import freeze_time
from lxml.html import HTMLParser, fromstring
from mock import Mock, patch
from pyquery import PyQuery as pq

from olympia import amo, core, ratings
from olympia.abuse.models import AbuseReport
from olympia.access.models import Group, GroupUser
from olympia.accounts.views import API_TOKEN_COOKIE
from olympia.activity.models import ActivityLog
from olympia.addons.models import (
    Addon, AddonApprovalsCounter, AddonDependency, AddonReviewerFlags,
    AddonUser)
from olympia.amo.templatetags.jinja_helpers import (
    user_media_path, user_media_url)
from olympia.amo.tests import (
    APITestClient, TestCase, addon_factory, check_links, file_factory, formset,
    initial, user_factory, version_factory)
from olympia.amo.urlresolvers import reverse
from olympia.files.models import File, FileValidation, WebextPermission
from olympia.ratings.models import Rating, RatingFlag
from olympia.reviewers.models import (
    AutoApprovalSummary, RereviewQueueTheme, ReviewerScore,
    ReviewerSubscription, Whiteboard)
from olympia.users.models import UserProfile
from olympia.versions.models import ApplicationsVersions, AppVersion
from olympia.zadmin.models import get_config


class TestRedirectsOldPaths(TestCase):
    def setUp(self):
        user = user_factory()
        self.client.login(email=user.email)

    def test_redirect_old_queue(self):
        response = self.client.get('/en-US/editors/queue/new')
        self.assert3xx(response, '/reviewers/queue/new', status_code=301)

    def test_redirect_old_review_page(self):
        response = self.client.get('/en-US/editors/review/foobar')
        self.assert3xx(response, '/reviewers/review/foobar', status_code=301)


class ReviewerTest(TestCase):
    fixtures = ['base/users', 'base/approvals']

    def login_as_admin(self):
        assert self.client.login(email='admin@mozilla.com')

    def login_as_reviewer(self):
        assert self.client.login(email='reviewer@mozilla.com')

    def make_review(self, username='a'):
        u = UserProfile.objects.create(username=username)
        a = Addon.objects.create(name='yermom', type=amo.ADDON_EXTENSION)
        return Rating.objects.create(user=u, addon=a, title='foo', body='bar')


class TestEventLog(ReviewerTest):

    def setUp(self):
        super(TestEventLog, self).setUp()
        user = user_factory()
        self.grant_permission(user, 'Ratings:Moderate')
        self.client.login(email=user.email)
        self.url = reverse('reviewers.eventlog')
        core.set_user(user)

    def test_log(self):
        response = self.client.get(self.url)
        assert response.status_code == 200

    def test_start_filter(self):
        response = self.client.get(self.url, {'start': '2011-01-01'})
        assert response.status_code == 200

    def test_enddate_filter(self):
        """
        Make sure that if our end date is 1/1/2011, that we include items from
        1/1/2011.  To not do as such would be dishonorable.
        """
        review = self.make_review(username='b')
        ActivityLog.create(
            amo.LOG.APPROVE_RATING, review, review.addon).update(
            created=datetime(2011, 1, 1))

        response = self.client.get(self.url, {'end': '2011-01-01'})
        assert response.status_code == 200
        assert pq(response.content)('tbody td').eq(0).text() == (
            'Jan. 1, 2011, midnight')

    def test_action_filter(self):
        """
        Based on setup we should see only two items if we filter for deleted
        reviews.
        """
        review = self.make_review()
        for i in xrange(2):
            ActivityLog.create(amo.LOG.APPROVE_RATING, review, review.addon)
            ActivityLog.create(amo.LOG.DELETE_RATING, review.id, review.addon)
        response = self.client.get(self.url, {'filter': 'deleted'})
        assert response.status_code == 200
        assert pq(response.content)('tbody tr').length == 2

    def test_no_results(self):
        response = self.client.get(self.url, {'end': '2004-01-01'})
        assert response.status_code == 200
        assert '"no-results"' in response.content

    def test_event_log_detail(self):
        review = self.make_review()
        ActivityLog.create(amo.LOG.APPROVE_RATING, review, review.addon)
        id_ = ActivityLog.objects.reviewer_events()[0].id
        response = self.client.get(
            reverse('reviewers.eventlog.detail', args=[id_]))
        assert response.status_code == 200


class TestReviewLog(ReviewerTest):
    fixtures = ReviewerTest.fixtures + ['base/addon_3615']

    def setUp(self):
        super(TestReviewLog, self).setUp()
        self.user = UserProfile.objects.get(email='reviewer@mozilla.com')
        self.login_as_reviewer()
        self.url = reverse('reviewers.reviewlog')

    def get_user(self):
        return UserProfile.objects.all()[0]

    def make_approvals(self):
        for addon in Addon.objects.all():
            ActivityLog.create(
                amo.LOG.REJECT_VERSION, addon, addon.current_version,
                user=self.get_user(), details={'comments': 'youwin'})

    def make_an_approval(self, action, comment='youwin', username=None,
                         addon=None):
        if username:
            user = UserProfile.objects.get(username=username)
        else:
            user = self.get_user()
        if not addon:
            addon = Addon.objects.all()[0]
        ActivityLog.create(action, addon, addon.current_version, user=user,
                           details={'comments': comment})

    def test_basic(self):
        self.make_approvals()
        response = self.client.get(self.url)
        assert response .status_code == 200
        doc = pq(response .content)
        assert doc('#log-filter button'), 'No filters.'
        # Should have 2 showing.
        rows = doc('tbody tr')
        assert rows.filter(':not(.hide)').length == 2
        assert rows.filter('.hide').eq(0).text() == 'youwin'
        # Should have none showing if the addons are unlisted.
        for addon in Addon.objects.all():
            self.make_addon_unlisted(addon)
        response = self.client.get(self.url)
        assert response .status_code == 200
        doc = pq(response.content)
        assert not doc('tbody tr :not(.hide)')

        # But they should have 2 showing for someone with the right perms.
        self.grant_permission(self.user, 'Addons:ReviewUnlisted')
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        rows = doc('tbody tr')
        assert rows.filter(':not(.hide)').length == 2
        assert rows.filter('.hide').eq(0).text() == 'youwin'

    def test_xss(self):
        a = Addon.objects.all()[0]
        a.name = '<script>alert("xss")</script>'
        a.save()
        ActivityLog.create(amo.LOG.REJECT_VERSION, a, a.current_version,
                           user=self.get_user(), details={'comments': 'xss!'})

        response = self.client.get(self.url)
        assert response.status_code == 200
        inner_html = pq(response.content)('#log-listing tbody td').eq(1).html()

        assert '&lt;script&gt;' in inner_html
        assert '<script>' not in inner_html

    def test_end_filter(self):
        """
        Let's use today as an end-day filter and make sure we see stuff if we
        filter.
        """
        self.make_approvals()
        # Make sure we show the stuff we just made.
        date = time.strftime('%Y-%m-%d')
        response = self.client.get(self.url, {'end': date})
        assert response.status_code == 200
        doc = pq(response.content)('#log-listing tbody')
        assert doc('tr:not(.hide)').length == 2
        assert doc('tr.hide').eq(0).text() == 'youwin'

    def test_end_filter_wrong(self):
        """
        Let's use today as an end-day filter and make sure we see stuff if we
        filter.
        """
        self.make_approvals()
        response = self.client.get(self.url, {'end': 'wrong!'})
        # If this is broken, we'll get a traceback.
        assert response.status_code == 200
        assert pq(response.content)('#log-listing tr:not(.hide)').length == 3

    def test_start_filter(self):
        with freeze_time('2017-08-01 10:00'):
            self.make_approvals()

        # Make sure we show the stuff we just made.
        response = self.client.get(self.url, {'start': '2017-07-31'})
        assert response.status_code == 200

        doc = pq(response.content)('#log-listing tbody')

        assert doc('tr:not(.hide)').length == 2
        assert doc('tr.hide').eq(0).text() == 'youwin'

    def test_start_default_filter(self):
        with freeze_time('2017-07-31 10:00'):
            self.make_approvals()

        with freeze_time('2017-08-01 10:00'):
            addon = Addon.objects.first()

            ActivityLog.create(
                amo.LOG.REJECT_VERSION, addon, addon.current_version,
                user=self.get_user(), details={'comments': 'youwin'})

        # Make sure the default 'start' to the 1st of a month works properly
        with freeze_time('2017-08-03 11:00'):
            response = self.client.get(self.url)
            assert response.status_code == 200

            doc = pq(response.content)('#log-listing tbody')
            assert doc('tr:not(.hide)').length == 1
            assert doc('tr.hide').eq(0).text() == 'youwin'

    def test_search_comment_exists(self):
        """Search by comment."""
        self.make_an_approval(amo.LOG.REQUEST_SUPER_REVIEW, comment='hello')
        response = self.client.get(self.url, {'search': 'hello'})
        assert response.status_code == 200
        assert pq(response.content)(
            '#log-listing tbody tr.hide').eq(0).text() == 'hello'

    def test_search_comment_case_exists(self):
        """Search by comment, with case."""
        self.make_an_approval(amo.LOG.REQUEST_SUPER_REVIEW, comment='hello')
        response = self.client.get(self.url, {'search': 'HeLlO'})
        assert response.status_code == 200
        assert pq(response.content)(
            '#log-listing tbody tr.hide').eq(0).text() == 'hello'

    def test_search_comment_doesnt_exist(self):
        """Search by comment, with no results."""
        self.make_an_approval(amo.LOG.REQUEST_SUPER_REVIEW, comment='hello')
        response = self.client.get(self.url, {'search': 'bye'})
        assert response.status_code == 200
        assert pq(response.content)('.no-results').length == 1

    def test_search_author_exists(self):
        """Search by author."""
        self.make_approvals()
        self.make_an_approval(
            amo.LOG.REQUEST_SUPER_REVIEW, username='reviewer', comment='hi')

        response = self.client.get(self.url, {'search': 'reviewer'})
        assert response.status_code == 200
        rows = pq(response.content)('#log-listing tbody tr')

        assert rows.filter(':not(.hide)').length == 1
        assert rows.filter('.hide').eq(0).text() == 'hi'

    def test_search_author_case_exists(self):
        """Search by author, with case."""
        self.make_approvals()
        self.make_an_approval(
            amo.LOG.REQUEST_SUPER_REVIEW, username='reviewer', comment='hi')

        response = self.client.get(self.url, {'search': 'ReviEwEr'})
        assert response.status_code == 200
        rows = pq(response.content)('#log-listing tbody tr')

        assert rows.filter(':not(.hide)').length == 1
        assert rows.filter('.hide').eq(0).text() == 'hi'

    def test_search_author_doesnt_exist(self):
        """Search by author, with no results."""
        self.make_approvals()
        self.make_an_approval(
            amo.LOG.REQUEST_SUPER_REVIEW, username='reviewer')

        response = self.client.get(self.url, {'search': 'wrong'})
        assert response.status_code == 200
        assert pq(response.content)('.no-results').length == 1

    def test_search_addon_exists(self):
        """Search by add-on name."""
        self.make_approvals()
        addon = Addon.objects.all()[0]
        response = self.client.get(self.url, {'search': addon.name})
        assert response.status_code == 200
        tr = pq(response.content)(
            '#log-listing tr[data-addonid="%s"]' % addon.id)
        assert tr.length == 1
        assert tr.siblings('.comments').text() == 'youwin'

    def test_search_addon_case_exists(self):
        """Search by add-on name, with case."""
        self.make_approvals()
        addon = Addon.objects.all()[0]
        response = self.client.get(
            self.url, {'search': str(addon.name).swapcase()})
        assert response.status_code == 200
        tr = pq(response.content)(
            '#log-listing tr[data-addonid="%s"]' % addon.id)
        assert tr.length == 1
        assert tr.siblings('.comments').text() == 'youwin'

    def test_search_addon_doesnt_exist(self):
        """Search by add-on name, with no results."""
        self.make_approvals()
        response = self.client.get(self.url, {'search': 'xxx'})
        assert response.status_code == 200
        assert pq(response.content)('.no-results').length == 1

    @patch('olympia.activity.models.ActivityLog.arguments', new=Mock)
    def test_addon_missing(self):
        self.make_approvals()
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert pq(response.content)('#log-listing tr td').eq(1).text() == (
            'Add-on has been deleted.')

    def test_request_info_logs(self):
        self.make_an_approval(amo.LOG.REQUEST_INFORMATION)
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert pq(response.content)('#log-listing tr td a').eq(1).text() == (
            'More information requested')

    def test_super_review_logs(self):
        self.make_an_approval(amo.LOG.REQUEST_SUPER_REVIEW)
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert pq(response.content)('#log-listing tr td a').eq(1).text() == (
            'Super review requested')

    def test_comment_logs(self):
        self.make_an_approval(amo.LOG.COMMENT_VERSION)
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert pq(response.content)('#log-listing tr td a').eq(1).text() == (
            'Commented')

    def test_content_approval(self):
        self.make_an_approval(amo.LOG.APPROVE_CONTENT)
        response = self.client.get(self.url)
        assert response.status_code == 200
        link = pq(response.content)('#log-listing tbody td a').eq(1)[0]
        assert link.attrib['href'] == '/en-US/reviewers/review-content/a3615'
        assert link.text_content().strip() == 'Content approved'

    def test_content_rejection(self):
        self.make_an_approval(amo.LOG.REJECT_CONTENT)
        response = self.client.get(self.url)
        assert response.status_code == 200
        link = pq(response.content)('#log-listing tbody td a').eq(1)[0]
        assert link.attrib['href'] == '/en-US/reviewers/review-content/a3615'
        assert link.text_content().strip() == 'Content rejected'

    @freeze_time('2017-08-03')
    def test_review_url(self):
        self.login_as_admin()
        addon = addon_factory()
        unlisted_version = version_factory(
            addon=addon, channel=amo.RELEASE_CHANNEL_UNLISTED)

        ActivityLog.create(
            amo.LOG.APPROVE_VERSION, addon, addon.current_version,
            user=self.get_user(), details={'comments': 'foo'})

        response = self.client.get(self.url)
        assert response.status_code == 200
        url = reverse('reviewers.review', args=[addon.slug])

        link = pq(response.content)(
            '#log-listing tbody tr[data-addonid] a').eq(1)
        assert link.attr('href') == url

        entry = ActivityLog.create(
            amo.LOG.APPROVE_VERSION, addon,
            unlisted_version,
            user=self.get_user(), details={'comments': 'foo'})

        # Force the latest entry to be at the top of the list so that we can
        # pick it more reliably later from the HTML
        entry.update(created=datetime.now() + timedelta(days=1))

        response = self.client.get(self.url)
        url = reverse(
            'reviewers.review',
            args=['unlisted', addon.slug])
        assert pq(response.content)(
            '#log-listing tr td a').eq(1).attr('href') == url


class TestDashboard(TestCase):
    def setUp(self):
        self.url = reverse('reviewers.dashboard')
        self.user = user_factory()
        self.client.login(email=self.user.email)

    def test_old_temporary_url_redirect(self):
        response = self.client.get('/en-US/reviewers/dashboard')
        self.assert3xx(
            response, reverse('reviewers.dashboard'), status_code=301)

    def test_not_a_reviewer(self):
        response = self.client.get(self.url)
        assert response.status_code == 403

    def test_admin_all_permissions(self):
        # Create a lot of add-ons to test the queue counts.
        # Nominated and pending.
        addon_factory(
            status=amo.STATUS_NOMINATED,
            type=amo.ADDON_STATICTHEME,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW})
        version_factory(
            addon=addon_factory(),
            file_kw={'status': amo.STATUS_AWAITING_REVIEW})
        version_factory(
            addon=addon_factory(),
            file_kw={'status': amo.STATUS_AWAITING_REVIEW})
        under_admin_review = addon_factory(
            status=amo.STATUS_NOMINATED,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW})
        AddonReviewerFlags.objects.create(
            addon=under_admin_review, needs_admin_code_review=True)
        under_admin_review_and_pending = addon_factory()
        AddonReviewerFlags.objects.create(
            addon=under_admin_review_and_pending, needs_admin_code_review=True)
        version_factory(
            addon=under_admin_review_and_pending,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW})
        # Auto-approved and Content Review.
        addon1 = addon_factory(
            version_kw={'is_webextension': True})
        AddonApprovalsCounter.reset_for_addon(addon=addon1)
        AutoApprovalSummary.objects.create(
            version=addon1.current_version, verdict=amo.AUTO_APPROVED)
        under_content_review = addon_factory(
            version_kw={'is_webextension': True})
        AddonApprovalsCounter.reset_for_addon(addon=under_content_review)
        AutoApprovalSummary.objects.create(
            version=under_content_review.current_version,
            verdict=amo.AUTO_APPROVED)
        AddonReviewerFlags.objects.create(
            addon=under_content_review, needs_admin_content_review=True)
        addon2 = addon_factory(
            version_kw={'is_webextension': True})
        AddonApprovalsCounter.reset_for_addon(addon=addon2)
        AutoApprovalSummary.objects.create(
            version=addon2.current_version, verdict=amo.AUTO_APPROVED)
        AddonReviewerFlags.objects.create(
            addon=addon2, needs_admin_content_review=True)
        under_code_review = addon_factory(
            version_kw={'is_webextension': True})
        AddonApprovalsCounter.reset_for_addon(addon=under_code_review)
        AutoApprovalSummary.objects.create(
            version=under_code_review.current_version,
            verdict=amo.AUTO_APPROVED)
        AddonReviewerFlags.objects.create(
            addon=under_code_review, needs_admin_code_review=True)
        admins_group = Group.objects.create(name='Admins', rules='*:*')
        GroupUser.objects.create(user=self.user, group=admins_group)

        # Addon with expired info request
        expired = addon_factory(name=u'Expired')
        AddonReviewerFlags.objects.create(
            addon=expired,
            pending_info_request=self.days_ago(42))

        # Rating
        rating = Rating.objects.create(
            addon=addon1, version=addon1.current_version, user=self.user,
            flag=True, body=u'This âdd-on sucks!!111', rating=1,
            editorreview=True)
        rating.ratingflag_set.create()

        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert len(doc('.dashboard h3')) == 9  # All 9 sections are present.
        expected_links = [
            reverse('reviewers.queue_nominated'),
            reverse('reviewers.queue_pending'),
            reverse('reviewers.performance'),
            reverse('reviewers.reviewlog'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Guide',
            reverse('reviewers.queue_nominated'),
            reverse('reviewers.queue_pending'),
            reverse('reviewers.performance'),
            reverse('reviewers.reviewlog'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Themes/Guidelines',
            reverse('reviewers.queue_auto_approved'),
            reverse('reviewers.performance'),
            reverse('reviewers.reviewlog'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Guide',
            reverse('reviewers.queue_content_review'),
            reverse('reviewers.performance'),
            reverse('reviewers.themes.list'),
            reverse('reviewers.themes.list_rereview'),
            reverse('reviewers.themes.list_flagged'),
            reverse('reviewers.themes.logs'),
            reverse('reviewers.themes.deleted'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Themes/Guidelines',
            reverse('reviewers.queue_moderated'),
            reverse('reviewers.eventlog'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Guide/Moderation',
            reverse('reviewers.unlisted_queue_all'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Guide',
            reverse('reviewers.motd'),
            reverse('reviewers.queue_expired_info_requests'),
        ]
        links = [link.attrib['href'] for link in doc('.dashboard a')]
        assert links == expected_links
        assert doc('.dashboard a')[0].text == 'New Add-ons (2)'
        assert doc('.dashboard a')[1].text == 'Add-on Updates (3)'
        assert doc('.dashboard a')[10].text == 'Auto Approved Add-ons (4)'
        assert doc('.dashboard a')[14].text == 'Content Review (4)'
        assert (doc('.dashboard a')[22].text ==
                'Ratings Awaiting Moderation (1)')
        assert (doc('.dashboard a')[28].text ==
                'Expired Information Requests (1)')

    def test_can_see_all_through_reviewer_view_all_permission(self):
        self.grant_permission(self.user, 'ReviewerTools:View')
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert len(doc('.dashboard h3')) == 9  # All 9 sections are present.
        expected_links = [
            reverse('reviewers.queue_nominated'),
            reverse('reviewers.queue_pending'),
            reverse('reviewers.performance'),
            reverse('reviewers.reviewlog'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Guide',
            reverse('reviewers.queue_nominated'),
            reverse('reviewers.queue_pending'),
            reverse('reviewers.performance'),
            reverse('reviewers.reviewlog'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Themes/Guidelines',
            reverse('reviewers.queue_auto_approved'),
            reverse('reviewers.performance'),
            reverse('reviewers.reviewlog'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Guide',
            reverse('reviewers.queue_content_review'),
            reverse('reviewers.performance'),
            reverse('reviewers.themes.list'),
            reverse('reviewers.themes.list_rereview'),
            reverse('reviewers.themes.list_flagged'),
            reverse('reviewers.themes.logs'),
            reverse('reviewers.themes.deleted'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Themes/Guidelines',
            reverse('reviewers.queue_moderated'),
            reverse('reviewers.eventlog'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Guide/Moderation',
            reverse('reviewers.unlisted_queue_all'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Guide',
            reverse('reviewers.motd'),
            reverse('reviewers.queue_expired_info_requests'),
        ]
        links = [link.attrib['href'] for link in doc('.dashboard a')]
        assert links == expected_links

    def test_legacy_reviewer(self):
        # Create some add-ons to test the queue counts.
        addon_factory(
            status=amo.STATUS_NOMINATED,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW})
        version_factory(
            addon=addon_factory(),
            file_kw={'status': amo.STATUS_AWAITING_REVIEW})
        version_factory(
            addon=addon_factory(),
            file_kw={'status': amo.STATUS_AWAITING_REVIEW})
        # These two are under admin review and will be ignored.
        under_admin_review = addon_factory(
            status=amo.STATUS_NOMINATED,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW})
        AddonReviewerFlags.objects.create(
            addon=under_admin_review, needs_admin_code_review=True)
        under_admin_review_and_pending = addon_factory()
        AddonReviewerFlags.objects.create(
            addon=under_admin_review_and_pending, needs_admin_code_review=True)
        version_factory(
            addon=under_admin_review_and_pending,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW})
        # This is a static theme so won't be shown
        addon_factory(
            status=amo.STATUS_NOMINATED,
            type=amo.ADDON_STATICTHEME,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW})

        # Grant user the permission to see only the legacy add-ons section.
        self.grant_permission(self.user, 'Addons:Review')

        # Test.
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert len(doc('.dashboard h3')) == 1
        expected_links = [
            reverse('reviewers.queue_nominated'),
            reverse('reviewers.queue_pending'),
            reverse('reviewers.performance'),
            reverse('reviewers.reviewlog'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Guide',
        ]
        links = [link.attrib['href'] for link in doc('.dashboard a')]
        assert links == expected_links
        assert doc('.dashboard a')[0].text == 'New Add-ons (1)'
        assert doc('.dashboard a')[1].text == 'Add-on Updates (2)'

    def test_post_reviewer(self):
        # Create an add-on to test the queue count. It's under admin content
        # review but that does not have an impact.
        addon = addon_factory(
            version_kw={'is_webextension': True})
        AddonApprovalsCounter.reset_for_addon(addon=addon)
        AutoApprovalSummary.objects.create(
            version=addon.current_version, verdict=amo.AUTO_APPROVED)
        AddonReviewerFlags.objects.create(
            addon=addon, needs_admin_content_review=True)
        # This one however is under admin code review, it's ignored.
        under_code_review = addon_factory(
            version_kw={'is_webextension': True})
        AddonApprovalsCounter.reset_for_addon(addon=under_code_review)
        AutoApprovalSummary.objects.create(
            version=under_code_review.current_version,
            verdict=amo.AUTO_APPROVED)
        AddonReviewerFlags.objects.create(
            addon=under_code_review, needs_admin_code_review=True)
        # Grant user the permission to see only the Auto Approved section.
        self.grant_permission(self.user, 'Addons:PostReview')

        # Test.
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert len(doc('.dashboard h3')) == 1
        expected_links = [
            reverse('reviewers.queue_auto_approved'),
            reverse('reviewers.performance'),
            reverse('reviewers.reviewlog'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Guide',
        ]
        links = [link.attrib['href'] for link in doc('.dashboard a')]
        assert links == expected_links
        assert doc('.dashboard a')[0].text == 'Auto Approved Add-ons (1)'

    def test_content_reviewer(self):
        # Create an add-on to test the queue count. It's under admin code
        # review but that does not have an impact.
        addon = addon_factory(
            version_kw={'is_webextension': True})
        AddonApprovalsCounter.reset_for_addon(addon=addon)
        AutoApprovalSummary.objects.create(
            version=addon.current_version, verdict=amo.AUTO_APPROVED)
        AddonReviewerFlags.objects.create(
            addon=addon, needs_admin_code_review=True)
        # This one is under admin *content* review so it's ignored.
        under_content_review = addon_factory(
            version_kw={'is_webextension': True})
        AddonApprovalsCounter.reset_for_addon(addon=under_content_review)
        AutoApprovalSummary.objects.create(
            version=under_content_review.current_version,
            verdict=amo.AUTO_APPROVED)
        AddonReviewerFlags.objects.create(
            addon=under_content_review, needs_admin_content_review=True)

        # Grant user the permission to see only the Content Review section.
        self.grant_permission(self.user, 'Addons:ContentReview')

        # Test.
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert len(doc('.dashboard h3')) == 1
        expected_links = [
            reverse('reviewers.queue_content_review'),
            reverse('reviewers.performance'),
        ]
        links = [link.attrib['href'] for link in doc('.dashboard a')]
        assert links == expected_links
        assert doc('.dashboard a')[0].text == 'Content Review (1)'

    def test_themes_reviewer(self):
        # Create some themes to test the queue counts.
        addon_factory(type=amo.ADDON_PERSONA, status=amo.STATUS_PENDING)
        addon_factory(type=amo.ADDON_PERSONA, status=amo.STATUS_PENDING)
        addon = addon_factory(type=amo.ADDON_PERSONA, status=amo.STATUS_PUBLIC)
        RereviewQueueTheme.objects.create(theme=addon.persona)
        addon_factory(type=amo.ADDON_PERSONA, status=amo.STATUS_REVIEW_PENDING)
        addon_factory(type=amo.ADDON_PERSONA, status=amo.STATUS_REVIEW_PENDING)
        addon_factory(type=amo.ADDON_PERSONA, status=amo.STATUS_REVIEW_PENDING)

        # Grant user the permission to see only the themes section.
        self.grant_permission(self.user, 'Personas:Review')

        # Test.
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert len(doc('.dashboard h3')) == 1
        expected_links = [
            reverse('reviewers.themes.list'),
            reverse('reviewers.themes.list_rereview'),
            reverse('reviewers.themes.list_flagged'),
            reverse('reviewers.themes.logs'),
            reverse('reviewers.themes.deleted'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Themes/Guidelines',
        ]
        links = [link.attrib['href'] for link in doc('.dashboard a')]
        assert links == expected_links
        assert doc('.dashboard a')[0].text == 'New Themes (2)'
        assert doc('.dashboard a')[1].text == 'Themes Updates (1)'
        assert doc('.dashboard a')[2].text == 'Flagged Themes (3)'

    def test_ratings_moderator(self):
        # Create an rating to test the queue count.
        addon = addon_factory()
        user = user_factory()
        rating = Rating.objects.create(
            addon=addon, version=addon.current_version, user=user, flag=True,
            body=u'This âdd-on sucks!!111', rating=1, editorreview=True)
        rating.ratingflag_set.create()

        # Grant user the permission to see only the ratings to review section.
        self.grant_permission(self.user, 'Ratings:Moderate')

        # Test.
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert len(doc('.dashboard h3')) == 1
        expected_links = [
            reverse('reviewers.queue_moderated'),
            reverse('reviewers.eventlog'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Guide/Moderation',
        ]
        links = [link.attrib['href'] for link in doc('.dashboard a')]
        assert links == expected_links
        assert doc('.dashboard a')[0].text == 'Ratings Awaiting Moderation (1)'

    def test_unlisted_reviewer(self):
        # Grant user the permission to see only the unlisted add-ons section.
        self.grant_permission(self.user, 'Addons:ReviewUnlisted')

        # Test.
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert len(doc('.dashboard h3')) == 1
        expected_links = [
            reverse('reviewers.unlisted_queue_all'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Guide',
        ]
        links = [link.attrib['href'] for link in doc('.dashboard a')]
        assert links == expected_links

    def test_static_theme_reviewer(self):
        # Create some static themes to test the queue counts.
        addon_factory(
            status=amo.STATUS_NOMINATED,
            type=amo.ADDON_STATICTHEME,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW})
        version_factory(
            addon=addon_factory(type=amo.ADDON_STATICTHEME),
            file_kw={'status': amo.STATUS_AWAITING_REVIEW})
        version_factory(
            addon=addon_factory(type=amo.ADDON_STATICTHEME,),
            file_kw={'status': amo.STATUS_AWAITING_REVIEW})
        # These two are under admin review and will be ignored.
        under_admin_review = addon_factory(
            status=amo.STATUS_NOMINATED,
            type=amo.ADDON_STATICTHEME,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW})
        AddonReviewerFlags.objects.create(
            addon=under_admin_review, needs_admin_code_review=True)
        under_admin_review_and_pending = addon_factory(
            type=amo.ADDON_STATICTHEME)
        AddonReviewerFlags.objects.create(
            addon=under_admin_review_and_pending, needs_admin_code_review=True)
        version_factory(
            addon=under_admin_review_and_pending,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW})
        # This is an extension so won't be shown
        addon_factory(
            status=amo.STATUS_NOMINATED,
            type=amo.ADDON_EXTENSION,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW})

        # Grant user the permission to see only the legacy add-ons section.
        self.grant_permission(self.user, 'Addons:ThemeReview')

        # Test.
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert len(doc('.dashboard h3')) == 1
        expected_links = [
            reverse('reviewers.queue_nominated'),
            reverse('reviewers.queue_pending'),
            reverse('reviewers.performance'),
            reverse('reviewers.reviewlog'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Themes/Guidelines',
        ]
        links = [link.attrib['href'] for link in doc('.dashboard a')]
        assert links == expected_links
        assert doc('.dashboard a')[0].text == 'New Add-ons (1)'
        assert doc('.dashboard a')[1].text == 'Add-on Updates (2)'

    def test_post_reviewer_and_content_reviewer(self):
        # Create add-ons to test the queue count. The first add-on has its
        # content approved, so the post review queue should contain 2 add-ons,
        # and the content review queue only 1.
        addon = addon_factory(
            version_kw={'is_webextension': True})
        AutoApprovalSummary.objects.create(
            version=addon.current_version, verdict=amo.AUTO_APPROVED)
        AddonApprovalsCounter.approve_content_for_addon(addon=addon)

        addon = addon_factory(
            version_kw={'is_webextension': True})
        AddonApprovalsCounter.reset_for_addon(addon=addon)
        AutoApprovalSummary.objects.create(
            version=addon.current_version, verdict=amo.AUTO_APPROVED)

        # Grant user the permission to see both the Content Review and the
        # Auto Approved Add-ons sections.
        self.grant_permission(self.user, 'Addons:ContentReview')
        self.grant_permission(self.user, 'Addons:PostReview')

        # Test.
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert len(doc('.dashboard h3')) == 2  # 2 sections are shown.
        expected_links = [
            reverse('reviewers.queue_auto_approved'),
            reverse('reviewers.performance'),
            reverse('reviewers.reviewlog'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Guide',
            reverse('reviewers.queue_content_review'),
            reverse('reviewers.performance'),
        ]
        links = [link.attrib['href'] for link in doc('.dashboard a')]
        assert links == expected_links
        assert doc('.dashboard a')[0].text == 'Auto Approved Add-ons (2)'
        assert 'target' not in doc('.dashboard a')[0].attrib
        assert doc('.dashboard a')[3].text == 'Review Guide'
        assert doc('.dashboard a')[3].attrib['target'] == '_blank'
        assert doc('.dashboard a')[3].attrib['rel'] == 'noopener noreferrer'
        assert doc('.dashboard a')[4].text == 'Content Review (1)'

    def test_legacy_reviewer_and_ratings_moderator(self):
        # Grant user the permission to see both the legacy add-ons and the
        # ratings moderation sections.
        self.grant_permission(self.user, 'Addons:Review')
        self.grant_permission(self.user, 'Ratings:Moderate')

        # Test.
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert len(doc('.dashboard h3')) == 2
        expected_links = [
            reverse('reviewers.queue_nominated'),
            reverse('reviewers.queue_pending'),
            reverse('reviewers.performance'),
            reverse('reviewers.reviewlog'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Guide',
            reverse('reviewers.queue_moderated'),
            reverse('reviewers.eventlog'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Guide/Moderation',
        ]
        links = [link.attrib['href'] for link in doc('.dashboard a')]
        assert links == expected_links
        assert doc('.dashboard a')[0].text == 'New Add-ons (0)'
        assert 'target' not in doc('.dashboard a')[0].attrib
        assert doc('.dashboard a')[1].text == 'Add-on Updates (0)'
        assert doc('.dashboard a')[5].text == 'Ratings Awaiting Moderation (0)'
        assert 'target' not in doc('.dashboard a')[6].attrib
        assert doc('.dashboard a')[7].text == 'Moderation Guide'
        assert doc('.dashboard a')[7].attrib['target'] == '_blank'
        assert doc('.dashboard a')[7].attrib['rel'] == 'noopener noreferrer'


class QueueTest(ReviewerTest):
    fixtures = ['base/users']
    listed = True

    def setUp(self):
        super(QueueTest, self).setUp()
        self.user = UserProfile.objects.get(email='reviewer@mozilla.com')
        self.login_as_reviewer()
        if self.listed is False:
            # Testing unlisted views: needs Addons:ReviewUnlisted perm.
            self.grant_permission(self.user, 'Addons:ReviewUnlisted')
        self.url = reverse('reviewers.queue_pending')
        self.addons = OrderedDict()
        self.expected_addons = []
        self.channel_name = 'listed' if self.listed else 'unlisted'

    def generate_files(self, subset=None, files=None):
        if subset is None:
            subset = []
        files = files or OrderedDict([
            ('Pending One', {
                'version_str': '0.1',
                'addon_status': amo.STATUS_PUBLIC,
                'file_status': amo.STATUS_AWAITING_REVIEW,
            }),
            ('Pending Two', {
                'version_str': '0.1',
                'addon_status': amo.STATUS_PUBLIC,
                'file_status': amo.STATUS_AWAITING_REVIEW,
            }),
            ('Nominated One', {
                'version_str': '0.1',
                'addon_status': amo.STATUS_NOMINATED,
                'file_status': amo.STATUS_AWAITING_REVIEW,
            }),
            ('Nominated Two', {
                'version_str': '0.1',
                'addon_status': amo.STATUS_NOMINATED,
                'file_status': amo.STATUS_AWAITING_REVIEW,
            }),
            ('Public', {
                'version_str': '0.1',
                'addon_status': amo.STATUS_PUBLIC,
                'file_status': amo.STATUS_PUBLIC,
            }),
        ])
        results = OrderedDict()
        channel = (amo.RELEASE_CHANNEL_LISTED if self.listed else
                   amo.RELEASE_CHANNEL_UNLISTED)
        for name, attrs in files.iteritems():
            if not subset or name in subset:
                version_kw = attrs.get('version_kw', {})
                version_kw.update(
                    {'channel': channel, 'version': attrs.pop('version_str')})
                attrs['version_kw'] = version_kw
                file_kw = attrs.get('file_kw', {})
                file_kw.update({'status': attrs.pop('file_status')})
                attrs['file_kw'] = file_kw
                results[name] = addon_factory(
                    status=attrs.pop('addon_status'), name=name, **attrs)
        self.addons.update(results)
        return results

    def generate_file(self, name):
        return self.generate_files([name])[name]

    def get_review_data(self):
        # Format: (Created n days ago,
        #          percentages of [< 5, 5-10, >10])
        return ((1, (0, 0, 100)),
                (8, (0, 50, 50)),
                (12, (50, 0, 50)))

    def get_addon_latest_version(self, addon):
        if self.listed:
            channel = amo.RELEASE_CHANNEL_LISTED
        else:
            channel = amo.RELEASE_CHANNEL_UNLISTED
        return addon.find_latest_version(channel=channel)

    def get_queue(self, addon):
        version = self.get_addon_latest_version(addon)
        assert version.current_queue.objects.filter(id=addon.id).count() == 1

    def get_expected_addons_by_names(self, names):
        expected_addons = []
        files = self.generate_files()
        for name in sorted(names):
            if name in files:
                    expected_addons.append(files[name])
        # Make sure all elements have been added
        assert len(expected_addons) == len(names)
        return expected_addons

    def _test_get_queue(self):
        for addon in self.expected_addons:
            self.get_queue(addon)

    def _test_queue_layout(self, name, tab_position, total_addons,
                           total_queues, per_page=None):
        args = {'per_page': per_page} if per_page else {}
        response = self.client.get(self.url, args)
        assert response.status_code == 200
        doc = pq(response.content)
        links = doc('.tabnav li a')
        link = links.eq(tab_position)

        assert links.length == total_queues
        assert link.text() == '%s (%s)' % (name, total_addons)
        assert link.attr('href') == self.url
        if per_page:
            assert doc('.data-grid-top .num-results').text() == (
                u'Results %s\u20131 of %s' % (per_page, total_addons))

    def _test_results(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        expected = []
        if not len(self.expected_addons):
            raise AssertionError('self.expected_addons was an empty list')
        for idx, addon in enumerate(self.expected_addons):
            latest_version = self.get_addon_latest_version(addon)
            assert latest_version
            name = '%s %s' % (unicode(addon.name),
                              latest_version.version)
            if self.channel_name == 'listed':
                # We typically don't include the channel name if it's the
                # default one, 'listed'.
                channel = []
            else:
                channel = [self.channel_name]
            url = reverse('reviewers.review', args=channel + [addon.slug])
            expected.append((name, url))
        doc = pq(response.content)
        links = doc('#addon-queue tr.addon-row td a:not(.app-icon)')
        assert len(links) == len(self.expected_addons)
        check_links(expected, links, verify=False)
        return doc


class TestQueueBasics(QueueTest):
    def test_only_viewable_by_reviewer(self):
        # Addon reviewer has access.
        response = self.client.get(self.url)
        assert response.status_code == 200

        # Regular user doesn't have access.
        self.client.logout()
        assert self.client.login(email='regular@mozilla.com')
        response = self.client.get(self.url)
        assert response.status_code == 403

        # Persona reviewer doesn't have access either.
        self.client.logout()
        assert self.client.login(email='persona_reviewer@mozilla.com')
        response = self.client.get(self.url)
        assert response.status_code == 403

    def test_invalid_page(self):
        response = self.client.get(self.url, {'page': 999})
        assert response.status_code == 200
        assert response.context['page'].number == 1

    def test_invalid_per_page(self):
        response = self.client.get(self.url, {'per_page': '<garbage>'})
        # No exceptions:
        assert response.status_code == 200

    @patch.multiple('olympia.reviewers.views',
                    REVIEWS_PER_PAGE_MAX=1,
                    REVIEWS_PER_PAGE=1)
    def test_max_per_page(self):
        self.generate_files()

        response = self.client.get(self.url, {'per_page': '2'})
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('.data-grid-top .num-results').text() == (
            u'Results 1\u20131 of 2')

    @patch('olympia.reviewers.views.REVIEWS_PER_PAGE', new=1)
    def test_reviews_per_page(self):
        self.generate_files()

        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('.data-grid-top .num-results').text() == (
            u'Results 1\u20131 of 2')

    def test_grid_headers(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        expected = [
            'Add-on',
            'Type',
            'Waiting Time',
            'Flags',
        ]
        assert [pq(th).text() for th in doc('#addon-queue tr th')[1:]] == (
            expected)

    def test_grid_headers_sort_after_search(self):
        params = dict(searching=['True'],
                      text_query=['abc'],
                      addon_type_ids=['2'],
                      sort=['addon_type_id'])
        response = self.client.get(self.url, params)
        assert response.status_code == 200
        tr = pq(response.content)('#addon-queue tr')
        sorts = {
            # Column index => sort.
            1: 'addon_name',        # Add-on.
            2: '-addon_type_id',    # Type.
            3: 'waiting_time_min',  # Waiting Time.
        }
        for idx, sort in sorts.iteritems():
            # Get column link.
            a = tr('th').eq(idx).find('a')
            # Update expected GET parameters with sort type.
            params.update(sort=[sort])
            # Parse querystring of link to make sure `sort` type is correct.
            assert urlparse.parse_qs(a.attr('href').split('?')[1]) == params

    def test_no_results(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert pq(response.content)('.queue-outer .no-results').length == 1

    def test_no_paginator_when_on_single_page(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert pq(response.content)('.pagination').length == 0

    def test_paginator_when_many_pages(self):
        # 'Pending One' and 'Pending Two' should be the only add-ons in
        # the pending queue, but we'll generate them all for good measure.
        self.generate_files()

        response = self.client.get(self.url, {'per_page': 1})
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('.data-grid-top .num-results').text() == (
            u'Results 1\u20131 of 2')
        assert doc('.data-grid-bottom .num-results').text() == (
            u'Results 1\u20131 of 2')

    def test_legacy_queue_sort(self):
        sorts = (
            ['age', 'Waiting Time'],
            ['name', 'Add-on'],
            ['type', 'Type'],
        )
        for key, text in sorts:
            response = self.client.get(self.url, {'sort': key})
            assert response.status_code == 200
            assert pq(response.content)('th.ordered a').text() == text

    def test_flags_jetpack(self):
        addon = addon_factory(
            status=amo.STATUS_NOMINATED, name='Jetpack',
            version_kw={'version': '0.1'},
            file_kw={'status': amo.STATUS_AWAITING_REVIEW,
                     'jetpack_version': 1.2})

        r = self.client.get(reverse('reviewers.queue_nominated'))

        rows = pq(r.content)('#addon-queue tr.addon-row')
        assert rows.length == 1
        assert rows.attr('data-addon') == str(addon.id)
        assert rows.find('td').eq(1).text() == 'Jetpack 0.1'
        assert rows.find('.ed-sprite-jetpack').length == 1

    def test_flags_is_restart_required(self):
        addon = addon_factory(
            status=amo.STATUS_NOMINATED, name='Some Add-on',
            version_kw={'version': '0.1'},
            file_kw={'status': amo.STATUS_AWAITING_REVIEW,
                     'is_restart_required': True})

        r = self.client.get(reverse('reviewers.queue_nominated'))

        rows = pq(r.content)('#addon-queue tr.addon-row')
        assert rows.length == 1
        assert rows.attr('data-addon') == str(addon.id)
        assert rows.find('td').eq(1).text() == 'Some Add-on 0.1'
        assert rows.find('.ed-sprite-jetpack').length == 0
        assert rows.find('.ed-sprite-is_restart_required').length == 1

    def test_flags_is_restart_required_false(self):
        addon = addon_factory(
            status=amo.STATUS_NOMINATED, name='Restartless',
            version_kw={'version': '0.1'},
            file_kw={'status': amo.STATUS_AWAITING_REVIEW,
                     'is_restart_required': False})

        r = self.client.get(reverse('reviewers.queue_nominated'))

        rows = pq(r.content)('#addon-queue tr.addon-row')
        assert rows.length == 1
        assert rows.attr('data-addon') == str(addon.id)
        assert rows.find('td').eq(1).text() == 'Restartless 0.1'
        assert rows.find('.ed-sprite-jetpack').length == 0
        assert rows.find('.ed-sprite-is_restart_required').length == 0

    def test_tabnav_permissions(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        links = doc('.tabnav li a').map(lambda i, e: e.attrib['href'])
        expected = [
            reverse('reviewers.queue_nominated'),
            reverse('reviewers.queue_pending'),
        ]
        assert links == expected

        self.grant_permission(self.user, 'Ratings:Moderate')
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        links = doc('.tabnav li a').map(lambda i, e: e.attrib['href'])
        expected.append(reverse('reviewers.queue_moderated'))
        assert links == expected

        self.grant_permission(self.user, 'Addons:PostReview')
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        links = doc('.tabnav li a').map(lambda i, e: e.attrib['href'])
        expected.append(reverse('reviewers.queue_auto_approved'))
        assert links == expected

        self.grant_permission(self.user, 'Addons:ContentReview')
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        links = doc('.tabnav li a').map(lambda i, e: e.attrib['href'])
        expected.append(reverse('reviewers.queue_content_review'))
        assert links == expected

        self.grant_permission(self.user, 'Reviews:Admin')
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        links = doc('.tabnav li a').map(lambda i, e: e.attrib['href'])
        expected.append(reverse('reviewers.queue_expired_info_requests'))
        assert links == expected


class TestPendingQueue(QueueTest):

    def setUp(self):
        super(TestPendingQueue, self).setUp()
        # These should be the only ones present.
        self.expected_addons = self.get_expected_addons_by_names(
            ['Pending One', 'Pending Two'])
        self.url = reverse('reviewers.queue_pending')

    def test_results(self):
        self._test_results()

    def test_queue_layout(self):
        self._test_queue_layout('Updates',
                                tab_position=1, total_addons=2, total_queues=2)

    def test_get_queue(self):
        self._test_get_queue()

    def test_webextensions_filtered_out_because_of_post_review(self):
        version = self.addons['Pending Two'].find_latest_version(
            channel=amo.RELEASE_CHANNEL_LISTED)
        version.files.update(is_webextension=True)

        # Webextensions are filtered out from the queue since auto_approve is
        # taking care of them.
        self.expected_addons = [self.addons['Pending One']]
        self._test_results()

    def test_webextension_with_auto_approval_disabled_false_filtered_out(self):
        version = self.addons['Pending Two'].find_latest_version(
            channel=amo.RELEASE_CHANNEL_LISTED)
        version.files.update(is_webextension=True)
        AddonReviewerFlags.objects.create(
            addon=self.addons['Pending Two'], auto_approval_disabled=False)

        self.expected_addons = [self.addons['Pending One']]
        self._test_results()

    def test_webextension_with_auto_approval_disabled_does_show_up(self):
        version = self.addons['Pending Two'].find_latest_version(
            channel=amo.RELEASE_CHANNEL_LISTED)
        version.files.update(is_webextension=True)

        version = self.addons['Pending Two'].find_latest_version(
            channel=amo.RELEASE_CHANNEL_LISTED)
        version.files.update(is_webextension=True)
        AddonReviewerFlags.objects.create(
            addon=self.addons['Pending One'], auto_approval_disabled=True)

        self.expected_addons = [self.addons['Pending One']]
        self._test_results()

    def test_static_theme_filtered_out(self):
        self.addons['Pending Two'].update(type=amo.ADDON_STATICTHEME)

        # Static Theme shouldn't be shown
        self.expected_addons = [self.addons['Pending One']]
        self._test_results()

        # Unless you have that permission also
        self.grant_permission(self.user, 'Addons:ThemeReview')
        self.expected_addons = [
            self.addons['Pending One'], self.addons['Pending Two']]
        self._test_results()


class TestStaticThemePendingQueue(QueueTest):

    def setUp(self):
        super(TestStaticThemePendingQueue, self).setUp()
        # These should be the only ones present.
        self.expected_addons = self.get_expected_addons_by_names(
            ['Pending One', 'Pending Two'])
        Addon.objects.all().update(type=amo.ADDON_STATICTHEME)
        self.url = reverse('reviewers.queue_pending')
        GroupUser.objects.filter(user=self.user).delete()
        self.grant_permission(self.user, 'Addons:ThemeReview')

    def test_results(self):
        self._test_results()

    def test_queue_layout(self):
        self._test_queue_layout('Updates',
                                tab_position=1, total_addons=2, total_queues=2)

    def test_get_queue(self):
        self._test_get_queue()

    def test_extensions_filtered_out(self):
        self.addons['Pending Two'].update(type=amo.ADDON_EXTENSION)

        # Extensions shouldn't be shown
        self.expected_addons = [self.addons['Pending One']]
        self._test_results()

        # Unless you have that permission also
        self.grant_permission(self.user, 'Addons:Review')
        self.expected_addons = [
            self.addons['Pending One'], self.addons['Pending Two']]
        self._test_results()


class TestNominatedQueue(QueueTest):

    def setUp(self):
        super(TestNominatedQueue, self).setUp()
        # These should be the only ones present.
        self.expected_addons = self.get_expected_addons_by_names(
            ['Nominated One', 'Nominated Two'])
        self.url = reverse('reviewers.queue_nominated')

    def test_results(self):
        self._test_results()

    def test_results_two_versions(self):
        version1 = self.addons['Nominated One'].versions.all()[0]
        version2 = self.addons['Nominated Two'].versions.all()[0]
        file_ = version2.files.get()

        # Versions are ordered by creation date, so make sure they're set.
        past = self.days_ago(1)
        version2.update(created=past, nomination=past)

        # Create another version, v0.2, by "cloning" v0.1.
        version2.pk = None
        version2.version = '0.2'
        version2.save()

        # Reset creation date once it has been saved.
        future = datetime.now() - timedelta(seconds=1)
        version2.update(created=future, nomination=future)

        # Associate v0.2 it with a file.
        file_.pk = None
        file_.version = version2
        file_.save()

        # disable old files like Version.from_upload() would.
        version2.disable_old_files()

        response = self.client.get(self.url)
        assert response.status_code == 200
        expected = [
            ('Nominated One 0.1', reverse('reviewers.review',
                                          args=[version1.addon.slug])),
            ('Nominated Two 0.2', reverse('reviewers.review',
                                          args=[version2.addon.slug])),
        ]
        doc = pq(response.content)
        check_links(
            expected,
            doc('#addon-queue tr.addon-row td a:not(.app-icon)'),
            verify=False)

    def test_queue_layout(self):
        self._test_queue_layout('New Add-ons',
                                tab_position=0, total_addons=2, total_queues=2)

    def test_get_queue(self):
        self._test_get_queue()

    def test_webextensions_filtered_out_because_of_post_review(self):
        version = self.addons['Nominated Two'].find_latest_version(
            channel=amo.RELEASE_CHANNEL_LISTED)
        version.files.update(is_webextension=True)

        # Webextensions are filtered out from the queue since auto_approve is
        # taking care of them.
        self.expected_addons = [self.addons['Nominated One']]
        self._test_results()

    def test_webextension_with_auto_approval_disabled_false_filtered_out(self):
        version = self.addons['Nominated Two'].find_latest_version(
            channel=amo.RELEASE_CHANNEL_LISTED)
        version.files.update(is_webextension=True)
        AddonReviewerFlags.objects.create(
            addon=self.addons['Nominated Two'], auto_approval_disabled=False)

        self.expected_addons = [self.addons['Nominated One']]
        self._test_results()

    def test_webextension_with_auto_approval_disabled_does_show_up(self):
        version = self.addons['Nominated Two'].find_latest_version(
            channel=amo.RELEASE_CHANNEL_LISTED)
        version.files.update(is_webextension=True)

        version = self.addons['Nominated One'].find_latest_version(
            channel=amo.RELEASE_CHANNEL_LISTED)
        version.files.update(is_webextension=True)
        AddonReviewerFlags.objects.create(
            addon=self.addons['Nominated One'], auto_approval_disabled=True)

        self.expected_addons = [self.addons['Nominated One']]
        self._test_results()

    def test_static_theme_filtered_out(self):
        self.addons['Nominated Two'].update(type=amo.ADDON_STATICTHEME)

        # Static Theme shouldn't be shown
        self.expected_addons = [self.addons['Nominated One']]
        self._test_results()

        # Unless you have that permission also
        self.grant_permission(self.user, 'Addons:ThemeReview')
        self.expected_addons = [
            self.addons['Nominated One'], self.addons['Nominated Two']]
        self._test_results()


class TestStaticThemeNominatedQueue(QueueTest):

    def setUp(self):
        super(TestStaticThemeNominatedQueue, self).setUp()
        # These should be the only ones present.
        self.expected_addons = self.get_expected_addons_by_names(
            ['Nominated One', 'Nominated Two'])
        self.url = reverse('reviewers.queue_nominated')
        Addon.objects.all().update(type=amo.ADDON_STATICTHEME)
        GroupUser.objects.filter(user=self.user).delete()
        self.grant_permission(self.user, 'Addons:ThemeReview')

    def test_results(self):
        self._test_results()

    def test_results_two_versions(self):
        version1 = self.addons['Nominated One'].versions.all()[0]
        version2 = self.addons['Nominated Two'].versions.all()[0]
        file_ = version2.files.get()

        # Versions are ordered by creation date, so make sure they're set.
        past = self.days_ago(1)
        version2.update(created=past, nomination=past)

        # Create another version, v0.2, by "cloning" v0.1.
        version2.pk = None
        version2.version = '0.2'
        version2.save()

        # Reset creation date once it has been saved.
        future = datetime.now() - timedelta(seconds=1)
        version2.update(created=future, nomination=future)

        # Associate v0.2 it with a file.
        file_.pk = None
        file_.version = version2
        file_.save()

        # disable old files like Version.from_upload() would.
        version2.disable_old_files()

        response = self.client.get(self.url)
        assert response.status_code == 200
        expected = [
            ('Nominated One 0.1', reverse('reviewers.review',
                                          args=[version1.addon.slug])),
            ('Nominated Two 0.2', reverse('reviewers.review',
                                          args=[version2.addon.slug])),
        ]
        doc = pq(response.content)
        check_links(
            expected,
            doc('#addon-queue tr.addon-row td a:not(.app-icon)'),
            verify=False)

    def test_queue_layout(self):
        self._test_queue_layout('New Add-ons',
                                tab_position=0, total_addons=2, total_queues=2)

    def test_get_queue(self):
        self._test_get_queue()

    def test_static_theme_filtered_out(self):
        self.addons['Nominated Two'].update(type=amo.ADDON_EXTENSION)

        # Static Theme shouldn't be shown
        self.expected_addons = [self.addons['Nominated One']]
        self._test_results()

        # Unless you have that permission also
        self.grant_permission(self.user, 'Addons:Review')
        self.expected_addons = [
            self.addons['Nominated One'], self.addons['Nominated Two']]
        self._test_results()


class TestModeratedQueue(QueueTest):
    fixtures = ['base/users', 'ratings/dev-reply']

    def setUp(self):
        super(TestModeratedQueue, self).setUp()

        self.url = reverse('reviewers.queue_moderated')
        url_flag = reverse('addons.ratings.flag', args=['a1865', 218468])

        response = self.client.post(url_flag, {'flag': RatingFlag.SPAM})
        assert response.status_code == 200

        assert RatingFlag.objects.filter(flag=RatingFlag.SPAM).count() == 1
        assert Rating.objects.filter(editorreview=True).count() == 1
        self.grant_permission(self.user, 'Ratings:Moderate')

    def test_results(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)('#reviews-flagged')

        rows = doc('.review-flagged:not(.review-saved)')
        assert rows.length == 1
        assert rows.find('h3').text() == ": Don't use Firefox 2.0!"

        # Default is "Skip."
        assert doc('#id_form-0-action_1:checked').length == 1

        flagged = doc('.reviews-flagged-reasons span.light').text()
        reviewer = RatingFlag.objects.all()[0].user.name
        assert flagged.startswith('Flagged by %s' % reviewer), (
            'Unexpected text: %s' % flagged)

    def setup_actions(self, action):
        response = self.client.get(self.url)
        assert response.status_code == 200
        form_0_data = initial(response.context['reviews_formset'].forms[0])

        assert Rating.objects.filter(addon=1865).count() == 2

        formset_data = formset(form_0_data)
        formset_data['form-0-action'] = action

        response = self.client.post(self.url, formset_data)
        self.assert3xx(response, self.url)

    def test_skip(self):
        self.setup_actions(ratings.REVIEW_MODERATE_SKIP)

        # Make sure it's still there.
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        rows = doc('#reviews-flagged .review-flagged:not(.review-saved)')
        assert rows.length == 1

    def test_skip_score(self):
        self.setup_actions(ratings.REVIEW_MODERATE_SKIP)
        assert ReviewerScore.objects.filter(
            note_key=amo.REVIEWED_ADDON_REVIEW).count() == 0

    def get_logs(self, action):
        return ActivityLog.objects.filter(action=action.id)

    def test_remove(self):
        """Make sure the reviewer tools can delete a review."""
        self.setup_actions(ratings.REVIEW_MODERATE_DELETE)
        logs = self.get_logs(amo.LOG.DELETE_RATING)
        assert logs.count() == 1

        # Make sure it's removed from the queue.
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert pq(response.content)('#reviews-flagged .no-results').length == 1

        response = self.client.get(reverse('reviewers.eventlog'))
        assert pq(response.content)('table .more-details').attr('href') == (
            reverse('reviewers.eventlog.detail', args=[logs[0].id]))

        # Make sure it was actually deleted.
        assert Rating.objects.filter(addon=1865).count() == 1
        # But make sure it wasn't *actually* deleted.
        assert Rating.unfiltered.filter(addon=1865).count() == 2

    def test_remove_fails_for_own_addon(self):
        """
        Make sure the reviewer tools can't delete a review for an
        add-on owned by the user.
        """
        addon = Addon.objects.get(pk=1865)
        user = UserProfile.objects.get(email='reviewer@mozilla.com')
        AddonUser(addon=addon, user=user).save()

        # Make sure the initial count is as expected
        assert Rating.objects.filter(addon=1865).count() == 2

        self.setup_actions(ratings.REVIEW_MODERATE_DELETE)
        logs = self.get_logs(amo.LOG.DELETE_RATING)
        assert logs.count() == 0

        # Make sure it's not removed from the queue.
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert pq(response.content)('#reviews-flagged .no-results').length == 0

        # Make sure it was not actually deleted.
        assert Rating.objects.filter(addon=1865).count() == 2

    def test_remove_score(self):
        self.setup_actions(ratings.REVIEW_MODERATE_DELETE)
        assert ReviewerScore.objects.filter(
            note_key=amo.REVIEWED_ADDON_REVIEW).count() == 1

    def test_keep(self):
        """Make sure the reviewer tools can remove flags and keep a review."""
        self.setup_actions(ratings.REVIEW_MODERATE_KEEP)
        logs = self.get_logs(amo.LOG.APPROVE_RATING)
        assert logs.count() == 1

        # Make sure it's removed from the queue.
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert pq(response.content)('#reviews-flagged .no-results').length == 1

        rating = Rating.objects.filter(addon=1865)

        # Make sure it's NOT deleted...
        assert rating.count() == 2

        # ...but it's no longer flagged.
        assert rating.filter(editorreview=1).count() == 0

    def test_keep_score(self):
        self.setup_actions(ratings.REVIEW_MODERATE_KEEP)
        assert ReviewerScore.objects.filter(
            note_key=amo.REVIEWED_ADDON_REVIEW).count() == 1

    def test_queue_layout(self):
        # From the fixtures we already have 2 reviews, one is flagged. We add
        # a bunch of reviews from different scenarios and make sure they don't
        # count towards the total.
        # Add a review associated with an normal addon
        rating = Rating.objects.create(
            addon=addon_factory(), user=user_factory(),
            body='show me', editorreview=True)
        RatingFlag.objects.create(rating=rating)

        # Add a review associated with an incomplete addon
        rating = Rating.objects.create(
            addon=addon_factory(status=amo.STATUS_NULL), user=user_factory(),
            title='please', body='dont show me', editorreview=True)
        RatingFlag.objects.create(rating=rating)

        # Add a review associated to an unlisted version
        addon = addon_factory()
        version = version_factory(
            addon=addon, channel=amo.RELEASE_CHANNEL_UNLISTED)
        rating = Rating.objects.create(
            addon=addon_factory(), version=version, user=user_factory(),
            title='please', body='dont show me either', editorreview=True)
        RatingFlag.objects.create(rating=rating)

        self._test_queue_layout('Rating Reviews',
                                tab_position=2, total_addons=2, total_queues=3)

    def test_no_reviews(self):
        Rating.objects.all().delete()

        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)('#reviews-flagged')

        assert doc('.no-results').length == 1
        assert doc('.review-saved button').length == 1  # Show only one button.

    def test_do_not_show_reviews_for_non_public_addons(self):
        Addon.objects.all().update(status=amo.STATUS_NULL)

        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)('#reviews-flagged')

        # There should be no results since all add-ons are not public.
        assert doc('.no-results').length == 1

    def test_do_not_show_reviews_for_unlisted_addons(self):
        for addon in Addon.objects.all():
            self.make_addon_unlisted(addon)

        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)('#reviews-flagged')

        # There should be no results since all add-ons are unlisted.
        assert doc('.no-results').length == 1


class TestUnlistedAllList(QueueTest):
    listed = False

    def setUp(self):
        super(TestUnlistedAllList, self).setUp()
        self.url = reverse('reviewers.unlisted_queue_all')
        # We should have all add-ons.
        self.expected_addons = self.get_expected_addons_by_names(
            ['Pending One', 'Pending Two', 'Nominated One', 'Nominated Two',
             'Public'])
        # Need to set unique nomination times or we get a psuedo-random order.
        for idx, addon in enumerate(self.expected_addons):
            latest_version = addon.find_latest_version(
                channel=amo.RELEASE_CHANNEL_UNLISTED)
            latest_version.update(
                nomination=(datetime.now() - timedelta(minutes=idx)))

    def test_results(self):
        self._test_results()

    def test_review_notes_json(self):
        latest_version = self.expected_addons[0].find_latest_version(
            channel=amo.RELEASE_CHANNEL_UNLISTED)
        log = ActivityLog.create(amo.LOG.APPROVE_VERSION,
                                 latest_version,
                                 self.expected_addons[0],
                                 user=UserProfile.objects.get(pk=999),
                                 details={'comments': 'stish goin` down son'})
        url = reverse('reviewers.queue_review_text') + str(log.id)
        response = self.client.get(url)
        assert response.status_code == 200
        assert (json.loads(response.content) ==
                {'reviewtext': 'stish goin` down son'})


class TestAutoApprovedQueue(QueueTest):

    def setUp(self):
        super(TestAutoApprovedQueue, self).setUp()
        self.url = reverse('reviewers.queue_auto_approved')

    def login_with_permission(self):
        user = UserProfile.objects.get(email='reviewer@mozilla.com')
        self.grant_permission(user, 'Addons:PostReview')
        self.client.login(email=user.email)

    def get_addon_latest_version(self, addon):
        """Method used by _test_results() to fetch the version that the queue
        is supposed to display. Overridden here because in our case, it's not
        necessarily the latest available version - we display the current
        public version instead (which is not guaranteed to be the latest
        auto-approved one, but good enough) for this page."""
        return addon.current_version

    def generate_files(self):
        """Generate add-ons needed for these tests."""
        # Has not been auto-approved.
        extra_addon = addon_factory(name=u'Extra Addôn 1')
        AutoApprovalSummary.objects.create(
            version=extra_addon.current_version, verdict=amo.NOT_AUTO_APPROVED)
        # Has not been auto-approved either, only dry run.
        extra_addon2 = addon_factory(name=u'Extra Addôn 2')
        AutoApprovalSummary.objects.create(
            version=extra_addon2.current_version,
            verdict=amo.WOULD_HAVE_BEEN_AUTO_APPROVED)
        # Has been auto-approved, but that auto-approval has been confirmed by
        # a human already.
        extra_addon3 = addon_factory(name=u'Extra Addôn 3')
        extra_summary3 = AutoApprovalSummary.objects.create(
            version=extra_addon3.current_version,
            verdict=amo.AUTO_APPROVED, confirmed=True)
        AddonApprovalsCounter.objects.create(
            addon=extra_addon3, counter=1,
            last_human_review=extra_summary3.created)

        # Has been auto-approved and reviewed by a human before.
        addon1 = addon_factory(name=u'Addôn 1')
        AutoApprovalSummary.objects.create(
            version=addon1.current_version, verdict=amo.AUTO_APPROVED)
        AddonApprovalsCounter.objects.create(
            addon=addon1, counter=1, last_human_review=self.days_ago(42))

        # Has been auto-approved twice, last_human_review is somehow None,
        # the 'created' date will be used to order it (older is higher).
        addon2 = addon_factory(name=u'Addôn 2')
        addon2.update(created=self.days_ago(10))
        AutoApprovalSummary.objects.create(
            version=addon2.current_version, verdict=amo.AUTO_APPROVED)
        AddonApprovalsCounter.objects.create(
            addon=addon2, counter=1, last_human_review=None)
        addon2_version2 = version_factory(addon=addon2)
        AutoApprovalSummary.objects.create(
            version=addon2_version2, verdict=amo.AUTO_APPROVED)

        # Has been auto-approved and never been seen by a human,
        # the 'created' date will be used to order it (newer is lower).
        addon3 = addon_factory(name=u'Addôn 3')
        addon3.update(created=self.days_ago(2))
        AutoApprovalSummary.objects.create(
            version=addon3.current_version, verdict=amo.AUTO_APPROVED)
        AddonApprovalsCounter.objects.create(
            addon=addon3, counter=1, last_human_review=None)

        # Has been auto-approved, should be first because of its weight.
        addon4 = addon_factory(name=u'Addôn 4')
        addon4.update(created=self.days_ago(14))
        AutoApprovalSummary.objects.create(
            version=addon4.current_version, verdict=amo.AUTO_APPROVED,
            weight=500)
        AddonApprovalsCounter.objects.create(
            addon=addon4, counter=0, last_human_review=self.days_ago(1))
        self.expected_addons = [addon4, addon2, addon3, addon1]

    def test_only_viewable_with_specific_permission(self):
        # Regular addon reviewer does not have access.
        response = self.client.get(self.url)
        assert response.status_code == 403

        # Regular user doesn't have access.
        self.client.logout()
        assert self.client.login(email='regular@mozilla.com')
        response = self.client.get(self.url)
        assert response.status_code == 403

    def test_results(self):
        self.login_with_permission()
        self.generate_files()
        self._test_results()

    def test_results_weights(self):
        addon1 = addon_factory(name=u'Addôn 1')
        AutoApprovalSummary.objects.create(
            version=addon1.current_version, verdict=amo.AUTO_APPROVED,
            weight=amo.POST_REVIEW_WEIGHT_HIGHEST_RISK + 1)
        AddonApprovalsCounter.reset_for_addon(addon1)

        addon2 = addon_factory(name=u'Addôn 2')
        AutoApprovalSummary.objects.create(
            version=addon2.current_version, verdict=amo.AUTO_APPROVED,
            weight=amo.POST_REVIEW_WEIGHT_HIGH_RISK + 1)
        AddonApprovalsCounter.reset_for_addon(addon2)

        addon3 = addon_factory(name=u'Addôn 3')
        AutoApprovalSummary.objects.create(
            version=addon3.current_version, verdict=amo.AUTO_APPROVED,
            weight=amo.POST_REVIEW_WEIGHT_MEDIUM_RISK + 1)
        AddonApprovalsCounter.reset_for_addon(addon3)

        addon4 = addon_factory(name=u'Addôn 4')
        AutoApprovalSummary.objects.create(
            version=addon4.current_version, verdict=amo.AUTO_APPROVED,
            weight=1)
        AddonApprovalsCounter.reset_for_addon(addon4)

        self.expected_addons = [addon1, addon2, addon3, addon4]

        self.login_with_permission()
        doc = self._test_results()
        expected = ['risk-highest', 'risk-high', 'risk-medium', 'risk-low']
        classnames = [
            item.attrib['class'] for item in doc('.addon-row td:eq(4) span')]
        assert expected == classnames

    def test_queue_layout(self):
        self.login_with_permission()
        self.generate_files()

        self._test_queue_layout("Auto Approved",
                                tab_position=2, total_addons=4, total_queues=3,
                                per_page=1)


class TestExpiredInfoRequestsQueue(QueueTest):

    def setUp(self):
        super(TestExpiredInfoRequestsQueue, self).setUp()
        self.url = reverse('reviewers.queue_expired_info_requests')

    def generate_files(self):
        # Extra add-on with no pending info request.
        addon_factory(name=u'Extra Addôn 1')

        # Extra add-on with a non-expired pending info request.
        extra_addon = addon_factory(name=u'Extra Addôn 2')
        AddonReviewerFlags.objects.create(
            addon=extra_addon,
            pending_info_request=datetime.now() + timedelta(days=1))

        # Addon with expired info request 1.
        addon1 = addon_factory(name=u'Addön 1')
        AddonReviewerFlags.objects.create(
            addon=addon1,
            pending_info_request=self.days_ago(2))

        # Addon with expired info request 2.
        addon2 = addon_factory(name=u'Addön 2')
        AddonReviewerFlags.objects.create(
            addon=addon2,
            pending_info_request=self.days_ago(42))

        self.expected_addons = [addon2, addon1]

    def test_results_no_permission(self):
        # Addon reviewer doesn't have access.
        response = self.client.get(self.url)
        assert response.status_code == 403

        # Regular user doesn't have access.
        self.client.logout()
        assert self.client.login(email='regular@mozilla.com')
        response = self.client.get(self.url)
        assert response.status_code == 403

    def test_results(self):
        self.grant_permission(self.user, 'Reviews:Admin')
        self.generate_files()
        self._test_results()


class TestContentReviewQueue(QueueTest):

    def setUp(self):
        super(TestContentReviewQueue, self).setUp()
        self.url = reverse('reviewers.queue_content_review')
        self.channel_name = 'content'

    def login_with_permission(self):
        user = UserProfile.objects.get(email='reviewer@mozilla.com')
        self.grant_permission(user, 'Addons:ContentReview')
        self.client.login(email=user.email)
        return user

    def get_addon_latest_version(self, addon):
        """Method used by _test_results() to fetch the version that the queue
        is supposed to display. Overridden here because in our case, it's not
        necessarily the latest available version - we display the current
        public version instead (which is not guaranteed to be the latest
        auto-approved one, but good enough) for this page."""
        return addon.current_version

    def generate_files(self):
        """Generate add-ons needed for these tests."""
        # Has not been auto-approved.
        extra_addon = addon_factory(name=u'Extra Addôn 1')
        AutoApprovalSummary.objects.create(
            version=extra_addon.current_version, verdict=amo.NOT_AUTO_APPROVED,
        )
        # Has not been auto-approved either, only dry run.
        extra_addon2 = addon_factory(name=u'Extra Addôn 2')
        AutoApprovalSummary.objects.create(
            version=extra_addon2.current_version,
            verdict=amo.WOULD_HAVE_BEEN_AUTO_APPROVED,
        )
        # Has been auto-approved, but that content has been approved by
        # a human already.
        extra_addon3 = addon_factory(name=u'Extra Addôn 3')
        AutoApprovalSummary.objects.create(
            version=extra_addon3.current_version,
            verdict=amo.AUTO_APPROVED, confirmed=True)
        AddonApprovalsCounter.objects.create(
            addon=extra_addon3, last_content_review=self.days_ago(1))

        # This one has never been content-reviewed, but it has the
        # needs_admin_content_review flag, and we're not an admin.
        extra_addon4 = addon_factory(name=u'Extra Addön 4')
        extra_addon4.update(created=self.days_ago(2))
        AutoApprovalSummary.objects.create(
            version=extra_addon4.current_version,
            verdict=amo.AUTO_APPROVED, confirmed=True)
        AddonApprovalsCounter.objects.create(
            addon=extra_addon4, last_content_review=None)
        AddonReviewerFlags.objects.create(
            addon=extra_addon4, needs_admin_content_review=True)

        # This first add-on has been content reviewed so long ago that we
        # should do it again.
        addon1 = addon_factory(name=u'Addön 1')
        AutoApprovalSummary.objects.create(
            version=addon1.current_version,
            verdict=amo.AUTO_APPROVED, confirmed=True)
        AddonApprovalsCounter.objects.create(
            addon=addon1, last_content_review=self.days_ago(370))

        # This one is quite similar, except its last content review is even
        # older..
        addon2 = addon_factory(name=u'Addön 1')
        AutoApprovalSummary.objects.create(
            version=addon2.current_version,
            verdict=amo.AUTO_APPROVED, confirmed=True)
        AddonApprovalsCounter.objects.create(
            addon=addon2, last_content_review=self.days_ago(842))

        # This one has never been content-reviewed. It has an
        # needs_admin_code_review flag, but that should not have any impact.
        addon3 = addon_factory(name=u'Addön 2')
        addon3.update(created=self.days_ago(2))
        AutoApprovalSummary.objects.create(
            version=addon3.current_version,
            verdict=amo.AUTO_APPROVED, confirmed=True)
        AddonApprovalsCounter.objects.create(
            addon=addon3, last_content_review=None)
        AddonReviewerFlags.objects.create(
            addon=addon3, needs_admin_code_review=True)

        # This one has never been content reviewed either, and it does not even
        # have an AddonApprovalsCounter.
        addon4 = addon_factory(name=u'Addön 3')
        addon4.update(created=self.days_ago(1))
        AutoApprovalSummary.objects.create(
            version=addon4.current_version,
            verdict=amo.AUTO_APPROVED, confirmed=True)
        assert not AddonApprovalsCounter.objects.no_cache().filter(
            addon=addon4).exists()

        # Addons with no last_content_review date should be first, ordered by
        # their creation date, older first.
        self.expected_addons = [addon3, addon4, addon2, addon1]

    def test_only_viewable_with_specific_permission(self):
        # Regular addon reviewer does not have access.
        response = self.client.get(self.url)
        assert response.status_code == 403

        # Regular user doesn't have access.
        self.client.logout()
        assert self.client.login(email='regular@mozilla.com')
        response = self.client.get(self.url)
        assert response.status_code == 403

    def test_results(self):
        self.login_with_permission()
        self.generate_files()
        self._test_results()

    def test_queue_layout(self):
        self.login_with_permission()
        self.generate_files()

        self._test_queue_layout('Content Review',
                                tab_position=2, total_addons=4, total_queues=3,
                                per_page=1)

    def test_queue_layout_admin(self):
        # Admins should see the extra add-on that needs admin content review.
        user = self.login_with_permission()
        self.grant_permission(user, 'Reviews:Admin')
        self.generate_files()

        self._test_queue_layout('Content Review',
                                tab_position=2, total_addons=5, total_queues=4)


class TestPerformance(QueueTest):
    fixtures = ['base/users', 'base/addon_3615']

    """Test the page at /reviewers/performance."""

    def setUpReviewer(self):
        self.login_as_reviewer()
        core.set_user(UserProfile.objects.get(username='reviewer'))
        self.create_logs()

    def setUpAdmin(self):
        self.login_as_admin()
        core.set_user(UserProfile.objects.get(username='admin'))
        self.create_logs()

    def get_url(self, args=None):
        if args is None:
            args = []
        return reverse('reviewers.performance', args=args)

    def create_logs(self):
        addon = Addon.objects.all()[0]
        version = addon.versions.all()[0]
        for i in amo.LOG_REVIEWER_REVIEW_ACTION:
            ActivityLog.create(amo.LOG_BY_ID[i], addon, version)
        # Throw in an automatic approval - should be ignored.
        ActivityLog.create(
            amo.LOG.APPROVE_VERSION, addon, version,
            user=UserProfile.objects.get(id=settings.TASK_USER_ID))

    def _test_chart(self):
        r = self.client.get(self.get_url())
        assert r.status_code == 200
        doc = pq(r.content)

        num = len(amo.LOG_REVIEWER_REVIEW_ACTION)
        label = datetime.now().strftime('%Y-%m')
        data = {label: {u'teamcount': num, u'teamavg': u'%s.0' % num,
                        u'usercount': num, u'teamamt': 1,
                        u'label': datetime.now().strftime('%b %Y')}}

        assert json.loads(doc('#monthly').attr('data-chart')) == data

    def test_performance_chart_reviewer(self):
        self.setUpReviewer()
        self._test_chart()

    def test_performance_chart_as_admin(self):
        self.setUpAdmin()
        self._test_chart()

    def test_usercount_with_more_than_one_reviewer(self):
        self.client.login(email='clouserw@gmail.com')
        core.set_user(UserProfile.objects.get(username='clouserw'))
        self.create_logs()
        self.setUpReviewer()
        r = self.client.get(self.get_url())
        assert r.status_code == 200
        doc = pq(r.content)
        data = json.loads(doc('#monthly').attr('data-chart'))
        label = datetime.now().strftime('%Y-%m')
        assert data[label]['usercount'] == len(amo.LOG_REVIEWER_REVIEW_ACTION)

    def _test_performance_other_user_as_admin(self):
        userid = core.get_user().pk

        r = self.client.get(self.get_url([10482]))
        doc = pq(r.content)

        assert doc('#select_user').length == 1  # Let them choose reviewers.
        options = doc('#select_user option')
        assert options.length == 3
        assert options.eq(2).val() == str(userid)

        assert 'clouserw' in doc('#reviews_user').text()

    def test_performance_other_user_as_admin(self):
        self.setUpAdmin()

        self._test_performance_other_user_as_admin()

    def test_performance_other_user_not_admin(self):
        self.setUpReviewer()

        r = self.client.get(self.get_url([10482]))
        doc = pq(r.content)

        assert doc('#select_user').length == 0  # Don't let them choose.
        assert doc('#reviews_user').text() == 'Your Reviews'


class SearchTest(ReviewerTest):
    listed = True

    def setUp(self):
        super(SearchTest, self).setUp()
        self.user = UserProfile.objects.get(email='reviewer@mozilla.com')
        self.login_as_reviewer()
        if self.listed is False:
            # Testing unlisted views: needs Addons:ReviewUnlisted perm.
            self.grant_permission(self.user, 'Addons:ReviewUnlisted')

    def named_addons(self, request):
        return [
            r.record.addon_name for r in request.context['page'].object_list]

    def search(self, *args, **kw):
        response = self.client.get(self.url, kw)
        assert response.status_code == 200
        assert response.context['search_form'].errors.as_text() == ''
        return response


class BaseTestQueueSearch(SearchTest):
    fixtures = ['base/users', 'base/appversion']
    __test__ = False  # this is an abstract test case

    def generate_files(self, subset=None):
        if subset is None:
            subset = []
        files = OrderedDict([
            ('Not Needing Admin Review', {
                'version_str': '0.1',
                'addon_status': amo.STATUS_NOMINATED,
                'file_status': amo.STATUS_AWAITING_REVIEW,
            }),
            ('Another Not Needing Admin Review', {
                'version_str': '0.1',
                'addon_status': amo.STATUS_NOMINATED,
                'file_status': amo.STATUS_AWAITING_REVIEW,
            }),
            ('Needs Admin Review', {
                'version_str': '0.1',
                'addon_status': amo.STATUS_NOMINATED,
                'file_status': amo.STATUS_AWAITING_REVIEW,
                'needs_admin_code_review': True,
            }),
            ('Justin Bieber Theme', {
                'version_str': '0.1',
                'addon_status': amo.STATUS_NOMINATED,
                'file_status': amo.STATUS_AWAITING_REVIEW,
                'type': amo.ADDON_THEME,
            }),
            ('Justin Bieber Search Bar', {
                'version_str': '0.1',
                'addon_status': amo.STATUS_NOMINATED,
                'file_status': amo.STATUS_AWAITING_REVIEW,
                'type': amo.ADDON_SEARCH,
            }),
            ('Bieber For Mobile', {
                'version_str': '0.1',
                'addon_status': amo.STATUS_NOMINATED,
                'file_status': amo.STATUS_AWAITING_REVIEW,
                'version_kw': {'application': amo.ANDROID.id},
            }),
            ('Linux Widget', {
                'version_str': '0.1',
                'addon_status': amo.STATUS_NOMINATED,
                'file_status': amo.STATUS_AWAITING_REVIEW,
            }),
            ('Mac Widget', {
                'version_str': '0.1',
                'addon_status': amo.STATUS_NOMINATED,
                'file_status': amo.STATUS_AWAITING_REVIEW,
            }),
            ('Deleted', {
                'version_str': '0.1',
                'addon_status': amo.STATUS_DELETED,
                'file_status': amo.STATUS_AWAITING_REVIEW,
            }),
        ])
        results = {}
        channel = (amo.RELEASE_CHANNEL_LISTED if self.listed else
                   amo.RELEASE_CHANNEL_UNLISTED)
        for name, attrs in files.iteritems():
            if not subset or name in subset:
                version_kw = attrs.get('version_kw', {})
                version_kw.update(
                    {'channel': channel, 'version': attrs.pop('version_str')})
                attrs['version_kw'] = version_kw
                file_kw = attrs.get('file_kw', {})
                file_kw.update({'status': attrs.pop('file_status')})
                attrs['file_kw'] = file_kw
                attrs.update({'version_kw': version_kw, 'file_kw': file_kw})
                needs_admin_code_review = attrs.pop(
                    'needs_admin_code_review', None)
                results[name] = addon_factory(
                    status=attrs.pop('addon_status'), name=name, **attrs)
                if needs_admin_code_review:
                    AddonReviewerFlags.objects.create(
                        addon=results[name], needs_admin_code_review=True)
        return results

    def generate_file(self, name):
        return self.generate_files([name])[name]

    def test_search_by_needs_admin_code_review_admin(self):
        self.login_as_admin()
        self.generate_files(['Not Needing Admin Review', 'Needs Admin Review'])
        response = self.search(needs_admin_code_review=1)
        assert response.status_code == 200
        assert self.named_addons(response) == ['Needs Admin Review']

    def test_queue_counts_admin(self):
        self.login_as_admin()
        self.generate_files(['Not Needing Admin Review', 'Needs Admin Review'])
        response = self.search(text_query='admin', per_page=1)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('.data-grid-top .num-results').text() == (
            u'Results 1\u20131 of 2')

    def test_search_by_addon_name_admin(self):
        self.login_as_admin()
        self.generate_files(['Not Needing Admin Review', 'Needs Admin Review',
                             'Justin Bieber Theme'])
        response = self.search(text_query='admin')
        assert response.status_code == 200
        assert sorted(self.named_addons(response)) == [
            'Needs Admin Review', 'Not Needing Admin Review']

    def test_not_searching(self, **kwargs):
        self.generate_files(['Not Needing Admin Review', 'Needs Admin Review'])
        response = self.search(**kwargs)
        assert response.status_code == 200
        assert sorted(self.named_addons(response)) == [
            'Not Needing Admin Review']
        # We were just displaying the queue, not searching, but the searching
        # hidden input in the form should always be set to True regardless, it
        # will be used once the user submits the form.
        doc = pq(response.content)
        assert doc('#id_searching').attr('value') == 'True'

    def test_not_searching_with_param(self):
        self.test_not_searching(some_param=1)

    def test_search_by_nothing(self):
        self.generate_files(['Not Needing Admin Review', 'Needs Admin Review'])
        response = self.search(searching='True')
        assert response.status_code == 200
        assert sorted(self.named_addons(response)) == (
            ['Needs Admin Review', 'Not Needing Admin Review'])

    def test_search_by_needs_admin_code_review(self):
        self.generate_files(['Not Needing Admin Review', 'Needs Admin Review'])
        response = self.search(needs_admin_code_review=1, searching='True')
        assert response.status_code == 200
        assert self.named_addons(response) == ['Needs Admin Review']

    def test_queue_counts(self):
        self.generate_files(['Not Needing Admin Review',
                             'Another Not Needing Admin Review',
                             'Needs Admin Review'])
        response = self.search(
            text_query='admin', per_page=1, searching='True')
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('.data-grid-top .num-results').text() == (
            u'Results 1\u20131 of 3')

    def test_search_by_addon_name(self):
        self.generate_files(['Not Needing Admin Review', 'Needs Admin Review',
                             'Justin Bieber Theme'])
        response = self.search(text_query='admin', searching='True')
        assert response.status_code == 200
        assert sorted(self.named_addons(response)) == (
            ['Needs Admin Review', 'Not Needing Admin Review'])

    def test_search_by_addon_in_locale(self):
        name = 'Not Needing Admin Review'
        generated = self.generate_file(name)
        uni = 'フォクすけといっしょ'.decode('utf8')
        addon = Addon.objects.get(pk=generated.id)
        addon.name = {'ja': uni}
        addon.save()
        self.url = self.url.replace('/en-US/', '/ja/')
        response = self.client.get(self.url, {'text_query': uni}, follow=True)
        assert response.status_code == 200
        assert self.named_addons(response) == [name]

    def test_search_by_addon_author(self):
        name = 'Not Needing Admin Review'
        generated = self.generate_file(name)
        user = UserProfile.objects.all()[0]
        email = user.email.swapcase()
        author = AddonUser.objects.create(user=user, addon=generated)
        for role in [amo.AUTHOR_ROLE_OWNER, amo.AUTHOR_ROLE_DEV]:
            author.role = role
            author.save()
            response = self.search(text_query=email)
            assert response.status_code == 200
            assert self.named_addons(response) == [name]

    def test_search_by_supported_email_in_locale(self):
        name = 'Not Needing Admin Review'
        generated = self.generate_file(name)
        uni = 'フォクすけといっしょ@site.co.jp'.decode('utf8')
        addon = Addon.objects.get(pk=generated.id)
        addon.support_email = {'ja': uni}
        addon.save()
        self.url = self.url.replace('/en-US/', '/ja/')
        response = self.client.get(self.url, {'text_query': uni}, follow=True)
        assert response.status_code == 200
        assert self.named_addons(response) == [name]

    def test_clear_search_visible(self):
        response = self.search(text_query='admin', searching=True)
        assert response.status_code == 200
        assert pq(response.content)(
            '.clear-queue-search').text() == 'clear search'

    def test_clear_search_hidden(self):
        response = self.search(text_query='admin')
        assert response.status_code == 200
        assert not pq(response.content)('.clear-queue-search').text()


class TestQueueSearch(BaseTestQueueSearch):
    __test__ = True

    def setUp(self):
        super(TestQueueSearch, self).setUp()
        self.url = reverse('reviewers.queue_nominated')

    def test_search_by_addon_type(self):
        self.generate_files(['Not Needing Admin Review', 'Justin Bieber Theme',
                             'Justin Bieber Search Bar'])
        response = self.search(addon_type_ids=[amo.ADDON_THEME])
        assert response.status_code == 200
        assert self.named_addons(response) == ['Justin Bieber Theme']

    def test_search_by_addon_type_any(self):
        self.generate_file('Not Needing Admin Review')
        response = self.search(addon_type_ids=[amo.ADDON_ANY])
        assert response.status_code == 200
        assert self.named_addons(response), 'Expected some add-ons'

    def test_search_by_many_addon_types(self):
        self.generate_files(['Not Needing Admin Review', 'Justin Bieber Theme',
                             'Justin Bieber Search Bar'])
        response = self.search(addon_type_ids=[amo.ADDON_THEME,
                                               amo.ADDON_SEARCH])
        assert response.status_code == 200
        assert sorted(self.named_addons(response)) == (
            ['Justin Bieber Search Bar', 'Justin Bieber Theme'])

    def test_search_by_app(self):
        self.generate_files(['Bieber For Mobile', 'Linux Widget'])
        response = self.search(application_id=[amo.ANDROID.id])
        assert response.status_code == 200
        assert self.named_addons(response) == ['Bieber For Mobile']

    def test_preserve_multi_apps(self):
        self.generate_files(['Bieber For Mobile', 'Linux Widget'])
        channel = (amo.RELEASE_CHANNEL_LISTED if self.listed else
                   amo.RELEASE_CHANNEL_UNLISTED)
        multi = addon_factory(
            status=amo.STATUS_NOMINATED, name='Multi Application',
            version_kw={'channel': channel, 'application': amo.FIREFOX.id},
            file_kw={'status': amo.STATUS_AWAITING_REVIEW})

        av_min, _ = AppVersion.objects.get_or_create(
            application=amo.ANDROID.id, version='4.0.99')
        av_max, _ = AppVersion.objects.get_or_create(
            application=amo.ANDROID.id, version='5.0.0')
        ApplicationsVersions.objects.get_or_create(
            application=amo.ANDROID.id, version=multi.versions.latest(),
            min=av_min, max=av_max)

        response = self.search(application_id=[amo.ANDROID.id])
        assert response.status_code == 200
        assert self.named_addons(response) == [
            'Bieber For Mobile', 'Multi Application']

    def test_clear_search_uses_correct_queue(self):
        # The "clear search" link points to the right listed or unlisted queue.
        # Listed queue.
        url = reverse('reviewers.queue_nominated')
        response = self.client.get(
            url, {'text_query': 'admin', 'searching': True})
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('.clear-queue-search').attr('href') == url


class TestQueueSearchUnlistedAllList(BaseTestQueueSearch):
    listed = False
    __test__ = True

    def setUp(self):
        super(TestQueueSearchUnlistedAllList, self).setUp()
        self.url = reverse('reviewers.unlisted_queue_all')

    def test_search_deleted(self):
        self.generate_files(['Not Needing Admin Review', 'Deleted'])
        r = self.search(deleted=1)
        assert self.named_addons(r) == ['Deleted']

    def test_search_not_deleted(self):
        self.generate_files(['Not Needing Admin Review', 'Deleted'])
        response = self.search(deleted=0)
        assert response.status_code == 200
        assert self.named_addons(response) == ['Not Needing Admin Review']

    def test_search_by_guid(self):
        name = 'Not Needing Admin Review'
        addon = self.generate_file(name)
        addon.update(guid='@guidymcguid')
        response = self.search(text_query='mcguid')
        assert response.status_code == 200
        assert self.named_addons(response) == ['Not Needing Admin Review']


class ReviewBase(QueueTest):

    def setUp(self):
        super(QueueTest, self).setUp()
        self.login_as_reviewer()
        self.addons = {}

        self.addon = self.generate_file('Public')
        self.version = self.addon.current_version
        self.file = self.version.files.get()
        self.reviewer = UserProfile.objects.get(username='reviewer')
        self.reviewer.update(display_name=u'A Reviêwer')
        self.url = reverse('reviewers.review', args=[self.addon.slug])

        AddonUser.objects.create(addon=self.addon, user_id=999)

    def get_addon(self):
        return Addon.objects.get(pk=self.addon.pk)

    def get_dict(self, **kw):
        data = {'operating_systems': 'win', 'applications': 'something',
                'comments': 'something'}
        data.update(kw)
        return data


class TestReview(ReviewBase):

    def test_reviewer_required(self):
        assert self.client.head(self.url).status_code == 200

    def test_not_anonymous(self):
        self.client.logout()
        self.assertLoginRedirects(self.client.head(self.url), to=self.url)

    @patch.object(settings, 'ALLOW_SELF_REVIEWS', False)
    def test_not_author(self):
        AddonUser.objects.create(addon=self.addon, user=self.reviewer)
        assert self.client.head(self.url).status_code == 302

    def test_review_unlisted_while_a_listed_version_is_awaiting_review(self):
        self.make_addon_unlisted(self.addon)
        version_factory(
            addon=self.addon, channel=amo.RELEASE_CHANNEL_LISTED,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW})
        self.addon.update(status=amo.STATUS_NOMINATED, slug='awaiting')
        self.url = reverse(
            'reviewers.review', args=('unlisted', self.addon.slug))
        self.grant_permission(self.reviewer, 'Addons:ReviewUnlisted')
        assert self.client.get(self.url).status_code == 200

    def test_needs_unlisted_reviewer_for_only_unlisted(self):
        self.addon.versions.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        assert self.client.head(self.url).status_code == 404
        self.grant_permission(self.reviewer, 'Addons:ReviewUnlisted')
        assert self.client.head(self.url).status_code == 200

    def test_dont_need_unlisted_reviewer_for_mixed_channels(self):
        version_factory(
            addon=self.addon, channel=amo.RELEASE_CHANNEL_UNLISTED,
            version='9.9')

        assert self.addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_UNLISTED)
        assert self.addon.current_version.channel == amo.RELEASE_CHANNEL_LISTED
        assert self.client.head(self.url).status_code == 200
        self.grant_permission(self.reviewer, 'Addons:ReviewUnlisted')
        assert self.client.head(self.url).status_code == 200

    def test_not_flags(self):
        self.addon.current_version.files.update(is_restart_required=False)
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert len(response.context['flags']) == 0

    def test_flag_needs_admin_code_review(self):
        self.addon.current_version.files.update(is_restart_required=False)
        AddonReviewerFlags.objects.create(
            addon=self.addon, needs_admin_code_review=True)
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert len(response.context['flags']) == 1

    def test_info_comments_requested(self):
        response = self.client.post(self.url, {'action': 'reply'})
        assert response.context['form'].errors['comments'][0] == (
            'This field is required.')

    def test_whiteboard_url(self):
        # Listed review.
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert (
            doc('#whiteboard_form').attr('action') ==
            '/en-US/reviewers/whiteboard/listed/public')

        # Content review.
        self.grant_permission(self.reviewer, 'Addons:ContentReview')
        AutoApprovalSummary.objects.create(
            version=self.addon.current_version, verdict=amo.AUTO_APPROVED)
        self.url = reverse(
            'reviewers.review', args=['content', self.addon.slug])
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert (
            doc('#whiteboard_form').attr('action') ==
            '/en-US/reviewers/whiteboard/content/public')

        # Unlisted review.
        self.grant_permission(self.reviewer, 'Addons:ReviewUnlisted')
        version_factory(addon=self.addon, channel=amo.RELEASE_CHANNEL_UNLISTED)
        self.url = reverse(
            'reviewers.review', args=['unlisted', self.addon.slug])
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert (
            doc('#whiteboard_form').attr('action') ==
            '/en-US/reviewers/whiteboard/unlisted/public')

        # Listed review, but deleted.
        self.addon.delete()
        self.url = reverse(
            'reviewers.review', args=['listed', self.addon.pk])
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert (
            doc('#whiteboard_form').attr('action') ==
            '/en-US/reviewers/whiteboard/listed/%d' % self.addon.pk)

    def test_no_whiteboards_for_static_themes(self):
        self.grant_permission(self.reviewer, 'Addons:ThemeReview')
        self.addon.update(type=amo.ADDON_STATICTHEME)
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert not doc('#whiteboard_form')

    def test_comment(self):
        response = self.client.post(self.url, {'action': 'comment',
                                               'comments': 'hello sailor'})
        assert response.status_code == 302
        assert len(mail.outbox) == 0

        comment_version = amo.LOG.COMMENT_VERSION
        assert ActivityLog.objects.filter(
            action=comment_version.id).count() == 1

    def test_info_requested(self):
        response = self.client.post(self.url, {'action': 'reply',
                                               'comments': 'hello sailor'})
        assert response.status_code == 302
        assert len(mail.outbox) == 1
        self.assertTemplateUsed(response, 'activity/emails/from_reviewer.txt')

    def test_super_review_requested(self):
        response = self.client.post(self.url, {'action': 'super',
                                               'comments': 'hello sailor'})
        assert response.status_code == 302

    def test_info_requested_canned_response(self):
        response = self.client.post(self.url, {'action': 'reply',
                                               'comments': 'hello sailor',
                                               'canned_response': 'foo'})
        assert response.status_code == 302
        assert len(mail.outbox) == 1
        self.assertTemplateUsed(response, 'activity/emails/from_reviewer.txt')

    def test_page_title(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('title').text() == (
            '%s :: Reviewer Tools :: Add-ons for Firefox' % self.addon.name)

    def test_files_shown(self):
        response = self.client.get(self.url)
        assert response.status_code == 200

        items = pq(response.content)('#review-files .files .file-info')
        assert items.length == 1

        f = self.version.all_files[0]
        expected = [
            ('All Platforms', f.get_url_path('reviewer')),
            ('Validation',
             reverse('devhub.file_validation', args=[self.addon.slug, f.id])),
            ('Contents', None),
        ]
        check_links(expected, items.find('a'), verify=False)

    def test_item_history(self, channel=amo.RELEASE_CHANNEL_LISTED):
        self.addons['something'] = addon_factory(
            status=amo.STATUS_PUBLIC, name=u'something',
            version_kw={'version': u'0.2',
                        'channel': channel},
            file_kw={'status': amo.STATUS_AWAITING_REVIEW})
        assert self.addon.versions.filter(channel=channel).count() == 1
        self.review_version(self.version, self.url)

        v2 = self.addons['something'].versions.all()[0]
        v2.addon = self.addon
        v2.created = v2.created + timedelta(days=1)
        v2.save()
        assert self.addon.versions.filter(channel=channel).count() == 2
        action = self.review_version(v2, self.url)

        response = self.client.get(self.url)
        assert response.status_code == 200
        # The 2 following lines replace pq(res.content), it's a workaround for
        # https://github.com/gawel/pyquery/issues/31
        UTF8_PARSER = HTMLParser(encoding='utf-8')
        doc = pq(fromstring(response.content, parser=UTF8_PARSER))
        table = doc('#review-files')

        # Check the history for both versions.
        ths = table.children('tr > th')
        assert ths.length == 2
        assert '0.1' in ths.eq(0).text()
        assert '0.2' in ths.eq(1).text()

        rows = table('td.files')
        assert rows.length == 2

        comments = rows.siblings('td')
        assert comments.length == 2

        for idx in xrange(comments.length):
            td = comments.eq(idx)
            assert td.find('.history-comment').text() == 'something'
            assert td.find('th').text() == {
                'public': 'Approved',
                'reply': 'Reviewer Reply'}[action]
            reviewer_name = td.find('td a').text()
            assert ((reviewer_name == self.reviewer.display_name) or
                    (reviewer_name == self.other_reviewer.display_name))

    def test_item_history_with_unlisted_versions_too(self):
        # Throw in an unlisted version to be ignored.
        version_factory(
            version=u'0.2', addon=self.addon,
            channel=amo.RELEASE_CHANNEL_UNLISTED,
            file_kw={'status': amo.STATUS_PUBLIC})
        self.test_item_history()

    def test_item_history_with_unlisted_review_page(self):
        self.addon.versions.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        self.version.reload()
        # Throw in an listed version to be ignored.
        version_factory(
            version=u'0.2', addon=self.addon,
            channel=amo.RELEASE_CHANNEL_LISTED,
            file_kw={'status': amo.STATUS_PUBLIC})
        self.url = reverse('reviewers.review', args=[
            'unlisted', self.addon.slug])
        self.grant_permission(self.reviewer, 'Addons:ReviewUnlisted')
        self.test_item_history(channel=amo.RELEASE_CHANNEL_UNLISTED)

    def generate_deleted_versions(self):
        self.addon = addon_factory(version_kw={
            'version': '1.0', 'created': self.days_ago(1)})
        self.url = reverse('reviewers.review', args=[self.addon.slug])

        versions = ({'version': '0.1', 'action': 'comment',
                     'comments': 'millenium hand and shrimp'},
                    {'version': '0.1', 'action': 'public',
                     'comments': 'buggrit'},
                    {'version': '0.2', 'action': 'comment',
                     'comments': 'I told em'},
                    {'version': '0.3'})

        for i, version_data in enumerate(versions):
            version = version_factory(
                addon=self.addon, version=version_data['version'],
                created=self.days_ago(-i),
                file_kw={'status': amo.STATUS_AWAITING_REVIEW})

            if 'action' in version_data:
                data = {'action': version_data['action'],
                        'operating_systems': 'win',
                        'applications': 'something',
                        'comments': version_data['comments']}
                self.client.post(self.url, data)
                version.delete(hard=True)

        self.addon.current_version.delete(hard=True)

    @patch('olympia.reviewers.utils.sign_file')
    def test_item_history_deleted(self, mock_sign):
        self.generate_deleted_versions()

        response = self.client.get(self.url)
        assert response.status_code == 200
        table = pq(response.content)('#review-files')

        # Check the history for all versions.
        ths = table.children('tr > th')
        assert ths.length == 3  # The 2 with the same number will be coalesced.
        assert '0.1' in ths.eq(0).text()
        assert '0.2' in ths.eq(1).text()
        assert '0.3' in ths.eq(2).text()
        for idx in xrange(2):
            assert 'Deleted' in ths.eq(idx).text()

        bodies = table.children('.listing-body')
        assert 'millenium hand and shrimp' in bodies.eq(0).text()
        assert 'buggrit' in bodies.eq(0).text()
        assert 'I told em' in bodies.eq(1).text()

        assert mock_sign.called

    def test_item_history_compat_ordered(self):
        """ Make sure that apps in compatibility are ordered. """
        av = AppVersion.objects.all()[0]
        v = self.addon.versions.all()[0]

        ApplicationsVersions.objects.create(
            version=v, application=amo.THUNDERBIRD.id, min=av, max=av)

        ApplicationsVersions.objects.create(
            version=v, application=amo.SEAMONKEY.id, min=av, max=av)

        assert self.addon.versions.count() == 1
        url = reverse('reviewers.review', args=[self.addon.slug])

        response = self.client.get(url)
        assert response.status_code == 200
        doc = pq(response.content)
        icons = doc('.listing-body .app-icon')
        assert icons.eq(0).attr('title') == "Firefox"
        assert icons.eq(1).attr('title') == "SeaMonkey"
        assert icons.eq(2).attr('title') == "Thunderbird"

    def test_item_history_weight(self):
        """ Make sure the weight is shown on the review page"""
        AutoApprovalSummary.objects.create(
            version=self.version, verdict=amo.AUTO_APPROVED,
            weight=284)
        self.grant_permission(self.reviewer, 'Addons:PostReview')
        url = reverse('reviewers.review', args=[self.addon.slug])
        response = self.client.get(url)
        assert response.status_code == 200
        doc = pq(response.content)
        risk = doc('.listing-body .file-weight')
        assert risk.text() == "Weight: 284"

    def test_item_history_notes(self):
        version = self.addon.versions.all()[0]
        version.releasenotes = 'hi'
        version.approvalnotes = 'secret hi'
        version.save()

        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)('#review-files')

        version = doc('.activity_version')
        assert version.length == 1
        assert version.text() == 'hi'

        approval = doc('.activity_approval')
        assert approval.length == 1
        assert approval.text() == 'secret hi'

    def test_item_history_header(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert ('Approved' in
                doc('#review-files .listing-header .light').text())

    def test_item_history_comment(self):
        # Add Comment.
        self.client.post(self.url, {'action': 'comment',
                                    'comments': 'hello sailor'})

        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)('#review-files')
        assert doc('th').eq(1).text() == 'Commented'
        assert doc('.history-comment').text() == 'hello sailor'

    def test_files_in_item_history(self):
        data = {'action': 'public', 'operating_systems': 'win',
                'applications': 'something', 'comments': 'something'}
        self.client.post(self.url, data)

        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        items = doc('#review-files .files .file-info')
        assert items.length == 1
        assert items.find('a.reviewers-install').text() == 'All Platforms'

    def test_no_items(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#review-files .no-activity').length == 1

    def test_hide_beta(self):
        version = self.addon.current_version
        file_ = version.files.all()[0]
        version.pk = None
        version.version = '0.3beta'
        version.save()

        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#review-files tr.listing-header').length == 2

        file_.pk = None
        file_.status = amo.STATUS_BETA
        file_.version = version
        file_.save()

        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#review-files tr.listing-header').length == 1

    def test_action_links(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        expected = [
            ('View Listing', self.addon.get_url_path()),
        ]
        check_links(expected, doc('#actions-addon a'), verify=False)

    def test_action_links_as_admin(self):
        self.login_as_admin()
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        expected = [
            ('View Listing', self.addon.get_url_path()),
            ('Edit', self.addon.get_dev_url()),
            ('Admin Page',
                reverse('zadmin.addon_manage', args=[self.addon.id])),
        ]
        check_links(expected, doc('#actions-addon a'), verify=False)

    def test_unlisted_addon_action_links_as_admin(self):
        """No "View Listing" link for unlisted addons, "edit"/"manage" links
        for the admins."""
        self.make_addon_unlisted(self.addon)
        self.login_as_admin()
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        expected = [
            ('Unlisted Review Page', reverse(
                'reviewers.review', args=('unlisted', self.addon.slug))),
            ('Edit', self.addon.get_dev_url()),
            ('Admin Page', reverse(
                'zadmin.addon_manage', args=[self.addon.id])),
        ]
        check_links(expected, doc('#actions-addon a'), verify=False)

    def test_mixed_channels_action_links_as_admin(self):
        self.make_addon_unlisted(self.addon)
        version_factory(
            addon=self.addon, channel=amo.RELEASE_CHANNEL_LISTED,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW})
        self.addon.update(status=amo.STATUS_NOMINATED)
        self.login_as_admin()
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        expected = [
            ('View Listing', self.addon.get_url_path()),
            ('Unlisted Review Page', reverse(
                'reviewers.review', args=('unlisted', self.addon.slug))),
            ('Edit', self.addon.get_dev_url()),
            ('Admin Page', reverse(
                'zadmin.addon_manage', args=[self.addon.id])),
        ]
        check_links(expected, doc('#actions-addon a'), verify=False)

    def test_mixed_channels_action_links_as_admin_on_unlisted_review(self):
        self.make_addon_unlisted(self.addon)
        version_factory(
            addon=self.addon, channel=amo.RELEASE_CHANNEL_LISTED,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW})
        self.addon.update(status=amo.STATUS_NOMINATED)
        self.login_as_admin()
        self.url = reverse(
            'reviewers.review', args=('unlisted', self.addon.slug))
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        expected = [
            ('View Listing', self.addon.get_url_path()),
            ('Listed Review Page',
                reverse('reviewers.review', args=(self.addon.slug,))),
            ('Edit', self.addon.get_dev_url()),
            ('Admin Page',
                reverse('zadmin.addon_manage', args=[self.addon.id])),
        ]
        check_links(expected, doc('#actions-addon a'), verify=False)

    def test_mixed_channels_action_links_as_regular_reviewer(self):
        self.make_addon_unlisted(self.addon)
        version_factory(
            addon=self.addon, channel=amo.RELEASE_CHANNEL_LISTED,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW})
        self.addon.update(status=amo.STATUS_NOMINATED)
        self.login_as_reviewer()
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        expected = [
            ('View Listing', self.addon.get_url_path()),
        ]
        check_links(expected, doc('#actions-addon a'), verify=False)

    def test_admin_links_as_non_admin(self):
        self.login_as_reviewer()
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        admin = doc('#actions-addon li')
        assert admin.length == 1

    def test_extra_actions_subscribe_checked_state(self):
        self.login_as_reviewer()
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        subscribe_input = doc('#notify_new_listed_versions')[0]
        assert 'checked' not in subscribe_input.attrib

        ReviewerSubscription.objects.create(
            addon=self.addon, user=self.reviewer)
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        subscribe_input = doc('#notify_new_listed_versions')[0]
        assert subscribe_input.attrib['checked'] == 'checked'

    def test_extra_actions_token(self):
        self.login_as_reviewer()
        self.client.cookies[API_TOKEN_COOKIE] = 'youdidntsaythemagicword'
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        token = doc('#extra-review-actions').attr('data-api-token')
        assert token == 'youdidntsaythemagicword'

    def test_extra_actions_not_for_reviewers(self):
        self.login_as_reviewer()
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert not doc('#force_disable_addon')
        assert not doc('#force_enable_addon')
        assert not doc('#clear_admin_code_review')
        assert not doc('#clear_admin_content_review')
        assert not doc('#disable_auto_approval')
        assert not doc('#enable_auto_approval')
        assert not doc('#clear_pending_info_request')

    def test_extra_actions_admin_disable_enable(self):
        self.login_as_admin()
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#force_disable_addon')
        elem = doc('#force_disable_addon')[0]
        assert 'hidden' not in elem.getparent().attrib.get('class', '')

        assert doc('#force_enable_addon')
        elem = doc('#force_enable_addon')[0]
        assert 'hidden' in elem.getparent().attrib.get('class', '')

    def test_unflag_option_forflagged_as_admin(self):
        self.login_as_admin()
        AddonReviewerFlags.objects.create(
            addon=self.addon, needs_admin_code_review=True)
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#clear_admin_code_review').length == 1
        assert doc('#clear_admin_content_review').length == 0

    def test_unflag_content_option_forflagged_as_admin(self):
        self.login_as_admin()
        AddonReviewerFlags.objects.create(
            addon=self.addon,
            needs_admin_code_review=False,
            needs_admin_content_review=True)
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#clear_admin_code_review').length == 0
        assert doc('#clear_admin_content_review').length == 1

    def test_disable_auto_approvals_as_admin(self):
        self.login_as_admin()
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#disable_auto_approval')
        elem = doc('#disable_auto_approval')[0]
        assert 'hidden' not in elem.getparent().attrib.get('class', '')

        assert doc('#enable_auto_approval')
        elem = doc('#enable_auto_approval')[0]
        assert 'hidden' in elem.getparent().attrib.get('class', '')

        # Both of them should be absent on static themes, which are not
        # auto-approved.
        self.addon.update(type=amo.ADDON_STATICTHEME)
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert not doc('#disable_auto_approval')
        assert not doc('#enable_auto_approval')

    def test_enable_auto_approvals_as_admin_auto_approvals_disabled(self):
        self.login_as_admin()
        AddonReviewerFlags.objects.create(
            addon=self.addon, auto_approval_disabled=True)
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#disable_auto_approval')
        elem = doc('#disable_auto_approval')[0]
        assert 'hidden' in elem.getparent().attrib.get('class', '')

        assert doc('#enable_auto_approval')
        elem = doc('#enable_auto_approval')[0]
        assert 'hidden' not in elem.getparent().attrib.get('class', '')

        # Both of them should be absent on static themes, which are not
        # auto-approved.
        self.addon.update(type=amo.ADDON_STATICTHEME)
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert not doc('#disable_auto_approval')
        assert not doc('#enable_auto_approval')

    def test_clear_pending_info_request_as_admin(self):
        self.login_as_admin()
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert not doc('#clear_pending_info_request')

        AddonReviewerFlags.objects.create(
            addon=self.addon, pending_info_request=self.days_ago(1))
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#clear_pending_info_request')

    def test_info_request_checkbox(self):
        self.login_as_reviewer()
        assert not self.addon.pending_info_request
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert 'checked' not in doc('#id_info_request')[0].attrib
        elm = doc('#id_info_request_deadline')[0]
        assert elm.attrib['readonly'] == 'readonly'
        assert elm.attrib['min'] == '7'
        assert elm.attrib['max'] == '7'
        assert elm.attrib['value'] == '7'

        AddonReviewerFlags.objects.create(
            addon=self.addon,
            pending_info_request=datetime.now() + timedelta(days=7))
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#id_info_request')[0].attrib['checked'] == 'checked'

    def test_info_request_checkbox_admin(self):
        self.login_as_admin()
        assert not self.addon.pending_info_request
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert 'checked' not in doc('#id_info_request')[0].attrib
        elm = doc('#id_info_request_deadline')[0]
        assert 'readonly' not in elm.attrib
        assert elm.attrib['min'] == '1'
        assert elm.attrib['max'] == '99'
        assert elm.attrib['value'] == '7'

    def test_no_public(self):
        has_public = self.version.files.filter(
            status=amo.STATUS_PUBLIC).exists()
        assert has_public

        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)

        validation = doc.find('.files')
        assert validation.find('a').eq(1).text() == "Validation"
        assert validation.find('a').eq(2).text() == "Contents"

        assert validation.find('a').length == 3

    def test_public_search(self):
        self.version.files.update(status=amo.STATUS_PUBLIC)
        self.addon.update(type=amo.ADDON_SEARCH)
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#review-files .files ul .file-info').length == 1

    def test_version_deletion(self):
        """
        Make sure that we still show review history for deleted versions.
        """
        # Add a new version to the add-on.
        addon = addon_factory(
            status=amo.STATUS_NOMINATED, name='something',
            version_kw={'version': '0.2'},
            file_kw={'status': amo.STATUS_AWAITING_REVIEW})

        assert self.addon.versions.count() == 1

        self.review_version(self.version, self.url)

        v2 = addon.versions.all()[0]
        v2.addon = self.addon
        v2.created = v2.created + timedelta(days=1)
        v2.save()
        self.review_version(v2, self.url)
        assert self.addon.versions.count() == 2

        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)

        # View the history verify two versions:
        ths = doc('table#review-files > tr > th:first-child')
        assert '0.1' in ths.eq(0).text()
        assert '0.2' in ths.eq(1).text()

        # Delete a version:
        v2.delete()
        # Verify two versions, one deleted:
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        ths = doc('table#review-files > tr > th:first-child')

        assert ths.length == 2
        assert '0.1' in ths.text()

    def test_no_versions(self):
        """The review page should still load if there are no versions. But not
        unless you have unlisted permissions."""
        assert self.client.get(self.url).status_code == 200
        response = self.client.post(self.url, {'action': 'comment',
                                               'comments': 'hello sailor'})
        assert response.status_code == 302
        self.assert3xx(response, reverse('reviewers.queue_pending'),
                       status_code=302)

        self.version.delete()
        # Regular reviewer has no permission, gets a 404.
        assert self.client.get(self.url).status_code == 404
        # Reviewer with more powers can look.
        self.grant_permission(self.reviewer, 'Addons:ReviewUnlisted')
        assert self.client.get(self.url).status_code == 200
        response = self.client.post(self.url, {'action': 'comment',
                                               'comments': 'hello sailor'})
        assert response.status_code == 302
        self.assert3xx(response, reverse('reviewers.queue_pending'),
                       status_code=302)

    def test_addon_deleted(self):
        """The review page should still load for deleted addons."""
        self.addon.delete()
        self.url = reverse('reviewers.review', args=[self.addon.pk])

        assert self.client.get(self.url).status_code == 200
        response = self.client.post(self.url, {'action': 'comment',
                                               'comments': 'hello sailor'})
        assert response.status_code == 302
        self.assert3xx(response, reverse('reviewers.queue_pending'),
                       status_code=302)

    @patch('olympia.reviewers.utils.sign_file')
    def review_version(self, version, url, mock_sign):
        if version.channel == amo.RELEASE_CHANNEL_LISTED:
            version.files.all()[0].update(status=amo.STATUS_AWAITING_REVIEW)
            action = 'public'
        else:
            action = 'reply'

        data = {
            'action': action,
            'operating_systems': 'win',
            'applications': 'something',
            'comments': 'something',
        }
        self.client.post(url, data)

        if version.channel == amo.RELEASE_CHANNEL_LISTED:
            assert mock_sign.called
        return action

    def test_dependencies_listed(self):
        AddonDependency.objects.create(addon=self.addon,
                                       dependent_addon=self.addon)
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        deps = doc('.addon-info .addon-dependencies')
        assert deps.length == 1
        assert deps.find('li').length == 1
        assert deps.find('a').attr('href') == self.addon.get_url_path()

    def test_eula_displayed(self):
        assert not bool(self.addon.eula)
        response = self.client.get(self.url)
        assert response.status_code == 200
        self.assertNotContains(response, 'View End-User License Agreement')

        self.addon.eula = 'Test!'
        self.addon.save()
        assert bool(self.addon.eula)
        response = self.client.get(self.url)
        assert response.status_code == 200
        self.assertContains(response, 'View End-User License Agreement')

    def test_privacy_policy_displayed(self):
        assert self.addon.privacy_policy is None
        response = self.client.get(self.url)
        assert response.status_code == 200
        self.assertNotContains(response, 'View Privacy Policy')

        self.addon.privacy_policy = 'Test!'
        self.addon.save()
        response = self.client.get(self.url)
        assert response.status_code == 200
        self.assertContains(response, 'View Privacy Policy')

    def test_requires_payment_indicator(self):
        assert not self.addon.requires_payment
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert 'No' in doc('tr.requires-payment td').text()

        self.addon.update(requires_payment=True)
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert 'Yes' in doc('tr.requires-payment td').text()

    def test_viewing(self):
        url = reverse('reviewers.review_viewing')
        response = self.client.post(url, {'addon_id': self.addon.id})
        data = json.loads(response.content)
        assert data['current'] == self.reviewer.id
        assert data['current_name'] == self.reviewer.name
        assert data['is_user'] == 1

        # Now, login as someone else and test.
        self.login_as_admin()
        response = self.client.post(url, {'addon_id': self.addon.id})
        data = json.loads(response.content)
        assert data['current'] == self.reviewer.id
        assert data['current_name'] == self.reviewer.name
        assert data['is_user'] == 0

    # Lets just override this to make the test a bit shorter.
    @mock.patch.object(amo, 'REVIEWER_REVIEW_LOCK_LIMIT', 1)
    def test_viewing_lock_limit(self):
        url = reverse('reviewers.review_viewing')

        response = self.client.post(url, {'addon_id': 1234})
        data = json.loads(response.content)
        assert data['current'] == self.reviewer.id
        assert data['current_name'] == self.reviewer.name
        assert data['is_user'] == 1

        # Second review page is over the limit.
        response = self.client.post(url, {'addon_id': 5678})
        data = json.loads(response.content)
        assert data['current'] == settings.TASK_USER_ID  # Mozilla's task ID.
        assert data['current_name'] == 'Review lock limit reached'
        assert data['is_user'] == 2

        # Now, login as someone else and test.  First page is blocked.
        self.login_as_admin()
        response = self.client.post(url, {'addon_id': 1234})
        data = json.loads(response.content)
        assert data['current'] == self.reviewer.id
        assert data['current_name'] == self.reviewer.name
        assert data['is_user'] == 0

        # Second page is available.
        response = self.client.post(url, {'addon_id': 5678})
        data = json.loads(response.content)
        admin = UserProfile.objects.get(username='admin')
        assert data['current'] == admin.id
        assert data['current_name'] == admin.name
        assert data['is_user'] == 1

    # Lets just override this to make the test a bit shorter.
    @mock.patch.object(amo, 'REVIEWER_REVIEW_LOCK_LIMIT', 1)
    def test_viewing_lock_admin(self):
        self.login_as_admin()
        url = reverse('reviewers.review_viewing')
        admin = UserProfile.objects.get(username='admin')

        response = self.client.post(url, {'addon_id': 101})
        data = json.loads(response.content)
        assert data['current'] == admin.id
        assert data['current_name'] == admin.name
        assert data['is_user'] == 1

        # Admin don't have time for no limits.
        response = self.client.post(url, {'addon_id': 202})
        data = json.loads(response.content)
        assert data['current'] == admin.id
        assert data['current_name'] == admin.name
        assert data['is_user'] == 1

    def test_viewing_review_unlocks(self):
        reviewing_url = reverse('reviewers.review_viewing')
        self.client.post(reviewing_url, {'addon_id': self.addon.id})
        key = '%s:review_viewing:%s' % (settings.CACHE_PREFIX, self.addon.id)
        assert cache.get(key) == self.reviewer.id

        self.client.post(self.url, {'action': 'comment',
                                    'comments': 'hello sailor'})
        # Processing a review should instantly clear the review lock on it.
        assert cache.get(key) is None

    def test_viewing_queue(self):
        response = self.client.post(reverse('reviewers.review_viewing'),
                                    {'addon_id': self.addon.id})
        data = json.loads(response.content)
        assert data['current'] == self.reviewer.id
        assert data['current_name'] == self.reviewer.name
        assert data['is_user'] == 1

        # Now, login as someone else and test.
        self.login_as_admin()
        r = self.client.post(reverse('reviewers.queue_viewing'),
                             {'addon_ids': self.addon.id})
        data = json.loads(r.content)
        assert data[str(self.addon.id)] == self.reviewer.display_name

    def test_display_same_files_only_once(self):
        """
        Test whether identical files for different platforms
        show up as one link with the appropriate text.
        """
        version = version_factory(
            addon=self.addon, version='0.2', file_kw=False)
        file_mac = file_factory(version=version, platform=amo.PLATFORM_MAC.id)
        file_android = file_factory(
            version=version, platform=amo.PLATFORM_ANDROID.id)

        # Signing causes the same uploaded file to be different
        file_mac.update(hash='xyz789', original_hash='123abc')
        file_android.update(hash='zyx987', original_hash='123abc')

        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        text = doc('.reviewers-install').eq(1).text()
        assert text == "Mac OS X / Android"

    def test_compare_no_link(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        info = doc('#review-files .file-info')
        assert info.length == 1
        assert info.find('a.compare').length == 0

    def test_file_info_for_static_themes(self):
        self.grant_permission(self.reviewer, 'Addons:ThemeReview')
        self.addon.update(type=amo.ADDON_STATICTHEME)
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        info = doc('#review-files .file-info')
        assert info.length == 1
        # Only the download/install link
        assert info.find('a').length == 1
        assert info.find('a')[0].text == u'Download'
        assert 'Compatibility' not in response.content

    def test_compare_link(self):
        first_file = self.addon.current_version.files.all()[0]
        first_file.update(status=amo.STATUS_PUBLIC)
        self.addon.current_version.update(created=self.days_ago(2))

        new_version = version_factory(addon=self.addon, version='0.2')
        new_file = new_version.files.all()[0]
        self.addon.update(_current_version=new_version)
        assert self.addon.current_version == new_version

        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert response.context['show_diff']
        links = doc('#review-files .file-info .compare')
        expected = [
            reverse('files.compare', args=[new_file.pk, first_file.pk]),
        ]
        check_links(expected, links, verify=False)

    def test_compare_link_auto_approved_ignored(self):
        first_file = self.addon.current_version.files.all()[0]
        first_file.update(status=amo.STATUS_PUBLIC)
        self.addon.current_version.update(created=self.days_ago(3))

        interim_version = version_factory(addon=self.addon, version='0.2')
        interim_version.update(created=self.days_ago(2))
        AutoApprovalSummary.objects.create(
            version=interim_version, verdict=amo.AUTO_APPROVED)

        new_version = version_factory(addon=self.addon, version='0.3')
        new_file = new_version.files.all()[0]

        self.addon.update(_current_version=new_version)
        assert self.addon.current_version == new_version

        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert response.context['show_diff']
        links = doc('#review-files .file-info .compare')
        # Comparison should be betweeen the last version and the first,
        # ignoring the interim version because it was auto-approved and not
        # manually confirmed by a human.
        expected = [
            reverse('files.compare', args=[new_file.pk, first_file.pk]),
        ]
        check_links(expected, links, verify=False)

    def test_compare_link_auto_approved_but_confirmed_not_ignored(self):
        first_file = self.addon.current_version.files.all()[0]
        first_file.update(status=amo.STATUS_PUBLIC)
        self.addon.current_version.update(created=self.days_ago(3))

        confirmed_version = version_factory(addon=self.addon, version='0.2')
        confirmed_version.update(created=self.days_ago(2))
        confirmed_file = confirmed_version.files.all()[0]
        AutoApprovalSummary.objects.create(
            verdict=amo.AUTO_APPROVED, version=confirmed_version,
            confirmed=True)

        interim_version = version_factory(addon=self.addon, version='0.3')
        interim_version.update(created=self.days_ago(1))
        AutoApprovalSummary.objects.create(
            version=interim_version, verdict=amo.AUTO_APPROVED)

        new_version = version_factory(addon=self.addon, version='0.4')
        new_file = new_version.files.all()[0]

        self.addon.update(_current_version=new_version)
        assert self.addon.current_version == new_version

        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert response.context['show_diff']
        links = doc('#review-files .file-info .compare')
        # Comparison should be betweeen the last version and the second,
        # ignoring the third version because it was auto-approved and not
        # manually confirmed by a human (the second was auto-approved but
        # was manually confirmed).
        expected = [
            reverse('files.compare', args=[new_file.pk, confirmed_file.pk]),
        ]
        check_links(expected, links, verify=False)

    def test_compare_link_not_auto_approved_but_confirmed(self):
        first_file = self.addon.current_version.files.all()[0]
        first_file.update(status=amo.STATUS_PUBLIC)
        self.addon.current_version.update(created=self.days_ago(3))

        confirmed_version = version_factory(addon=self.addon, version='0.2')
        confirmed_version.update(created=self.days_ago(2))
        confirmed_file = confirmed_version.files.all()[0]
        AutoApprovalSummary.objects.create(
            verdict=amo.NOT_AUTO_APPROVED, version=confirmed_version
        )

        new_version = version_factory(addon=self.addon, version='0.3')
        new_file = new_version.files.all()[0]

        self.addon.update(_current_version=new_version)
        assert self.addon.current_version == new_version

        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert response.context['show_diff']
        links = doc('#review-files .file-info .compare')
        # Comparison should be betweeen the last version and the second,
        # because second was approved by human before auto-approval ran on it
        expected = [
            reverse('files.compare', args=[new_file.pk, confirmed_file.pk]),
        ]
        check_links(expected, links, verify=False)

    def test_download_sources_link(self):
        version = self.addon.current_version
        tdir = temp.gettempdir()
        source_file = temp.NamedTemporaryFile(suffix='.zip', dir=tdir)
        source_file.write('a' * (2 ** 21))
        source_file.seek(0)
        version.source = DjangoFile(source_file)
        version.save()

        url = reverse('reviewers.review', args=[self.addon.pk])

        # Admin reviewer: able to download sources.
        user = UserProfile.objects.get(email='admin@mozilla.com')
        self.client.login(email=user.email)
        response = self.client.get(url, follow=True)
        assert response.status_code == 200
        assert 'Download files' in response.content

        # Standard reviewer: should know that sources were provided.
        user = UserProfile.objects.get(email='reviewer@mozilla.com')
        self.client.login(email=user.email)
        response = self.client.get(url, follow=True)
        assert response.status_code == 200
        assert 'The developer has provided source code.' in response.content

    @patch('olympia.reviewers.utils.sign_file')
    def test_admin_flagged_addon_actions_as_admin(self, mock_sign_file):
        self.version.files.update(status=amo.STATUS_AWAITING_REVIEW)
        self.addon.update(status=amo.STATUS_NOMINATED)
        AddonReviewerFlags.objects.create(
            addon=self.addon, needs_admin_code_review=True)
        self.login_as_admin()
        response = self.client.post(self.url, self.get_dict(action='public'),
                                    follow=True)
        assert response.status_code == 200
        addon = self.get_addon()
        assert self.version == addon.current_version
        assert addon.status == amo.STATUS_PUBLIC
        assert addon.current_version.files.all()[0].status == amo.STATUS_PUBLIC

        assert mock_sign_file.called

    def test_admin_flagged_addon_actions_as_reviewer(self):
        self.version.files.update(status=amo.STATUS_AWAITING_REVIEW)
        self.addon.update(status=amo.STATUS_NOMINATED)
        AddonReviewerFlags.objects.create(
            addon=self.addon, needs_admin_code_review=True)
        self.login_as_reviewer()
        response = self.client.post(self.url, self.get_dict(action='public'))
        assert response.status_code == 200  # Form error.
        # The add-on status must not change as non-admin reviewers are not
        # allowed to review admin-flagged add-ons.
        addon = self.get_addon()
        assert addon.status == amo.STATUS_NOMINATED
        assert self.version == addon.current_version
        assert addon.current_version.files.all()[0].status == (
            amo.STATUS_AWAITING_REVIEW)
        assert response.context['form'].errors['action'] == (
            [u'Select a valid choice. public is not one of the available '
             u'choices.'])

    def test_confirm_auto_approval_no_permission(self):
        AutoApprovalSummary.objects.create(
            version=self.addon.current_version, verdict=amo.AUTO_APPROVED)
        self.login_as_reviewer()  # Legacy reviewer, not post-review.
        response = self.client.post(
            self.url, {'action': 'confirm_auto_approved'})
        assert response.status_code == 403
        # Nothing happened: the user did not have the permission to do that.
        assert ActivityLog.objects.filter(
            action=amo.LOG.CONFIRM_AUTO_APPROVED.id).count() == 0

    def test_attempt_to_use_content_review_permission_for_post_review_actions(
            self):
        # Try to use confirm_auto_approved outside of content review, while
        # only having Addons:ContentReview permission.
        self.grant_permission(self.reviewer, 'Addons:ContentReview')
        AutoApprovalSummary.objects.create(
            version=self.addon.current_version, verdict=amo.AUTO_APPROVED)
        self.login_as_reviewer()
        response = self.client.post(
            self.url, {'action': 'confirm_auto_approved'})
        assert response.status_code == 403
        # Nothing happened: the user did not have the permission to do that.
        assert ActivityLog.objects.filter(
            action=amo.LOG.CONFIRM_AUTO_APPROVED.id).count() == 0

    def test_confirm_auto_approval_content_review(self):
        GroupUser.objects.filter(user=self.reviewer).all().delete()
        self.url = reverse(
            'reviewers.review', args=['content', self.addon.slug])
        summary = AutoApprovalSummary.objects.create(
            version=self.addon.current_version, verdict=amo.AUTO_APPROVED)
        self.grant_permission(self.reviewer, 'Addons:ContentReview')
        response = self.client.post(self.url, {
            'action': 'confirm_auto_approved',
            'comments': 'ignore me this action does not support comments'
        })
        assert response.status_code == 302
        summary.reload()
        assert summary.confirmed is None  # We're only doing a content review.
        assert ActivityLog.objects.filter(
            action=amo.LOG.CONFIRM_AUTO_APPROVED.id).count() == 0
        assert ActivityLog.objects.filter(
            action=amo.LOG.APPROVE_CONTENT.id).count() == 1
        a_log = ActivityLog.objects.filter(
            action=amo.LOG.APPROVE_CONTENT.id).get()
        assert a_log.details['version'] == self.addon.current_version.version
        assert a_log.details['comments'] == ''
        self.assert3xx(response, reverse('reviewers.queue_content_review'))

    def test_cant_contentreview_if_admin_content_review_flag_is_set(self):
        GroupUser.objects.filter(user=self.reviewer).all().delete()
        self.url = reverse(
            'reviewers.review', args=['content', self.addon.slug])
        AutoApprovalSummary.objects.create(
            version=self.addon.current_version, verdict=amo.AUTO_APPROVED)
        AddonReviewerFlags.objects.create(
            addon=self.addon, needs_admin_content_review=True)
        self.grant_permission(self.reviewer, 'Addons:ContentReview')
        response = self.client.post(self.url, {
            'action': 'confirm_auto_approved',
            'comments': 'ignore me this action does not support comments'
        })
        # The request will succeed but nothing will happen.
        assert response.status_code == 200
        assert ActivityLog.objects.filter(
            action=amo.LOG.APPROVE_CONTENT.id).count() == 0

    def test_admin_can_contentreview_if_admin_content_review_flag_is_set(self):
        GroupUser.objects.filter(user=self.reviewer).all().delete()
        self.url = reverse(
            'reviewers.review', args=['content', self.addon.slug])
        summary = AutoApprovalSummary.objects.create(
            version=self.addon.current_version, verdict=amo.AUTO_APPROVED)
        AddonReviewerFlags.objects.create(
            addon=self.addon, needs_admin_content_review=True)
        self.grant_permission(self.reviewer, 'Addons:ContentReview')
        self.grant_permission(self.reviewer, 'Reviews:Admin')
        response = self.client.post(self.url, {
            'action': 'confirm_auto_approved',
            'comments': 'ignore me this action does not support comments'
        })
        assert response.status_code == 302
        summary.reload()
        assert summary.confirmed is None  # We're only doing a content review.
        assert ActivityLog.objects.filter(
            action=amo.LOG.CONFIRM_AUTO_APPROVED.id).count() == 0
        assert ActivityLog.objects.filter(
            action=amo.LOG.APPROVE_CONTENT.id).count() == 1
        a_log = ActivityLog.objects.filter(
            action=amo.LOG.APPROVE_CONTENT.id).get()
        assert a_log.details['version'] == self.addon.current_version.version
        assert a_log.details['comments'] == ''
        self.assert3xx(response, reverse('reviewers.queue_content_review'))

    def test_confirm_auto_approval_with_permission(self):
        summary = AutoApprovalSummary.objects.create(
            version=self.addon.current_version, verdict=amo.AUTO_APPROVED)
        GroupUser.objects.filter(user=self.reviewer).all().delete()
        self.grant_permission(self.reviewer, 'Addons:PostReview')
        response = self.client.post(self.url, {
            'action': 'confirm_auto_approved',
            'comments': 'ignore me this action does not support comments'
        })
        summary.reload()
        assert response.status_code == 302
        assert summary.confirmed is True
        assert ActivityLog.objects.filter(
            action=amo.LOG.CONFIRM_AUTO_APPROVED.id).count() == 1
        a_log = ActivityLog.objects.filter(
            action=amo.LOG.CONFIRM_AUTO_APPROVED.id).get()
        assert a_log.details['version'] == self.addon.current_version.version
        assert a_log.details['comments'] == ''
        self.assert3xx(response, reverse('reviewers.queue_auto_approved'))

    def test_user_changes_log(self):
        # Activity logs related to user changes should be displayed.
        # Create an activy log for each of the following: user addition, role
        # change and deletion.
        author = self.addon.addonuser_set.get()
        core.set_user(author.user)
        ActivityLog.create(amo.LOG.ADD_USER_WITH_ROLE,
                           author.user, author.get_role_display(), self.addon)
        ActivityLog.create(amo.LOG.CHANGE_USER_WITH_ROLE,
                           author.user, author.get_role_display(), self.addon)
        ActivityLog.create(amo.LOG.REMOVE_USER_WITH_ROLE,
                           author.user, author.get_role_display(), self.addon)

        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert 'user_changes' in response.context
        user_changes_log = response.context['user_changes']
        actions = [log.activity_log.action for log in user_changes_log]
        assert actions == [
            amo.LOG.ADD_USER_WITH_ROLE.id,
            amo.LOG.CHANGE_USER_WITH_ROLE.id,
            amo.LOG.REMOVE_USER_WITH_ROLE.id]

        # Make sure the logs are displayed in the page.
        user_changes = doc('#user-changes li')
        assert len(user_changes) == 3
        assert '(Owner) added to ' in user_changes[0].text
        assert 'role changed to Owner for ' in user_changes[1].text
        assert '(Owner) removed from ' in user_changes[2].text

    @override_settings(CELERY_ALWAYS_EAGER=True)
    @mock.patch('olympia.devhub.tasks.validate')
    def test_validation_not_run_eagerly(self, validate):
        """Tests that validation is not run in eager mode."""
        assert not self.file.has_been_validated

        response = self.client.get(self.url)
        assert response.status_code == 200

        assert not validate.called

    @override_settings(CELERY_ALWAYS_EAGER=False)
    @mock.patch('olympia.devhub.tasks.validate')
    def test_validation_run(self, validate):
        """Tests that validation is run if necessary."""
        assert not self.file.has_been_validated

        response = self.client.get(self.url)
        assert response.status_code == 200

        validate.assert_called_once_with(self.file)

    @override_settings(CELERY_ALWAYS_EAGER=False)
    @mock.patch('olympia.devhub.tasks.validate')
    def test_validation_not_run_again(self, validate):
        """Tests that validation is not run for files which have cached
        results."""

        FileValidation.objects.create(file=self.file, validation=json.dumps(
            amo.VALIDATOR_SKELETON_RESULTS))

        response = self.client.get(self.url)
        assert response.status_code == 200

        assert not validate.called

    def test_review_is_review_listed(self):
        review_page = self.client.get(
            reverse('reviewers.review', args=[self.addon.slug]))
        listed_review_page = self.client.get(
            reverse('reviewers.review', args=['listed', self.addon.slug]))
        assert (pq(review_page.content)('#review-files').text() ==
                pq(listed_review_page.content)('#review-files').text())

    def test_approvals_info(self):
        approval_info = AddonApprovalsCounter.objects.create(
            addon=self.addon, last_human_review=datetime.now(), counter=42)
        self.file.update(is_webextension=True)
        AutoApprovalSummary.objects.create(
            version=self.version, verdict=amo.AUTO_APPROVED)
        self.grant_permission(self.reviewer, 'Addons:PostReview')
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('.last-approval-date')

        approval_info.delete()
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        # no AddonApprovalsCounter: nothing displayed.
        assert not doc('.last-approval-date')

    def test_no_auto_approval_summaries_since_everything_is_public(self):
        self.grant_permission(self.reviewer, 'Addons:PostReview')
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert not doc('.auto_approval')

    def test_permissions_display(self):
        permissions = ['bookmarks', 'high', 'voltage']
        self.file.update(is_webextension=True)
        WebextPermission.objects.create(
            permissions=permissions,
            file=self.file)
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        info = doc('#review-files .file-info div')
        assert info.eq(1).text() == 'Permissions: ' + ', '.join(permissions)

    def test_abuse_reports(self):
        report = AbuseReport.objects.create(
            addon=self.addon, message=u'Et mël mazim ludus.',
            ip_address='10.1.2.3')
        created_at = defaultfilters.date(report.created)
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert not doc('.abuse_reports')

        self.grant_permission(self.reviewer, 'Addons:PostReview')
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert not doc('.abuse_reports')

        AutoApprovalSummary.objects.create(
            verdict=amo.AUTO_APPROVED, version=self.version)
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('.abuse_reports')
        assert (
            doc('.abuse_reports').text() ==
            u'anonymous [10.1.2.3] reported Public on %s\nEt mël mazim ludus.'
            % created_at)

    def test_abuse_reports_developers(self):
        report = AbuseReport.objects.create(
            user=self.addon.listed_authors[0], message=u'Foo, Bâr!',
            ip_address='10.4.5.6')
        created_at = defaultfilters.date(report.created)
        AutoApprovalSummary.objects.create(
            verdict=amo.AUTO_APPROVED, version=self.version)
        self.grant_permission(self.reviewer, 'Addons:PostReview')
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('.abuse_reports')
        assert (
            doc('.abuse_reports').text() ==
            u'anonymous [10.4.5.6] reported regularuser التطب on %s\nFoo, Bâr!'
            % created_at)

    def test_user_ratings(self):
        user = user_factory()
        rating = Rating.objects.create(
            body=u'Lôrem ipsum dolor', rating=3, ip_address='10.5.6.7',
            addon=self.addon, user=user)
        created_at = defaultfilters.date(rating.created)
        Rating.objects.create(  # Review with no body, ignored.
            rating=1, addon=self.addon, user=user_factory())
        Rating.objects.create(  # Reply to a review, ignored.
            body='Replyyyyy', reply_to=rating,
            addon=self.addon, user=user_factory())
        Rating.objects.create(  # Review with high rating,, ignored.
            body=u'Qui platônem temporibus in', rating=5, addon=self.addon,
            user=user_factory())
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert not doc('.user_ratings')

        self.grant_permission(self.reviewer, 'Addons:PostReview')
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert not doc('.user_ratings')

        AutoApprovalSummary.objects.create(
            verdict=amo.AUTO_APPROVED, version=self.version)
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('.user_ratings')
        assert (
            doc('.user_ratings').text() ==
            u'%s on %s [10.5.6.7]\n'
            u'Rated 3 out of 5 stars\nLôrem ipsum dolor' % (
                user.username, created_at
            )
        )

    def test_data_value_attributes(self):
        AutoApprovalSummary.objects.create(
            verdict=amo.AUTO_APPROVED, version=self.version)
        self.grant_permission(self.reviewer, 'Addons:PostReview')
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)

        expected_actions_values = [
            'confirm_auto_approved|', 'reject_multiple_versions|', 'reply|',
            'super|', 'comment|']
        assert [
            act.attrib['data-value'] for act in
            doc('.data-toggle.review-actions-desc')] == expected_actions_values

        assert (
            doc('select#id_versions.data-toggle')[0].attrib['data-value'] ==
            'reject_multiple_versions|')

        assert (
            doc('.data-toggle.review-comments')[0].attrib['data-value'] ==
            'reject_multiple_versions|reply|super|comment|')
        # We don't have approve/reject actions so these have an empty
        # data-value.
        assert (
            doc('.data-toggle.review-files')[0].attrib['data-value'] == '|')
        assert (
            doc('.data-toggle.review-tested')[0].attrib['data-value'] == '|')

        assert (
            doc('.data-toggle.review-info-request')[0].attrib['data-value'] ==
            'reply|')

    def test_data_value_attributes_unreviewed(self):
        self.file.update(status=amo.STATUS_AWAITING_REVIEW)
        self.grant_permission(self.reviewer, 'Addons:PostReview')
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)

        expected_actions_values = [
            'public|', 'reject|', 'reply|', 'super|', 'comment|']
        assert [
            act.attrib['data-value'] for act in
            doc('.data-toggle.review-actions-desc')] == expected_actions_values

        assert (
            doc('select#id_versions.data-toggle')[0].attrib['data-value'] ==
            'reject_multiple_versions|')

        assert (
            doc('.data-toggle.review-comments')[0].attrib['data-value'] ==
            'public|reject|reply|super|comment|')
        assert (
            doc('.data-toggle.review-files')[0].attrib['data-value'] ==
            'public|reject|')
        assert (
            doc('.data-toggle.review-tested')[0].attrib['data-value'] ==
            'public|reject|')

    def test_data_value_attributes_static_theme(self):
        self.addon.update(type=amo.ADDON_STATICTHEME)
        self.file.update(status=amo.STATUS_AWAITING_REVIEW)
        self.grant_permission(self.reviewer, 'Addons:ThemeReview')
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)

        expected_actions_values = [
            'public|', 'reject|', 'reply|', 'super|', 'comment|']
        assert [
            act.attrib['data-value'] for act in
            doc('.data-toggle.review-actions-desc')] == expected_actions_values

        assert (
            doc('select#id_versions.data-toggle')[0].attrib['data-value'] ==
            'reject_multiple_versions|')

        assert (
            doc('.data-toggle.review-comments')[0].attrib['data-value'] ==
            'public|reject|reply|super|comment|')
        # we don't show files and tested with for any static theme actions
        assert (
            doc('.data-toggle.review-files')[0].attrib['data-value'] ==
            '|')
        assert (
            doc('.data-toggle.review-tested')[0].attrib['data-value'] ==
            '|')

    def test_post_review_ignore_disabled_or_beta(self):
        # Though the latest version will be disabled, the add-on is public and
        # was auto-approved so the confirmation action is available.
        AutoApprovalSummary.objects.create(
            verdict=amo.AUTO_APPROVED, version=self.version)
        version_factory(addon=self.addon, file_kw={'status': amo.STATUS_BETA})
        version_factory(
            addon=self.addon, file_kw={'status': amo.STATUS_DISABLED})
        self.grant_permission(self.reviewer, 'Addons:PostReview')
        response = self.client.get(self.url)
        assert response.status_code == 200
        expected_actions = [
            'confirm_auto_approved', 'reject_multiple_versions', 'reply',
            'super', 'comment']
        assert (
            [action[0] for action in response.context['actions']] ==
            expected_actions)

    def test_content_review_ignore_disabled_or_beta(self):
        # Though the latest version will be disabled, the add-on is public and
        # was auto-approved so the content approval action is available.
        AutoApprovalSummary.objects.create(
            verdict=amo.AUTO_APPROVED, version=self.version)
        version_factory(addon=self.addon, file_kw={'status': amo.STATUS_BETA})
        version_factory(
            addon=self.addon, file_kw={'status': amo.STATUS_DISABLED})
        self.grant_permission(self.reviewer, 'Addons:ContentReview')
        self.url = reverse(
            'reviewers.review', args=['content', self.addon.slug])
        response = self.client.get(self.url)
        assert response.status_code == 200
        expected_actions = [
            'confirm_auto_approved', 'reject_multiple_versions', 'reply',
            'super', 'comment']
        assert (
            [action[0] for action in response.context['actions']] ==
            expected_actions)

    @mock.patch('olympia.versions.models.walkfiles')
    def test_static_theme_backgrounds(self, walkfiles_mock):
        background_files = ['a.png', 'b.png', 'c.png']
        walkfiles_folder = os.path.join(
            user_media_path('addons'), str(self.addon.id),
            unicode(self.addon.current_version.id))
        walkfiles_mock.return_value = [
            os.path.join(walkfiles_folder, filename)
            for filename in background_files]
        self.addon.update(type=amo.ADDON_STATICTHEME)
        self.grant_permission(self.reviewer, 'Addons:ThemeReview')

        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        backgrounds_div = doc('div.all-backgrounds')
        assert backgrounds_div.length == 1
        images = doc('div.all-backgrounds a.thumbnail')
        assert images.length == len(walkfiles_mock.return_value)
        background_file_folder = '/'.join([
            user_media_url('addons'), str(self.addon.id),
            unicode(self.addon.current_version.id)])
        background_file_urls = [
            background_file_folder + '/' + filename
            for filename in background_files]
        loop_ct = 0
        for a_tag in images:
            assert a_tag.attrib['href'] in background_file_urls
            assert a_tag.attrib['title'] == (
                'Background file {0} of {1} - {2}'.format(
                    loop_ct + 1, len(background_files),
                    background_files[loop_ct]))
            loop_ct += 1


class TestReviewPending(ReviewBase):

    def setUp(self):
        super(TestReviewPending, self).setUp()
        self.file = file_factory(version=self.version,
                                 status=amo.STATUS_AWAITING_REVIEW,
                                 is_webextension=True)
        self.addon.update(status=amo.STATUS_PUBLIC)

    def pending_dict(self):
        return self.get_dict(action='public')

    @patch('olympia.reviewers.utils.sign_file')
    def test_pending_to_public(self, mock_sign):
        statuses = (self.version.files.values_list('status', flat=True)
                    .order_by('status'))
        assert list(statuses) == [
            amo.STATUS_AWAITING_REVIEW, amo.STATUS_PUBLIC]

        response = self.client.post(self.url, self.pending_dict())
        assert self.get_addon().status == amo.STATUS_PUBLIC
        self.assert3xx(response, reverse('reviewers.queue_pending'))

        statuses = (self.version.files.values_list('status', flat=True)
                    .order_by('status'))
        assert list(statuses) == [amo.STATUS_PUBLIC, amo.STATUS_PUBLIC]

        assert mock_sign.called

    def test_display_only_unreviewed_files(self):
        """Only the currently unreviewed files are displayed."""
        self.file.update(filename='somefilename.xpi')
        reviewed = File.objects.create(version=self.version,
                                       status=amo.STATUS_PUBLIC,
                                       filename='file_reviewed.xpi')
        disabled = File.objects.create(version=self.version,
                                       status=amo.STATUS_DISABLED,
                                       filename='file_disabled.xpi')
        unreviewed = File.objects.create(version=self.version,
                                         status=amo.STATUS_AWAITING_REVIEW,
                                         filename='file_unreviewed.xpi')
        response = self.client.get(self.url, self.pending_dict())
        assert response.status_code == 200
        doc = pq(response.content)
        assert len(doc('.review-actions-files ul li')) == 2
        assert reviewed.filename not in response.content
        assert disabled.filename not in response.content
        assert unreviewed.filename in response.content
        assert self.file.filename in response.content

    @patch('olympia.reviewers.utils.sign_file')
    def test_review_unreviewed_files(self, mock_sign):
        """Review all the unreviewed files when submitting a review."""
        reviewed = File.objects.create(version=self.version,
                                       status=amo.STATUS_PUBLIC)
        disabled = File.objects.create(version=self.version,
                                       status=amo.STATUS_DISABLED)
        unreviewed = File.objects.create(version=self.version,
                                         status=amo.STATUS_AWAITING_REVIEW)
        self.login_as_admin()
        response = self.client.post(self.url, self.pending_dict())
        self.assert3xx(response, reverse('reviewers.queue_pending'))

        assert self.addon.reload().status == amo.STATUS_PUBLIC
        assert reviewed.reload().status == amo.STATUS_PUBLIC
        assert disabled.reload().status == amo.STATUS_DISABLED
        assert unreviewed.reload().status == amo.STATUS_PUBLIC
        assert self.file.reload().status == amo.STATUS_PUBLIC

        assert mock_sign.called

    def test_auto_approval_summary_with_post_review(self):
        AutoApprovalSummary.objects.create(
            version=self.version,
            verdict=amo.NOT_AUTO_APPROVED,
            is_locked=True,
        )
        self.grant_permission(self.reviewer, 'Addons:PostReview')
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        # Locked by a reviewer is shown.
        assert len(doc('.auto_approval li')) == 1
        assert doc('.auto_approval li').eq(0).text() == (
            'Is locked by a reviewer.')


class TestReviewerMOTD(ReviewerTest):

    def get_url(self, save=False):
        return reverse('reviewers.%smotd' % ('save_' if save else ''))

    def test_change_motd(self):
        self.login_as_admin()
        motd = "Let's get crazy"
        response = self.client.post(self.get_url(save=True), {'motd': motd})
        url = self.get_url()
        self.assert3xx(response, url)
        response = self.client.get(url)
        assert response.status_code == 200
        assert pq(response.content)('.daily-message p').text() == motd

    def test_require_reviewer_to_view(self):
        url = self.get_url()
        self.assertLoginRedirects(self.client.head(url), to=url)

    def test_require_admin_to_change_motd(self):
        self.login_as_reviewer()

        response = self.client.get(self.get_url())
        assert response.status_code == 403

        response = self.client.post(reverse('reviewers.save_motd'),
                                    {'motd': "I'm a sneaky reviewer"})
        assert response.status_code == 403

    def test_motd_edit_group(self):
        user = UserProfile.objects.get(email='reviewer@mozilla.com')
        group = Group.objects.create(name='Add-on Reviewer MOTD',
                                     rules='AddonReviewerMOTD:Edit')
        GroupUser.objects.create(user=user, group=group)
        self.login_as_reviewer()
        response = self.client.post(reverse('reviewers.save_motd'),
                                    {'motd': 'I am the keymaster.'})
        assert response.status_code == 302
        assert get_config('reviewers_review_motd') == 'I am the keymaster.'

    def test_form_errors(self):
        self.login_as_admin()
        response = self.client.post(self.get_url(save=True))
        doc = pq(response.content)
        assert doc('#reviewer-motd .errorlist').text() == (
            'This field is required.')


class TestStatusFile(ReviewBase):

    def get_file(self):
        return self.version.files.all()[0]

    def check_status(self, expected):
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#review-files .file-info div').text() == expected

    def test_status_full(self):
        self.get_file().update(status=amo.STATUS_AWAITING_REVIEW)
        for status in [amo.STATUS_NOMINATED, amo.STATUS_PUBLIC]:
            self.addon.update(status=status)
            self.check_status('Awaiting Review')

    def test_status_full_reviewed(self):
        self.get_file().update(status=amo.STATUS_PUBLIC)
        self.addon.update(status=amo.STATUS_PUBLIC)
        self.check_status('Approved')

    def test_other(self):
        self.addon.update(status=amo.STATUS_BETA)
        self.check_status(unicode(File.STATUS_CHOICES[self.get_file().status]))


class TestWhiteboard(ReviewBase):
    @property
    def addon_param(self):
        return self.addon.pk if self.addon.is_deleted else self.addon.slug

    def test_whiteboard_addition(self):
        public_whiteboard_info = u'Public whiteboard info.'
        private_whiteboard_info = u'Private whiteboard info.'
        url = reverse(
            'reviewers.whiteboard', args=['listed', self.addon_param])
        response = self.client.post(url, {
            'whiteboard-private': private_whiteboard_info,
            'whiteboard-public': public_whiteboard_info
        })
        self.assert3xx(response, reverse(
            'reviewers.review', args=('listed', self.addon_param)))
        addon = self.addon.reload()
        assert addon.whiteboard.public == public_whiteboard_info
        assert addon.whiteboard.private == private_whiteboard_info

    def test_whiteboard_addition_content_review(self):
        public_whiteboard_info = u'Public whiteboard info for content.'
        private_whiteboard_info = u'Private whiteboard info for content.'
        url = reverse(
            'reviewers.whiteboard', args=['content', self.addon_param])
        response = self.client.post(url, {
            'whiteboard-private': private_whiteboard_info,
            'whiteboard-public': public_whiteboard_info
        })
        assert response.status_code == 403  # Not a content reviewer.

        user = UserProfile.objects.get(email='reviewer@mozilla.com')
        self.grant_permission(user, 'Addons:ContentReview')
        self.login_as_reviewer()

        response = self.client.post(url, {
            'whiteboard-private': private_whiteboard_info,
            'whiteboard-public': public_whiteboard_info
        })
        self.assert3xx(response, reverse(
            'reviewers.review', args=('content', self.addon_param)))
        addon = self.addon.reload()
        assert addon.whiteboard.public == public_whiteboard_info
        assert addon.whiteboard.private == private_whiteboard_info

    def test_whiteboard_addition_unlisted_addon(self):
        user = UserProfile.objects.get(email='reviewer@mozilla.com')
        self.grant_permission(user, 'Addons:ReviewUnlisted')
        self.login_as_reviewer()
        self.make_addon_unlisted(self.addon)
        public_whiteboard_info = u'Public whiteboard info unlisted.'
        private_whiteboard_info = u'Private whiteboard info unlisted.'
        url = reverse(
            'reviewers.whiteboard', args=['unlisted', self.addon_param])
        response = self.client.post(url, {
            'whiteboard-private': private_whiteboard_info,
            'whiteboard-public': public_whiteboard_info
        })
        self.assert3xx(response, reverse(
            'reviewers.review', args=('unlisted', self.addon_param)))

        addon = self.addon.reload()
        assert addon.whiteboard.public == public_whiteboard_info
        assert addon.whiteboard.private == private_whiteboard_info

    def test_delete_empty(self):
        url = reverse(
            'reviewers.whiteboard', args=['listed', self.addon_param])
        response = self.client.post(url, {
            'whiteboard-private': '',
            'whiteboard-public': ''
        })
        self.assert3xx(response, reverse(
            'reviewers.review', args=('listed', self.addon_param)))
        assert not Whiteboard.objects.filter(pk=self.addon.pk)


class TestWhiteboardDeleted(TestWhiteboard):

    def setUp(self):
        super(TestWhiteboardDeleted, self).setUp()
        self.addon.delete()


class TestAbuseReports(TestCase):
    fixtures = ['base/users', 'base/addon_3615']

    def setUp(self):
        addon = Addon.objects.get(pk=3615)
        addon_developer = addon.listed_authors[0]
        someone = UserProfile.objects.exclude(pk=addon_developer.pk)[0]
        AbuseReport.objects.create(addon=addon, message=u'wôo')
        AbuseReport.objects.create(addon=addon, message=u'yéah',
                                   reporter=someone)
        # Make a user abuse report to make sure it doesn't show up.
        AbuseReport.objects.create(user=someone, message=u'hey nöw')
        # Make a user abuse report for one of the add-on developers: it should
        # show up.
        AbuseReport.objects.create(user=addon_developer, message='bü!')

    def test_abuse_reports_list(self):
        assert self.client.login(email='admin@mozilla.com')
        r = self.client.get(reverse('reviewers.abuse_reports', args=['a3615']))
        assert r.status_code == 200
        # We see the two abuse reports created in setUp.
        assert len(r.context['reports']) == 3

    def test_no_abuse_reports_link_for_unlisted_addons(self):
        """Unlisted addons aren't public, and thus have no abuse reports."""
        addon = Addon.objects.get(pk=3615)
        self.make_addon_unlisted(addon)
        self.client.login(email='admin@mozilla.com')
        response = reverse('reviewers.review', args=[addon.slug])
        abuse_report_url = reverse('reviewers.abuse_reports', args=['a3615'])
        assert abuse_report_url not in response


class TestLeaderboard(ReviewerTest):
    fixtures = ['base/users']

    def setUp(self):
        super(TestLeaderboard, self).setUp()
        self.url = reverse('reviewers.leaderboard')

        self.user = UserProfile.objects.get(email='reviewer@mozilla.com')
        self.login_as_reviewer()
        core.set_user(self.user)

    def _award_points(self, user, score):
        ReviewerScore.objects.create(user=user, note_key=amo.REVIEWED_MANUAL,
                                     score=score, note='Thing.')

    def test_leaderboard_ranks(self):
        other_reviewer = UserProfile.objects.create(
            username='post_reviewer',
            display_name='',  # No display_name, will fall back on name.
            email='post_reviewer@mozilla.com')
        self.grant_permission(
            other_reviewer, 'Addons:PostReview',
            name='Reviewers: Add-ons'  # The name of the group matters here.
        )

        users = (self.user,
                 UserProfile.objects.get(email='persona_reviewer@mozilla.com'),
                 other_reviewer)

        self._award_points(users[0], amo.REVIEWED_LEVELS[0]['points'] - 1)
        self._award_points(users[1], amo.REVIEWED_LEVELS[0]['points'] + 1)
        self._award_points(users[2], amo.REVIEWED_LEVELS[0]['points'] + 2)

        def get_cells():
            doc = pq(self.client.get(self.url).content.decode('utf-8'))

            cells = doc('#leaderboard > tbody > tr > .name, '
                        '#leaderboard > tbody > tr > .level')

            return [cells.eq(i).text() for i in range(0, cells.length)]

        assert get_cells() == (
            [users[2].name,
             users[1].name,
             unicode(amo.REVIEWED_LEVELS[0]['name']),
             users[0].name])

        self._award_points(users[0], 1)

        assert get_cells() == (
            [users[2].name,
             users[1].name,
             users[0].name,
             unicode(amo.REVIEWED_LEVELS[0]['name'])])

        self._award_points(users[0], -1)
        self._award_points(users[2], (amo.REVIEWED_LEVELS[1]['points'] -
                                      amo.REVIEWED_LEVELS[0]['points']))

        assert get_cells() == (
            [users[2].name,
             unicode(amo.REVIEWED_LEVELS[1]['name']),
             users[1].name,
             unicode(amo.REVIEWED_LEVELS[0]['name']),
             users[0].name])


class TestXssOnAddonName(amo.tests.TestXss):

    def test_reviewers_abuse_report_page(self):
        url = reverse('reviewers.abuse_reports', args=[self.addon.slug])
        self.assertNameAndNoXSS(url)

    def test_reviewers_review_page(self):
        url = reverse('reviewers.review', args=[self.addon.slug])
        self.assertNameAndNoXSS(url)


class TestAddonReviewerViewSet(TestCase):
    client_class = APITestClient

    def setUp(self):
        super(TestAddonReviewerViewSet, self).setUp()
        self.user = user_factory()
        self.addon = addon_factory()
        self.subscribe_url = reverse(
            'reviewers-addon-subscribe', kwargs={'pk': self.addon.pk})
        self.unsubscribe_url = reverse(
            'reviewers-addon-unsubscribe', kwargs={'pk': self.addon.pk})
        self.enable_url = reverse(
            'reviewers-addon-enable', kwargs={'pk': self.addon.pk})
        self.disable_url = reverse(
            'reviewers-addon-disable', kwargs={'pk': self.addon.pk})
        self.flags_url = reverse(
            'reviewers-addon-flags', kwargs={'pk': self.addon.pk})

    def test_subscribe_not_logged_in(self):
        response = self.client.post(self.subscribe_url)
        assert response.status_code == 401

    def test_subscribe_no_rights(self):
        self.client.login_api(self.user)
        response = self.client.post(self.subscribe_url)
        assert response.status_code == 403

    def test_subscribe_addon_does_not_exist(self):
        self.grant_permission(self.user, 'Addons:PostReview')
        self.client.login_api(self.user)
        self.subscribe_url = reverse(
            'reviewers-addon-subscribe', kwargs={'pk': self.addon.pk + 42})
        response = self.client.post(self.subscribe_url)
        assert response.status_code == 404

    def test_subscribe_already_subscribed(self):
        ReviewerSubscription.objects.create(
            user=self.user, addon=self.addon)
        self.grant_permission(self.user, 'Addons:PostReview')
        self.client.login_api(self.user)
        self.subscribe_url = reverse(
            'reviewers-addon-subscribe', kwargs={'pk': self.addon.pk})
        response = self.client.post(self.subscribe_url)
        assert response.status_code == 202
        assert ReviewerSubscription.objects.count() == 1

    def test_subscribe(self):
        self.grant_permission(self.user, 'Addons:PostReview')
        self.client.login_api(self.user)
        self.subscribe_url = reverse(
            'reviewers-addon-subscribe', kwargs={'pk': self.addon.pk})
        response = self.client.post(self.subscribe_url)
        assert response.status_code == 202
        assert ReviewerSubscription.objects.count() == 1

    def test_unsubscribe_not_logged_in(self):
        response = self.client.post(self.unsubscribe_url)
        assert response.status_code == 401

    def test_unsubscribe_no_rights(self):
        self.client.login_api(self.user)
        response = self.client.post(self.unsubscribe_url)
        assert response.status_code == 403

    def test_unsubscribe_addon_does_not_exist(self):
        self.grant_permission(self.user, 'Addons:PostReview')
        self.client.login_api(self.user)
        self.unsubscribe_url = reverse(
            'reviewers-addon-subscribe', kwargs={'pk': self.addon.pk + 42})
        response = self.client.post(self.unsubscribe_url)
        assert response.status_code == 404

    def test_unsubscribe_not_subscribed(self):
        self.grant_permission(self.user, 'Addons:PostReview')
        self.client.login_api(self.user)
        self.subscribe_url = reverse(
            'reviewers-addon-subscribe', kwargs={'pk': self.addon.pk})
        response = self.client.post(self.unsubscribe_url)
        assert response.status_code == 202
        assert ReviewerSubscription.objects.count() == 0

    def test_unsubscribe(self):
        ReviewerSubscription.objects.create(
            user=self.user, addon=self.addon)
        self.grant_permission(self.user, 'Addons:PostReview')
        self.client.login_api(self.user)
        self.subscribe_url = reverse(
            'reviewers-addon-subscribe', kwargs={'pk': self.addon.pk})
        response = self.client.post(self.unsubscribe_url)
        assert response.status_code == 202
        assert ReviewerSubscription.objects.count() == 0

    def test_unsubscribe_dont_touch_another(self):
        another_user = user_factory()
        another_addon = addon_factory()
        ReviewerSubscription.objects.create(
            user=self.user, addon=self.addon)
        ReviewerSubscription.objects.create(
            user=self.user, addon=another_addon)
        ReviewerSubscription.objects.create(
            user=another_user, addon=self.addon)
        self.grant_permission(self.user, 'Addons:PostReview')
        self.client.login_api(self.user)
        self.subscribe_url = reverse(
            'reviewers-addon-subscribe', kwargs={'pk': self.addon.pk})
        response = self.client.post(self.unsubscribe_url)
        assert response.status_code == 202
        assert ReviewerSubscription.objects.count() == 2
        assert not ReviewerSubscription.objects.filter(
            addon=self.addon, user=self.user).exists()

    def test_enable_not_logged_in(self):
        response = self.client.post(self.enable_url)
        assert response.status_code == 401

    def test_enable_no_rights(self):
        self.client.login_api(self.user)
        response = self.client.post(self.enable_url)
        assert response.status_code == 403

        # Being a reviewer is not enough.
        self.grant_permission(self.user, 'Addons:Review')
        response = self.client.post(self.enable_url)
        assert response.status_code == 403

    def test_enable_addon_does_not_exist(self):
        self.grant_permission(self.user, 'Reviews:Admin')
        self.client.login_api(self.user)
        self.enable_url = reverse(
            'reviewers-addon-enable', kwargs={'pk': self.addon.pk + 42})
        response = self.client.post(self.enable_url)
        assert response.status_code == 404

    def test_enable(self):
        self.grant_permission(self.user, 'Reviews:Admin')
        self.client.login_api(self.user)
        self.addon.update(status=amo.STATUS_DISABLED)
        response = self.client.post(self.enable_url)
        assert response.status_code == 202
        self.addon.reload()
        assert self.addon.status == amo.STATUS_PUBLIC
        assert ActivityLog.objects.count() == 1
        activity_log = ActivityLog.objects.latest('pk')
        assert activity_log.action == amo.LOG.CHANGE_STATUS.id
        assert activity_log.arguments[0] == self.addon

    def test_enable_already_public(self):
        self.grant_permission(self.user, 'Reviews:Admin')
        self.client.login_api(self.user)
        response = self.client.post(self.enable_url)
        assert response.status_code == 202
        self.addon.reload()
        assert self.addon.status == amo.STATUS_PUBLIC
        assert ActivityLog.objects.count() == 1
        activity_log = ActivityLog.objects.latest('pk')
        assert activity_log.action == amo.LOG.CHANGE_STATUS.id
        assert activity_log.arguments[0] == self.addon

    def test_enable_no_public_versions_should_fall_back_to_incomplete(self):
        self.grant_permission(self.user, 'Reviews:Admin')
        self.client.login_api(self.user)
        self.addon.update(status=amo.STATUS_DISABLED)
        self.addon.versions.all().delete()
        response = self.client.post(self.enable_url)
        assert response.status_code == 202
        self.addon.reload()
        assert self.addon.status == amo.STATUS_NULL

    def test_enable_version_is_awaiting_review_fall_back_to_nominated(self):
        self.grant_permission(self.user, 'Reviews:Admin')
        self.client.login_api(self.user)
        self.addon.current_version.files.all().update(
            status=amo.STATUS_AWAITING_REVIEW)
        self.addon.update(status=amo.STATUS_DISABLED)
        response = self.client.post(self.enable_url)
        assert response.status_code == 202
        self.addon.reload()
        assert self.addon.status == amo.STATUS_NOMINATED

    def test_disable_not_logged_in(self):
        response = self.client.post(self.disable_url)
        assert response.status_code == 401

    def test_disable_no_rights(self):
        self.client.login_api(self.user)
        response = self.client.post(self.disable_url)
        assert response.status_code == 403

        # Being a reviewer is not enough.
        self.grant_permission(self.user, 'Addons:Review')
        response = self.client.post(self.disable_url)
        assert response.status_code == 403

    def test_disable_addon_does_not_exist(self):
        self.grant_permission(self.user, 'Reviews:Admin')
        self.client.login_api(self.user)
        self.disable_url = reverse(
            'reviewers-addon-enable', kwargs={'pk': self.addon.pk + 42})
        response = self.client.post(self.disable_url)
        assert response.status_code == 404

    def test_disable(self):
        self.grant_permission(self.user, 'Reviews:Admin')
        self.client.login_api(self.user)
        self.addon.versions.all().delete()
        response = self.client.post(self.disable_url)
        assert response.status_code == 202
        self.addon.reload()
        assert self.addon.status == amo.STATUS_DISABLED
        assert ActivityLog.objects.count() == 1
        activity_log = ActivityLog.objects.latest('pk')
        assert activity_log.action == amo.LOG.CHANGE_STATUS.id
        assert activity_log.arguments[0] == self.addon

    def test_patch_flags_not_logged_in(self):
        response = self.client.patch(
            self.flags_url, {'auto_approval_disabled': True})
        assert response.status_code == 401

    def test_patch_flags_no_permissions(self):
        self.client.login_api(self.user)
        response = self.client.patch(
            self.flags_url, {'auto_approval_disabled': True})
        assert response.status_code == 403

        # Being a reviewer is not enough.
        self.grant_permission(self.user, 'Addons:Review')
        response = self.client.patch(
            self.flags_url, {'auto_approval_disabled': True})
        assert response.status_code == 403

    def test_patch_flags_addon_does_not_exist(self):
        self.grant_permission(self.user, 'Reviews:Admin')
        self.client.login_api(self.user)
        self.flags_url = reverse(
            'reviewers-addon-flags', kwargs={'pk': self.addon.pk + 42})
        response = self.client.patch(
            self.flags_url, {'auto_approval_disabled': True})
        assert response.status_code == 404

    def test_patch_flags_no_flags_yet_still_works_transparently(self):
        assert not AddonReviewerFlags.objects.filter(addon=self.addon).exists()
        self.grant_permission(self.user, 'Reviews:Admin')
        self.client.login_api(self.user)
        response = self.client.patch(
            self.flags_url, {'auto_approval_disabled': True})
        assert response.status_code == 200
        assert AddonReviewerFlags.objects.filter(addon=self.addon).exists()
        reviewer_flags = AddonReviewerFlags.objects.get(addon=self.addon)
        assert reviewer_flags.auto_approval_disabled
        assert ActivityLog.objects.count() == 0

    def test_patch_flags_change_everything(self):
        AddonReviewerFlags.objects.create(
            addon=self.addon,
            pending_info_request=self.days_ago(1),
            auto_approval_disabled=True)
        self.grant_permission(self.user, 'Reviews:Admin')
        self.client.login_api(self.user)
        data = {
            'auto_approval_disabled': False,
            'needs_admin_code_review': True,
            'needs_admin_content_review': True,
            'pending_info_request': None,
        }
        response = self.client.patch(self.flags_url, data)
        assert response.status_code == 200
        assert AddonReviewerFlags.objects.filter(addon=self.addon).exists()
        reviewer_flags = AddonReviewerFlags.objects.get(addon=self.addon)
        assert reviewer_flags.auto_approval_disabled is False
        assert reviewer_flags.needs_admin_code_review is True
        assert reviewer_flags.needs_admin_content_review is True
        assert reviewer_flags.pending_info_request is None
        assert ActivityLog.objects.count() == 1
        activity_log = ActivityLog.objects.latest('pk')
        assert activity_log.action == amo.LOG.ADMIN_ALTER_INFO_REQUEST.id
        assert activity_log.arguments[0] == self.addon
