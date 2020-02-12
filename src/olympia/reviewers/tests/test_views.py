# -*- coding: utf-8 -*-
import json
import os
import time
from urllib.parse import parse_qs

from collections import OrderedDict
from datetime import datetime, timedelta
from unittest import mock

from django.conf import settings
from django.core import mail
from django.core.cache import cache
from django.core.files import temp
from django.core.files.base import File as DjangoFile
from django.db import connection, reset_queries
from django.test.client import RequestFactory
from django.test.utils import override_settings

from rest_framework.test import APIRequestFactory

import pytest

from freezegun import freeze_time
from lxml.html import HTMLParser, fromstring
from pyquery import PyQuery as pq
from waffle.testutils import override_flag

from olympia import amo, core, ratings
from olympia.abuse.models import AbuseReport
from olympia.access.models import Group, GroupUser
from olympia.accounts.views import API_TOKEN_COOKIE
from olympia.accounts.serializers import BaseUserSerializer
from olympia.activity.models import ActivityLog, DraftComment
from olympia.addons.models import (
    Addon, AddonApprovalsCounter, AddonReviewerFlags, AddonUser, DeniedGuid,
    ReusedGUID)
from olympia.amo.storage_utils import copy_stored_file
from olympia.amo.templatetags.jinja_helpers import (
    absolutify, format_date, format_datetime)
from olympia.amo.tests import (
    APITestClient, TestCase, addon_factory, check_links, file_factory, formset,
    initial, reverse_ns, user_factory, version_factory)
from olympia.amo.urlresolvers import reverse
from olympia.blocklist.models import Block
from olympia.discovery.models import DiscoveryItem
from olympia.files.models import File, FileValidation, WebextPermission
from olympia.lib.git import AddonGitRepository
from olympia.lib.tests.test_git import apply_changes
from olympia.ratings.models import Rating, RatingFlag
from olympia.reviewers.models import (
    AutoApprovalSummary, CannedResponse, ReviewerScore, ReviewerSubscription,
    Whiteboard)
from olympia.reviewers.utils import ContentReviewTable
from olympia.reviewers.views import _queue
from olympia.reviewers.serializers import (
    CannedResponseSerializer, AddonBrowseVersionSerializer)
from olympia.users.models import UserProfile
from olympia.versions.models import ApplicationsVersions, AppVersion
from olympia.versions.tasks import extract_version_to_git
from olympia.zadmin.models import get_config


EMPTY_PNG = (
    b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08'
    b'\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00'
    b'\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82')


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
        return Rating.objects.create(user=u, addon=a, body='baa')


class TestRatingsModerationLog(ReviewerTest):

    def setUp(self):
        super(TestRatingsModerationLog, self).setUp()
        user = user_factory()
        self.grant_permission(user, 'Ratings:Moderate')
        self.client.login(email=user.email)
        self.url = reverse('reviewers.ratings_moderation_log')
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
        for i in range(2):
            ActivityLog.create(amo.LOG.APPROVE_RATING, review, review.addon)
            ActivityLog.create(amo.LOG.DELETE_RATING, review.id, review.addon)
        response = self.client.get(self.url, {'filter': 'deleted'})
        assert response.status_code == 200
        assert pq(response.content)('tbody tr').length == 2

    def test_no_results(self):
        response = self.client.get(self.url, {'end': '2004-01-01'})
        assert response.status_code == 200
        assert b'"no-results"' in response.content

    def test_moderation_log_detail(self):
        review = self.make_review()
        ActivityLog.create(amo.LOG.APPROVE_RATING, review, review.addon)
        id_ = ActivityLog.objects.moderation_events()[0].id
        response = self.client.get(
            reverse('reviewers.ratings_moderation_log.detail', args=[id_]))
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
        with self.assertNumQueries(15):
            # 15 queries:
            # - 2 savepoints because of tests
            # - 2 user and its groups
            # - 2 for motd config and site notice
            # - 2 for collections and addons belonging to the user (menu bar)
            # - 1 count for the pagination
            # - 1 for the activities
            # - 1 for the users for these activities
            # - 1 for the addons for these activities
            # - 1 for the translations of these add-ons
            # - 1 for the versions for these activities
            # - 1 for the translations of these versions
            response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        rows = doc('tbody tr')
        assert rows.filter(':not(.hide)').length == 2
        assert rows.filter('.hide').eq(0).text() == 'youwin'

        # Add more activity, it'd still should not cause more queries.
        self.make_an_approval(amo.LOG.APPROVE_CONTENT, addon=addon_factory())
        self.make_an_approval(amo.LOG.REJECT_CONTENT, addon=addon_factory())
        with self.assertNumQueries(15):
            response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        rows = doc('tbody tr')
        assert rows.filter(':not(.hide)').length == 4

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
        self.make_an_approval(amo.LOG.REQUEST_ADMIN_REVIEW_CODE,
                              comment='hello')
        response = self.client.get(self.url, {'search': 'hello'})
        assert response.status_code == 200
        assert pq(response.content)(
            '#log-listing tbody tr.hide').eq(0).text() == 'hello'

    def test_search_comment_case_exists(self):
        """Search by comment, with case."""
        self.make_an_approval(amo.LOG.REQUEST_ADMIN_REVIEW_CODE,
                              comment='hello')
        response = self.client.get(self.url, {'search': 'HeLlO'})
        assert response.status_code == 200
        assert pq(response.content)(
            '#log-listing tbody tr.hide').eq(0).text() == 'hello'

    def test_search_comment_doesnt_exist(self):
        """Search by comment, with no results."""
        self.make_an_approval(amo.LOG.REQUEST_ADMIN_REVIEW_CODE,
                              comment='hello')
        response = self.client.get(self.url, {'search': 'bye'})
        assert response.status_code == 200
        assert pq(response.content)('.no-results').length == 1

    def test_search_author_exists(self):
        """Search by author."""
        self.make_approvals()
        self.make_an_approval(
            amo.LOG.REQUEST_ADMIN_REVIEW_CODE, username='reviewer',
            comment='hi')

        response = self.client.get(self.url, {'search': 'reviewer'})
        assert response.status_code == 200
        rows = pq(response.content)('#log-listing tbody tr')

        assert rows.filter(':not(.hide)').length == 1
        assert rows.filter('.hide').eq(0).text() == 'hi'

    def test_search_author_case_exists(self):
        """Search by author, with case."""
        self.make_approvals()
        self.make_an_approval(
            amo.LOG.REQUEST_ADMIN_REVIEW_CODE, username='reviewer',
            comment='hi')

        response = self.client.get(self.url, {'search': 'ReviEwEr'})
        assert response.status_code == 200
        rows = pq(response.content)('#log-listing tbody tr')

        assert rows.filter(':not(.hide)').length == 1
        assert rows.filter('.hide').eq(0).text() == 'hi'

    def test_search_author_doesnt_exist(self):
        """Search by author, with no results."""
        self.make_approvals()
        self.make_an_approval(
            amo.LOG.REQUEST_ADMIN_REVIEW_CODE, username='reviewer')

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

    def test_addon_missing(self):
        self.make_approvals()
        activity = ActivityLog.objects.latest('pk')
        activity.update(_arguments='')
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
        self.make_an_approval(amo.LOG.REQUEST_ADMIN_REVIEW_CODE)
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert pq(response.content)('#log-listing tr td a').eq(1).text() == (
            'Admin add-on-review requested')

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

    def test_reviewers_can_only_see_addon_types_they_have_perms_for(self):
        def check_two_showing():
            response = self.client.get(self.url)
            assert response.status_code == 200
            doc = pq(response .content)
            assert doc('#log-filter button'), 'No filters.'
            rows = doc('tbody tr')
            assert rows.filter(':not(.hide)').length == 2
            assert rows.filter('.hide').eq(0).text() == 'youwin'

        def check_none_showing():
            response = self.client.get(self.url)
            assert response.status_code == 200
            doc = pq(response.content)
            assert not doc('tbody tr :not(.hide)')

        self.make_approvals()
        for perm in ['Review', 'ContentReview', 'PostReview']:
            GroupUser.objects.filter(user=self.user).delete()
            self.grant_permission(self.user, 'Addons:%s' % perm)
            # Should have 2 showing.
            check_two_showing()

        # Should have none showing if the addons are static themes.
        for addon in Addon.objects.all():
            addon.update(type=amo.ADDON_STATICTHEME)
        for perm in ['Review', 'ContentReview', 'PostReview']:
            GroupUser.objects.filter(user=self.user).delete()
            self.grant_permission(self.user, 'Addons:%s' % perm)
            check_none_showing()

        # But they should have 2 showing for someone with the right perms.
        GroupUser.objects.filter(user=self.user).delete()
        self.grant_permission(self.user, 'Addons:ThemeReview')
        check_two_showing()

        # Check if we set them back to extensions theme reviewers can't see 'em
        for addon in Addon.objects.all():
            addon.update(type=amo.ADDON_EXTENSION)
        check_none_showing()


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
        # Recommended extensions
        DiscoveryItem.objects.create(
            recommendable=True,
            addon=addon_factory(
                status=amo.STATUS_NOMINATED,
                version_kw={'recommendation_approved': True},
                file_kw={'status': amo.STATUS_AWAITING_REVIEW}))
        DiscoveryItem.objects.create(
            recommendable=True,
            addon=version_factory(
                addon=addon_factory(),
                recommendation_approved=True,
                file_kw={'status': amo.STATUS_AWAITING_REVIEW}).addon)
        # Nominated and pending themes, not being counted
        # as per https://github.com/mozilla/addons-server/issues/11796
        addon_factory(
            status=amo.STATUS_NOMINATED,
            type=amo.ADDON_STATICTHEME,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW})
        version_factory(
            addon=addon_factory(type=amo.ADDON_STATICTHEME),
            file_kw={'status': amo.STATUS_AWAITING_REVIEW})
        # Nominated and pending extensions.
        version_factory(
            addon=addon_factory(),
            file_kw={'status': amo.STATUS_AWAITING_REVIEW})
        AddonReviewerFlags.objects.create(
            needs_admin_code_review=True,
            addon=addon_factory(
                status=amo.STATUS_NOMINATED,
                file_kw={'status': amo.STATUS_AWAITING_REVIEW}))
        under_admin_review_and_pending = addon_factory()
        AddonReviewerFlags.objects.create(
            addon=under_admin_review_and_pending,
            needs_admin_theme_review=True)
        version_factory(
            addon=under_admin_review_and_pending,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW})
        # Auto-approved and Content Review.
        addon1 = addon_factory(
            file_kw={'is_webextension': True})
        AddonApprovalsCounter.reset_for_addon(addon=addon1)
        AutoApprovalSummary.objects.create(
            version=addon1.current_version, verdict=amo.AUTO_APPROVED)
        under_content_review = addon_factory(
            file_kw={'is_webextension': True})
        AddonApprovalsCounter.reset_for_addon(addon=under_content_review)
        AutoApprovalSummary.objects.create(
            version=under_content_review.current_version,
            verdict=amo.AUTO_APPROVED)
        AddonReviewerFlags.objects.create(
            addon=under_content_review, needs_admin_content_review=True)
        addon2 = addon_factory(
            file_kw={'is_webextension': True})
        AddonApprovalsCounter.reset_for_addon(addon=addon2)
        AutoApprovalSummary.objects.create(
            version=addon2.current_version, verdict=amo.AUTO_APPROVED)
        AddonReviewerFlags.objects.create(
            addon=addon2, needs_admin_content_review=True)
        under_code_review = addon_factory(
            file_kw={'is_webextension': True})
        AddonApprovalsCounter.reset_for_addon(addon=under_code_review)
        AutoApprovalSummary.objects.create(
            version=under_code_review.current_version,
            verdict=amo.AUTO_APPROVED)
        AddonReviewerFlags.objects.create(
            addon=under_code_review, needs_admin_code_review=True)
        admins_group = Group.objects.create(name='Admins', rules='*:*')
        GroupUser.objects.create(user=self.user, group=admins_group)

        # Pending addon with expired info request.
        addon1 = addon_factory(name=u'Pending Addön 1',
                               status=amo.STATUS_NOMINATED)
        AddonReviewerFlags.objects.create(
            addon=addon1,
            pending_info_request=self.days_ago(2))

        # Public addon with expired info request.
        addon2 = addon_factory(name=u'Public Addön 2',
                               status=amo.STATUS_APPROVED)
        AddonReviewerFlags.objects.create(
            addon=addon2,
            pending_info_request=self.days_ago(42))

        # Deleted addon with expired info request.
        addon3 = addon_factory(name=u'Deleted Addön 3',
                               status=amo.STATUS_DELETED)
        AddonReviewerFlags.objects.create(
            addon=addon3,
            pending_info_request=self.days_ago(42))

        # Mozilla-disabled addon with expired info request.
        addon4 = addon_factory(name=u'Disabled Addön 4',
                               status=amo.STATUS_DISABLED)
        AddonReviewerFlags.objects.create(
            addon=addon4,
            pending_info_request=self.days_ago(42))

        # Incomplete addon with expired info request.
        addon5 = addon_factory(name=u'Incomplete Addön 5',
                               status=amo.STATUS_NULL)
        AddonReviewerFlags.objects.create(
            addon=addon5,
            pending_info_request=self.days_ago(42))

        # Invisible (user-disabled) addon with expired info request.
        addon6 = addon_factory(name=u'Incomplete Addön 5',
                               status=amo.STATUS_APPROVED,
                               disabled_by_user=True)
        AddonReviewerFlags.objects.create(
            addon=addon6,
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
        assert len(doc('.dashboard h3')) == 9  # All sections are present.
        expected_links = [
            reverse('reviewers.queue_recommended'),
            reverse('reviewers.queue_extension'),
            reverse('reviewers.performance'),
            reverse('reviewers.reviewlog'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Guide',
            reverse('reviewers.queue_needs_human_review'),
            reverse('reviewers.queue_auto_approved'),
            reverse('reviewers.performance'),
            reverse('reviewers.reviewlog'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Guide',
            reverse('reviewers.queue_content_review'),
            reverse('reviewers.performance'),
            reverse('reviewers.queue_theme_nominated'),
            reverse('reviewers.queue_theme_pending'),
            reverse('reviewers.performance'),
            reverse('reviewers.reviewlog'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Themes/Guidelines',
            reverse('reviewers.queue_moderated'),
            reverse('reviewers.ratings_moderation_log'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Guide/Moderation',
            reverse('reviewers.unlisted_queue_all'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Guide',
            reverse('reviewers.motd'),
            reverse('reviewers.queue_expired_info_requests'),
        ]
        links = [link.attrib['href'] for link in doc('.dashboard a')]
        assert links == expected_links
        # pre-approval addons
        assert doc('.dashboard a')[0].text == 'Recommended (2)'
        assert doc('.dashboard a')[1].text == 'Other Pending Review (3)'
        # auto-approved addons
        assert doc('.dashboard a')[6].text == 'Auto Approved Add-ons (4)'
        # content review
        assert doc('.dashboard a')[10].text == 'Content Review (11)'
        # themes
        assert doc('.dashboard a')[12].text == 'New (1)'
        assert doc('.dashboard a')[13].text == 'Updates (1)'
        # user ratings moderation
        assert (doc('.dashboard a')[17].text ==
                'Ratings Awaiting Moderation (1)')
        # admin tools
        assert (doc('.dashboard a')[23].text ==
                'Expired Information Requests (2)')

    def test_can_see_all_through_reviewer_view_all_permission(self):
        self.grant_permission(self.user, 'ReviewerTools:View')
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert len(doc('.dashboard h3')) == 9  # All sections are present.
        expected_links = [
            reverse('reviewers.queue_extension'),
            reverse('reviewers.performance'),
            reverse('reviewers.reviewlog'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Guide',
            reverse('reviewers.queue_needs_human_review'),
            reverse('reviewers.queue_auto_approved'),
            reverse('reviewers.performance'),
            reverse('reviewers.reviewlog'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Guide',
            reverse('reviewers.queue_content_review'),
            reverse('reviewers.performance'),
            reverse('reviewers.queue_theme_nominated'),
            reverse('reviewers.queue_theme_pending'),
            reverse('reviewers.performance'),
            reverse('reviewers.reviewlog'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Themes/Guidelines',
            reverse('reviewers.queue_moderated'),
            reverse('reviewers.ratings_moderation_log'),
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
        assert len(doc('.dashboard h3')) == 2
        expected_links = [
            reverse('reviewers.queue_extension'),
            reverse('reviewers.performance'),
            reverse('reviewers.reviewlog'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Guide',
            reverse('reviewers.queue_needs_human_review'),
        ]
        links = [link.attrib['href'] for link in doc('.dashboard a')]
        assert links == expected_links
        assert doc('.dashboard a')[0].text == 'Other Pending Review (3)'

    def test_post_reviewer(self):
        # Create an add-on to test the queue count. It's under admin content
        # review but that does not have an impact.
        addon = addon_factory(
            file_kw={'is_webextension': True})
        AddonApprovalsCounter.reset_for_addon(addon=addon)
        AutoApprovalSummary.objects.create(
            version=addon.current_version, verdict=amo.AUTO_APPROVED)
        AddonReviewerFlags.objects.create(
            addon=addon, needs_admin_content_review=True)
        # This one however is under admin code review, it's ignored.
        under_code_review = addon_factory(
            file_kw={'is_webextension': True})
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
            file_kw={'is_webextension': True})
        AddonApprovalsCounter.reset_for_addon(addon=addon)
        AutoApprovalSummary.objects.create(
            version=addon.current_version, verdict=amo.AUTO_APPROVED)
        AddonReviewerFlags.objects.create(
            addon=addon, needs_admin_code_review=True)
        # This one is under admin *content* review so it's ignored.
        under_content_review = addon_factory(
            file_kw={'is_webextension': True})
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
            reverse('reviewers.ratings_moderation_log'),
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
            addon=under_admin_review, needs_admin_theme_review=True)
        under_admin_review_and_pending = addon_factory(
            type=amo.ADDON_STATICTHEME)
        AddonReviewerFlags.objects.create(
            addon=under_admin_review_and_pending,
            needs_admin_theme_review=True)
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
            reverse('reviewers.queue_theme_nominated'),
            reverse('reviewers.queue_theme_pending'),
            reverse('reviewers.performance'),
            reverse('reviewers.reviewlog'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Themes/Guidelines',
        ]
        links = [link.attrib['href'] for link in doc('.dashboard a')]
        assert links == expected_links
        assert doc('.dashboard a')[0].text == 'New (1)'
        assert doc('.dashboard a')[1].text == 'Updates (2)'

    def test_post_reviewer_and_content_reviewer(self):
        # Create add-ons to test the queue count. The first add-on has its
        # content approved, so the post review queue should contain 2 add-ons,
        # and the content review queue only 1.
        addon = addon_factory(
            file_kw={'is_webextension': True})
        AutoApprovalSummary.objects.create(
            version=addon.current_version, verdict=amo.AUTO_APPROVED)
        AddonApprovalsCounter.approve_content_for_addon(addon=addon)

        addon = addon_factory(
            file_kw={'is_webextension': True})
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
        assert len(doc('.dashboard h3')) == 3
        expected_links = [
            reverse('reviewers.queue_extension'),
            reverse('reviewers.performance'),
            reverse('reviewers.reviewlog'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Guide',
            reverse('reviewers.queue_needs_human_review'),
            reverse('reviewers.queue_moderated'),
            reverse('reviewers.ratings_moderation_log'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Guide/Moderation',
        ]
        links = [link.attrib['href'] for link in doc('.dashboard a')]
        assert links == expected_links
        assert doc('.dashboard a')[0].text == 'Other Pending Review (0)'
        assert 'target' not in doc('.dashboard a')[0].attrib
        assert doc('.dashboard a')[5].text == 'Ratings Awaiting Moderation (0)'
        assert 'target' not in doc('.dashboard a')[5].attrib
        assert doc('.dashboard a')[7].text == 'Moderation Guide'
        assert doc('.dashboard a')[7].attrib['target'] == '_blank'
        assert doc('.dashboard a')[7].attrib['rel'] == 'noopener noreferrer'

    def test_view_mobile_site_link_hidden(self):
        self.grant_permission(self.user, 'ReviewerTools:View')
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert not doc('a.mobile-link')


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
        self.url = reverse('reviewers.queue_extension')
        self.addons = OrderedDict()
        self.expected_addons = []
        self.channel_name = 'listed' if self.listed else 'unlisted'

    def generate_files(self, subset=None, files=None):
        if subset is None:
            subset = []
        files = files or OrderedDict([
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
            ('Pending One', {
                'version_str': '0.1',
                'addon_status': amo.STATUS_APPROVED,
                'file_status': amo.STATUS_AWAITING_REVIEW,
            }),
            ('Pending Two', {
                'version_str': '0.1',
                'addon_status': amo.STATUS_APPROVED,
                'file_status': amo.STATUS_AWAITING_REVIEW,
            }),
            ('Public', {
                'version_str': '0.1',
                'addon_status': amo.STATUS_APPROVED,
                'file_status': amo.STATUS_APPROVED,
            }),
        ])
        results = OrderedDict()
        channel = (amo.RELEASE_CHANNEL_LISTED if self.listed else
                   amo.RELEASE_CHANNEL_UNLISTED)
        for name, attrs in files.items():
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

    def get_expected_addons_by_names(self, names):
        expected_addons = []
        files = self.generate_files()
        for name in sorted(names):
            if name in files:
                expected_addons.append(files[name])
        # Make sure all elements have been added
        assert len(expected_addons) == len(names)
        return expected_addons

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
        # We typically don't include the channel name if it's the
        # default one, 'listed'.
        channel = [] if self.channel_name == 'listed' else [self.channel_name]
        for idx, addon in enumerate(self.expected_addons):
            if self.channel_name == 'unlisted':
                # In unlisted queue we don't display latest version number.
                name = str(addon.name)
            else:
                latest_version = self.get_addon_latest_version(addon)
                assert latest_version
                name = '%s %s' % (str(addon.name), latest_version.version)
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

        # Theme reviewer doesn't have access either.
        self.client.logout()
        assert self.client.login(email='theme_reviewer@mozilla.com')
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

    @mock.patch.multiple('olympia.reviewers.views',
                         REVIEWS_PER_PAGE_MAX=1,
                         REVIEWS_PER_PAGE=1)
    def test_max_per_page(self):
        self.generate_files()

        response = self.client.get(self.url, {'per_page': '2'})
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('.data-grid-top .num-results').text() == (
            u'Results 1\u20131 of 4')

    @mock.patch('olympia.reviewers.views.REVIEWS_PER_PAGE', new=1)
    def test_reviews_per_page(self):
        self.generate_files()

        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('.data-grid-top .num-results').text() == (
            u'Results 1\u20131 of 4')

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
        params = {'searching': ['True'],
                  'text_query': ['abc'],
                  'addon_type_ids': ['2'],
                  'sort': ['addon_type_id']}
        response = self.client.get(self.url, params)
        assert response.status_code == 200
        tr = pq(response.content)('#addon-queue tr')
        sorts = {
            # Column index => sort.
            1: 'addon_name',        # Add-on.
            2: '-addon_type_id',    # Type.
            3: 'waiting_time_min',  # Waiting Time.
        }
        for idx, sort in sorts.items():
            # Get column link.
            a = tr('th').eq(idx).find('a')
            # Update expected GET parameters with sort type.
            params.update(sort=[sort])
            # Parse querystring of link to make sure `sort` type is correct.
            assert parse_qs(a.attr('href').split('?')[1]) == params

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
            u'Results 1\u20131 of 4')
        assert doc('.data-grid-bottom .num-results').text() == (
            u'Results 1\u20131 of 4')

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

    def test_flags_is_restart_required(self):
        addon = addon_factory(
            status=amo.STATUS_NOMINATED, name='Some Add-on',
            version_kw={'version': '0.1'},
            file_kw={'status': amo.STATUS_AWAITING_REVIEW,
                     'is_restart_required': True})

        r = self.client.get(reverse('reviewers.queue_extension'))

        rows = pq(r.content)('#addon-queue tr.addon-row')
        assert rows.length == 1
        assert rows.attr('data-addon') == str(addon.id)
        assert rows.find('td').eq(1).text() == 'Some Add-on 0.1'
        assert rows.find('.ed-sprite-is_restart_required').length == 1

    def test_flags_is_restart_required_false(self):
        addon = addon_factory(
            status=amo.STATUS_NOMINATED, name='Restartless',
            version_kw={'version': '0.1'},
            file_kw={'status': amo.STATUS_AWAITING_REVIEW,
                     'is_restart_required': False})

        r = self.client.get(reverse('reviewers.queue_extension'))

        rows = pq(r.content)('#addon-queue tr.addon-row')
        assert rows.length == 1
        assert rows.attr('data-addon') == str(addon.id)
        assert rows.find('td').eq(1).text() == 'Restartless 0.1'
        assert rows.find('.ed-sprite-is_restart_required').length == 0

    def test_tabnav_permissions(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        links = doc('.tabnav li a').map(lambda i, e: e.attrib['href'])
        expected = [
            reverse('reviewers.queue_extension'),
            reverse('reviewers.queue_needs_human_review'),
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

        self.grant_permission(self.user, 'Addons:RecommendedReview')
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        links = doc('.tabnav li a').map(lambda i, e: e.attrib['href'])
        expected.insert(0, reverse('reviewers.queue_recommended'))
        assert links == expected

        self.grant_permission(self.user, 'Reviews:Admin')
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        links = doc('.tabnav li a').map(lambda i, e: e.attrib['href'])
        expected.append(reverse('reviewers.queue_expired_info_requests'))
        assert links == expected

    @override_settings(DEBUG=True, LESS_PREPROCESS=False)
    def test_queue_is_never_executing_the_full_query(self):
        """Test that _queue() is paginating without accidentally executing the
        full query."""
        self.grant_permission(self.user, 'Addons:ContentReview')
        request = RequestFactory().get('/')
        request.user = self.user
        request.APP = amo.FIREFOX

        self.generate_files()
        qs = Addon.objects.all().no_transforms()

        # Execute the queryset we're passing to the _queue() so that we have
        # the exact query to compare to later (we can't use str(qs.query) to do
        # that, it has subtle differences in representation because of the way
        # params are passed for the lang=lang hack).
        reset_queries()
        list(qs)
        assert len(connection.queries) == 1
        full_query = connection.queries[0]['sql']

        qs = qs.all()  # Trash queryset caching
        reset_queries()
        response = _queue(
            request, ContentReviewTable, 'content_review', qs=qs,
            SearchForm=None)
        assert connection.queries
        assert full_query not in [item['sql'] for item in connection.queries]
        assert response.status_code == 200
        doc = pq(response.content)
        assert len(doc('#addon-queue tr.addon-row')) == qs.count()

        request = RequestFactory().get('/', {'per_page': 2})
        request.user = self.user
        request.APP = amo.FIREFOX
        qs = qs.all()  # Trash queryset caching
        reset_queries()
        response = _queue(
            request, ContentReviewTable, 'content_review', qs=qs,
            SearchForm=None)
        assert connection.queries
        assert full_query not in [item['sql'] for item in connection.queries]
        assert response.status_code == 200
        doc = pq(response.content)
        assert len(doc('#addon-queue tr.addon-row')) == 2

        request = RequestFactory().get('/', {'per_page': 2, 'page': 2})
        request.user = self.user
        request.APP = amo.FIREFOX
        qs = qs.all()  # Trash queryset caching
        reset_queries()
        response = _queue(
            request, ContentReviewTable, 'content_review', qs=qs,
            SearchForm=None)
        assert connection.queries
        assert full_query not in [item['sql'] for item in connection.queries]
        assert response.status_code == 200
        doc = pq(response.content)
        assert len(doc('#addon-queue tr.addon-row')) == 2


class TestThemePendingQueue(QueueTest):

    def setUp(self):
        super(TestThemePendingQueue, self).setUp()
        # These should be the only ones present.
        self.expected_addons = self.get_expected_addons_by_names(
            ['Pending One', 'Pending Two'])
        Addon.objects.all().update(type=amo.ADDON_STATICTHEME)
        self.url = reverse('reviewers.queue_theme_pending')
        GroupUser.objects.filter(user=self.user).delete()
        self.grant_permission(self.user, 'Addons:ThemeReview')

    def test_results(self):
        self._test_results()

    def test_queue_layout(self):
        self._test_queue_layout('🎨 Updates',
                                tab_position=1, total_addons=2, total_queues=2)

    def test_extensions_filtered_out(self):
        self.addons['Pending Two'].update(type=amo.ADDON_EXTENSION)

        # Extensions shouldn't be shown
        self.expected_addons = [self.addons['Pending One']]
        self._test_results()

        # Even if you have that permission also
        self.grant_permission(self.user, 'Addons:Review')
        self.expected_addons = [self.addons['Pending One']]
        self._test_results()


class TestExtensionQueue(QueueTest):

    def setUp(self):
        super().setUp()
        # These should be the only ones present.
        self.expected_addons = self.get_expected_addons_by_names(
            ['Pending One', 'Pending Two', 'Nominated One', 'Nominated Two'])
        self.url = reverse('reviewers.queue_extension')

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
        self._test_queue_layout('🛠️ Other Pending Review',
                                tab_position=0, total_addons=4, total_queues=2)

    def test_webextensions_filtered_out_because_of_post_review(self):
        self.addons['Nominated Two'].find_latest_version(
            channel=amo.RELEASE_CHANNEL_LISTED).files.update(
            is_webextension=True)
        self.addons['Pending Two'].find_latest_version(
            channel=amo.RELEASE_CHANNEL_LISTED).files.update(
            is_webextension=True)

        # Webextensions are filtered out from the queue since auto_approve is
        # taking care of them.
        self.expected_addons = [
            self.addons['Nominated One'], self.addons['Pending One']]
        self._test_results()

    def test_webextension_with_auto_approval_disabled_false_filtered_out(self):
        self.addons['Pending Two'].find_latest_version(
            channel=amo.RELEASE_CHANNEL_LISTED).files.update(
            is_webextension=True)
        AddonReviewerFlags.objects.create(
            addon=self.addons['Pending Two'], auto_approval_disabled=False)
        self.addons['Nominated Two'].find_latest_version(
            channel=amo.RELEASE_CHANNEL_LISTED).files.update(
            is_webextension=True)
        AddonReviewerFlags.objects.create(
            addon=self.addons['Nominated Two'], auto_approval_disabled=False)

        self.expected_addons = [
            self.addons['Nominated One'], self.addons['Pending One']]
        self._test_results()

    def test_webextension_with_auto_approval_disabled_does_show_up(self):
        self.addons['Pending Two'].find_latest_version(
            channel=amo.RELEASE_CHANNEL_LISTED).files.update(
            is_webextension=True)
        self.addons['Nominated Two'].find_latest_version(
            channel=amo.RELEASE_CHANNEL_LISTED).files.update(
            is_webextension=True)

        self.addons['Pending One'].find_latest_version(
            channel=amo.RELEASE_CHANNEL_LISTED).files.update(
            is_webextension=True)
        AddonReviewerFlags.objects.create(
            addon=self.addons['Pending One'], auto_approval_disabled=True)
        self.addons['Nominated One'].find_latest_version(
            channel=amo.RELEASE_CHANNEL_LISTED).files.update(
            is_webextension=True)
        AddonReviewerFlags.objects.create(
            addon=self.addons['Nominated One'], auto_approval_disabled=True)

        self.expected_addons = [
            self.addons['Nominated One'], self.addons['Pending One']]
        self._test_results()

    def test_webextension_with_auto_approval_delayed_until_past_filtered_out(
            self):
        self.addons['Pending Two'].find_latest_version(
            channel=amo.RELEASE_CHANNEL_LISTED).files.update(
            is_webextension=True)
        AddonReviewerFlags.objects.create(
            addon=self.addons['Pending Two'],
            auto_approval_delayed_until=datetime.now() - timedelta(hours=24))
        self.addons['Nominated Two'].find_latest_version(
            channel=amo.RELEASE_CHANNEL_LISTED).files.update(
            is_webextension=True)
        AddonReviewerFlags.objects.create(
            addon=self.addons['Nominated Two'],
            auto_approval_delayed_until=datetime.now() - timedelta(hours=24))

        self.expected_addons = [
            self.addons['Nominated One'], self.addons['Pending One']]
        self._test_results()

    def test_webextension_with_auto_approval_delayed_until_does_show_up(self):
        self.addons['Pending Two'].find_latest_version(
            channel=amo.RELEASE_CHANNEL_LISTED).files.update(
            is_webextension=True)
        self.addons['Nominated Two'].find_latest_version(
            channel=amo.RELEASE_CHANNEL_LISTED).files.update(
            is_webextension=True)

        self.addons['Pending One'].find_latest_version(
            channel=amo.RELEASE_CHANNEL_LISTED).files.update(
            is_webextension=True)
        AddonReviewerFlags.objects.create(
            addon=self.addons['Pending One'],
            auto_approval_delayed_until=datetime.now() + timedelta(hours=24))
        self.addons['Nominated One'].find_latest_version(
            channel=amo.RELEASE_CHANNEL_LISTED).files.update(
            is_webextension=True)
        AddonReviewerFlags.objects.create(
            addon=self.addons['Nominated One'],
            auto_approval_delayed_until=datetime.now() + timedelta(hours=24))

        self.expected_addons = [
            self.addons['Nominated One'], self.addons['Pending One']]
        self._test_results()

    def test_static_theme_filtered_out(self):
        self.addons['Pending Two'].update(type=amo.ADDON_STATICTHEME)
        self.addons['Nominated Two'].update(type=amo.ADDON_STATICTHEME)

        # Static Theme shouldn't be shown
        self.expected_addons = [
            self.addons['Nominated One'], self.addons['Pending One']]
        self._test_results()

        # Even if you have that permission also
        self.grant_permission(self.user, 'Addons:ThemeReview')
        self._test_results()

    def test_search_plugins_filtered_out(self):
        self.addons['Nominated Two'].update(type=amo.ADDON_SEARCH)
        self.addons['Pending Two'].update(type=amo.ADDON_SEARCH)

        # search extensions are filtered out from the queue since auto_approve
        # is taking care of them.
        self.expected_addons = [
            self.addons['Nominated One'], self.addons['Pending One']]
        self._test_results()


class TestThemeNominatedQueue(QueueTest):

    def setUp(self):
        super(TestThemeNominatedQueue, self).setUp()
        # These should be the only ones present.
        self.expected_addons = self.get_expected_addons_by_names(
            ['Nominated One', 'Nominated Two'])
        Addon.objects.all().update(type=amo.ADDON_STATICTHEME)
        self.url = reverse('reviewers.queue_theme_nominated')
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
        self._test_queue_layout('🎨 New',
                                tab_position=0, total_addons=2, total_queues=2)

    def test_static_theme_filtered_out(self):
        self.addons['Nominated Two'].update(type=amo.ADDON_EXTENSION)

        # Static Theme shouldn't be shown
        self.expected_addons = [self.addons['Nominated One']]
        self._test_results()

        # Even if you have that permission also
        self.grant_permission(self.user, 'Addons:Review')
        self.expected_addons = [self.addons['Nominated One']]
        self._test_results()


class TestRecommendedQueue(QueueTest):
    def setUp(self):
        super().setUp()
        self.grant_permission(self.user, 'Addons:RecommendedReview')
        # These should be the only ones present.
        self.expected_addons = self.get_expected_addons_by_names(
            ['Pending One', 'Pending Two', 'Nominated One', 'Nominated Two'])
        for addon in self.expected_addons:
            DiscoveryItem.objects.create(addon=addon, recommendable=True)
        self.url = reverse('reviewers.queue_recommended')

    def test_results(self):
        self._test_results()

    @pytest.mark.skip(reason='Unexplained failure due to nomination dates')
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
        self._test_queue_layout(
            'Recommended', tab_position=0, total_addons=4, total_queues=3)

    def test_nothing_recommended_filtered_out(self):
        version = self.addons['Nominated One'].find_latest_version(
            channel=amo.RELEASE_CHANNEL_LISTED)
        version.files.update(is_webextension=True)

        version = self.addons['Pending Two'].find_latest_version(
            channel=amo.RELEASE_CHANNEL_LISTED)
        version.files.update(is_webextension=True)
        AddonReviewerFlags.objects.create(
            addon=self.addons['Pending Two'], auto_approval_disabled=False)

        self._test_results()


class TestModeratedQueue(QueueTest):
    fixtures = ['base/users', 'ratings/dev-reply']

    def setUp(self):
        super(TestModeratedQueue, self).setUp()

        self.url = reverse('reviewers.queue_moderated')

        RatingFlag.objects.create(
            rating_id=218468, user=self.user, flag=RatingFlag.SPAM)
        Rating.objects.get(pk=218468).update(editorreview=True)

        assert RatingFlag.objects.filter(flag=RatingFlag.SPAM).count() == 1
        assert Rating.objects.filter(editorreview=True).count() == 1
        self.user.groupuser_set.all().delete()  # Remove all permissions
        self.grant_permission(self.user, 'Ratings:Moderate')

    def test_results(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)('#reviews-flagged')

        rows = doc('.review-flagged:not(.review-saved)')
        assert rows.length == 1
        assert rows.find('h3').text() == ''

        # Default is "Skip."
        assert doc('#id_form-0-action_1:checked').length == 1

        flagged = doc('.reviews-flagged-reasons span.light').text()
        reviewer = RatingFlag.objects.all()[0].user.name
        assert flagged.startswith('Flagged by %s' % reviewer), (
            'Unexpected text: %s' % flagged)

        addon = Addon.objects.get(id=1865)
        addon.name = u'náme'
        addon.save()
        response = self.client.get(self.url)
        doc = pq(response.content)('#reviews-flagged')

        rows = doc('.review-flagged:not(.review-saved)')
        assert rows.length == 1
        assert rows.find('h3').text() == u'náme'

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

        response = self.client.get(reverse('reviewers.ratings_moderation_log'))
        assert pq(response.content)('table .more-details').attr('href') == (
            reverse('reviewers.ratings_moderation_log.detail',
                    args=[logs[0].id]))

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
            body='dont show me', editorreview=True)
        RatingFlag.objects.create(rating=rating)

        # Add a review associated to an unlisted version
        addon = addon_factory()
        version = version_factory(
            addon=addon, channel=amo.RELEASE_CHANNEL_UNLISTED)
        rating = Rating.objects.create(
            addon=addon_factory(), version=version, user=user_factory(),
            body='dont show me either', editorreview=True)
        RatingFlag.objects.create(rating=rating)

        self._test_queue_layout('Rating Reviews',
                                tab_position=0, total_addons=2, total_queues=1)

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
        # We should have all add-ons, sorted by id desc.
        self.generate_files()
        self.expected_addons = [
            self.addons['Public'],
            self.addons['Pending Two'],
            self.addons['Pending One'],
            self.addons['Nominated Two'],
            self.addons['Nominated One'],
        ]

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
        self.user.groupuser_set.all().delete()  # Remove all permissions
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
        with self.assertNumQueries(25):
            # 25 queries is a lot, but it used to be much much worse.
            # - 2 for savepoints because we're in tests
            # - 2 for user/groups
            # - 10 for various queue counts, including current one
            #      (unfortunately duplicated because it appears in two
            #       completely different places)
            # - 3 for the addons in the queues and their files (regardless of
            #     how many are in the queue - that's the important bit)
            # - 2 for config items (motd / site notice)
            # - 2 for my add-ons / my collection in user menu
            # - 4 for reviewer scores and user stuff displayed above the queue
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

        self._test_queue_layout(
            'Auto Approved', tab_position=0, total_addons=4, total_queues=1,
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

        # Pending addon with expired info request.
        addon1 = addon_factory(name=u'Pending Addön 1',
                               status=amo.STATUS_NOMINATED)
        AddonReviewerFlags.objects.create(
            addon=addon1,
            pending_info_request=self.days_ago(2))

        # Public addon with expired info request.
        addon2 = addon_factory(name=u'Public Addön 2',
                               status=amo.STATUS_APPROVED)
        AddonReviewerFlags.objects.create(
            addon=addon2,
            pending_info_request=self.days_ago(42))

        # Deleted addon with expired info request.
        addon3 = addon_factory(name=u'Deleted Addön 3',
                               status=amo.STATUS_DELETED)
        AddonReviewerFlags.objects.create(
            addon=addon3,
            pending_info_request=self.days_ago(42))

        # Mozilla-disabled addon with expired info request.
        addon4 = addon_factory(name=u'Disabled Addön 4',
                               status=amo.STATUS_DISABLED)
        AddonReviewerFlags.objects.create(
            addon=addon4,
            pending_info_request=self.days_ago(42))

        # Incomplete addon with expired info request.
        addon5 = addon_factory(name=u'Incomplete Addön 5',
                               status=amo.STATUS_NULL)
        AddonReviewerFlags.objects.create(
            addon=addon5,
            pending_info_request=self.days_ago(42))

        # Invisible (user-disabled) addon with expired info request.
        addon6 = addon_factory(name=u'Incomplete Addön 5',
                               status=amo.STATUS_APPROVED,
                               disabled_by_user=True)
        AddonReviewerFlags.objects.create(
            addon=addon6,
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
        self.user.groupuser_set.all().delete()  # Remove all permissions
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
        # The extra_ addons should not appear in the queue.
        # This first add-on has been content reviewed long ago.
        extra_addon1 = addon_factory(name=u'Extra Addön 1')
        AutoApprovalSummary.objects.create(
            version=extra_addon1.current_version,
            verdict=amo.AUTO_APPROVED, confirmed=True)
        AddonApprovalsCounter.objects.create(
            addon=extra_addon1, last_content_review=self.days_ago(370))

        # This one is quite similar, except its last content review is even
        # older..
        extra_addon2 = addon_factory(name=u'Extra Addön 2')
        AutoApprovalSummary.objects.create(
            version=extra_addon2.current_version,
            verdict=amo.AUTO_APPROVED, confirmed=True)
        AddonApprovalsCounter.objects.create(
            addon=extra_addon2, last_content_review=self.days_ago(842))

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

        # Those should appear in the queue
        # Has not been auto-approved.
        addon1 = addon_factory(name=u'Addôn 1', created=self.days_ago(4))

        # Has not been auto-approved either, only dry run.
        addon2 = addon_factory(name=u'Addôn 2', created=self.days_ago(3))
        AutoApprovalSummary.objects.create(
            version=addon2.current_version,
            verdict=amo.WOULD_HAVE_BEEN_AUTO_APPROVED,
        )

        # This one has never been content-reviewed. It has an
        # needs_admin_code_review flag, but that should not have any impact.
        addon3 = addon_factory(name=u'Addön 3', created=self.days_ago(2))
        AutoApprovalSummary.objects.create(
            version=addon3.current_version,
            verdict=amo.AUTO_APPROVED, confirmed=True)
        AddonApprovalsCounter.objects.create(
            addon=addon3, last_content_review=None)
        AddonReviewerFlags.objects.create(
            addon=addon3, needs_admin_code_review=True)

        # This one has never been content reviewed either, and it does not even
        # have an AddonApprovalsCounter.
        addon4 = addon_factory(name=u'Addön 4', created=self.days_ago(1))
        AutoApprovalSummary.objects.create(
            version=addon4.current_version,
            verdict=amo.AUTO_APPROVED, confirmed=True)
        assert not AddonApprovalsCounter.objects.filter(addon=addon4).exists()

        # Those should *not* appear in the queue
        # Has not been auto-approved but themes, langpacks and search plugins
        # are excluded.
        addon_factory(
            name=u'Theme 1', created=self.days_ago(4),
            type=amo.ADDON_STATICTHEME)
        addon_factory(
            name=u'Langpack 1', created=self.days_ago(4),
            type=amo.ADDON_LPAPP)
        addon_factory(
            name=u'search plugin 1', created=self.days_ago(4),
            type=amo.ADDON_SEARCH)

        # Addons with no last_content_review date, ordered by
        # their creation date, older first.
        self.expected_addons = [addon1, addon2, addon3, addon4]

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
        with self.assertNumQueries(25):
            # 25 queries is a lot, but it used to be much much worse.
            # - 2 for savepoints because we're in tests
            # - 2 for user/groups
            # - 10 for various queue counts, including current one
            #      (unfortunately duplicated because it appears in two
            #       completely different places)
            # - 3 for the addons in the queues and their files (regardless of
            #     how many are in the queue - that's the important bit)
            # - 2 for config items (motd / site notice)
            # - 2 for my add-ons / my collection in user menu
            # - 4 for reviewer scores and user stuff displayed above the queue
            self._test_results()

    def test_queue_layout(self):
        self.login_with_permission()
        self.generate_files()

        self._test_queue_layout(
            'Content Review', tab_position=0, total_addons=4, total_queues=1,
            per_page=1)

    def test_queue_layout_admin(self):
        # Admins should see the extra add-on that needs admin content review.
        user = self.login_with_permission()
        self.grant_permission(user, 'Reviews:Admin')
        self.generate_files()

        self._test_queue_layout(
            'Content Review', tab_position=0, total_addons=5, total_queues=2)


class TestNeedsHumanReviewQueue(QueueTest):
    fixtures = ['base/users']

    def setUp(self):
        super().setUp()
        self.url = reverse('reviewers.queue_needs_human_review')

    def generate_files(self):
        # Has no versions needing human review.
        extra_addon = addon_factory()
        version_factory(
            addon=extra_addon, channel=amo.RELEASE_CHANNEL_UNLISTED)

        # Has 3 listed versions, 2 needing human review, 1 unlisted but not
        # needing human review.
        addon1 = addon_factory(created=self.days_ago(31))
        addon1_v1 = addon1.current_version
        addon1_v1.update(needs_human_review=True)
        version_factory(addon=addon1, needs_human_review=True)
        version_factory(addon=addon1)
        version_factory(addon=addon1, channel=amo.RELEASE_CHANNEL_UNLISTED)
        AddonApprovalsCounter.objects.create(
            addon=addon1, counter=1, last_human_review=self.days_ago(1))

        # Has 1 listed and 1 unlisted versions, both needing human review.
        addon2 = addon_factory(
            created=self.days_ago(15),
            version_kw={'needs_human_review': True})
        addon2.current_version
        version_factory(
            addon=addon2, channel=amo.RELEASE_CHANNEL_UNLISTED,
            needs_human_review=True)

        # Has 2 unlisted versions, 1 needing human review. Needs admin content
        # review but that shouldn't matter.
        addon3 = addon_factory(
            created=self.days_ago(7),
            version_kw={'channel': amo.RELEASE_CHANNEL_UNLISTED,
                        'needs_human_review': True})
        addon3.versions.get()
        version_factory(
            addon=addon3, channel=amo.RELEASE_CHANNEL_UNLISTED)
        AddonReviewerFlags.objects.create(
            addon=addon3, needs_admin_content_review=True)

        # Needs admin code review, so wouldn't show up for regular reviewers.
        addon4 = addon_factory(
            created=self.days_ago(1),
            version_kw={'needs_human_review': True})
        AddonReviewerFlags.objects.create(
            addon=addon4, needs_admin_code_review=True)

        self.expected_addons = [addon1, addon2, addon3]

    def test_results(self):
        self.generate_files()
        response = self.client.get(self.url)
        assert response.status_code == 200

        expected = []
        # addon1
        addon = self.expected_addons[0]
        expected.append((
            'Listed versions needing human review (2)',
            reverse('reviewers.review', args=[addon.slug])
        ))
        # addon2
        addon = self.expected_addons[1]
        expected.append((
            'Listed versions needing human review (1)',
            reverse('reviewers.review', args=[addon.slug])
        ))
        expected.append((
            'Unlisted versions needing human review (1)',
            reverse('reviewers.review', args=['unlisted', addon.slug])
        ))
        # addon3
        addon = self.expected_addons[2]
        expected.append((
            'Unlisted versions needing human review (1)',
            reverse('reviewers.review', args=['unlisted', addon.slug])
        ))

        doc = pq(response.content)
        links = doc('#addon-queue tr.addon-row td a:not(.app-icon)')
        # Number of expected links is not equal to len(self.expected_addons)
        # because we display a review link for each channel that has versions
        # needing review per add-on, and addon2 has both unlisted and listed
        # versions needing review.
        assert len(links) == 4
        check_links(expected, links, verify=False)

    def test_only_viewable_with_specific_permission(self):
        # Post-review reviewer does not have access.
        self.user.groupuser_set.all().delete()  # Remove all permissions
        self.grant_permission(self.user, 'Addons:PostReview')
        response = self.client.get(self.url)
        assert response.status_code == 403

        # Regular user doesn't have access.
        self.client.logout()
        assert self.client.login(email='regular@mozilla.com')
        response = self.client.get(self.url)
        assert response.status_code == 403

    def test_queue_layout(self):
        self.generate_files()

        self._test_queue_layout(
            'Flagged By Scanners',
            tab_position=1, total_addons=3, total_queues=2, per_page=1)

    def test_queue_layout_admin(self):
        # Admins should see the extra add-on that needs admin content review.
        self.login_as_admin()
        self.generate_files()

        self._test_queue_layout(
            'Flagged By Scanners',
            tab_position=2, total_addons=4, total_queues=9, per_page=1)


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
            ('Bieber Lang', {
                'version_str': '0.1',
                'addon_status': amo.STATUS_NOMINATED,
                'file_status': amo.STATUS_AWAITING_REVIEW,
                'type': amo.ADDON_LPAPP,
            }),
            ('Justin Bieber Search Bar', {
                'version_str': '0.1',
                'addon_status': amo.STATUS_NOMINATED,
                'file_status': amo.STATUS_AWAITING_REVIEW,
                'type': amo.ADDON_SEARCH,
            }),
            ('Bieber Dictionary', {
                'version_str': '0.1',
                'addon_status': amo.STATUS_NOMINATED,
                'file_status': amo.STATUS_AWAITING_REVIEW,
                'type': amo.ADDON_DICT,
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
        for name, attrs in files.items():
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
                             'Bieber Lang'])
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
                             'Bieber Lang'])
        response = self.search(text_query='admin', searching='True')
        assert response.status_code == 200
        assert sorted(self.named_addons(response)) == (
            ['Needs Admin Review', 'Not Needing Admin Review'])

    def test_search_by_addon_in_locale(self):
        name = 'Not Needing Admin Review'
        generated = self.generate_file(name)
        uni = u'フォクすけといっしょ'
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
        uni = u'フォクすけといっしょ@site.co.jp'
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
        self.url = reverse('reviewers.queue_extension')

    def test_search_by_addon_type(self):
        self.generate_files(['Not Needing Admin Review', 'Bieber Lang',
                             'Justin Bieber Search Bar'])
        response = self.search(addon_type_ids=[amo.ADDON_LPAPP])
        assert response.status_code == 200
        assert self.named_addons(response) == ['Bieber Lang']

    def test_search_by_addon_type_any(self):
        self.generate_file('Not Needing Admin Review')
        response = self.search(addon_type_ids=[amo.ADDON_ANY])
        assert response.status_code == 200
        assert self.named_addons(response), 'Expected some add-ons'

    def test_search_by_many_addon_types(self):
        self.generate_files(['Not Needing Admin Review', 'Bieber Lang',
                             'Bieber Dictionary'])
        response = self.search(
            addon_type_ids=[amo.ADDON_LPAPP, amo.ADDON_DICT])
        assert response.status_code == 200
        assert sorted(self.named_addons(response)) == (
            ['Bieber Dictionary', 'Bieber Lang'])

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
        assert list(sorted(self.named_addons(response))) == [
            'Bieber For Mobile', 'Multi Application']

    def test_clear_search_uses_correct_queue(self):
        # The "clear search" link points to the right listed or unlisted queue.
        # Listed queue.
        url = reverse('reviewers.queue_extension')
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


@override_flag('code-manager', active=False)
class TestReview(ReviewBase):

    def test_reviewer_required(self):
        assert self.client.head(self.url).status_code == 200

    def test_not_anonymous(self):
        self.client.logout()
        self.assertLoginRedirects(self.client.head(self.url), to=self.url)

    @mock.patch.object(settings, 'ALLOW_SELF_REVIEWS', False)
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
        self.addon.update_version()
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

    def test_need_recommended_reviewer_for_recommendable_addon(self):
        item = DiscoveryItem.objects.create(addon=self.addon)
        assert self.client.head(self.url).status_code == 200

        item.update(recommendable=True)
        assert self.client.head(self.url).status_code == 403

        self.grant_permission(self.reviewer, 'Addons:RecommendedReview')
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
        assert doc('#id_whiteboard-public')
        assert doc('#id_whiteboard-private')

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

    def test_whiteboard_for_static_themes(self):
        self.grant_permission(self.reviewer, 'Addons:ThemeReview')
        self.addon.update(type=amo.ADDON_STATICTHEME)
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert (
            doc('#whiteboard_form').attr('action') ==
            '/en-US/reviewers/whiteboard/listed/public')
        assert doc('#id_whiteboard-public')
        assert not doc('#id_whiteboard-private')

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

        items = pq(response.content)('#versions-history .files .file-info')
        assert items.length == 1

        file_ = self.version.all_files[0]
        expected = [
            ('All Platforms', file_.get_absolute_url('reviewer')),
            ('Validation', reverse(
                'devhub.file_validation', args=[self.addon.slug, file_.id])),
            ('Contents', None),
        ]
        check_links(expected, items.find('a'), verify=False)

    def test_item_history(self, channel=amo.RELEASE_CHANNEL_LISTED):
        self.addons['something'] = addon_factory(
            status=amo.STATUS_APPROVED, name=u'something',
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
        table = doc('#versions-history .review-files')

        # Check the history for both versions.
        ths = table.children('tr > th')
        assert ths.length == 2
        assert '0.1' in ths.eq(0).text()
        assert '0.2' in ths.eq(1).text()

        rows = table('td.files')
        assert rows.length == 2

        comments = rows.siblings('td')
        assert comments.length == 2

        for idx in range(comments.length):
            td = comments.eq(idx)
            assert td.find('.history-comment').text() == 'something'
            assert td.find('th').text() == {
                'public': 'Approved',
                'reply': 'Reviewer Reply'}[action]
            reviewer_name = td.find('td a').text()
            assert ((reviewer_name == self.reviewer.name) or
                    (reviewer_name == self.other_reviewer.name))

    def test_item_history_pagination(self):
        addon = self.addons['Public']
        addon.current_version.update(created=self.days_ago(366))
        for i in range(0, 10):
            # Add versions 1.0 to 1.9
            version_factory(
                addon=addon, version=f'1.{i}', created=self.days_ago(365 - i))
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        table = doc('#versions-history .review-files')
        ths = table.children('tr > th')
        assert ths.length == 10
        # Original version should not be there any more, it's on the second
        # page. Versions on the page should be displayed in chronological order
        assert '1.0' in ths.eq(0).text()
        assert '1.1' in ths.eq(1).text()
        assert '1.9' in ths.eq(9).text()

        response = self.client.get(self.url, {'page': 2})
        assert response.status_code == 200
        doc = pq(response.content)
        table = doc('#versions-history .review-files')
        ths = table.children('tr > th')
        assert ths.length == 1
        assert '0.1' in ths.eq(0).text()

    def test_item_history_with_unlisted_versions_too(self):
        # Throw in an unlisted version to be ignored.
        version_factory(
            version=u'0.2', addon=self.addon,
            channel=amo.RELEASE_CHANNEL_UNLISTED,
            file_kw={'status': amo.STATUS_APPROVED})
        self.test_item_history()

    def test_item_history_with_unlisted_review_page(self):
        self.addon.versions.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        self.version.reload()
        # Throw in an listed version to be ignored.
        version_factory(
            version=u'0.2', addon=self.addon,
            channel=amo.RELEASE_CHANNEL_LISTED,
            file_kw={'status': amo.STATUS_APPROVED})
        self.url = reverse('reviewers.review', args=[
            'unlisted', self.addon.slug])
        self.grant_permission(self.reviewer, 'Addons:ReviewUnlisted')
        self.test_item_history(channel=amo.RELEASE_CHANNEL_UNLISTED)

    def test_item_history_compat_ordered(self):
        """ Make sure that apps in compatibility are ordered. """
        av = AppVersion.objects.all()[0]
        v = self.addon.versions.all()[0]

        ApplicationsVersions.objects.create(
            version=v, application=amo.ANDROID.id, min=av, max=av)

        assert self.addon.versions.count() == 1
        url = reverse('reviewers.review', args=[self.addon.slug])

        response = self.client.get(url)
        assert response.status_code == 200
        doc = pq(response.content)
        icons = doc('.listing-body .app-icon')
        assert icons.eq(0).attr('title') == 'Firefox for Android'
        assert icons.eq(1).attr('title') == 'Firefox'

    def test_item_history_weight(self):
        """ Make sure the weight is shown on the review page"""
        AutoApprovalSummary.objects.create(
            version=self.version, verdict=amo.AUTO_APPROVED,
            weight=284, weight_info={'fôo': 200, 'bär': 84})
        self.grant_permission(self.reviewer, 'Addons:PostReview')
        url = reverse('reviewers.review', args=[self.addon.slug])
        response = self.client.get(url)
        assert response.status_code == 200
        doc = pq(response.content)
        risk = doc('.listing-body .file-weight')
        assert risk.text() == "Weight: 284"
        assert risk.attr['title'] == 'bär: 84\nfôo: 200'

    def test_item_history_notes(self):
        version = self.addon.versions.all()[0]
        version.release_notes = 'hi'
        version.approval_notes = 'secret hi'
        version.save()

        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)('#versions-history .review-files')

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
        assert ('Approved' in doc(
            '#versions-history .review-files .listing-header .light').text())

    def test_item_history_comment(self):
        # Add Comment.
        self.client.post(self.url, {'action': 'comment',
                                    'comments': 'hello sailor'})

        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)('#versions-history .review-files')
        assert doc('th').eq(1).text() == 'Commented'
        assert doc('.history-comment').text() == 'hello sailor'

    def test_files_in_item_history(self):
        data = {'action': 'public', 'operating_systems': 'win',
                'applications': 'something', 'comments': 'something'}
        self.client.post(self.url, data)

        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        items = doc('#versions-history .review-files .files .file-info')
        assert items.length == 1
        assert items.find('a.reviewers-install').text() == 'All Platforms'

    def test_no_items(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#versions-history .review-files .no-activity').length == 1

    def test_action_links(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        expected = [
            ('View Product Page', self.addon.get_url_path()),
        ]
        check_links(expected, doc('#actions-addon a'), verify=False)

    def test_action_links_as_admin(self):
        self.login_as_admin()
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        expected = [
            ('View Product Page', self.addon.get_url_path()),
            ('Edit', self.addon.get_dev_url()),
            ('Admin Page',
                reverse('zadmin.addon_manage', args=[self.addon.id])),
        ]
        check_links(expected, doc('#actions-addon a'), verify=False)

    def test_unlisted_addon_action_links_as_admin(self):
        """No "View Product Page" link for unlisted addons, "edit"/"manage" links
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
            ('View Product Page', self.addon.get_url_path()),
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
            ('View Product Page', self.addon.get_url_path()),
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
            ('View Product Page', self.addon.get_url_path()),
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
        AddonReviewerFlags.objects.create(
            addon=self.addon,
            auto_approval_disabled=True,
            needs_admin_code_review=True,
            needs_admin_content_review=True,
            needs_admin_theme_review=True,
            auto_approval_delayed_until=datetime.now() + timedelta(hours=1))
        self.login_as_reviewer()
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert not doc('#force_disable_addon')
        assert not doc('#force_enable_addon')
        assert not doc('#block_addon')
        assert not doc('#edit_addon_block')
        assert not doc('#clear_admin_code_review')
        assert not doc('#clear_admin_content_review')
        assert not doc('#clear_admin_theme_review')
        assert not doc('#disable_auto_approval')
        assert not doc('#enable_auto_approval')
        assert not doc('#clear_auto_approval_delayed_until')
        assert not doc('#clear_pending_info_request')
        assert not doc('#deny_resubmission')
        assert not doc('#allow_resubmission')

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

        # Not present because it hasn't been set yet
        assert not doc('#clear_auto_approval_delayed_until')

        flags = AddonReviewerFlags.objects.create(
            addon=self.addon, auto_approval_delayed_until=self.days_ago(1))
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)

        # Still not present because it's in the past.
        assert not doc('#clear_auto_approval_delayed_until')

        flags.update(
            auto_approval_delayed_until=datetime.now() + timedelta(hours=24))
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#clear_auto_approval_delayed_until')

    def test_no_resubmission_buttons_when_addon_is_not_deleted(self):
        self.login_as_admin()

        response = self.client.get(self.url)

        doc = pq(response.content)
        assert not doc('#deny_resubmission')
        assert not doc('#allow_resubmission')

    def test_resubmission_buttons_are_displayed_for_deleted_addons(self):
        self.login_as_admin()
        self.addon.update(status=amo.STATUS_DELETED)
        assert not self.addon.is_guid_denied

        response = self.client.get(self.url)

        assert response.status_code == 200
        doc = pq(response.content)
        # The "deny" button is visible when the GUID is not denied.
        assert doc('#deny_resubmission')
        elem = doc('#deny_resubmission')[0]
        assert 'hidden' not in elem.getparent().attrib.get('class', '')
        # The "allow" button is hidden when the GUID is not denied.
        assert doc('#allow_resubmission')
        elem = doc('#allow_resubmission')[0]
        assert 'hidden' in elem.getparent().attrib.get('class', '')

    def test_resubmission_buttons_are_displayed_for_deleted_addons_and_denied_guid(self):  # noqa
        self.login_as_admin()
        self.addon.update(status=amo.STATUS_DELETED)
        self.addon.deny_resubmission()
        assert self.addon.is_guid_denied

        response = self.client.get(self.url)

        assert response.status_code == 200
        doc = pq(response.content)
        # The "deny" button is hidden when the GUID is denied.
        assert doc('#deny_resubmission')
        elem = doc('#deny_resubmission')[0]
        assert 'hidden' in elem.getparent().attrib.get('class', '')
        # The "allow" button is visible when the GUID is denied.
        assert doc('#allow_resubmission')
        elem = doc('#allow_resubmission')[0]
        assert 'hidden' not in elem.getparent().attrib.get('class', '')

    def test_admin_block_actions(self):
        self.login_as_admin()
        assert not self.addon.block
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#block_addon')
        assert not doc('#edit_addon_block')
        assert doc('#block_addon')[0].attrib.get('href') == (
            reverse('admin:blocklist_blocksubmission_add') + '?guids=' +
            self.addon.guid)

        block = Block.objects.create(
            addon=self.addon, updated_by=user_factory())
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert not doc('#block_addon')
        assert doc('#edit_addon_block')
        assert doc('#edit_addon_block')[0].attrib.get('href') == (
            reverse('admin:blocklist_block_change', args=(block.id,)))

    def test_unflag_option_forflagged_as_admin(self):
        self.login_as_admin()
        AddonReviewerFlags.objects.create(
            addon=self.addon, needs_admin_code_review=True)
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#clear_admin_code_review').length == 1
        assert doc('#clear_admin_content_review').length == 0
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
        assert doc('#clear_admin_theme_review').length == 0

    def test_unflag_theme_option_forflagged_as_admin(self):
        self.login_as_admin()
        AddonReviewerFlags.objects.create(
            addon=self.addon,
            needs_admin_code_review=False,
            needs_admin_content_review=False,
            needs_admin_theme_review=True)
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#clear_admin_code_review').length == 0
        assert doc('#clear_admin_content_review').length == 0
        assert doc('#clear_admin_theme_review').length == 1

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

        # Still present for dictionaries
        self.addon.update(type=amo.ADDON_DICT)
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#disable_auto_approval')
        assert doc('#enable_auto_approval')

        # And search plugins
        self.addon.update(type=amo.ADDON_SEARCH)
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#disable_auto_approval')
        assert doc('#enable_auto_approval')

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
            status=amo.STATUS_APPROVED).exists()
        assert has_public

        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)

        validation = doc.find('.files')
        assert validation.find('a').eq(1).text() == "Validation"
        assert validation.find('a').eq(2).text() == "Contents"

        assert validation.find('a').length == 3

    def test_public_search(self):
        self.version.files.update(status=amo.STATUS_APPROVED)
        self.addon.update(type=amo.ADDON_SEARCH)
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#versions-history .files ul .file-info').length == 1

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
        ths = doc('#versions-history .review-files > tr > th:first-child')
        assert '0.1' in ths.eq(0).text()
        assert '0.2' in ths.eq(1).text()

        # Delete a version:
        v2.delete()
        # Verify two versions, one deleted:
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        ths = doc('#versions-history .review-files > tr > th:first-child')

        assert ths.length == 2
        assert '0.1' in ths.text()

    def test_no_versions(self):
        """The review page should still load if there are no versions."""
        assert self.client.get(self.url).status_code == 200
        response = self.client.post(self.url, {'action': 'comment',
                                               'comments': 'hello sailor'})
        assert response.status_code == 302
        self.assert3xx(response, reverse('reviewers.queue_extension'),
                       status_code=302)

        self.version.delete()
        # Regular reviewer can still see it since the deleted version was
        # listed.
        assert self.client.get(self.url).status_code == 200
        response = self.client.post(self.url, {'action': 'comment',
                                               'comments': 'hello sailor'})
        assert response.status_code == 302
        self.assert3xx(response, reverse('reviewers.queue_extension'),
                       status_code=302)

        # Now they need unlisted permission cause we can't find a listed
        # version, even deleted.
        self.version.delete(hard=True)
        assert self.client.get(self.url).status_code == 404
        # Reviewer with more powers can look.
        self.grant_permission(self.reviewer, 'Addons:ReviewUnlisted')
        assert self.client.get(self.url).status_code == 200
        response = self.client.post(self.url, {'action': 'comment',
                                               'comments': 'hello sailor'})
        assert response.status_code == 302
        self.assert3xx(response, reverse('reviewers.queue_extension'),
                       status_code=302)

    def test_addon_deleted(self):
        """The review page should still load for deleted addons."""
        self.addon.delete()
        self.url = reverse('reviewers.review', args=[self.addon.pk])

        assert self.client.get(self.url).status_code == 200
        response = self.client.post(self.url, {'action': 'comment',
                                               'comments': 'hello sailor'})
        assert response.status_code == 302
        self.assert3xx(response, reverse('reviewers.queue_extension'),
                       status_code=302)

    @mock.patch('olympia.reviewers.utils.sign_file')
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
        eula_url = reverse(
            'reviewers.eula', args=(self.addon.slug,))
        self.assertContains(response, eula_url + '"')

        # The url should pass on the channel param so the backlink works
        self.make_addon_unlisted(self.addon)
        self.login_as_admin()
        unlisted_url = reverse(
            'reviewers.review', args=['unlisted', self.addon.slug])
        response = self.client.get(unlisted_url)
        assert response.status_code == 200
        eula_url = reverse(
            'reviewers.eula', args=(self.addon.slug,))
        self.assertContains(response, eula_url + '?channel=unlisted"')

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
        privacy_url = reverse(
            'reviewers.privacy', args=(self.addon.slug,))
        self.assertContains(response, privacy_url + '"')

        self.make_addon_unlisted(self.addon)
        self.login_as_admin()
        unlisted_url = reverse(
            'reviewers.review', args=['unlisted', self.addon.slug])
        response = self.client.get(unlisted_url)
        assert response.status_code == 200
        privacy_url = reverse(
            'reviewers.privacy', args=(self.addon.slug,))
        self.assertContains(response, privacy_url + '?channel=unlisted"')

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

    def test_addon_id_display(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert self.addon.guid in doc('tr.addon-guid td').text()

    def test_amo_id_display(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert str(self.addon.id) in doc('tr.addon-amo-id td').text()

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
        key = 'review_viewing:{id}'.format(id=self.addon.id)
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
        response = self.client.get(reverse(
            'reviewers.queue_viewing'),
            {'addon_ids': '%s,4242' % self.addon.id})
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data[str(self.addon.id)] == self.reviewer.name

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
        info = doc('#versions-history .file-info')
        assert info.length == 1
        assert info.find('a.compare').length == 0

    def test_file_info_for_static_themes(self):
        self.grant_permission(self.reviewer, 'Addons:ThemeReview')
        self.addon.update(type=amo.ADDON_STATICTHEME)
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        info = doc('#versions-history .file-info')
        assert info.length == 1
        # Only the download/install link
        assert info.find('a').length == 1
        assert info.find('a')[0].text == u'Download'
        assert b'Compatibility' not in response.content

    def test_compare_link(self):
        first_file = self.addon.current_version.files.all()[0]
        first_file.update(status=amo.STATUS_APPROVED)
        self.addon.current_version.update(created=self.days_ago(2))

        new_version = version_factory(addon=self.addon, version='0.2')
        new_file = new_version.files.all()[0]
        self.addon.update(_current_version=new_version)
        assert self.addon.current_version == new_version

        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert response.context['show_diff']
        links = doc('#versions-history .file-info .compare')
        expected = [
            reverse('files.compare', args=[new_file.pk, first_file.pk]),
        ]
        check_links(expected, links, verify=False)

    def test_compare_link_auto_approved_ignored(self):
        first_file = self.addon.current_version.files.all()[0]
        first_file.update(status=amo.STATUS_APPROVED)
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
        links = doc('#versions-history .file-info .compare')
        # Comparison should be between the last version and the first,
        # ignoring the interim version because it was auto-approved and not
        # manually confirmed by a human.
        expected = [
            reverse('files.compare', args=[new_file.pk, first_file.pk]),
        ]
        check_links(expected, links, verify=False)

    def test_compare_link_auto_approved_but_confirmed_not_ignored(self):
        first_file = self.addon.current_version.files.all()[0]
        first_file.update(status=amo.STATUS_APPROVED)
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
        links = doc('#versions-history .file-info .compare')
        # Comparison should be between the last version and the second,
        # ignoring the third version because it was auto-approved and not
        # manually confirmed by a human (the second was auto-approved but
        # was manually confirmed).
        expected = [
            reverse('files.compare', args=[new_file.pk, confirmed_file.pk]),
        ]
        check_links(expected, links, verify=False)

    def test_compare_link_not_auto_approved_but_confirmed(self):
        first_file = self.addon.current_version.files.all()[0]
        first_file.update(status=amo.STATUS_APPROVED)
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
        links = doc('#versions-history .file-info .compare')
        # Comparison should be between the last version and the second,
        # because second was approved by human before auto-approval ran on it
        expected = [
            reverse('files.compare', args=[new_file.pk, confirmed_file.pk]),
        ]
        check_links(expected, links, verify=False)

    def test_download_sources_link(self):
        version = self.addon.current_version
        tdir = temp.gettempdir()
        source_file = temp.NamedTemporaryFile(
            suffix='.zip', dir=tdir, mode='r+')
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
        assert b'Download files' in response.content

        # Standard reviewer: should know that sources were provided.
        user = UserProfile.objects.get(email='reviewer@mozilla.com')
        self.client.login(email=user.email)
        response = self.client.get(url, follow=True)
        assert response.status_code == 200
        assert b'The developer has provided source code.' in response.content

    @mock.patch('olympia.reviewers.utils.sign_file')
    def test_approve_recommended_addon(self, mock_sign_file):
        self.version.files.update(status=amo.STATUS_AWAITING_REVIEW)
        self.addon.update(status=amo.STATUS_NOMINATED)
        DiscoveryItem.objects.create(addon=self.addon, recommendable=True)
        self.grant_permission(self.reviewer, 'Addons:RecommendedReview')
        response = self.client.post(self.url, {
            'action': 'public',
            'comments': 'all good'
        })
        assert response.status_code == 302
        self.assert3xx(response, reverse('reviewers.queue_recommended'))
        addon = self.get_addon()
        assert addon.status == amo.STATUS_APPROVED
        assert addon.current_version
        assert addon.current_version.all_files[0].status == amo.STATUS_APPROVED
        assert addon.current_version.recommendation_approved
        assert mock_sign_file.called

    @mock.patch('olympia.reviewers.utils.sign_file')
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
        assert addon.status == amo.STATUS_APPROVED
        assert addon.current_version.files.all()[0].status == (
            amo.STATUS_APPROVED)

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

    def test_admin_flagged_addon_actions_as_content_reviewer(self):
        AddonReviewerFlags.objects.create(
            addon=self.addon, needs_admin_code_review=True)
        summary = AutoApprovalSummary.objects.create(
            version=self.addon.current_version, verdict=amo.AUTO_APPROVED)
        GroupUser.objects.filter(user=self.reviewer).all().delete()
        self.grant_permission(self.reviewer, 'Addons:ContentReview')
        self.url = reverse(
            'reviewers.review', args=['content', self.addon.slug])
        response = self.client.post(
            self.url, self.get_dict(action='approve_content'))
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

    def test_approve_content_content_review(self):
        GroupUser.objects.filter(user=self.reviewer).all().delete()
        self.url = reverse(
            'reviewers.review', args=['content', self.addon.slug])
        summary = AutoApprovalSummary.objects.create(
            version=self.addon.current_version, verdict=amo.AUTO_APPROVED)
        self.grant_permission(self.reviewer, 'Addons:ContentReview')
        response = self.client.post(self.url, {
            'action': 'approve_content',
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
            'action': 'approve_content',
            'comments': 'ignore me this action does not support comments'
        })
        assert response.status_code == 200  # Form error
        assert ActivityLog.objects.filter(
            action=amo.LOG.APPROVE_CONTENT.id).count() == 0

    def test_cant_addonreview_if_admin_content_review_flag_is_set(self):
        AutoApprovalSummary.objects.create(
            version=self.addon.current_version, verdict=amo.AUTO_APPROVED)
        AddonReviewerFlags.objects.create(
            addon=self.addon, needs_admin_content_review=True)
        self.grant_permission(self.reviewer, 'Addons:PostReview')
        for action in ['approve_content', 'public', 'reject',
                       'reject_multiple_versions']:
            response = self.client.post(self.url, self.get_dict(action=action))
            assert response.status_code == 200  # Form error.
            # The add-on status must not change as non-admin reviewers are not
            # allowed to review admin-flagged add-ons.
            addon = self.get_addon()
            assert addon.status == amo.STATUS_APPROVED
            assert self.version == addon.current_version
            assert addon.current_version.files.all()[0].status == (
                amo.STATUS_APPROVED)
            assert response.context['form'].errors['action'] == (
                [u'Select a valid choice. %s is not one of the available '
                 u'choices.' % action])
            assert ActivityLog.objects.filter(
                action=amo.LOG.CONFIRM_AUTO_APPROVED.id).count() == 0
            assert ActivityLog.objects.filter(
                action=amo.LOG.REJECT_VERSION.id).count() == 0
            assert ActivityLog.objects.filter(
                action=amo.LOG.APPROVE_VERSION.id).count() == 0

    def test_cant_review_static_theme_if_admin_theme_review_flag_is_set(self):
        self.version.files.update(status=amo.STATUS_AWAITING_REVIEW)
        self.addon.update(
            type=amo.ADDON_STATICTHEME, status=amo.STATUS_NOMINATED)
        AddonReviewerFlags.objects.create(
            addon=self.addon, needs_admin_theme_review=True)
        self.grant_permission(self.reviewer, 'Addons:ThemeReview')
        for action in ['public', 'reject']:
            response = self.client.post(self.url, self.get_dict(action=action))
            assert response.status_code == 200  # Form error.
            # The add-on status must not change as non-admin reviewers are not
            # allowed to review admin-flagged add-ons.
            addon = self.get_addon()
            assert addon.status == amo.STATUS_NOMINATED
            assert self.version == addon.current_version
            assert addon.current_version.files.all()[0].status == (
                amo.STATUS_AWAITING_REVIEW)
            assert response.context['form'].errors['action'] == (
                [u'Select a valid choice. %s is not one of the available '
                 u'choices.' % action])
            assert ActivityLog.objects.filter(
                action=amo.LOG.REJECT_VERSION.id).count() == 0
            assert ActivityLog.objects.filter(
                action=amo.LOG.APPROVE_VERSION.id).count() == 0

    @mock.patch('olympia.reviewers.utils.sign_file')
    def test_admin_can_review_statictheme_if_admin_theme_review_flag_set(
            self, mock_sign_file):
        self.version.files.update(status=amo.STATUS_AWAITING_REVIEW)
        self.addon.update(
            type=amo.ADDON_STATICTHEME, status=amo.STATUS_NOMINATED)
        AddonReviewerFlags.objects.create(
            addon=self.addon, needs_admin_theme_review=True)
        self.grant_permission(self.reviewer, 'Addons:ThemeReview')
        self.grant_permission(self.reviewer, 'Reviews:Admin')
        response = self.client.post(self.url, {
            'action': 'public',
            'comments': 'it`s good'
        })
        assert response.status_code == 302
        assert self.get_addon().status == amo.STATUS_APPROVED
        assert mock_sign_file.called

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
            'action': 'approve_content',
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

    def test_reject_multiple_versions(self):
        old_version = self.version
        old_version.update(needs_human_review=True)
        self.version = version_factory(addon=self.addon, version='3.0')
        AutoApprovalSummary.objects.create(
            version=self.addon.current_version, verdict=amo.AUTO_APPROVED)
        GroupUser.objects.filter(user=self.reviewer).all().delete()
        self.grant_permission(self.reviewer, 'Addons:PostReview')

        response = self.client.post(self.url, {
            'action': 'reject_multiple_versions',
            'comments': 'multireject!',
            'versions': [old_version.pk, self.version.pk],
        })

        assert response.status_code == 302
        for version in [old_version, self.version]:
            version.reload()
            assert not version.needs_human_review
            file_ = version.files.all().get()
            assert file_.status == amo.STATUS_DISABLED

    def test_block_multiple_versions(self):
        self.url = reverse(
            'reviewers.review', args=('unlisted', self.addon.slug))
        old_version = self.version
        old_version.update(needs_human_review=True)
        self.version = version_factory(addon=self.addon, version='3.0')
        self.make_addon_unlisted(self.addon)
        self.grant_permission(self.reviewer, 'Addons:ReviewUnlisted')
        self.grant_permission(self.reviewer, 'Admin:Tools')
        self.grant_permission(self.reviewer, 'Reviews:Admin')
        self.grant_permission(self.reviewer, 'Blocklist:Create')

        response = self.client.post(self.url, {
            'action': 'block_multiple_versions',
            'comments': 'multiblock!',  # should be ignored anyway
            'versions': [old_version.pk, self.version.pk],
        })

        for version in [old_version, self.version]:
            version.reload()
            assert not version.needs_human_review
            file_ = version.files.all().get()
            assert file_.status == amo.STATUS_DISABLED

        assert response.status_code == 302
        new_block_url = (
            reverse('admin:blocklist_blocksubmission_add') +
            '?guids=%s&min_version=%s&max_version=%s' % (
                self.addon.guid, old_version.version, self.version.version))
        self.assertRedirects(response, new_block_url)

    def test_user_changes_log(self):
        # Activity logs related to user changes should be displayed.
        # Create an activy log for each of the following: user addition, role
        # change and deletion.
        author = self.addon.addonuser_set.get()
        core.set_user(author.user)
        ActivityLog.create(
            amo.LOG.ADD_USER_WITH_ROLE, author.user,
            str(author.get_role_display()), self.addon)
        ActivityLog.create(
            amo.LOG.CHANGE_USER_WITH_ROLE, author.user,
            str(author.get_role_display()), self.addon)
        ActivityLog.create(
            amo.LOG.REMOVE_USER_WITH_ROLE, author.user,
            str(author.get_role_display()), self.addon)

        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert 'user_changes_log' in response.context
        user_changes_log = response.context['user_changes_log']
        actions = [log.action for log in user_changes_log]
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

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @mock.patch('olympia.devhub.tasks.validate')
    def test_validation_not_run_eagerly(self, validate):
        """Tests that validation is not run in eager mode."""
        assert not self.file.has_been_validated

        response = self.client.get(self.url)
        assert response.status_code == 200

        assert not validate.called

    @override_settings(CELERY_TASK_ALWAYS_EAGER=False)
    @mock.patch('olympia.devhub.tasks.validate')
    def test_validation_run(self, validate):
        """Tests that validation is run if necessary."""
        assert not self.file.has_been_validated

        response = self.client.get(self.url)
        assert response.status_code == 200

        validate.assert_called_once_with(self.file)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=False)
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
        assert (pq(review_page.content)('#versions-history').text() ==
                pq(listed_review_page.content)('#versions-history').text())

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
        info = doc('#versions-history .file-info div')
        assert info.eq(1).text() == 'Permissions: ' + ', '.join(permissions)

    def test_abuse_reports(self):
        report = AbuseReport.objects.create(
            addon=self.addon,
            message=u'Et mël mazim ludus.',
            country_code='FR',
            client_id='4815162342',
            addon_name='Unused here',
            addon_summary='Not used either',
            addon_version='42.0',
            addon_signature=AbuseReport.ADDON_SIGNATURES.UNSIGNED,
            application=amo.ANDROID.id,
            application_locale='fr_FR',
            operating_system='Løst OS',
            operating_system_version='20040922',
            install_date=self.days_ago(1),
            reason=AbuseReport.REASONS.POLICY,
            addon_install_origin='https://example.com/',
            addon_install_method=AbuseReport.ADDON_INSTALL_METHODS.LINK,
            addon_install_source=AbuseReport.ADDON_INSTALL_SOURCES.UNKNOWN,
            report_entry_point=AbuseReport.REPORT_ENTRY_POINTS.MENU,
        )
        created_at = format_datetime(report.created)
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('.abuse_reports')
        expected = [
            'Developer/Addon',
            'Application',
            'Install date',
            'Install origin',
            'Category',
            'Date',
            'Reporter',
            'Public 42.0',
            'Firefox for Android fr_FR Løst OS 20040922',
            '1\xa0day ago',
            'https://example.com/',
            'Method: Direct link',
            'Source: Unknown',
            'Hateful, violent, or illegal content',
            created_at,
            'anonymous [FR]',
            'Et mël mazim ludus.',
        ]

        assert doc('.abuse_reports').text().split('\n') == expected

    def test_abuse_reports_unlisted_addon(self):
        user = UserProfile.objects.get(email='reviewer@mozilla.com')
        self.grant_permission(user, 'Addons:ReviewUnlisted')
        self.login_as_reviewer()
        self.make_addon_unlisted(self.addon)
        self.test_abuse_reports()

    def test_abuse_reports_developers(self):
        report = AbuseReport.objects.create(
            user=self.addon.listed_authors[0], message=u'Foo, Bâr!',
            country_code='DE')
        created_at = format_datetime(report.created)
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('.abuse_reports')
        expected = [
            'Developer/Addon',
            'Application',
            'Install date',
            'Install origin',
            'Category',
            'Date',
            'Reporter',
            'regularuser التطب',
            'Firefox',
            'None',
            created_at,
            'anonymous [DE]',
            'Foo, Bâr!',
        ]

        assert doc('.abuse_reports').text().split('\n') == expected

    def test_abuse_reports_developers_unlisted_addon(self):
        user = UserProfile.objects.get(email='reviewer@mozilla.com')
        self.grant_permission(user, 'Addons:ReviewUnlisted')
        self.login_as_reviewer()
        self.make_addon_unlisted(self.addon)
        self.test_abuse_reports_developers()

    def test_user_ratings(self):
        user = user_factory()
        rating = Rating.objects.create(
            body=u'Lôrem ipsum dolor', rating=3, ip_address='10.5.6.7',
            addon=self.addon, user=user)
        created_at = format_date(rating.created)
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
        assert doc('.user_ratings')
        assert (
            doc('.user_ratings').text() ==
            u'%s on %s [10.5.6.7]\n'
            u'Rated 3 out of 5 stars\nLôrem ipsum dolor' % (
                user.name, created_at
            )
        )

    def test_user_ratings_unlisted_addon(self):
        user = UserProfile.objects.get(email='reviewer@mozilla.com')
        self.grant_permission(user, 'Addons:ReviewUnlisted')
        self.login_as_reviewer()
        self.make_addon_unlisted(self.addon)
        self.test_user_ratings()

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

        assert 'data-value' not in doc('select#id_versions.data-toggle')[0]

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

        assert 'data-value' not in doc('select#id_versions.data-toggle')[0]

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

    def test_post_review_ignore_disabled(self):
        # Though the latest version will be disabled, the add-on is public and
        # was auto-approved so the confirmation action is available.
        AutoApprovalSummary.objects.create(
            verdict=amo.AUTO_APPROVED, version=self.version)
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

    def test_content_review_ignore_disabled(self):
        # Though the latest version will be disabled, the add-on is public and
        # was auto-approved so the content approval action is available.
        AutoApprovalSummary.objects.create(
            verdict=amo.AUTO_APPROVED, version=self.version)
        version_factory(
            addon=self.addon, file_kw={'status': amo.STATUS_DISABLED})
        self.grant_permission(self.reviewer, 'Addons:ContentReview')
        self.url = reverse(
            'reviewers.review', args=['content', self.addon.slug])
        response = self.client.get(self.url)
        assert response.status_code == 200
        expected_actions = [
            'approve_content', 'reject_multiple_versions', 'reply',
            'super', 'comment']
        assert (
            [action[0] for action in response.context['actions']] ==
            expected_actions)

    def test_static_theme_backgrounds(self):
        self.addon.update(type=amo.ADDON_STATICTHEME)
        self.grant_permission(self.reviewer, 'Addons:ThemeReview')

        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        backgrounds_div = doc('div.all-backgrounds')
        assert backgrounds_div.attr('data-backgrounds-url') == (
            reverse('reviewers.theme_background_images',
                    args=[self.addon.current_version.id])
        )

    def test_reused_guid_from_previous_deleted_addon(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert b'Previously deleted entries' not in response.content

        old_one = addon_factory(status=amo.STATUS_DELETED)
        old_two = addon_factory(status=amo.STATUS_DELETED)
        old_other = addon_factory(status=amo.STATUS_DELETED)
        old_noguid = addon_factory(status=amo.STATUS_DELETED)
        ReusedGUID.objects.create(addon=old_one, guid='reuse@')
        ReusedGUID.objects.create(addon=old_two, guid='reuse@')
        ReusedGUID.objects.create(addon=old_other, guid='other@')
        ReusedGUID.objects.create(addon=old_noguid, guid='')
        self.addon.update(guid='reuse@')

        response = self.client.get(self.url)
        assert response.status_code == 200
        assert b'Previously deleted entries' in response.content
        expected = [
            (f'{old_one.id}', reverse('reviewers.review', args=[old_one.id])),
            (f'{old_two.id}', reverse('reviewers.review', args=[old_two.id])),
        ]
        doc = pq(response.content)
        check_links(
            expected, doc('div.results table.item-history a'), verify=False)

        # test unlisted review pages link to unlisted review pages
        self.make_addon_unlisted(self.addon)
        self.login_as_admin()
        response = self.client.get(
            reverse('reviewers.review', args=['unlisted', self.addon.slug]))
        assert response.status_code == 200
        expected = [
            (f'{old_one.id}', reverse(
                'reviewers.review', args=['unlisted', old_one.id])),
            (f'{old_two.id}', reverse(
                'reviewers.review', args=['unlisted', old_two.id])),
        ]
        doc = pq(response.content)
        check_links(
            expected, doc('div.results table.item-history a'), verify=False)

        # make sure an empty guid isn't considered (e.g. search plugins)
        self.addon.update(guid=None)
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert b'Previously deleted entries' not in response.content
        self.addon.update(guid='')
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert b'Previously deleted entries' not in response.content

    def test_versions_that_needs_human_review_are_highlighted(self):
        self.addon.current_version.update(created=self.days_ago(366))
        for i in range(0, 10):
            # Add versions 1.0 to 1.9. Flag a few of them as needing human
            # review.
            version_factory(
                addon=self.addon, version=f'1.{i}',
                needs_human_review=not bool(i % 3),
                created=self.days_ago(365 - i))

        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        tds = doc('#versions-history .review-files td.files')
        assert tds.length == 10
        # Original version should not be there any more, it's on the second
        # page. Versions on the page should be displayed in chronological order
        # Versions 1.0, 1.3, 1.6, 1.9 are flagged for human review.
        assert 'Flagged by automated scanners' in tds.eq(0).text()
        assert 'Flagged by automated scanners' in tds.eq(3).text()
        assert 'Flagged by automated scanners' in tds.eq(6).text()
        assert 'Flagged by automated scanners' in tds.eq(9).text()

        # There are no other flagged versions in the other page.
        span = doc('#review-files-header .risk-high')
        assert span.length == 0

        # Load the second page. This time there should be a message indicating
        # there are flagged versions in other pages.
        response = self.client.get(self.url, {'page': 2})
        assert response.status_code == 200
        doc = pq(response.content)
        span = doc('#review-files-header .risk-high')
        assert span.length == 1
        assert span.text() == '4 versions flagged by scanners on other pages.'

    def test_blocked_versions(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert b'Blocked' not in response.content

        block = Block.objects.create(
            guid=self.addon.guid, updated_by=user_factory())
        response = self.client.get(self.url)
        assert b'Blocked' in response.content
        span = pq(response.content)('#versions-history .blocked-version')
        assert span.text() == 'Blocked'
        assert span.length == 1  # addon only has 1 version

        version_factory(addon=self.addon, version='99')
        response = self.client.get(self.url)
        span = pq(response.content)('#versions-history .blocked-version')
        assert span.text() == 'Blocked Blocked'
        assert span.length == 2  # a new version is blocked too

        block.update(max_version='98')
        response = self.client.get(self.url)
        span = pq(response.content)('#versions-history .blocked-version')
        assert span.text() == 'Blocked'
        assert span.length == 1


class TestAbuseReportsView(ReviewerTest):
    def setUp(self):
        self.addon_developer = user_factory()
        self.addon = addon_factory(name='Flôp', users=[self.addon_developer])
        self.url = reverse('reviewers.abuse_reports', args=[self.addon.slug])
        self.login_as_reviewer()

    def test_abuse_reports(self):
        report = AbuseReport.objects.create(
            addon=self.addon,
            message='Et mël mazim ludus.',
            country_code='FR',
            client_id='4815162342',
            addon_name='Unused here',
            addon_summary='Not used either',
            addon_version='42.0',
            addon_signature=AbuseReport.ADDON_SIGNATURES.UNSIGNED,
            application=amo.ANDROID.id,
            application_locale='fr_FR',
            operating_system='Løst OS',
            operating_system_version='20040922',
            install_date=self.days_ago(1),
            reason=AbuseReport.REASONS.POLICY,
            addon_install_origin='https://example.com/',
            addon_install_method=AbuseReport.ADDON_INSTALL_METHODS.LINK,
            addon_install_source=AbuseReport.ADDON_INSTALL_SOURCES.UNKNOWN,
            report_entry_point=AbuseReport.REPORT_ENTRY_POINTS.MENU,
        )
        created_at = format_datetime(report.created)
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert len(doc('.abuse_reports')) == 1
        expected = [
            'Developer/Addon',
            'Application',
            'Install date',
            'Install origin',
            'Category',
            'Date',
            'Reporter',
            'Flôp 42.0',
            'Firefox for Android fr_FR Løst OS 20040922',
            '1\xa0day ago',
            'https://example.com/',
            'Method: Direct link',
            'Source: Unknown',
            'Hateful, violent, or illegal content',
            created_at,
            'anonymous [FR]',
            'Et mël mazim ludus.',
        ]

        assert doc('.abuse_reports').text().split('\n') == expected

    def test_queries(self):
        AbuseReport.objects.create(addon=self.addon, message='One')
        AbuseReport.objects.create(addon=self.addon, message='Two')
        AbuseReport.objects.create(addon=self.addon, message='Three')
        AbuseReport.objects.create(user=self.addon_developer, message='Four')
        with self.assertNumQueries(21):
            # - 2 savepoint/release savepoint
            # - 2 for user and groups
            # - 1 for the add-on
            # - 1 for its translations
            # - 7 for the add-on default transformer
            # - 1 for reviewer motd config
            # - 1 for site notice config
            # - 2 for add-ons from logged in user and its collections
            # - 1 for abuse reports count (pagination)
            # - 1 for the abuse reports
            # - 2 for the add-on and its translations (duplicate, but it's
            #     coming from the abuse reports queryset, annoying to get rid
            #     of)
            response = self.client.get(self.url)
        assert response.status_code == 200


@override_flag('code-manager', active=True)
class TestCodeManagerLinks(ReviewBase):

    def get_links(self):
        response = self.client.get(self.url)
        assert response.status_code == 200

        doc = pq(response.content)
        return doc.find('.code-manager-links')

    def test_link_to_contents(self):
        links = self.get_links()

        contents = links.find('a').eq(0)
        assert contents.text() == "Contents"
        assert contents.attr('href').endswith(
            '/browse/{}/versions/{}/'.format(
                self.addon.pk, self.version.pk
            )
        )

        # There should only be one Contents link for the version.
        assert links.find('a').length == 1

    def test_link_to_version_comparison(self):
        last_version = self.addon.current_version
        last_version.files.update(status=amo.STATUS_APPROVED)
        last_version.update(created=self.days_ago(2))

        new_version = version_factory(addon=self.addon, version='0.2')
        self.addon.update(_current_version=new_version)

        links = self.get_links()

        compare = links.find('a').eq(2)
        assert compare.text() == "Compare"
        assert compare.attr('href').endswith(
            '/compare/{}/versions/{}...{}/'.format(
                self.addon.pk,
                last_version.pk,
                new_version.pk,
            )
        )

        # There should be three links:
        # 1. The first version's Contents link
        # 2. The second version's Contents link
        # 3. The second version's Compare link
        assert links.find('a').length == 3

    def test_hide_links_when_flag_is_inactive(self):
        with override_flag('code-manager', active=False):
            assert self.get_links() == []


class TestReviewPending(ReviewBase):

    def setUp(self):
        super(TestReviewPending, self).setUp()
        self.file = file_factory(version=self.version,
                                 status=amo.STATUS_AWAITING_REVIEW,
                                 is_webextension=True)
        self.addon.update(status=amo.STATUS_APPROVED)

    def pending_dict(self):
        return self.get_dict(action='public')

    @mock.patch('olympia.reviewers.utils.sign_file')
    def test_pending_to_public(self, mock_sign):
        statuses = (self.version.files.values_list('status', flat=True)
                    .order_by('status'))
        assert list(statuses) == [
            amo.STATUS_AWAITING_REVIEW, amo.STATUS_APPROVED]

        response = self.client.post(self.url, self.pending_dict())
        assert self.get_addon().status == amo.STATUS_APPROVED
        self.assert3xx(response, reverse('reviewers.queue_extension'))

        statuses = (self.version.files.values_list('status', flat=True)
                    .order_by('status'))
        assert list(statuses) == [amo.STATUS_APPROVED, amo.STATUS_APPROVED]

        assert mock_sign.called

    @override_settings(ENABLE_ADDON_SIGNING=True)
    def test_pending_to_public_search(self):
        # sign_file() is *not* mocked here. We shouldn't need to, it should
        # just avoid signing search plugins silently.
        self.version.files.all().update(is_webextension=False)
        self.addon.update(type=amo.ADDON_SEARCH)
        response = self.client.post(self.url, self.pending_dict())
        self.assert3xx(response, reverse('reviewers.queue_extension'))
        assert self.get_addon().status == amo.STATUS_APPROVED
        statuses = (self.version.files.values_list('status', flat=True)
                    .order_by('status'))
        assert list(statuses) == [amo.STATUS_APPROVED, amo.STATUS_APPROVED]

    def test_display_only_unreviewed_files(self):
        """Only the currently unreviewed files are displayed."""
        self.file.update(filename=b'somefilename.xpi')
        reviewed = File.objects.create(version=self.version,
                                       status=amo.STATUS_APPROVED,
                                       filename=b'file_reviewed.xpi')
        disabled = File.objects.create(version=self.version,
                                       status=amo.STATUS_DISABLED,
                                       filename=b'file_disabled.xpi')
        unreviewed = File.objects.create(version=self.version,
                                         status=amo.STATUS_AWAITING_REVIEW,
                                         filename=b'file_unreviewed.xpi')
        response = self.client.get(self.url, self.pending_dict())
        assert response.status_code == 200
        doc = pq(response.content)
        assert len(doc('.review-actions-files ul li')) == 2
        assert reviewed.filename not in response.content
        assert disabled.filename not in response.content
        assert unreviewed.filename in response.content
        assert self.file.filename in response.content

    @mock.patch('olympia.reviewers.utils.sign_file')
    def test_review_unreviewed_files(self, mock_sign):
        """Review all the unreviewed files when submitting a review."""
        reviewed = File.objects.create(version=self.version,
                                       status=amo.STATUS_APPROVED)
        disabled = File.objects.create(version=self.version,
                                       status=amo.STATUS_DISABLED)
        unreviewed = File.objects.create(version=self.version,
                                         status=amo.STATUS_AWAITING_REVIEW)
        self.login_as_admin()
        response = self.client.post(self.url, self.pending_dict())
        self.assert3xx(response, reverse('reviewers.queue_extension'))

        assert self.addon.reload().status == amo.STATUS_APPROVED
        assert reviewed.reload().status == amo.STATUS_APPROVED
        assert disabled.reload().status == amo.STATUS_DISABLED
        assert unreviewed.reload().status == amo.STATUS_APPROVED
        assert self.file.reload().status == amo.STATUS_APPROVED

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
            'Is locked by a reviewer')

    def test_comments_box_doesnt_have_required_html_attribute(self):
        """Regression test

        https://github.com/mozilla/addons-server/issues/8907"""
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert doc('#id_comments').attr('required') is None


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
        assert doc('#versions-history .file-info div').text() == expected

    def test_status_full(self):
        self.get_file().update(status=amo.STATUS_AWAITING_REVIEW)
        for status in [amo.STATUS_NOMINATED, amo.STATUS_APPROVED]:
            self.addon.update(status=status)
            self.check_status('Awaiting Review')

    def test_status_full_reviewed(self):
        self.get_file().update(status=amo.STATUS_APPROVED)
        self.addon.update(status=amo.STATUS_APPROVED)
        self.check_status('Approved')


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
                 UserProfile.objects.get(email='theme_reviewer@mozilla.com'),
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
             str(amo.REVIEWED_LEVELS[0]['name']),
             users[0].name])

        self._award_points(users[0], 1)

        assert get_cells() == (
            [users[2].name,
             users[1].name,
             users[0].name,
             str(amo.REVIEWED_LEVELS[0]['name'])])

        self._award_points(users[0], -1)
        self._award_points(users[2], (amo.REVIEWED_LEVELS[1]['points'] -
                                      amo.REVIEWED_LEVELS[0]['points']))

        assert get_cells() == (
            [users[2].name,
             str(amo.REVIEWED_LEVELS[1]['name']),
             users[1].name,
             str(amo.REVIEWED_LEVELS[0]['name']),
             users[0].name])


class TestXssOnAddonName(amo.tests.TestXss):

    def test_reviewers_abuse_report_page(self):
        url = reverse('reviewers.abuse_reports', args=[self.addon.slug])
        self.assertNameAndNoXSS(url)

    def test_reviewers_review_page(self):
        url = reverse('reviewers.review', args=[self.addon.slug])
        self.assertNameAndNoXSS(url)


class TestPolicyView(ReviewerTest):
    def setUp(self):
        super(TestPolicyView, self).setUp()
        self.addon = addon_factory()
        self.eula_url = reverse('reviewers.eula', args=[self.addon.slug])
        self.privacy_url = reverse('reviewers.privacy', args=[self.addon.slug])
        self.login_as_reviewer()
        self.review_url = reverse(
            'reviewers.review', args=('listed', self.addon.slug,))

    def test_eula(self):
        assert not bool(self.addon.eula)
        response = self.client.get(self.eula_url)
        assert response.status_code == 404

        self.addon.eula = u'Eulá!'
        self.addon.save()
        assert bool(self.addon.eula)
        response = self.client.get(self.eula_url)
        assert response.status_code == 200
        self.assertContains(
            response,
            '{addon} :: EULA'.format(addon=self.addon.name))
        self.assertContains(response, u'End-User License Agreement')
        self.assertContains(response, u'Eulá!')
        self.assertContains(response, str(self.review_url))

    def test_eula_with_channel(self):
        unlisted_review_url = reverse(
            'reviewers.review', args=('unlisted', self.addon.slug,))
        self.addon.eula = u'Eulá!'
        self.addon.save()
        assert bool(self.addon.eula)
        response = self.client.get(self.eula_url + '?channel=unlisted')
        assert response.status_code == 403  # Because unlisted
        self.grant_permission(
            UserProfile.objects.get(email='reviewer@mozilla.com'),
            'ReviewerTools:View')  # so get the view permissions
        response = self.client.get(self.eula_url + '?channel=unlisted')
        assert response.status_code == 200
        self.assertContains(response, u'Eulá!')
        self.assertContains(response, str(unlisted_review_url))

    def test_privacy(self):
        assert not bool(self.addon.privacy_policy)
        response = self.client.get(self.privacy_url)
        assert response.status_code == 404

        self.addon.privacy_policy = u'Prívacy Pólicy?'
        self.addon.save()
        assert bool(self.addon.privacy_policy)
        response = self.client.get(self.privacy_url)
        assert response.status_code == 200
        self.assertContains(
            response,
            '{addon} :: Privacy Policy'.format(addon=self.addon.name))
        self.assertContains(response, 'Privacy Policy')
        self.assertContains(response, u'Prívacy Pólicy?')
        self.assertContains(response, str(self.review_url))

    def test_privacy_with_channel(self):
        unlisted_review_url = reverse(
            'reviewers.review', args=('unlisted', self.addon.slug,))
        self.addon.privacy_policy = u'Prívacy Pólicy?'
        self.addon.save()
        assert bool(self.addon.privacy_policy)
        response = self.client.get(self.privacy_url + '?channel=unlisted')
        assert response.status_code == 403  # Because unlisted
        self.grant_permission(
            UserProfile.objects.get(email='reviewer@mozilla.com'),
            'ReviewerTools:View')  # so get the view permissions
        response = self.client.get(self.privacy_url + '?channel=unlisted')
        assert response.status_code == 200
        self.assertContains(response, u'Prívacy Pólicy?')
        self.assertContains(response, str(unlisted_review_url))


class TestAddonReviewerViewSet(TestCase):
    client_class = APITestClient

    def setUp(self):
        super(TestAddonReviewerViewSet, self).setUp()
        self.user = user_factory()
        self.addon = addon_factory()
        self.subscribe_url = reverse_ns(
            'reviewers-addon-subscribe', kwargs={'pk': self.addon.pk})
        self.unsubscribe_url = reverse_ns(
            'reviewers-addon-unsubscribe', kwargs={'pk': self.addon.pk})
        self.enable_url = reverse_ns(
            'reviewers-addon-enable', kwargs={'pk': self.addon.pk})
        self.disable_url = reverse_ns(
            'reviewers-addon-disable', kwargs={'pk': self.addon.pk})
        self.flags_url = reverse_ns(
            'reviewers-addon-flags', kwargs={'pk': self.addon.pk})
        self.deny_resubmission_url = reverse_ns(
            'reviewers-addon-deny-resubmission', kwargs={'pk': self.addon.pk})
        self.allow_resubmission_url = reverse_ns(
            'reviewers-addon-allow-resubmission', kwargs={'pk': self.addon.pk})

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
        self.subscribe_url = reverse_ns(
            'reviewers-addon-subscribe', kwargs={'pk': self.addon.pk + 42})
        response = self.client.post(self.subscribe_url)
        assert response.status_code == 404

    def test_subscribe_already_subscribed(self):
        ReviewerSubscription.objects.create(
            user=self.user, addon=self.addon)
        self.grant_permission(self.user, 'Addons:PostReview')
        self.client.login_api(self.user)
        self.subscribe_url = reverse_ns(
            'reviewers-addon-subscribe', kwargs={'pk': self.addon.pk})
        response = self.client.post(self.subscribe_url)
        assert response.status_code == 202
        assert ReviewerSubscription.objects.count() == 1

    def test_subscribe(self):
        self.grant_permission(self.user, 'Addons:PostReview')
        self.client.login_api(self.user)
        self.subscribe_url = reverse_ns(
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
        self.unsubscribe_url = reverse_ns(
            'reviewers-addon-subscribe', kwargs={'pk': self.addon.pk + 42})
        response = self.client.post(self.unsubscribe_url)
        assert response.status_code == 404

    def test_unsubscribe_not_subscribed(self):
        self.grant_permission(self.user, 'Addons:PostReview')
        self.client.login_api(self.user)
        self.subscribe_url = reverse_ns(
            'reviewers-addon-subscribe', kwargs={'pk': self.addon.pk})
        response = self.client.post(self.unsubscribe_url)
        assert response.status_code == 202
        assert ReviewerSubscription.objects.count() == 0

    def test_unsubscribe(self):
        ReviewerSubscription.objects.create(
            user=self.user, addon=self.addon)
        self.grant_permission(self.user, 'Addons:PostReview')
        self.client.login_api(self.user)
        self.subscribe_url = reverse_ns(
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
        self.subscribe_url = reverse_ns(
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
        self.enable_url = reverse_ns(
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
        assert self.addon.status == amo.STATUS_APPROVED
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
        assert self.addon.status == amo.STATUS_APPROVED
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
        self.disable_url = reverse_ns(
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
        self.flags_url = reverse_ns(
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
            'needs_admin_theme_review': True,
            'pending_info_request': None,
        }
        response = self.client.patch(self.flags_url, data)
        assert response.status_code == 200
        assert AddonReviewerFlags.objects.filter(addon=self.addon).exists()
        reviewer_flags = AddonReviewerFlags.objects.get(addon=self.addon)
        assert reviewer_flags.auto_approval_disabled is False
        assert reviewer_flags.needs_admin_code_review is True
        assert reviewer_flags.needs_admin_content_review is True
        assert reviewer_flags.needs_admin_theme_review is True
        assert reviewer_flags.pending_info_request is None
        assert ActivityLog.objects.count() == 1
        activity_log = ActivityLog.objects.latest('pk')
        assert activity_log.action == amo.LOG.ADMIN_ALTER_INFO_REQUEST.id
        assert activity_log.arguments[0] == self.addon

    def test_deny_resubmission(self):
        self.grant_permission(self.user, 'Reviews:Admin')
        self.client.login_api(self.user)
        assert DeniedGuid.objects.count() == 0
        response = self.client.post(self.deny_resubmission_url)
        assert response.status_code == 202
        assert DeniedGuid.objects.count() == 1

    def test_deny_resubmission_with_denied_guid(self):
        self.grant_permission(self.user, 'Reviews:Admin')
        self.client.login_api(self.user)
        self.addon.deny_resubmission()
        assert DeniedGuid.objects.count() == 1
        response = self.client.post(self.deny_resubmission_url)
        assert response.status_code == 409
        assert DeniedGuid.objects.count() == 1

    def test_allow_resubmission(self):
        self.grant_permission(self.user, 'Reviews:Admin')
        self.client.login_api(self.user)
        self.addon.deny_resubmission()
        assert DeniedGuid.objects.count() == 1
        response = self.client.post(self.allow_resubmission_url)
        assert response.status_code == 202
        assert DeniedGuid.objects.count() == 0

    def test_allow_resubmission_with_non_denied_guid(self):
        self.grant_permission(self.user, 'Reviews:Admin')
        self.client.login_api(self.user)
        response = self.client.post(self.allow_resubmission_url)
        assert response.status_code == 409
        assert DeniedGuid.objects.count() == 0


class AddonReviewerViewSetPermissionMixin(object):
    __test__ = False

    def test_disabled_version_reviewer(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)
        self.version.files.update(status=amo.STATUS_DISABLED)
        self._test_url()

    def test_disabled_version_author(self):
        user = UserProfile.objects.create(username='author')
        AddonUser.objects.create(user=user, addon=self.addon)
        self.client.login_api(user)
        self.version.files.update(status=amo.STATUS_DISABLED)
        self._test_url()

    def test_disabled_version_admin(self):
        user = UserProfile.objects.create(username='admin')
        self.grant_permission(user, '*:*')
        self.client.login_api(user)
        self.version.files.update(status=amo.STATUS_DISABLED)
        self._test_url()

    def test_disabled_version_user_but_not_author(self):
        user = UserProfile.objects.create(username='simpleuser')
        self.client.login_api(user)
        self.version.files.update(status=amo.STATUS_DISABLED)
        response = self.client.get(self.url)
        assert response.status_code == 403

    def test_deleted_version_reviewer(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)
        self.version.delete()
        response = self.client.get(self.url)
        assert response.status_code == 404

    def test_deleted_version_author(self):
        user = UserProfile.objects.create(username='author')
        AddonUser.objects.create(user=user, addon=self.addon)
        self.client.login_api(user)
        self.version.delete()
        response = self.client.get(self.url)
        assert response.status_code == 404

    def test_deleted_version_admin(self):
        user = UserProfile.objects.create(username='admin')
        self.grant_permission(user, '*:*')
        self.client.login_api(user)
        self.version.delete()
        self._test_url()

    def test_deleted_version_user_but_not_author(self):
        user = UserProfile.objects.create(username='simpleuser')
        self.client.login_api(user)
        self.version.delete()
        response = self.client.get(self.url)
        assert response.status_code == 404

    def test_unlisted_version_reviewer(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)
        self.version.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        response = self.client.get(self.url)
        assert response.status_code == 404

    def test_unlisted_version_unlisted_reviewer(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:ReviewUnlisted')
        self.client.login_api(user)
        self.version.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        self._test_url()

    def test_unlisted_version_author(self):
        user = UserProfile.objects.create(username='author')
        AddonUser.objects.create(user=user, addon=self.addon)
        self.client.login_api(user)
        self.version.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        self._test_url()

    def test_unlisted_version_admin(self):
        user = UserProfile.objects.create(username='admin')
        self.grant_permission(user, '*:*')
        self.client.login_api(user)
        self.version.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        self._test_url()

    def test_unlisted_version_user_but_not_author(self):
        user = UserProfile.objects.create(username='simpleuser')
        self.client.login_api(user)
        self.version.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        response = self.client.get(self.url)
        assert response.status_code == 404


class TestReviewAddonVersionViewSetDetail(
        TestCase, AddonReviewerViewSetPermissionMixin):
    client_class = APITestClient
    __test__ = True

    def setUp(self):
        super(TestReviewAddonVersionViewSetDetail, self).setUp()

        # TODO: Most of the initial setup could be moved to
        # setUpTestData but unfortunately paths are setup in pytest via a
        # regular autouse fixture that has function-scope so functions in
        # setUpTestData doesn't use proper paths (cgrebs)
        self.addon = addon_factory(
            name=u'My Addôn', slug='my-addon',
            file_kw={'filename': 'webextension_no_id.xpi'})

        extract_version_to_git(self.addon.current_version.pk)

        self.version = self.addon.current_version
        self.version.refresh_from_db()

        self._set_tested_url()

    def _test_url(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        result = json.loads(response.content)
        assert result['id'] == self.version.pk
        assert result['file']['id'] == self.version.current_file.pk

        # part of manifest.json
        assert '"name": "Beastify"' in result['file']['content']

    def _set_tested_url(self):
        self.url = reverse_ns('reviewers-versions-detail', kwargs={
            'addon_pk': self.addon.pk,
            'pk': self.version.pk})

    def test_anonymous(self):
        response = self.client.get(self.url)
        assert response.status_code == 401

    def test_requested_file(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)

        response = self.client.get(self.url + '?file=README.md')
        assert response.status_code == 200
        result = json.loads(response.content)

        assert result['file']['content'] == '# beastify\n'

        # make sure the correct download url is correctly generated
        assert result['file']['download_url'] == absolutify(reverse(
            'reviewers.download_git_file',
            kwargs={
                'version_id': self.version.pk,
                'filename': 'README.md'
            }
        ))

    def test_non_existent_requested_file_returns_404(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)

        response = self.client.get(self.url + '?file=UNKNOWN_FILE')
        assert response.status_code == 404

    def test_supports_search_plugins(self):
        self.addon = addon_factory(
            name=u'My Addôn', slug='my-addon',
            file_kw={'filename': 'search.xml'})

        extract_version_to_git(self.addon.current_version.pk)

        self.version = self.addon.current_version
        self.version.refresh_from_db()

        self._set_tested_url()

        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)

        response = self.client.get(self.url)
        assert response.status_code == 200
        result = json.loads(response.content)

        assert result['file']['content'].startswith(
            '<?xml version="1.0" encoding="utf-8"?>')

        # make sure the correct download url is correctly generated
        assert result['file']['download_url'] == absolutify(reverse(
            'reviewers.download_git_file',
            kwargs={
                'version_id': self.version.pk,
                'filename': 'search.xml'
            }
        ))

    def test_version_get_not_found(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)
        self.url = reverse_ns('reviewers-versions-detail', kwargs={
            'addon_pk': self.addon.pk,
            'pk': self.version.current_file.pk + 42})
        response = self.client.get(self.url)
        assert response.status_code == 404

    def test_mixed_channel_only_listed_without_unlisted_perm(self):
        user = UserProfile.objects.create(username='admin')

        # User doesn't have ReviewUnlisted permission
        self.grant_permission(user, 'Addons:Review')

        self.client.login_api(user)

        # Add an unlisted version to the mix
        unlisted_version = version_factory(
            addon=self.addon, channel=amo.RELEASE_CHANNEL_UNLISTED)

        # Now the add-on has both, listed and unlisted versions
        # but only reviewers with Addons:ReviewUnlisted are able
        # to see them
        url = reverse_ns('reviewers-versions-detail', kwargs={
            'addon_pk': self.addon.pk,
            'pk': self.version.pk})

        response = self.client.get(url)
        assert response.status_code == 200

        url = reverse_ns('reviewers-versions-detail', kwargs={
            'addon_pk': self.addon.pk,
            'pk': unlisted_version.pk})

        response = self.client.get(url)
        assert response.status_code == 404


class TestReviewAddonVersionViewSetList(TestCase):
    client_class = APITestClient

    def setUp(self):
        super(TestReviewAddonVersionViewSetList, self).setUp()

        self.addon = addon_factory(
            name=u'My Addôn', slug='my-addon',
            file_kw={'filename': 'webextension_no_id.xpi'})

        extract_version_to_git(self.addon.current_version.pk)

        self.version = self.addon.current_version
        self.version.refresh_from_db()

        self._set_tested_url()

    def _test_url(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        result = json.loads(response.content)
        assert result == [{
            'version': self.version.version,
            'id': self.version.id,
            'channel': u'listed',
        }]

    def _set_tested_url(self):
        self.url = reverse_ns('reviewers-versions-list', kwargs={
            'addon_pk': self.addon.pk})

    def test_anonymous(self):
        response = self.client.get(self.url)
        assert response.status_code == 401

    def test_permissions_reviewer(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)
        self._test_url()

    def test_permissions_disabled_version_author(self):
        user = UserProfile.objects.create(username='author')
        AddonUser.objects.create(user=user, addon=self.addon)
        self.client.login_api(user)
        self.version.files.update(status=amo.STATUS_DISABLED)
        self._test_url()

    def test_permissions_disabled_version_admin(self):
        user = UserProfile.objects.create(username='admin')
        self.grant_permission(user, '*:*')
        self.client.login_api(user)
        self.version.files.update(status=amo.STATUS_DISABLED)
        self._test_url()

    def test_permissions_disabled_version_user_but_not_author(self):
        user = UserProfile.objects.create(username='simpleuser')
        self.client.login_api(user)
        self.version.files.update(status=amo.STATUS_DISABLED)
        response = self.client.get(self.url)
        assert response.status_code == 403

    def test_show_only_listed_without_unlisted_permission(self):
        user = UserProfile.objects.create(username='admin')

        # User doesn't have ReviewUnlisted permission
        self.grant_permission(user, 'Addons:Review')

        self.client.login_api(user)

        version_factory(
            addon=self.addon, channel=amo.RELEASE_CHANNEL_UNLISTED)

        response = self.client.get(self.url)
        assert response.status_code == 200
        result = json.loads(response.content)

        assert result == [
            {
                'version': self.version.version,
                'id': self.version.id,
                'channel': u'listed'
            },
        ]

    def test_show_listed_and_unlisted_with_permissions(self):
        user = UserProfile.objects.create(username='admin')

        # User doesn't have Review permission
        self.grant_permission(user, 'Addons:ReviewUnlisted')

        self.client.login_api(user)

        unlisted_version = version_factory(
            addon=self.addon, channel=amo.RELEASE_CHANNEL_UNLISTED)

        # We have a .only() and .no_transforms or .only_translations
        # querysets which reduces the amount of queries to "only" 10
        with self.assertNumQueries(10):
            response = self.client.get(self.url)

        assert response.status_code == 200
        result = json.loads(response.content)

        assert result == [
            {
                'version': unlisted_version.version,
                'id': unlisted_version.id,
                'channel': u'unlisted'
            },
            {
                'version': self.version.version,
                'id': self.version.id,
                'channel': u'listed'
            },
        ]


class TestDraftCommentViewSet(TestCase):
    client_class = APITestClient

    def setUp(self):
        super().setUp()

        self.addon = addon_factory(
            name=u'My Addôn', slug='my-addon',
            file_kw={'filename': 'webextension_no_id.xpi'})

        extract_version_to_git(self.addon.current_version.pk)

        self.version = self.addon.current_version
        self.version.refresh_from_db()

    def test_create_and_retrieve(self):
        user = user_factory(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)

        data = {
            'comment': 'Some really fancy comment',
            'lineno': 20,
            'filename': 'manifest.json',
        }

        url = reverse_ns('reviewers-versions-draft-comment-list', kwargs={
            'addon_pk': self.addon.pk,
            'version_pk': self.version.pk
        })

        response = self.client.post(url, data)
        comment_id = response.json()['id']
        assert response.status_code == 201

        response = self.client.post(url, data)
        assert response.status_code == 201

        assert DraftComment.objects.count() == 2

        response = self.client.get(url)

        request = APIRequestFactory().get('/')
        request.user = user

        assert response.json()['count'] == 2
        assert response.json()['results'][0] == {
            'id': comment_id,
            'filename': 'manifest.json',
            'lineno': 20,
            'comment': 'Some really fancy comment',
            'canned_response': None,
            'version': json.loads(json.dumps(
                AddonBrowseVersionSerializer(self.version).data,
                cls=amo.utils.AMOJSONEncoder)),
            'user': json.loads(json.dumps(
                BaseUserSerializer(
                    user, context={'request': request}).data,
                cls=amo.utils.AMOJSONEncoder))
        }

    def test_list_queries(self):
        user = user_factory(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)
        DraftComment.objects.create(
            version=self.version, comment='test1', user=user,
            lineno=0, filename='manifest.json')
        DraftComment.objects.create(
            version=self.version, comment='test2', user=user,
            lineno=1, filename='manifest.json')
        DraftComment.objects.create(
            version=self.version, comment='test3', user=user,
            lineno=2, filename='manifest.json')
        url = reverse_ns('reviewers-versions-draft-comment-list', kwargs={
            'addon_pk': self.addon.pk,
            'version_pk': self.version.pk
        })
        with self.assertNumQueries(15):
            # - 2 savepoints because of tests
            # - 2 user and groups
            # - 2 addon and translations
            # - 2 version and translations
            # - 1 applications versions
            # - 2 licenses and translations
            # - 1 files
            # - 1 file validation
            # - 1 count
            # - 1 drafts
            response = self.client.get(url, {'lang': 'en-US'})
        assert response.json()['count'] == 3

    def test_create_retrieve_and_update(self):
        user = user_factory(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)

        data = {
            'comment': 'Some really fancy comment',
            'lineno': 20,
            'filename': 'manifest.json',
        }

        url = reverse_ns('reviewers-versions-draft-comment-list', kwargs={
            'addon_pk': self.addon.pk,
            'version_pk': self.version.pk
        })

        response = self.client.post(url, data)
        assert response.status_code == 201

        comment = DraftComment.objects.first()

        response = self.client.get(url)

        assert response.json()['count'] == 1
        assert (
            response.json()['results'][0]['comment'] ==
            'Some really fancy comment')

        url = reverse_ns('reviewers-versions-draft-comment-detail', kwargs={
            'addon_pk': self.addon.pk,
            'version_pk': self.version.pk,
            'pk': comment.pk
        })

        response = self.client.patch(url, {
            'comment': 'Updated comment!'
        })

        assert response.status_code == 200

        response = self.client.get(url)

        assert response.json()['comment'] == 'Updated comment!'
        assert response.json()['lineno'] == 20

        response = self.client.patch(url, {
            'lineno': 18
        })

        assert response.status_code == 200

        response = self.client.get(url)

        assert response.json()['lineno'] == 18

        # Patch two fields at the same time
        response = self.client.patch(url, {
            'lineno': 16,
            'filename': 'new_manifest.json'
        })

        assert response.status_code == 200
        response = self.client.get(url)

        assert response.json()['lineno'] == 16
        assert response.json()['filename'] == 'new_manifest.json'

    def test_draft_optional_fields(self):
        user = user_factory(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)

        data = {
            'comment': 'Some really fancy comment',
        }

        url = reverse_ns('reviewers-versions-draft-comment-list', kwargs={
            'addon_pk': self.addon.pk,
            'version_pk': self.version.pk
        })

        response = self.client.post(url, data)
        comment_id = response.json()['id']

        assert response.status_code == 201

        url = reverse_ns('reviewers-versions-draft-comment-detail', kwargs={
            'addon_pk': self.addon.pk,
            'version_pk': self.version.pk,
            'pk': comment_id
        })

        response = self.client.get(url)

        assert response.json()['comment'] == 'Some really fancy comment'
        assert response.json()['lineno'] is None
        assert response.json()['filename'] is None
        assert response.json()['canned_response'] is None

    def test_delete(self):
        user = user_factory(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)

        comment = DraftComment.objects.create(
            version=self.version, comment='test', user=user,
            lineno=0, filename='manifest.json')

        url = reverse_ns('reviewers-versions-draft-comment-detail', kwargs={
            'addon_pk': self.addon.pk,
            'version_pk': self.version.pk,
            'pk': comment.pk
        })

        response = self.client.delete(url)
        assert response.status_code == 204

        assert DraftComment.objects.first() is None

    def test_canned_response_and_comment_not_together(self):
        user = user_factory(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)

        canned_response = CannedResponse.objects.create(
            name=u'Terms of services',
            response=u'doesn\'t regard our terms of services',
            category=amo.CANNED_RESPONSE_CATEGORY_OTHER,
            type=amo.CANNED_RESPONSE_TYPE_ADDON)

        data = {
            'comment': 'Some really fancy comment',
            'canned_response': canned_response.pk,
            'lineno': 20,
            'filename': 'manifest.json',
        }

        url = reverse_ns('reviewers-versions-draft-comment-list', kwargs={
            'addon_pk': self.addon.pk,
            'version_pk': self.version.pk,
        })

        response = self.client.post(url, data)
        assert response.status_code == 400
        assert (
            str(response.data['comment'][0]) ==
            "You can't submit a comment if `canned_response` is defined.")

    def test_doesnt_allow_empty_comment(self):
        user = user_factory(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)

        data = {
            'comment': '',
            'lineno': 20,
            'filename': 'manifest.json',
        }

        url = reverse_ns('reviewers-versions-draft-comment-list', kwargs={
            'addon_pk': self.addon.pk,
            'version_pk': self.version.pk,
        })

        response = self.client.post(url, data)
        assert response.status_code == 400
        assert (
            str(response.data['comment'][0]) ==
            "You can't submit an empty comment.")

    def test_disallow_lineno_without_filename(self):
        user = user_factory(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)

        data = {
            'comment': 'Some really fancy comment',
            'lineno': 20,
            'filename': None,
        }

        url = reverse_ns('reviewers-versions-draft-comment-list', kwargs={
            'addon_pk': self.addon.pk,
            'version_pk': self.version.pk,
        })

        response = self.client.post(url, data)
        assert response.status_code == 400
        assert (
            str(response.data['comment'][0]) ==
            'You can\'t submit a line number without associating it to a '
            'filename.')

    def test_allows_explicit_canned_response_null(self):
        user = user_factory(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)

        data = {
            'comment': 'Some random comment',
            'canned_response': None,
            'lineno': 20,
            'filename': 'manifest.json',
        }

        url = reverse_ns('reviewers-versions-draft-comment-list', kwargs={
            'addon_pk': self.addon.pk,
            'version_pk': self.version.pk,
        })

        response = self.client.post(url, data)
        assert response.status_code == 201

    def test_canned_response(self):
        user = user_factory(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)

        canned_response = CannedResponse.objects.create(
            name=u'Terms of services',
            response=u'doesn\'t regard our terms of services',
            category=amo.CANNED_RESPONSE_CATEGORY_OTHER,
            type=amo.CANNED_RESPONSE_TYPE_ADDON)

        data = {
            'canned_response': canned_response.pk,
            'lineno': 20,
            'filename': 'manifest.json',
        }

        url = reverse_ns('reviewers-versions-draft-comment-list', kwargs={
            'addon_pk': self.addon.pk,
            'version_pk': self.version.pk,
        })

        response = self.client.post(url, data)
        comment_id = response.json()['id']

        assert response.status_code == 201
        assert DraftComment.objects.count() == 1

        response = self.client.get(url)

        request = APIRequestFactory().get('/')
        request.user = user

        assert response.json()['count'] == 1
        assert response.json()['results'][0] == {
            'id': comment_id,
            'filename': 'manifest.json',
            'lineno': 20,
            'comment': '',
            'canned_response': json.loads(json.dumps(
                CannedResponseSerializer(canned_response).data,
                cls=amo.utils.AMOJSONEncoder)),
            'version': json.loads(json.dumps(
                AddonBrowseVersionSerializer(self.version).data,
                cls=amo.utils.AMOJSONEncoder)),
            'user': json.loads(json.dumps(
                BaseUserSerializer(
                    user, context={'request': request}).data,
                cls=amo.utils.AMOJSONEncoder))
        }

    def test_delete_not_comment_owner(self):
        user = user_factory(username='reviewer')
        self.grant_permission(user, 'Addons:Review')

        comment = DraftComment.objects.create(
            version=self.version, comment='test', user=user,
            lineno=0, filename='manifest.json')

        # Let's login as someone else who is also a reviewer
        other_reviewer = user_factory(username='reviewer2')

        # Let's give the user admin permissions which doesn't help
        self.grant_permission(other_reviewer, '*:*')

        self.client.login_api(other_reviewer)

        url = reverse_ns('reviewers-versions-draft-comment-detail', kwargs={
            'addon_pk': self.addon.pk,
            'version_pk': self.version.pk,
            'pk': comment.pk
        })

        response = self.client.delete(url)
        assert response.status_code == 404

    def test_disabled_version_user_but_not_author(self):
        user = user_factory(username='simpleuser')
        self.client.login_api(user)
        self.version.files.update(status=amo.STATUS_DISABLED)

        data = {
            'comment': 'Some really fancy comment',
            'lineno': 20,
            'filename': 'manifest.json',
        }

        url = reverse_ns('reviewers-versions-draft-comment-list', kwargs={
            'addon_pk': self.addon.pk,
            'version_pk': self.version.pk
        })

        response = self.client.post(url, data)
        assert response.status_code == 403

    def test_deleted_version_reviewer(self):
        user = user_factory(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)
        self.version.delete()

        data = {
            'comment': 'Some really fancy comment',
            'lineno': 20,
            'filename': 'manifest.json',
        }

        url = reverse_ns('reviewers-versions-draft-comment-list', kwargs={
            'addon_pk': self.addon.pk,
            'version_pk': self.version.pk
        })

        response = self.client.post(url, data)
        assert response.status_code == 404

    def test_deleted_version_author(self):
        user = user_factory(username='author')
        AddonUser.objects.create(user=user, addon=self.addon)
        self.client.login_api(user)
        self.version.delete()

        data = {
            'comment': 'Some really fancy comment',
            'lineno': 20,
            'filename': 'manifest.json',
        }

        url = reverse_ns('reviewers-versions-draft-comment-list', kwargs={
            'addon_pk': self.addon.pk,
            'version_pk': self.version.pk
        })

        response = self.client.post(url, data)
        assert response.status_code == 404

    def test_deleted_version_user_but_not_author(self):
        user = user_factory(username='simpleuser')
        self.client.login_api(user)
        self.version.delete()

        data = {
            'comment': 'Some really fancy comment',
            'lineno': 20,
            'filename': 'manifest.json',
        }

        url = reverse_ns('reviewers-versions-draft-comment-list', kwargs={
            'addon_pk': self.addon.pk,
            'version_pk': self.version.pk
        })

        response = self.client.post(url, data)
        assert response.status_code == 404

    def test_unlisted_version_reviewer(self):
        user = user_factory(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)
        self.version.update(channel=amo.RELEASE_CHANNEL_UNLISTED)

        data = {
            'comment': 'Some really fancy comment',
            'lineno': 20,
            'filename': 'manifest.json',
        }

        url = reverse_ns('reviewers-versions-draft-comment-list', kwargs={
            'addon_pk': self.addon.pk,
            'version_pk': self.version.pk
        })

        response = self.client.post(url, data)
        assert response.status_code == 403

    def test_unlisted_version_user_but_not_author(self):
        user = user_factory(username='simpleuser')
        self.client.login_api(user)
        self.version.update(channel=amo.RELEASE_CHANNEL_UNLISTED)

        data = {
            'comment': 'Some really fancy comment',
            'lineno': 20,
            'filename': 'manifest.json',
        }

        url = reverse_ns('reviewers-versions-draft-comment-list', kwargs={
            'addon_pk': self.addon.pk,
            'version_pk': self.version.pk
        })

        response = self.client.post(url, data)
        assert response.status_code == 403


class TestReviewAddonVersionCompareViewSet(
        TestCase, AddonReviewerViewSetPermissionMixin):
    client_class = APITestClient
    __test__ = True

    def setUp(self):
        super(TestReviewAddonVersionCompareViewSet, self).setUp()

        self.addon = addon_factory(
            name=u'My Addôn', slug='my-addon',
            file_kw={'filename': 'webextension_no_id.xpi'})

        extract_version_to_git(self.addon.current_version.pk)

        self.version = self.addon.current_version
        self.version.refresh_from_db()

        # Default to initial commit for simplicity
        self.compare_to_version = self.version

        self._set_tested_url()

    def _test_url(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        result = json.loads(response.content)

        assert result['id'] == self.version.pk
        assert result['file']['id'] == self.version.current_file.pk
        assert result['file']['diff']['path'] == 'manifest.json'

        change = result['file']['diff']['hunks'][0]['changes'][3]

        assert '"name": "Beastify"' in change['content']
        assert change['type'] == 'insert'

    def _set_tested_url(self):
        self.url = reverse_ns('reviewers-versions-compare-detail', kwargs={
            'addon_pk': self.addon.pk,
            'version_pk': self.version.pk,
            'pk': self.compare_to_version.pk})

    def test_anonymous(self):
        response = self.client.get(self.url)
        assert response.status_code == 401

    def test_requested_file(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)

        response = self.client.get(self.url + '?file=README.md')
        assert response.status_code == 200
        result = json.loads(response.content)
        assert result['file']['diff']['path'] == 'README.md'

        change = result['file']['diff']['hunks'][0]['changes'][0]

        assert change['content'] == '# beastify'
        assert change['type'] == 'insert'

    def test_supports_search_plugins(self):
        self.addon = addon_factory(
            name=u'My Addôn', slug='my-addon',
            file_kw={'filename': 'search.xml'})

        extract_version_to_git(self.addon.current_version.pk)

        self.version = self.addon.current_version
        self.version.refresh_from_db()

        new_version = version_factory(
            addon=self.addon, file_kw={'filename': 'search.xml'})

        repo = AddonGitRepository.extract_and_commit_from_version(new_version)

        apply_changes(repo, new_version, '<xml></xml>\n', 'search.xml')

        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)

        self.url = reverse_ns('reviewers-versions-compare-detail', kwargs={
            'addon_pk': self.addon.pk,
            'version_pk': self.version.pk,
            'pk': new_version.pk})

        response = self.client.get(self.url)
        assert response.status_code == 200
        result = json.loads(response.content)
        changes = result['file']['diff']['hunks'][0]['changes']

        assert result['file']['diff']['path'] == 'search.xml'
        assert changes[-1] == {
            'content': '<xml></xml>',
            'new_line_number': 1,
            'old_line_number': -1,
            'type': 'insert'
        }

        assert all(x['type'] == 'delete' for x in changes[:-1])

    def test_version_get_not_found(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)
        self.url = reverse_ns('reviewers-versions-compare-detail', kwargs={
            'addon_pk': self.addon.pk,
            'version_pk': self.version.pk + 42,
            'pk': self.compare_to_version.pk})
        response = self.client.get(self.url)
        assert response.status_code == 404

    def test_compare_basic(self):
        new_version = version_factory(
            addon=self.addon, file_kw={'filename': 'webextension_no_id.xpi'})

        repo = AddonGitRepository.extract_and_commit_from_version(new_version)

        apply_changes(repo, new_version, '{"id": "random"}\n', 'manifest.json')
        apply_changes(repo, new_version, 'Updated readme\n', 'README.md')

        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)

        self.url = reverse_ns('reviewers-versions-compare-detail', kwargs={
            'addon_pk': self.addon.pk,
            'version_pk': self.version.pk,
            'pk': new_version.pk})

        response = self.client.get(self.url + '?file=README.md')
        assert response.status_code == 200

        result = json.loads(response.content)

        assert result['file']['diff']['path'] == 'README.md'
        assert result['file']['diff']['hunks'][0]['changes'] == [
            {
                'content': '# beastify',
                'new_line_number': -1,
                'old_line_number': 1,
                'type': 'delete'
            },
            {
                'content': 'Updated readme',
                'new_line_number': 1,
                'old_line_number': -1,
                'type': 'insert'
            }
        ]

    def test_compare_with_deleted_file(self):
        new_version = version_factory(
            addon=self.addon, file_kw={'filename': 'webextension_no_id.xpi'})

        repo = AddonGitRepository.extract_and_commit_from_version(new_version)

        deleted_file = 'README.md'
        apply_changes(repo, new_version, '', deleted_file, delete=True)

        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)

        self.url = reverse_ns('reviewers-versions-compare-detail', kwargs={
            'addon_pk': self.addon.pk,
            'version_pk': self.version.pk,
            'pk': new_version.pk})

        response = self.client.get(self.url + '?file=' + deleted_file)
        assert response.status_code == 200
        result = json.loads(response.content)
        assert result['file']['download_url'] is None

    def test_dont_servererror_on_binary_file(self):
        """Regression test for
        https://github.com/mozilla/addons-server/issues/11712"""
        new_version = version_factory(
            addon=self.addon, file_kw={
                'filename': 'webextension_no_id.xpi',
                'is_webextension': True,
            }
        )

        repo = AddonGitRepository.extract_and_commit_from_version(new_version)
        apply_changes(repo, new_version, EMPTY_PNG, 'foo.png')

        next_version = version_factory(
            addon=self.addon, file_kw={
                'filename': 'webextension_no_id.xpi',
                'is_webextension': True,
            }
        )

        repo = AddonGitRepository.extract_and_commit_from_version(next_version)
        apply_changes(repo, next_version, EMPTY_PNG, 'foo.png')

        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)

        self.url = reverse_ns('reviewers-versions-compare-detail', kwargs={
            'addon_pk': self.addon.pk,
            'version_pk': new_version.pk,
            'pk': next_version.pk})

        response = self.client.get(self.url + '?file=foo.png')
        assert response.status_code == 200
        result = json.loads(response.content)
        assert result['file']['download_url']

    def test_compare_with_deleted_version(self):
        new_version = version_factory(
            addon=self.addon, file_kw={'filename': 'webextension_no_id.xpi'})

        # We need to run extraction first and delete afterwards, otherwise
        # we'll end up with errors because files don't exist anymore.
        AddonGitRepository.extract_and_commit_from_version(new_version)

        new_version.delete()

        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')

        # A reviewer needs the `Addons:ViewDeleted` permission to view and
        # compare deleted versions
        self.grant_permission(user, 'Addons:ViewDeleted')

        self.client.login_api(user)

        self.url = reverse_ns('reviewers-versions-compare-detail', kwargs={
            'addon_pk': self.addon.pk,
            'version_pk': self.version.pk,
            'pk': new_version.pk})

        response = self.client.get(self.url)
        assert response.status_code == 200
        result = json.loads(response.content)
        assert result['file']['download_url']


class TestDownloadGitFileView(TestCase):
    def setUp(self):
        super(TestDownloadGitFileView, self).setUp()

        self.addon = addon_factory(
            name=u'My Addôn', slug='my-addon',
            file_kw={'filename': 'webextension_no_id.xpi'})

        extract_version_to_git(self.addon.current_version.pk)

        self.version = self.addon.current_version
        self.version.refresh_from_db()

    def test_download_basic(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login(email=user.email)

        url = reverse('reviewers.download_git_file', kwargs={
            'version_id': self.version.pk,
            'filename': 'manifest.json'
        })

        response = self.client.get(url)
        assert response.status_code == 200
        assert (
            response['Content-Disposition'] ==
            'attachment; filename="manifest.json"')

        content = response.content.decode('utf-8')
        assert content.startswith('{')
        assert '"manifest_version": 2' in content

    @override_settings(CSP_REPORT_ONLY=False)
    def test_download_respects_csp(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login(email=user.email)

        url = reverse('reviewers.download_git_file', kwargs={
            'version_id': self.version.pk,
            'filename': 'manifest.json'
        })

        response = self.client.get(url)

        assert response.status_code == 200

        # Make sure a default-src is set.
        assert "default-src 'none'" in response['content-security-policy']
        # Make sure things are as locked down as possible,
        # as per https://bugzilla.mozilla.org/show_bug.cgi?id=1566954
        assert "object-src 'none'" in response['content-security-policy']
        assert "base-uri 'none'" in response['content-security-policy']
        assert "form-action 'none'" in response['content-security-policy']
        assert "frame-ancestors 'none'" in response['content-security-policy']

        # The report-uri should be set.
        assert "report-uri" in response['content-security-policy']

        # Other properties that we defined by default aren't set
        assert "style-src" not in response['content-security-policy']
        assert "font-src" not in response['content-security-policy']
        assert "frame-src" not in response['content-security-policy']
        assert "child-src" not in response['content-security-policy']

    def test_download_emoji_filename(self):
        new_version = version_factory(
            addon=self.addon, file_kw={'filename': 'webextension_no_id.xpi'})

        repo = AddonGitRepository.extract_and_commit_from_version(new_version)

        apply_changes(repo, new_version, u'\n', u'😀❤.txt')

        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login(email=user.email)

        url = reverse('reviewers.download_git_file', kwargs={
            'version_id': new_version.pk,
            'filename': u'😀❤.txt'
        })

        response = self.client.get(url)
        assert response.status_code == 200
        assert (
            response['Content-Disposition'] ==
            "attachment; filename*=utf-8''%F0%9F%98%80%E2%9D%A4.txt")

    def test_download_notfound(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login(email=user.email)

        url = reverse('reviewers.download_git_file', kwargs={
            'version_id': self.version.pk,
            'filename': 'doesnotexist.json'
        })

        response = self.client.get(url)
        assert response.status_code == 404

    def _test_url_success(self):
        url = reverse('reviewers.download_git_file', kwargs={
            'version_id': self.version.pk,
            'filename': 'manifest.json'
        })

        response = self.client.get(url)
        assert response.status_code == 200

        content = response.content.decode('utf-8')
        assert content.startswith('{')
        assert '"manifest_version": 2' in content

    def test_disabled_version_reviewer(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login(email=user.email)
        self.version.files.update(status=amo.STATUS_DISABLED)
        self._test_url_success()

    def test_disabled_version_author(self):
        user = UserProfile.objects.create(username='author')
        AddonUser.objects.create(user=user, addon=self.addon)
        self.client.login(email=user.email)
        self.version.files.update(status=amo.STATUS_DISABLED)
        self._test_url_success()

    def test_disabled_version_admin(self):
        user = UserProfile.objects.create(username='admin')
        self.grant_permission(user, '*:*')
        self.client.login(email=user.email)
        self.version.files.update(status=amo.STATUS_DISABLED)
        self._test_url_success()

    def test_disabled_version_user_but_not_author(self):
        user = UserProfile.objects.create(username='simpleuser')
        self.client.login(email=user.email)
        self.version.files.update(status=amo.STATUS_DISABLED)

        url = reverse('reviewers.download_git_file', kwargs={
            'version_id': self.version.pk,
            'filename': 'manifest.json'
        })

        response = self.client.get(url)
        assert response.status_code == 403

    def test_unlisted_version_reviewer(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login(email=user.email)
        self.version.update(channel=amo.RELEASE_CHANNEL_UNLISTED)

        url = reverse('reviewers.download_git_file', kwargs={
            'version_id': self.version.pk,
            'filename': 'manifest.json'
        })

        response = self.client.get(url)
        assert response.status_code == 404

    def test_unlisted_version_unlisted_reviewer(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:ReviewUnlisted')
        self.client.login(email=user.email)
        self.version.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        self._test_url_success()

    def test_unlisted_version_author(self):
        user = UserProfile.objects.create(username='author')
        AddonUser.objects.create(user=user, addon=self.addon)
        self.client.login(email=user.email)
        self.version.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        self._test_url_success()

    def test_unlisted_version_admin(self):
        user = UserProfile.objects.create(username='admin')
        self.grant_permission(user, '*:*')
        self.client.login(email=user.email)
        self.version.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        self._test_url_success()

    def test_unlisted_version_user_but_not_author(self):
        user = UserProfile.objects.create(username='simpleuser')
        self.client.login(email=user.email)
        self.version.update(channel=amo.RELEASE_CHANNEL_UNLISTED)

        url = reverse('reviewers.download_git_file', kwargs={
            'version_id': self.version.pk,
            'filename': 'manifest.json'
        })

        response = self.client.get(url)
        assert response.status_code == 404


class TestCannedResponseViewSet(TestCase):
    client_class = APITestClient

    def setUp(self):
        super(TestCannedResponseViewSet, self).setUp()

        self.canned_response = CannedResponse.objects.create(
            name=u'Terms of services',
            response=u'doesn\'t regard our terms of services',
            category=amo.CANNED_RESPONSE_CATEGORY_OTHER,
            type=amo.CANNED_RESPONSE_TYPE_ADDON)

        self.url = reverse_ns('reviewers-canned-response-list')

    def _test_url(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        result = json.loads(response.content)
        category = self.canned_response.category
        assert result == [{
            'id': self.canned_response.id,
            'title': self.canned_response.name,
            'response': self.canned_response.response,
            'category': amo.CANNED_RESPONSE_CATEGORY_CHOICES[category],
        }]

    def test_anonymous(self):
        response = self.client.get(self.url)
        assert response.status_code == 401

    def test_permissions_reviewer(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)
        self._test_url()

    def test_permissions_authenticated_but_not_reviewer(self):
        user = UserProfile.objects.create(username='reviewer')
        self.client.login_api(user)
        response = self.client.get(self.url)
        assert response.status_code == 403

    def test_admin(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, '*:*')
        self.client.login_api(user)
        self._test_url()

    def test_unlisted_reviewer(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:ReviewUnlisted')
        self.client.login_api(user)
        self._test_url()

    def test_post_reviewer(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:PostReview')
        self.client.login_api(user)
        self._test_url()


class TestThemeBackgroundImages(ReviewBase):

    def setUp(self):
        super(TestThemeBackgroundImages, self).setUp()
        self.url = reverse(
            'reviewers.theme_background_images',
            args=[self.addon.current_version.id])

    def test_not_reviewer(self):
        user_factory(email='irregular@mozilla.com')
        assert self.client.login(email='irregular@mozilla.com')
        response = self.client.post(self.url, follow=True)
        assert response.status_code == 403

    def test_no_header_image(self):
        response = self.client.post(self.url, follow=True)
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data == {}

    def test_header_images(self):
        destination = self.addon.current_version.all_files[0].current_file_path
        zip_file = os.path.join(
            settings.ROOT,
            'src/olympia/devhub/tests/addons/static_theme_tiled.zip')
        copy_stored_file(zip_file, destination)
        response = self.client.post(self.url, follow=True)
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data
        assert len(data.items()) == 3
        assert 'empty.png' in data
        assert len(data['empty.png']) == 444  # base64-encoded size
        assert 'weta_for_tiling.png' in data
        assert len(data['weta_for_tiling.png']) == 124496  # b64-encoded size
        assert 'transparent.gif' in data
        assert len(data['transparent.gif']) == 56  # base64-encoded size
