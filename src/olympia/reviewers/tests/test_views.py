import json
import os
import time

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
from django.urls import reverse
from django.utils.formats import localize

from rest_framework.test import APIRequestFactory

from freezegun import freeze_time
from lxml.html import HTMLParser, fromstring
from pyquery import PyQuery as pq

from olympia import amo, core, ratings
from olympia.abuse.models import AbuseReport
from olympia.access import acl
from olympia.access.models import Group, GroupUser
from olympia.accounts.serializers import BaseUserSerializer
from olympia.activity.models import ActivityLog, DraftComment
from olympia.addons.models import (
    Addon,
    AddonApprovalsCounter,
    AddonReviewerFlags,
    AddonUser,
    DeniedGuid,
)
from olympia.amo.templatetags.jinja_helpers import (
    absolutify,
    format_date,
    format_datetime,
)
from olympia.amo.tests import (
    APITestClientSessionID,
    TestCase,
    addon_factory,
    check_links,
    formset,
    initial,
    reverse_ns,
    user_factory,
    version_factory,
    version_review_flags_factory,
)
from olympia.blocklist.models import Block, BlocklistSubmission
from olympia.blocklist.utils import block_activity_log_save
from olympia.constants.promoted import LINE, RECOMMENDED, SPOTLIGHT, STRATEGIC
from olympia.constants.reviewers import REVIEWER_DELAYED_REJECTION_PERIOD_DAYS_DEFAULT
from olympia.constants.scanners import CUSTOMS, MAD, YARA
from olympia.files.models import FileValidation, WebextPermission
from olympia.git.utils import AddonGitRepository, extract_version_to_git
from olympia.git.tests.test_utils import apply_changes
from olympia.ratings.models import Rating, RatingFlag
from olympia.reviewers.models import (
    AutoApprovalSummary,
    CannedResponse,
    ReviewActionReason,
    ReviewerScore,
    ReviewerSubscription,
    Whiteboard,
)
from olympia.reviewers.templatetags.jinja_helpers import code_manager_url
from olympia.reviewers.views import _queue
from olympia.reviewers.serializers import CannedResponseSerializer
from olympia.scanners.models import ScannerResult, ScannerRule
from olympia.users.models import UserProfile
from olympia.versions.models import (
    ApplicationsVersions,
    AppVersion,
    VersionReviewerFlags,
)
from olympia.zadmin.models import get_config


EMPTY_PNG = (
    b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08'
    b'\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00'
    b'\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
)


class TestRedirectsOldPaths(TestCase):
    def setUp(self):
        user = user_factory()
        self.client.force_login(user)

    def test_redirect_old_queue(self):
        response = self.client.get('/en-US/editors/queue/new')
        self.assert3xx(response, '/reviewers/queue/new', status_code=301)

    def test_redirect_old_review_page(self):
        response = self.client.get('/en-US/editors/review/foobar')
        self.assert3xx(response, '/reviewers/review/foobar', status_code=301)


class ReviewerTest(TestCase):
    fixtures = ['base/users', 'base/approvals']

    def login_as_admin(self):
        self.client.force_login(UserProfile.objects.get(email='admin@mozilla.com'))

    def login_as_reviewer(self):
        self.client.force_login(UserProfile.objects.get(email='reviewer@mozilla.com'))

    def make_review(self, username='a'):
        u = UserProfile.objects.create(username=username)
        a = Addon.objects.create(name='yermom', type=amo.ADDON_EXTENSION)
        return Rating.objects.create(user=u, addon=a, body='baa')


class TestRatingsModerationLog(ReviewerTest):
    def setUp(self):
        super().setUp()
        user = user_factory()
        self.grant_permission(user, 'Ratings:Moderate')
        self.client.force_login(user)
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
        ActivityLog.create(amo.LOG.APPROVE_RATING, review, review.addon).update(
            created=datetime(2011, 1, 1)
        )

        response = self.client.get(self.url, {'end': '2011-01-01'})
        assert response.status_code == 200
        assert pq(response.content)('tbody td').eq(0).text() == localize(
            datetime(2011, 1, 1)
        )

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
            reverse('reviewers.ratings_moderation_log.detail', args=[id_])
        )
        assert response.status_code == 200


class TestReviewLog(ReviewerTest):
    fixtures = ReviewerTest.fixtures + ['base/addon_3615']

    def setUp(self):
        super().setUp()
        self.user = UserProfile.objects.get(email='reviewer@mozilla.com')
        self.login_as_reviewer()
        self.url = reverse('reviewers.reviewlog')

    def get_user(self):
        return UserProfile.objects.all()[0]

    def make_approvals(self):
        for addon in Addon.objects.all():
            ActivityLog.create(
                amo.LOG.REJECT_VERSION,
                addon,
                addon.current_version,
                user=self.get_user(),
                details={'comments': 'youwin'},
            )

    def make_an_approval(self, action, comment='youwin', username=None, addon=None):
        if username:
            user = UserProfile.objects.get(username=username)
        else:
            user = self.get_user()
        if not addon:
            addon = Addon.objects.all()[0]
        ActivityLog.create(
            action,
            addon,
            addon.current_version,
            user=user,
            details={'comments': comment},
        )

    def test_basic(self):
        self.make_approvals()
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#log-filter button'), 'No filters.'
        # Should have 2 showing.
        rows = doc('tbody tr')
        assert rows.filter(':not(.hide)').length == 2
        assert rows.filter('.hide').eq(0).text() == 'youwin'
        # Should have none showing if the addons are unlisted.
        for addon in Addon.objects.all():
            self.make_addon_unlisted(addon)
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert not doc('tbody tr :not(.hide)')

        # But they should have 2 showing for someone with the right perms.
        self.grant_permission(self.user, 'Addons:ReviewUnlisted')
        with self.assertNumQueries(14):
            # 14 queries:
            # - 2 savepoints because of tests
            # - 2 user and its groups
            # - 2 for motd config and site notice
            # - 1 for collections and addons belonging to the user (menu bar)
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
        with self.assertNumQueries(14):
            response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        rows = doc('tbody tr')
        assert rows.filter(':not(.hide)').length == 4

    def test_xss(self):
        a = Addon.objects.all()[0]
        a.name = '<script>alert("xss")</script>'
        a.save()
        ActivityLog.create(
            amo.LOG.REJECT_VERSION,
            a,
            a.current_version,
            user=self.get_user(),
            details={'comments': 'xss!'},
        )

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
                amo.LOG.REJECT_VERSION,
                addon,
                addon.current_version,
                user=self.get_user(),
                details={'comments': 'youwin'},
            )

        # Make sure the default 'start' to the 1st of a month works properly
        with freeze_time('2017-08-03 11:00'):
            response = self.client.get(self.url)
            assert response.status_code == 200

            doc = pq(response.content)('#log-listing tbody')
            assert doc('tr:not(.hide)').length == 1
            assert doc('tr.hide').eq(0).text() == 'youwin'

    def test_search_comment_exists(self):
        """Search by comment."""
        self.make_an_approval(amo.LOG.REQUEST_ADMIN_REVIEW_CODE, comment='hello')
        response = self.client.get(self.url, {'search': 'hello'})
        assert response.status_code == 200
        assert (
            pq(response.content)('#log-listing tbody tr.hide').eq(0).text() == 'hello'
        )

    def test_search_comment_case_exists(self):
        """Search by comment, with case."""
        self.make_an_approval(amo.LOG.REQUEST_ADMIN_REVIEW_CODE, comment='hello')
        response = self.client.get(self.url, {'search': 'HeLlO'})
        assert response.status_code == 200
        assert (
            pq(response.content)('#log-listing tbody tr.hide').eq(0).text() == 'hello'
        )

    def test_search_comment_doesnt_exist(self):
        """Search by comment, with no results."""
        self.make_an_approval(amo.LOG.REQUEST_ADMIN_REVIEW_CODE, comment='hello')
        response = self.client.get(self.url, {'search': 'bye'})
        assert response.status_code == 200
        assert pq(response.content)('.no-results').length == 1

    def test_search_author_exists(self):
        """Search by author."""
        self.make_approvals()
        self.make_an_approval(
            amo.LOG.REQUEST_ADMIN_REVIEW_CODE, username='reviewer', comment='hi'
        )

        response = self.client.get(self.url, {'search': 'reviewer'})
        assert response.status_code == 200
        rows = pq(response.content)('#log-listing tbody tr')

        assert rows.filter(':not(.hide)').length == 1
        assert rows.filter('.hide').eq(0).text() == 'hi'

    def test_search_author_case_exists(self):
        """Search by author, with case."""
        self.make_approvals()
        self.make_an_approval(
            amo.LOG.REQUEST_ADMIN_REVIEW_CODE, username='reviewer', comment='hi'
        )

        response = self.client.get(self.url, {'search': 'ReviEwEr'})
        assert response.status_code == 200
        rows = pq(response.content)('#log-listing tbody tr')

        assert rows.filter(':not(.hide)').length == 1
        assert rows.filter('.hide').eq(0).text() == 'hi'

    def test_search_author_doesnt_exist(self):
        """Search by author, with no results."""
        self.make_approvals()
        self.make_an_approval(amo.LOG.REQUEST_ADMIN_REVIEW_CODE, username='reviewer')

        response = self.client.get(self.url, {'search': 'wrong'})
        assert response.status_code == 200
        assert pq(response.content)('.no-results').length == 1

    def test_search_addon_exists(self):
        """Search by add-on name."""
        self.make_approvals()
        addon = Addon.objects.all()[0]
        response = self.client.get(self.url, {'search': addon.name})
        assert response.status_code == 200
        tr = pq(response.content)('#log-listing tr[data-addonid="%s"]' % addon.id)
        assert tr.length == 1
        assert tr.siblings('.comments').text() == 'youwin'

    def test_search_addon_case_exists(self):
        """Search by add-on name, with case."""
        self.make_approvals()
        addon = Addon.objects.all()[0]
        response = self.client.get(self.url, {'search': str(addon.name).swapcase()})
        assert response.status_code == 200
        tr = pq(response.content)('#log-listing tr[data-addonid="%s"]' % addon.id)
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
            'Add-on has been deleted.'
        )

    def test_super_review_logs(self):
        self.make_an_approval(amo.LOG.REQUEST_ADMIN_REVIEW_CODE)
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert pq(response.content)('#log-listing tr td a').eq(1).text() == (
            'Admin add-on-review requested'
        )

    def test_comment_logs(self):
        self.make_an_approval(amo.LOG.COMMENT_VERSION)
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert pq(response.content)('#log-listing tr td a').eq(1).text() == (
            'Commented'
        )

    def test_content_approval(self):
        self.make_an_approval(amo.LOG.APPROVE_CONTENT)
        response = self.client.get(self.url)
        assert response.status_code == 200
        link = pq(response.content)('#log-listing tbody td a').eq(1)[0]
        assert link.attrib['href'] == '/en-US/reviewers/review-content/3615'
        assert link.text_content().strip() == 'Content approved'

    def test_content_rejection(self):
        self.make_an_approval(amo.LOG.REJECT_CONTENT)
        response = self.client.get(self.url)
        assert response.status_code == 200
        link = pq(response.content)('#log-listing tbody td a').eq(1)[0]
        assert link.attrib['href'] == '/en-US/reviewers/review-content/3615'
        assert link.text_content().strip() == 'Content rejected'

    @freeze_time('2017-08-03')
    def test_review_url(self):
        self.login_as_admin()
        addon = addon_factory()
        unlisted_version = version_factory(addon=addon, channel=amo.CHANNEL_UNLISTED)

        ActivityLog.create(
            amo.LOG.APPROVE_VERSION,
            addon,
            addon.current_version,
            user=self.get_user(),
            details={'comments': 'foo'},
        )

        response = self.client.get(self.url)
        assert response.status_code == 200
        url = reverse('reviewers.review', args=[addon.pk])

        link = pq(response.content)('#log-listing tbody tr[data-addonid] a').eq(1)
        assert link.attr('href') == url

        entry = ActivityLog.create(
            amo.LOG.APPROVE_VERSION,
            addon,
            unlisted_version,
            user=self.get_user(),
            details={'comments': 'foo'},
        )

        # Force the latest entry to be at the top of the list so that we can
        # pick it more reliably later from the HTML
        entry.update(created=datetime.now() + timedelta(days=1))

        response = self.client.get(self.url)
        url = reverse('reviewers.review', args=['unlisted', addon.pk])
        assert pq(response.content)('#log-listing tr td a').eq(1).attr('href') == url

    def test_review_url_force_disable(self):
        self.login_as_reviewer()
        addon = addon_factory()

        ActivityLog.create(
            amo.LOG.FORCE_DISABLE,
            addon,
            user=self.get_user(),
        )

        response = self.client.get(self.url)
        assert response.status_code == 200
        url = reverse('reviewers.review', args=[addon.pk])

        link = pq(response.content)('#log-listing tbody tr[data-addonid] a').eq(1)
        assert link.attr('href') == url

    def test_reviewers_can_only_see_addon_types_they_have_perms_for(self):
        def check_two_showing():
            response = self.client.get(self.url)
            assert response.status_code == 200
            doc = pq(response.content)
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
        for perm in ['Review', 'ContentReview']:
            GroupUser.objects.filter(user=self.user).delete()
            self.grant_permission(self.user, 'Addons:%s' % perm)
            # Should have 2 showing.
            check_two_showing()

        # Should have none showing if the addons are static themes.
        for addon in Addon.objects.all():
            addon.update(type=amo.ADDON_STATICTHEME)
        for perm in ['Review', 'ContentReview']:
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
        self.client.force_login(self.user)

    def test_old_temporary_url_redirect(self):
        response = self.client.get('/en-US/reviewers/dashboard')
        self.assert3xx(response, reverse('reviewers.dashboard'), status_code=301)

    def test_not_a_reviewer(self):
        response = self.client.get(self.url)
        assert response.status_code == 403

    def test_admin_all_permissions(self):
        # Create a lot of add-ons to test the queue counts.
        # Recommended extensions
        addon_factory(
            promoted=RECOMMENDED,
            status=amo.STATUS_NOMINATED,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        version_factory(
            addon=addon_factory(
                promoted=RECOMMENDED, version_kw={'promotion_approved': False}
            ),
            promotion_approved=True,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        # Nominated and pending themes, not being counted
        # as per https://github.com/mozilla/addons-server/issues/11796
        addon_factory(
            status=amo.STATUS_NOMINATED,
            type=amo.ADDON_STATICTHEME,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        version_factory(
            addon=addon_factory(type=amo.ADDON_STATICTHEME),
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        # Nominated and pending extensions.
        AddonReviewerFlags.objects.create(
            auto_approval_disabled=True,
            addon=version_factory(
                addon=addon_factory(), file_kw={'status': amo.STATUS_AWAITING_REVIEW}
            ).addon,
        )
        AddonReviewerFlags.objects.create(
            needs_admin_code_review=True,
            auto_approval_disabled=True,
            addon=addon_factory(
                status=amo.STATUS_NOMINATED,
                file_kw={'status': amo.STATUS_AWAITING_REVIEW},
            ),
        )
        under_admin_review_and_pending = addon_factory()
        AddonReviewerFlags.objects.create(
            addon=under_admin_review_and_pending,
            needs_admin_theme_review=True,
            auto_approval_disabled=True,
        )
        version_factory(
            addon=under_admin_review_and_pending,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        # Auto-approved and Content Review.
        addon1 = addon_factory()
        AddonApprovalsCounter.reset_for_addon(addon=addon1)
        AutoApprovalSummary.objects.create(
            version=addon1.current_version, verdict=amo.AUTO_APPROVED
        )
        under_content_review = addon_factory()
        AddonApprovalsCounter.reset_for_addon(addon=under_content_review)
        AutoApprovalSummary.objects.create(
            version=under_content_review.current_version, verdict=amo.AUTO_APPROVED
        )
        AddonReviewerFlags.objects.create(
            addon=under_content_review, needs_admin_content_review=True
        )
        addon2 = addon_factory()
        AddonApprovalsCounter.reset_for_addon(addon=addon2)
        AutoApprovalSummary.objects.create(
            version=addon2.current_version, verdict=amo.AUTO_APPROVED
        )
        AddonReviewerFlags.objects.create(addon=addon2, needs_admin_content_review=True)
        under_code_review = addon_factory()
        AddonApprovalsCounter.reset_for_addon(addon=under_code_review)
        AutoApprovalSummary.objects.create(
            version=under_code_review.current_version, verdict=amo.AUTO_APPROVED
        )
        AddonReviewerFlags.objects.create(
            addon=under_code_review, needs_admin_code_review=True
        )
        admins_group = Group.objects.create(name='Admins', rules='*:*')
        GroupUser.objects.create(user=self.user, group=admins_group)

        # Pending addon
        addon_factory(name='Pending Addön', status=amo.STATUS_NOMINATED)

        # Public addon
        addon = addon_factory(name='Public Addön', status=amo.STATUS_APPROVED)

        # Deleted addon
        addon_factory(name='Deleted Addön', status=amo.STATUS_DELETED)

        # Mozilla-disabled addon
        addon_factory(name='Disabled Addön', status=amo.STATUS_DISABLED)

        # Incomplete addon
        addon_factory(name='Incomplete Addön', status=amo.STATUS_NULL)

        # Invisible (user-disabled) addon
        addon_factory(
            name='Invisible Addön', status=amo.STATUS_APPROVED, disabled_by_user=True
        )

        pending_rejection = addon_factory(name='Pending Rejection Addôn')
        version_review_flags_factory(
            version=pending_rejection.current_version,
            pending_rejection=datetime.now() + timedelta(days=4),
        )

        # Rating
        rating = Rating.objects.create(
            addon=addon,
            version=addon.current_version,
            user=self.user,
            flag=True,
            body='This âdd-on sucks!!111',
            rating=1,
            editorreview=True,
        )
        rating.ratingflag_set.create()

        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert len(doc('.dashboard h3')) == 9  # All sections are present.
        expected_links = [
            reverse('reviewers.queue_recommended'),
            reverse('reviewers.queue_extension'),
            reverse('reviewers.reviewlog'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Guide',
            reverse('reviewers.queue_scanners'),
            reverse('reviewers.queue_mad'),
            reverse('reviewers.queue_auto_approved'),
            reverse('reviewers.reviewlog'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Guide',
            reverse('reviewers.queue_content_review'),
            reverse('reviewers.queue_theme_nominated'),
            reverse('reviewers.queue_theme_pending'),
            reverse('reviewers.reviewlog'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Themes/Guidelines',
            reverse('reviewers.queue_moderated'),
            reverse('reviewers.ratings_moderation_log'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Guide/Moderation',
            reverse('reviewers.unlisted_queue_all'),
            reverse('reviewers.unlisted_queue_pending_manual_approval'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Guide',
            reverse('reviewers.motd'),
            reverse('reviewers.queue_pending_rejection'),
        ]
        links = [link.attrib['href'] for link in doc('.dashboard a')]
        assert links == expected_links
        # pre-approval addons
        assert doc('.dashboard a')[0].text == 'Recommended (2)'
        assert doc('.dashboard a')[1].text == 'Other Pending Review (3)'
        # auto-approved addons
        assert doc('.dashboard a')[6].text == 'Auto Approved Add-ons (4)'
        # content review
        assert doc('.dashboard a')[9].text == 'Content Review (11)'
        # themes
        assert doc('.dashboard a')[10].text == 'New (1)'
        assert doc('.dashboard a')[11].text == 'Updates (1)'
        # user ratings moderation
        assert doc('.dashboard a')[14].text == 'Ratings Awaiting Moderation (1)'
        # admin tools
        assert doc('.dashboard a')[21].text == 'Add-ons Pending Rejection (1)'

    def test_can_see_all_through_reviewer_view_all_permission(self):
        self.grant_permission(self.user, 'ReviewerTools:View')
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert len(doc('.dashboard h3')) == 9  # All sections are present.
        expected_links = [
            reverse('reviewers.queue_recommended'),
            reverse('reviewers.queue_extension'),
            reverse('reviewers.reviewlog'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Guide',
            reverse('reviewers.queue_scanners'),
            reverse('reviewers.queue_mad'),
            reverse('reviewers.queue_auto_approved'),
            reverse('reviewers.reviewlog'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Guide',
            reverse('reviewers.queue_content_review'),
            reverse('reviewers.queue_theme_nominated'),
            reverse('reviewers.queue_theme_pending'),
            reverse('reviewers.reviewlog'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Themes/Guidelines',
            reverse('reviewers.queue_moderated'),
            reverse('reviewers.ratings_moderation_log'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Guide/Moderation',
            reverse('reviewers.unlisted_queue_all'),
            reverse('reviewers.unlisted_queue_pending_manual_approval'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Guide',
            reverse('reviewers.motd'),
            reverse('reviewers.queue_pending_rejection'),
        ]
        links = [link.attrib['href'] for link in doc('.dashboard a')]
        assert links == expected_links

    def test_regular_reviewer(self):
        # Create some add-ons to test the queue counts.
        AddonReviewerFlags.objects.create(
            auto_approval_disabled=True,
            addon=addon_factory(
                status=amo.STATUS_NOMINATED,
                file_kw={'status': amo.STATUS_AWAITING_REVIEW},
            ),
        )
        AddonReviewerFlags.objects.create(
            auto_approval_disabled=True,
            addon=version_factory(
                addon=addon_factory(), file_kw={'status': amo.STATUS_AWAITING_REVIEW}
            ).addon,
        )
        AddonReviewerFlags.objects.create(
            auto_approval_disabled=True,
            addon=version_factory(
                addon=addon_factory(), file_kw={'status': amo.STATUS_AWAITING_REVIEW}
            ).addon,
        )
        # These two are under admin review and will be ignored.
        under_admin_review = addon_factory(
            status=amo.STATUS_NOMINATED, file_kw={'status': amo.STATUS_AWAITING_REVIEW}
        )
        AddonReviewerFlags.objects.create(
            addon=under_admin_review, needs_admin_code_review=True
        )
        under_admin_review_and_pending = addon_factory()
        AddonReviewerFlags.objects.create(
            addon=under_admin_review_and_pending, needs_admin_code_review=True
        )
        version_factory(
            addon=under_admin_review_and_pending,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        # This is a static theme so won't be shown
        addon_factory(
            status=amo.STATUS_NOMINATED,
            type=amo.ADDON_STATICTHEME,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        # Create an add-on to test the post-review queue count.
        # It's under admin content review but that does not have an impact.
        addon = addon_factory()
        AddonApprovalsCounter.reset_for_addon(addon=addon)
        AutoApprovalSummary.objects.create(
            version=addon.current_version, verdict=amo.AUTO_APPROVED
        )
        AddonReviewerFlags.objects.create(addon=addon, needs_admin_content_review=True)
        # This one however is under admin code review, it's ignored.
        under_code_review = addon_factory()
        AddonApprovalsCounter.reset_for_addon(addon=under_code_review)
        AutoApprovalSummary.objects.create(
            version=under_code_review.current_version, verdict=amo.AUTO_APPROVED
        )
        AddonReviewerFlags.objects.create(
            addon=under_code_review, needs_admin_code_review=True
        )

        # Grant user the permission to see only the legacy/post add-ons section
        self.grant_permission(self.user, 'Addons:Review')

        # Test.
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert len(doc('.dashboard h3')) == 3
        expected_links = [
            reverse('reviewers.queue_extension'),
            reverse('reviewers.reviewlog'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Guide',
            reverse('reviewers.queue_scanners'),
            reverse('reviewers.queue_mad'),
            reverse('reviewers.queue_auto_approved'),
            reverse('reviewers.reviewlog'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Guide',
        ]
        links = [link.attrib['href'] for link in doc('.dashboard a')]
        assert links == expected_links
        assert doc('.dashboard a')[0].text == 'Other Pending Review (3)'
        assert doc('.dashboard a')[5].text == 'Auto Approved Add-ons (1)'

    def test_content_reviewer(self):
        # Create an add-on to test the queue count. It's under admin code
        # review but that does not have an impact.
        addon = addon_factory()
        AddonApprovalsCounter.reset_for_addon(addon=addon)
        AutoApprovalSummary.objects.create(
            version=addon.current_version, verdict=amo.AUTO_APPROVED
        )
        AddonReviewerFlags.objects.create(addon=addon, needs_admin_code_review=True)
        # This one is under admin *content* review so it's ignored.
        under_content_review = addon_factory()
        AddonApprovalsCounter.reset_for_addon(addon=under_content_review)
        AutoApprovalSummary.objects.create(
            version=under_content_review.current_version, verdict=amo.AUTO_APPROVED
        )
        AddonReviewerFlags.objects.create(
            addon=under_content_review, needs_admin_content_review=True
        )

        # Grant user the permission to see only the Content Review section.
        self.grant_permission(self.user, 'Addons:ContentReview')

        # Test.
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert len(doc('.dashboard h3')) == 1
        expected_links = [
            reverse('reviewers.queue_content_review'),
        ]
        links = [link.attrib['href'] for link in doc('.dashboard a')]
        assert links == expected_links
        assert doc('.dashboard a')[0].text == 'Content Review (1)'

    def test_ratings_moderator(self):
        # Create an rating to test the queue count.
        addon = addon_factory()
        user = user_factory()
        rating = Rating.objects.create(
            addon=addon,
            version=addon.current_version,
            user=user,
            flag=True,
            body='This âdd-on sucks!!111',
            rating=1,
            editorreview=True,
        )
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
            reverse('reviewers.unlisted_queue_pending_manual_approval'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Guide',
        ]
        links = [link.attrib['href'] for link in doc('.dashboard a')]
        assert links == expected_links

    def test_unlisted_viewer(self):
        # Grant user the permission read-only unlisted access.
        self.grant_permission(self.user, 'ReviewerTools:ViewUnlisted')

        # Test.
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert len(doc('.dashboard h3')) == 9
        expected_links = [
            reverse('reviewers.unlisted_queue_all'),
            reverse('reviewers.unlisted_queue_pending_manual_approval'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Guide',
        ]
        links = [link.attrib['href'] for link in doc('.dashboard a')]
        assert (expected_link in links for expected_link in expected_links)

    def test_static_theme_reviewer(self):
        # Create some static themes to test the queue counts.
        addon_factory(
            status=amo.STATUS_NOMINATED,
            type=amo.ADDON_STATICTHEME,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        version_factory(
            addon=addon_factory(type=amo.ADDON_STATICTHEME),
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        version_factory(
            addon=addon_factory(
                type=amo.ADDON_STATICTHEME,
            ),
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        # These two are under admin review and will be ignored.
        under_admin_review = addon_factory(
            status=amo.STATUS_NOMINATED,
            type=amo.ADDON_STATICTHEME,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        AddonReviewerFlags.objects.create(
            addon=under_admin_review, needs_admin_theme_review=True
        )
        under_admin_review_and_pending = addon_factory(type=amo.ADDON_STATICTHEME)
        AddonReviewerFlags.objects.create(
            addon=under_admin_review_and_pending, needs_admin_theme_review=True
        )
        version_factory(
            addon=under_admin_review_and_pending,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        # This is an extension so won't be shown
        addon_factory(
            status=amo.STATUS_NOMINATED,
            type=amo.ADDON_EXTENSION,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )

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
            reverse('reviewers.reviewlog'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Themes/Guidelines',
        ]
        links = [link.attrib['href'] for link in doc('.dashboard a')]
        assert links == expected_links
        assert doc('.dashboard a')[0].text == 'New (1)'
        assert doc('.dashboard a')[1].text == 'Updates (2)'

    def test_legacy_reviewer_and_ratings_moderator(self):
        # Grant user the permission to see both the legacy add-ons and the
        # ratings moderation sections.
        self.grant_permission(self.user, 'Addons:Review')
        self.grant_permission(self.user, 'Ratings:Moderate')

        # Test.
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert len(doc('.dashboard h3')) == 4
        expected_links = [
            reverse('reviewers.queue_extension'),
            reverse('reviewers.reviewlog'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Guide',
            reverse('reviewers.queue_scanners'),
            reverse('reviewers.queue_mad'),
            reverse('reviewers.queue_auto_approved'),
            reverse('reviewers.reviewlog'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Guide',
            reverse('reviewers.queue_moderated'),
            reverse('reviewers.ratings_moderation_log'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Guide/Moderation',
        ]
        links = [link.attrib['href'] for link in doc('.dashboard a')]
        assert links == expected_links
        assert doc('.dashboard a')[0].text == 'Other Pending Review (0)'
        assert 'target' not in doc('.dashboard a')[0].attrib
        assert doc('.dashboard a')[8].text == ('Ratings Awaiting Moderation (0)')
        assert 'target' not in doc('.dashboard a')[5].attrib
        assert doc('.dashboard a')[10].text == 'Moderation Guide'
        assert doc('.dashboard a')[10].attrib['target'] == '_blank'
        assert doc('.dashboard a')[10].attrib['rel'] == 'noopener noreferrer'

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
        super().setUp()
        self.user = UserProfile.objects.get(email='reviewer@mozilla.com')
        self.login_as_reviewer()
        if self.listed is False:
            # Testing unlisted views: needs Addons:ReviewUnlisted perm.
            self.grant_permission(self.user, 'Addons:ReviewUnlisted')
        self.url = reverse('reviewers.queue_extension')
        self.addons = OrderedDict()
        self.expected_addons = []
        self.channel_name = 'listed' if self.listed else 'unlisted'

    def generate_files(self, subset=None, files=None, auto_approve_disabled=False):
        if subset is None:
            subset = []
        channel = amo.CHANNEL_LISTED if self.listed else amo.CHANNEL_UNLISTED
        files = files or OrderedDict(
            [
                (
                    'Nominated One',
                    {
                        'file_kw': {
                            'status': amo.STATUS_AWAITING_REVIEW,
                        },
                        'version_kw': {
                            'created': self.days_ago(5),
                            'nomination': self.days_ago(5),
                            'version': '0.1',
                        },
                        'status': amo.STATUS_NOMINATED,
                    },
                ),
                (
                    'Nominated Two',
                    {
                        'file_kw': {
                            'status': amo.STATUS_AWAITING_REVIEW,
                        },
                        'version_kw': {
                            'created': self.days_ago(4),
                            'nomination': self.days_ago(4),
                            'version': '0.1',
                        },
                        'status': amo.STATUS_NOMINATED,
                    },
                ),
                (
                    'Pending One',
                    {
                        'file_kw': {
                            'status': amo.STATUS_AWAITING_REVIEW,
                        },
                        'version_kw': {
                            'created': self.days_ago(3),
                            'nomination': self.days_ago(3),
                            'version': '0.1',
                        },
                        'status': amo.STATUS_APPROVED,
                    },
                ),
                (
                    'Pending Two',
                    {
                        'file_kw': {
                            'status': amo.STATUS_AWAITING_REVIEW,
                        },
                        'version_kw': {
                            'created': self.days_ago(2),
                            'nomination': self.days_ago(2),
                            'version': '0.1',
                        },
                        'status': amo.STATUS_APPROVED,
                    },
                ),
                (
                    'Public',
                    {
                        'file_kw': {
                            'status': amo.STATUS_APPROVED,
                        },
                        'version_kw': {
                            'created': self.days_ago(1),
                            'nomination': self.days_ago(1),
                            'version': '0.1',
                        },
                        'status': amo.STATUS_APPROVED,
                    },
                ),
            ]
        )
        results = OrderedDict()
        for name, attrs in files.items():
            if not subset or name in subset:
                version_kw = attrs.pop('version_kw', {})
                version_kw['channel'] = channel
                file_kw = attrs.pop('file_kw', {})
                results[name] = addon_factory(
                    name=name, version_kw=version_kw, file_kw=file_kw, **attrs
                )
                if auto_approve_disabled:
                    AddonReviewerFlags.objects.create(
                        addon=results[name],
                        auto_approval_disabled=True,
                    )
                # status might be wrong because we want to force a particular
                # status without necessarily having the requirements for it.
                # So update it if we didn't end up with the one we want.
                if 'status' in attrs and results[name].status != attrs['status']:
                    results[name].update(status=attrs['status'])
        self.addons.update(results)
        return results

    def generate_file(self, name):
        return self.generate_files([name])[name]

    def get_review_data(self):
        # Format: (Created n days ago,
        #          percentages of [< 5, 5-10, >10])
        return ((1, (0, 0, 100)), (8, (0, 50, 50)), (12, (50, 0, 50)))

    def get_addon_latest_version(self, addon):
        if self.listed:
            channel = amo.CHANNEL_LISTED
        else:
            channel = amo.CHANNEL_UNLISTED
        return addon.find_latest_version(channel=channel)

    def get_expected_addons_by_names(self, names, auto_approve_disabled=False):
        expected_addons = []
        files = self.generate_files(auto_approve_disabled=auto_approve_disabled)
        for name in sorted(names):
            if name in files:
                expected_addons.append(files[name])
        # Make sure all elements have been added
        assert len(expected_addons) == len(names)
        return expected_addons

    def _test_queue_layout(
        self, name, tab_position, total_addons, total_queues, per_page=None
    ):
        args = {'per_page': per_page} if per_page else {}
        response = self.client.get(self.url, args)
        assert response.status_code == 200
        doc = pq(response.content)
        links = doc('.tabnav li a')
        link = links.eq(tab_position)

        assert links.length == total_queues
        assert link.text() == '%s' % name
        assert link.attr('href') == self.url
        if per_page:
            assert doc('.data-grid-top .num-results').text() == (
                f'Results {per_page}\u20131 of {total_addons}'
            )

    def _test_results(self, dont_expect_version_number=False):
        response = self.client.get(self.url)
        assert response.status_code == 200
        expected = []
        if not len(self.expected_addons):
            raise AssertionError('self.expected_addons was an empty list')
        # We typically don't include the channel name if it's the
        # default one, 'listed'.
        channel = [] if self.channel_name == 'listed' else [self.channel_name]
        for idx, addon in enumerate(self.expected_addons):
            if self.channel_name == 'unlisted' or dont_expect_version_number:
                # In unlisted queue we don't display latest version number.
                name = str(addon.name)
            else:
                latest_version = self.get_addon_latest_version(addon)
                assert latest_version
                name = f'{str(addon.name)} {latest_version.version}'
            url = reverse('reviewers.review', args=channel + [addon.pk])
            expected.append((name, url))
        doc = pq(response.content)
        rows = doc('#addon-queue tr.addon-row')
        assert len(rows) == len(self.expected_addons)
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
        self.client.force_login(UserProfile.objects.get(email='regular@mozilla.com'))
        response = self.client.get(self.url)
        assert response.status_code == 403

        # Theme reviewer doesn't have access either.
        self.client.logout()
        self.client.force_login(
            UserProfile.objects.get(email='theme_reviewer@mozilla.com')
        )
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

    @mock.patch.multiple(
        'olympia.reviewers.views', REVIEWS_PER_PAGE_MAX=1, REVIEWS_PER_PAGE=1
    )
    def test_max_per_page(self):
        self.generate_files(auto_approve_disabled=True)

        response = self.client.get(self.url, {'per_page': '2'})
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('.data-grid-top .num-results').text() == ('Results 1\u20131 of 4')

    @mock.patch('olympia.reviewers.views.REVIEWS_PER_PAGE', new=1)
    def test_reviews_per_page(self):
        self.generate_files(auto_approve_disabled=True)

        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('.data-grid-top .num-results').text() == ('Results 1\u20131 of 4')

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
        assert [pq(th).text() for th in doc('#addon-queue tr th')[1:]] == (expected)

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
        self.generate_files(auto_approve_disabled=True)

        response = self.client.get(self.url, {'per_page': 1})
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('.data-grid-top .num-results').text() == ('Results 1\u20131 of 4')
        assert doc('.data-grid-bottom .num-results').text() == ('Results 1\u20131 of 4')

    def test_flags_promoted(self):
        addon = addon_factory(name='Firefox Fún')
        version_factory(
            addon=addon, version='1.1', file_kw={'status': amo.STATUS_AWAITING_REVIEW}
        )
        self.make_addon_promoted(addon, LINE)

        r = self.client.get(reverse('reviewers.queue_extension'))

        rows = pq(r.content)('#addon-queue tr.addon-row')
        assert rows.length == 1
        assert rows.attr('data-addon') == str(addon.id)
        assert rows.find('td').eq(1).text() == 'Firefox Fún 1.1'
        assert rows.find('.ed-sprite-promoted-line').length == 1

    def test_tabnav_permissions(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        links = doc('.tabnav li a').map(lambda i, e: e.attrib['href'])
        expected = [
            reverse('reviewers.queue_extension'),
            reverse('reviewers.queue_scanners'),
            reverse('reviewers.queue_mad'),
            reverse('reviewers.queue_auto_approved'),
        ]
        assert links == expected

        self.grant_permission(self.user, 'Ratings:Moderate')
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        links = doc('.tabnav li a').map(lambda i, e: e.attrib['href'])
        expected = [
            reverse('reviewers.queue_extension'),
            reverse('reviewers.queue_scanners'),
            reverse('reviewers.queue_mad'),
            reverse('reviewers.queue_moderated'),
            reverse('reviewers.queue_auto_approved'),
        ]
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
        expected.extend(
            [
                reverse('reviewers.queue_pending_rejection'),
            ]
        )
        assert links == expected

    @override_settings(DEBUG=True, LESS_PREPROCESS=False)
    def test_queue_is_never_executing_the_full_query(self):
        """Test that _queue() is paginating without accidentally executing the
        full query."""
        self.grant_permission(self.user, 'Addons:ContentReview')
        request = RequestFactory().get('/')
        request.user = self.user

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

        reset_queries()
        response = _queue(request, 'content_review')
        response.render()
        assert connection.queries
        assert full_query not in [item['sql'] for item in connection.queries]
        assert response.status_code == 200
        doc = pq(response.content)
        assert len(doc('#addon-queue tr.addon-row')) == qs.count()

        request = RequestFactory().get('/', {'per_page': 2})
        request.user = self.user
        reset_queries()
        response = _queue(request, 'content_review')
        response.render()
        assert connection.queries
        assert full_query not in [item['sql'] for item in connection.queries]
        assert response.status_code == 200
        doc = pq(response.content)
        assert len(doc('#addon-queue tr.addon-row')) == 2

        request = RequestFactory().get('/', {'per_page': 2, 'page': 2})
        request.user = self.user
        reset_queries()
        response = _queue(request, 'content_review')
        response.render()
        assert connection.queries
        assert full_query not in [item['sql'] for item in connection.queries]
        assert response.status_code == 200
        doc = pq(response.content)
        assert len(doc('#addon-queue tr.addon-row')) == 2


class TestThemePendingQueue(QueueTest):
    def setUp(self):
        super().setUp()
        # These should be the only ones present.
        self.expected_addons = self.get_expected_addons_by_names(
            ['Pending One', 'Pending Two']
        )
        Addon.objects.all().update(type=amo.ADDON_STATICTHEME)
        self.url = reverse('reviewers.queue_theme_pending')
        GroupUser.objects.filter(user=self.user).delete()
        self.grant_permission(self.user, 'Addons:ThemeReview')

    def test_results(self):
        self._test_results()

    def test_queue_layout(self):
        self._test_queue_layout(
            '🎨 Updates', tab_position=1, total_addons=2, total_queues=2
        )

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
        self.get_expected_addons_by_names(
            ['Pending One', 'Pending Two', 'Nominated One', 'Nominated Two']
        )
        self.expected_addons = []
        self.url = reverse('reviewers.queue_extension')

    def test_results(self):
        self.expected_addons = self.get_expected_addons_by_names(
            ['Pending One', 'Pending Two', 'Nominated One', 'Nominated Two'],
            auto_approve_disabled=True,
        )
        self._test_results()

    def test_results_two_versions(self):
        self.expected_addons = self.get_expected_addons_by_names(
            ['Pending One', 'Pending Two', 'Nominated One', 'Nominated Two'],
            auto_approve_disabled=True,
        )
        version1 = self.addons['Nominated One'].versions.all()[0]
        version2 = self.addons['Nominated Two'].versions.all()[0]
        file_ = version2.file

        # Create another version for Nominated Two, v0.2, by "cloning" v0.1.
        # Its creation date must be more recent than v0.1 for version ordering
        # to work. Its nomination date must be coherent with that, but also
        # not cause the queue order to change with respect to the other
        # add-ons.
        version2.created = version2.created + timedelta(minutes=1)
        version2.nomination = version2.nomination + timedelta(minutes=1)
        version2.pk = None
        version2.version = '0.2'
        version2.save()

        # Associate v0.2 it with a file.
        file_.pk = None
        file_.version = version2
        file_.save()

        # disable old files like Version.from_upload() would.
        version2.disable_old_files()

        response = self.client.get(self.url)
        assert response.status_code == 200
        expected = [
            (
                'Nominated One 0.1',
                reverse('reviewers.review', args=[version1.addon.pk]),
            ),
            (
                'Nominated Two 0.2',
                reverse('reviewers.review', args=[version2.addon.pk]),
            ),
        ]
        doc = pq(response.content)
        check_links(
            expected, doc('#addon-queue tr.addon-row td a:not(.app-icon)'), verify=False
        )

    def test_queue_layout(self):
        self._test_queue_layout(
            '🛠️ Other Pending Review', tab_position=0, total_addons=4, total_queues=4
        )

    def test_webextension_with_auto_approval_disabled_false_filtered_out(self):
        AddonReviewerFlags.objects.create(
            addon=self.addons['Pending Two'], auto_approval_disabled=False
        )
        AddonReviewerFlags.objects.create(
            addon=self.addons['Nominated Two'],
            auto_approval_disabled_until_next_approval=False,
        )

        AddonReviewerFlags.objects.create(
            addon=self.addons['Nominated One'], auto_approval_disabled=True
        )
        AddonReviewerFlags.objects.create(
            addon=self.addons['Pending One'], auto_approval_disabled=True
        )

        self.expected_addons = [
            self.addons['Nominated One'],
            self.addons['Pending One'],
        ]
        self._test_results()

    def test_webextension_with_auto_approval_disabled_does_show_up(self):
        AddonReviewerFlags.objects.create(
            addon=self.addons['Pending One'], auto_approval_disabled=True
        )
        AddonReviewerFlags.objects.create(
            addon=self.addons['Nominated One'],
            auto_approval_disabled_until_next_approval=True,
        )

        self.expected_addons = [
            self.addons['Nominated One'],
            self.addons['Pending One'],
        ]
        self._test_results()

    def test_webextension_with_auto_approval_delayed(self):
        AddonReviewerFlags.objects.create(
            addon=self.addons['Pending One'],
            auto_approval_delayed_until=datetime.now() + timedelta(hours=24),
        )
        AddonReviewerFlags.objects.create(
            addon=self.addons['Nominated One'],
            auto_approval_delayed_until=datetime.now() + timedelta(hours=24),
        )
        AddonReviewerFlags.objects.create(
            addon=self.addons['Pending Two'],
            auto_approval_delayed_until=datetime.now() - timedelta(hours=24),
        )
        AddonReviewerFlags.objects.create(
            addon=self.addons['Nominated Two'],
            auto_approval_delayed_until=datetime.now() - timedelta(hours=24),
        )

        self.expected_addons = [
            self.addons['Nominated One'],
            self.addons['Pending One'],
        ]
        self._test_results()

    def test_promoted_addon_in_pre_review_group_does_show_up(self):
        self.make_addon_promoted(self.addons['Pending One'], group=LINE)
        self.make_addon_promoted(self.addons['Nominated One'], group=SPOTLIGHT)
        # STRATEGIC isn't a pre_review group so won't show up
        self.make_addon_promoted(self.addons['Nominated Two'], group=STRATEGIC)
        # RECOMMENDED is pre_review, but is handled in it's own queue
        self.make_addon_promoted(self.addons['Pending Two'], group=RECOMMENDED)

        self.expected_addons = [
            self.addons['Nominated One'],
            self.addons['Pending One'],
        ]
        self._test_results()

    def test_static_theme_filtered_out(self):
        for addon in self.addons.values():
            AddonReviewerFlags.objects.create(addon=addon, auto_approval_disabled=True)
        self.addons['Pending Two'].update(type=amo.ADDON_STATICTHEME)
        self.addons['Nominated Two'].update(type=amo.ADDON_STATICTHEME)

        # Static Theme shouldn't be shown
        self.expected_addons = [
            self.addons['Nominated One'],
            self.addons['Pending One'],
        ]
        self._test_results()

        # Even if you have that permission also
        self.grant_permission(self.user, 'Addons:ThemeReview')
        self._test_results()

    def test_pending_rejection_filtered_out(self):
        for addon in self.addons.values():
            AddonReviewerFlags.objects.create(addon=addon, auto_approval_disabled=True)
        version_review_flags_factory(
            version=self.addons['Nominated Two'].current_version,
            pending_rejection=datetime.now(),
        )
        version_review_flags_factory(
            version=self.addons['Pending Two'].current_version,
            pending_rejection=datetime.now(),
        )
        self.expected_addons = [
            self.addons['Nominated One'],
            self.addons['Pending One'],
        ]
        self._test_results()


class TestThemeNominatedQueue(QueueTest):
    def setUp(self):
        super().setUp()
        # These should be the only ones present.
        self.expected_addons = self.get_expected_addons_by_names(
            ['Nominated One', 'Nominated Two']
        )
        Addon.objects.all().update(type=amo.ADDON_STATICTHEME)
        self.url = reverse('reviewers.queue_theme_nominated')
        GroupUser.objects.filter(user=self.user).delete()
        self.grant_permission(self.user, 'Addons:ThemeReview')

    def test_results(self):
        self._test_results()

    def test_results_two_versions(self):
        version1 = self.addons['Nominated One'].versions.all()[0]
        version2 = self.addons['Nominated Two'].versions.all()[0]
        file_ = version2.file

        # Create another version for Nominated Two, v0.2, by "cloning" v0.1.
        # Its creation date must be more recent than v0.1 for version ordering
        # to work. Its nomination date must be coherent with that, but also
        # not cause the queue order to change with respect to the other
        # add-ons.
        version2.created = version2.created + timedelta(minutes=1)
        version2.nomination = version2.nomination + timedelta(minutes=1)
        version2.pk = None
        version2.version = '0.2'
        version2.save()

        # Associate v0.2 it with a file.
        file_.pk = None
        file_.version = version2
        file_.save()

        # disable old files like Version.from_upload() would.
        version2.disable_old_files()

        response = self.client.get(self.url)
        assert response.status_code == 200
        expected = [
            (
                'Nominated One 0.1',
                reverse('reviewers.review', args=[version1.addon.pk]),
            ),
            (
                'Nominated Two 0.2',
                reverse('reviewers.review', args=[version2.addon.pk]),
            ),
        ]
        doc = pq(response.content)
        check_links(
            expected, doc('#addon-queue tr.addon-row td a:not(.app-icon)'), verify=False
        )

    def test_queue_layout(self):
        self._test_queue_layout('🎨 New', tab_position=0, total_addons=2, total_queues=2)

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
            ['Pending One', 'Pending Two', 'Nominated One', 'Nominated Two']
        )
        for addon in self.expected_addons:
            self.make_addon_promoted(addon, RECOMMENDED)
        self.url = reverse('reviewers.queue_recommended')

    def test_results(self):
        self._test_results()

    def test_results_two_versions(self):
        version1 = self.addons['Nominated One'].versions.all()[0]
        version2 = self.addons['Nominated Two'].versions.all()[0]
        file_ = version2.file

        # Create another version for Nominated Two, v0.2, by "cloning" v0.1.
        # Its creation date must be more recent than v0.1 for version ordering
        # to work. Its nomination date must be coherent with that, but also
        # not cause the queue order to change with respect to the other
        # add-ons.
        version2.created = version2.created + timedelta(minutes=1)
        version2.nomination = version2.nomination + timedelta(minutes=1)
        version2.pk = None
        version2.version = '0.2'
        version2.save()

        # Associate v0.2 it with a file.
        file_.pk = None
        file_.version = version2
        file_.save()

        # disable old files like Version.from_upload() would.
        version2.disable_old_files()

        response = self.client.get(self.url)
        assert response.status_code == 200
        expected = [
            (
                'Nominated One 0.1',
                reverse('reviewers.review', args=[version1.addon.pk]),
            ),
            (
                'Nominated Two 0.2',
                reverse('reviewers.review', args=[version2.addon.pk]),
            ),
        ]
        doc = pq(response.content)
        check_links(
            expected, doc('#addon-queue tr.addon-row td a:not(.app-icon)'), verify=False
        )

    def test_queue_layout(self):
        self._test_queue_layout(
            'Recommended', tab_position=0, total_addons=4, total_queues=5
        )

    def test_nothing_recommended_filtered_out(self):
        AddonReviewerFlags.objects.create(
            addon=self.addons['Pending Two'], auto_approval_disabled=False
        )

        self._test_results()


class TestModeratedQueue(QueueTest):
    fixtures = ['base/users', 'ratings/dev-reply']

    def setUp(self):
        super().setUp()

        self.url = reverse('reviewers.queue_moderated')

        RatingFlag.objects.create(
            rating_id=218468, user=self.user, flag=RatingFlag.SPAM
        )
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
            'Unexpected text: %s' % flagged
        )

        addon = Addon.objects.get(id=1865)
        addon.name = 'náme'
        addon.save()
        response = self.client.get(self.url)
        doc = pq(response.content)('#reviews-flagged')

        rows = doc('.review-flagged:not(.review-saved)')
        assert rows.length == 1
        assert rows.find('h3').text() == 'náme'

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
        assert (
            ReviewerScore.objects.filter(note_key=amo.REVIEWED_ADDON_REVIEW).count()
            == 0
        )

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
            reverse('reviewers.ratings_moderation_log.detail', args=[logs[0].id])
        )

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
        assert (
            ReviewerScore.objects.filter(note_key=amo.REVIEWED_ADDON_REVIEW).count()
            == 1
        )

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
        assert (
            ReviewerScore.objects.filter(note_key=amo.REVIEWED_ADDON_REVIEW).count()
            == 1
        )

    def test_queue_layout(self):
        # From the fixtures we already have 2 reviews, one is flagged. We add
        # a bunch of reviews from different scenarios and make sure they don't
        # count towards the total.
        # Add a review associated with an normal addon
        rating = Rating.objects.create(
            addon=addon_factory(),
            user=user_factory(),
            body='show me',
            editorreview=True,
        )
        RatingFlag.objects.create(rating=rating)

        # Add a review associated with an incomplete addon
        rating = Rating.objects.create(
            addon=addon_factory(status=amo.STATUS_NULL),
            user=user_factory(),
            body='dont show me',
            editorreview=True,
        )
        RatingFlag.objects.create(rating=rating)

        # Add a review associated to an unlisted version
        addon = addon_factory()
        version = version_factory(addon=addon, channel=amo.CHANNEL_UNLISTED)
        rating = Rating.objects.create(
            addon=addon_factory(),
            version=version,
            user=user_factory(),
            body='dont show me either',
            editorreview=True,
        )
        RatingFlag.objects.create(rating=rating)

        self._test_queue_layout(
            'Rating Reviews', tab_position=0, total_addons=2, total_queues=1
        )

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
        super().setUp()
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
            channel=amo.CHANNEL_UNLISTED
        )
        log = ActivityLog.create(
            amo.LOG.APPROVE_VERSION,
            latest_version,
            self.expected_addons[0],
            user=UserProfile.objects.get(pk=999),
            details={'comments': 'stish goin` down son'},
        )
        url = reverse('reviewers.queue_review_text') + str(log.id)
        response = self.client.get(url)
        assert response.status_code == 200
        assert json.loads(response.content) == {'reviewtext': 'stish goin` down son'}


class TestUnlistedPendingManualApproval(QueueTest):
    listed = False

    def setUp(self):
        super().setUp()
        self.url = reverse('reviewers.unlisted_queue_pending_manual_approval')
        self.generate_files()
        self.expected_addons = [
            self.addons['Pending One'],
            self.addons['Nominated Two'],
            self.addons['Pending Two'],
            self.addons['Nominated One'],
        ]
        for i, addon in enumerate(self.expected_addons):
            AutoApprovalSummary.objects.create(
                version=addon.versions.latest('pk'), score=100 - i
            )
            AddonReviewerFlags.objects.create(
                addon=addon, auto_approval_disabled_unlisted=True
            )
        # Set one of the add-ons as needing an admin, regular reviewer
        # shouldn't see it in their queue.
        self.reserved_addon = self.expected_addons.pop()
        flags = AddonReviewerFlags.objects.get(addon=self.reserved_addon)
        flags.update(needs_admin_code_review=True)

    def test_results(self):
        with self.assertNumQueries(14):
            # - 2 for savepoints because we're in tests
            # - 2 for user/groups
            # - 1 for the current queue count for pagination purposes
            # - 2 for config items (motd / site notice)
            # - 1 for my add-ons in user menu
            # - 4 for reviewer scores and user stuff displayed above the queue
            # - 1 main queue query
            # - 1 translations
            self._test_results()

    def test_results_admin_reviewer(self):
        self.client.force_login(UserProfile.objects.get(email='admin@mozilla.com'))
        # Add back the add-on set as needing an admin code review to the
        # expected list since we are now an admin reviewer.
        self.expected_addons.append(self.reserved_addon)
        self.test_results()
        self.test_queue_layout()

    def test_queue_layout(self):
        self._test_queue_layout(
            'Unlisted Add-ons Pending Manual Approval',
            tab_position=1,
            total_addons=len(self.expected_addons),
            total_queues=2,
            per_page=1,
        )

    def test_only_viewable_with_specific_permission(self):
        # Regular addon reviewer does not have access.
        self.user.groupuser_set.all().delete()  # Remove all permissions
        response = self.client.get(self.url)
        assert response.status_code == 403

        # Regular user doesn't have access.
        self.client.logout()
        self.client.force_login(UserProfile.objects.get(email='regular@mozilla.com'))
        response = self.client.get(self.url)
        assert response.status_code == 403


class TestAutoApprovedQueue(QueueTest):
    def setUp(self):
        super().setUp()
        self.url = reverse('reviewers.queue_auto_approved')

    def login_with_permission(self):
        user = UserProfile.objects.get(email='reviewer@mozilla.com')
        self.user.groupuser_set.all().delete()  # Remove all permissions
        self.grant_permission(user, 'Addons:Review')
        self.client.force_login(user)

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
        extra_addon = addon_factory(name='Extra Addôn 1')
        AutoApprovalSummary.objects.create(
            version=extra_addon.current_version, verdict=amo.NOT_AUTO_APPROVED
        )
        # Has not been auto-approved either, only dry run.
        extra_addon2 = addon_factory(name='Extra Addôn 2')
        AutoApprovalSummary.objects.create(
            version=extra_addon2.current_version,
            verdict=amo.WOULD_HAVE_BEEN_AUTO_APPROVED,
        )
        # Has been auto-approved, but that auto-approval has been confirmed by
        # a human already.
        extra_addon3 = addon_factory(name='Extra Addôn 3')
        extra_summary3 = AutoApprovalSummary.objects.create(
            version=extra_addon3.current_version,
            verdict=amo.AUTO_APPROVED,
            confirmed=True,
        )
        AddonApprovalsCounter.objects.create(
            addon=extra_addon3, counter=1, last_human_review=extra_summary3.created
        )

        # Has been auto-approved and reviewed by a human before.
        addon1 = addon_factory(name='Addôn 1')
        AutoApprovalSummary.objects.create(
            version=addon1.current_version, verdict=amo.AUTO_APPROVED
        )
        AddonApprovalsCounter.objects.create(
            addon=addon1, counter=1, last_human_review=self.days_ago(42)
        )

        # Has been auto-approved twice, last_human_review is somehow None,
        # the 'created' date will be used to order it (older is higher).
        addon2 = addon_factory(name='Addôn 2')
        addon2.update(created=self.days_ago(10))
        AutoApprovalSummary.objects.create(
            version=addon2.current_version, verdict=amo.AUTO_APPROVED
        )
        AddonApprovalsCounter.objects.create(
            addon=addon2, counter=1, last_human_review=None
        )
        addon2_version2 = version_factory(addon=addon2)
        AutoApprovalSummary.objects.create(
            version=addon2_version2, verdict=amo.AUTO_APPROVED
        )

        # Has been auto-approved and never been seen by a human,
        # the 'created' date will be used to order it (newer is lower).
        addon3 = addon_factory(name='Addôn 3')
        addon3.update(created=self.days_ago(2))
        AutoApprovalSummary.objects.create(
            version=addon3.current_version, verdict=amo.AUTO_APPROVED
        )
        # Somehow a high score for customs, not mad: will be ignored.
        ScannerResult.objects.create(
            scanner=CUSTOMS, version=addon3.current_version, score=0.95
        )
        AddonApprovalsCounter.objects.create(
            addon=addon3, counter=1, last_human_review=None
        )

        # Has been auto-approved, should be second because of its weight.
        addon4 = addon_factory(name='Addôn 4')
        addon4.update(created=self.days_ago(14))
        AutoApprovalSummary.objects.create(
            version=addon4.current_version,
            verdict=amo.AUTO_APPROVED,
            weight=500,
            score=75,
        )
        AddonApprovalsCounter.objects.create(
            addon=addon4, counter=0, last_human_review=self.days_ago(1)
        )

        # Has been auto-approved, should be first because of its score.
        addon5 = addon_factory(name='Addôn 5')
        AutoApprovalSummary.objects.create(
            version=addon5.current_version,
            verdict=amo.AUTO_APPROVED,
            weight=10,
            score=90,
        )
        self.expected_addons = [addon5, addon4, addon2, addon3, addon1]

    def test_only_viewable_with_specific_permission(self):
        # content reviewer does not have access.
        self.user.groupuser_set.all().delete()  # Remove all permissions
        self.grant_permission(self.user, 'Addons:ContentReview')
        response = self.client.get(self.url)
        assert response.status_code == 403

        # Regular user doesn't have access.
        self.client.logout()
        self.client.force_login(UserProfile.objects.get(email='regular@mozilla.com'))
        response = self.client.get(self.url)
        assert response.status_code == 403

    def test_results(self):
        self.login_with_permission()
        self.generate_files()
        with self.assertNumQueries(14):
            # - 2 for savepoints because we're in tests
            # - 2 for user/groups
            # - 1 for the current queue count for pagination purposes
            # - 2 for the addons in the queues and their files (regardless of
            #     how many are in the queue - that's the important bit)
            # - 2 for config items (motd / site notice)
            # - 1 for my add-ons in user menu
            # - 4 for reviewer scores and user stuff displayed above the queue
            self._test_results()

    def test_queue_layout(self):
        self.login_with_permission()
        self.generate_files()

        self._test_queue_layout(
            'Auto Approved', tab_position=3, total_addons=5, total_queues=4, per_page=1
        )

    def test_pending_rejection_filtered_out(self):
        self.login_with_permission()
        self.generate_files()
        version_review_flags_factory(
            version=self.expected_addons[0].current_version,
            pending_rejection=datetime.now(),
        )
        version_review_flags_factory(
            version=self.expected_addons[1].current_version,
            pending_rejection=datetime.now(),
        )
        self.expected_addons = self.expected_addons[2:]
        self._test_results()

    def test_flags_promoted(self):
        self.login_with_permission()
        addon = addon_factory(name='Addôn', version_kw={'version': '77.6'})
        AutoApprovalSummary.objects.create(
            version=addon.current_version, verdict=amo.AUTO_APPROVED
        )
        AddonApprovalsCounter.objects.create(
            addon=addon, counter=1, last_human_review=self.days_ago(42)
        )
        self.make_addon_promoted(addon, STRATEGIC)

        r = self.client.get(self.url)

        rows = pq(r.content)('#addon-queue tr.addon-row')
        assert rows.length == 1
        assert rows.attr('data-addon') == str(addon.id)
        assert rows.find('td').eq(1).text() == 'Addôn 77.6'
        assert rows.find('.ed-sprite-promoted-strategic').length == 1


class TestContentReviewQueue(QueueTest):
    def setUp(self):
        super().setUp()
        self.url = reverse('reviewers.queue_content_review')
        self.channel_name = 'content'

    def login_with_permission(self):
        user = UserProfile.objects.get(email='reviewer@mozilla.com')
        self.user.groupuser_set.all().delete()  # Remove all permissions
        self.grant_permission(user, 'Addons:ContentReview')
        self.client.force_login(user)
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
        extra_addon1 = addon_factory(name='Extra Addön 1')
        AutoApprovalSummary.objects.create(
            version=extra_addon1.current_version,
            verdict=amo.AUTO_APPROVED,
            confirmed=True,
        )
        AddonApprovalsCounter.objects.create(
            addon=extra_addon1, last_content_review=self.days_ago(370)
        )

        # This one is quite similar, except its last content review is even
        # older..
        extra_addon2 = addon_factory(name='Extra Addön 2')
        AutoApprovalSummary.objects.create(
            version=extra_addon2.current_version,
            verdict=amo.AUTO_APPROVED,
            confirmed=True,
        )
        AddonApprovalsCounter.objects.create(
            addon=extra_addon2, last_content_review=self.days_ago(842)
        )

        # Has been auto-approved, but that content has been approved by
        # a human already.
        extra_addon3 = addon_factory(name='Extra Addôn 3')
        AutoApprovalSummary.objects.create(
            version=extra_addon3.current_version,
            verdict=amo.AUTO_APPROVED,
            confirmed=True,
        )
        AddonApprovalsCounter.objects.create(
            addon=extra_addon3, last_content_review=self.days_ago(1)
        )

        # This one has never been content-reviewed, but it has the
        # needs_admin_content_review flag, and we're not an admin.
        extra_addon4 = addon_factory(name='Extra Addön 4')
        extra_addon4.update(created=self.days_ago(2))
        AutoApprovalSummary.objects.create(
            version=extra_addon4.current_version,
            verdict=amo.AUTO_APPROVED,
            confirmed=True,
        )
        AddonApprovalsCounter.objects.create(
            addon=extra_addon4, last_content_review=None
        )
        AddonReviewerFlags.objects.create(
            addon=extra_addon4, needs_admin_content_review=True
        )

        # Those should appear in the queue
        # Has not been auto-approved.
        addon1 = addon_factory(name='Addôn 1', created=self.days_ago(4))

        # Has not been auto-approved either, only dry run.
        addon2 = addon_factory(name='Addôn 2', created=self.days_ago(3))
        AutoApprovalSummary.objects.create(
            version=addon2.current_version,
            verdict=amo.WOULD_HAVE_BEEN_AUTO_APPROVED,
        )

        # This one has never been content-reviewed. It has an
        # needs_admin_code_review flag, but that should not have any impact.
        addon3 = addon_factory(name='Addön 3', created=self.days_ago(2))
        AutoApprovalSummary.objects.create(
            version=addon3.current_version, verdict=amo.AUTO_APPROVED, confirmed=True
        )
        AddonApprovalsCounter.objects.create(addon=addon3, last_content_review=None)
        AddonReviewerFlags.objects.create(addon=addon3, needs_admin_code_review=True)

        # This one has never been content reviewed either, and it does not even
        # have an AddonApprovalsCounter.
        addon4 = addon_factory(name='Addön 4', created=self.days_ago(1))
        AutoApprovalSummary.objects.create(
            version=addon4.current_version, verdict=amo.AUTO_APPROVED, confirmed=True
        )
        assert not AddonApprovalsCounter.objects.filter(addon=addon4).exists()

        # Those should *not* appear in the queue
        # Has not been auto-approved but themes, langpacks and search plugins
        # are excluded.
        addon_factory(
            name='Theme 1', created=self.days_ago(4), type=amo.ADDON_STATICTHEME
        )
        addon_factory(name='Langpack 1', created=self.days_ago(4), type=amo.ADDON_LPAPP)

        # Addons with no last_content_review date, ordered by
        # their creation date, older first.
        self.expected_addons = [addon1, addon2, addon3, addon4]

    def test_only_viewable_with_specific_permission(self):
        # Regular addon reviewer does not have access.
        response = self.client.get(self.url)
        assert response.status_code == 403

        # Regular user doesn't have access.
        self.client.logout()
        self.client.force_login(UserProfile.objects.get(email='regular@mozilla.com'))
        response = self.client.get(self.url)
        assert response.status_code == 403

    def test_results(self):
        self.login_with_permission()
        self.generate_files()
        with self.assertNumQueries(14):
            # - 2 for savepoints because we're in tests
            # - 2 for user/groups
            # - 1 for the current queue count for pagination purposes
            # - 2 for the addons in the queues and their files (regardless of
            #     how many are in the queue - that's the important bit)
            # - 2 for config items (motd / site notice)
            # - 1 for my add-ons in user menu
            # - 4 for reviewer scores and user stuff displayed above the queue
            self._test_results()

    def test_queue_layout(self):
        self.login_with_permission()
        self.generate_files()

        self._test_queue_layout(
            'Content Review', tab_position=0, total_addons=4, total_queues=1, per_page=1
        )

    def test_queue_layout_admin(self):
        # Admins should see the extra add-on that needs admin content review.
        user = self.login_with_permission()
        self.grant_permission(user, 'Reviews:Admin')
        self.generate_files()

        self._test_queue_layout(
            'Content Review', tab_position=0, total_addons=5, total_queues=2
        )

    def test_pending_rejection_filtered_out(self):
        self.login_with_permission()
        self.generate_files()
        version_review_flags_factory(
            version=self.expected_addons[0].current_version,
            pending_rejection=datetime.now(),
        )
        version_review_flags_factory(
            version=self.expected_addons[1].current_version,
            pending_rejection=datetime.now(),
        )
        self.expected_addons = self.expected_addons[2:]
        self._test_results()


class TestScannersReviewQueue(QueueTest):
    fixtures = ['base/users']

    def setUp(self):
        super().setUp()
        self.url = reverse('reviewers.queue_scanners')

    def generate_files(self):
        # Has no versions needing human review.
        extra_addon = addon_factory()
        version_factory(addon=extra_addon, channel=amo.CHANNEL_UNLISTED)

        # Has 3 listed versions, 2 needing human review, 1 unlisted but not
        # needing human review.
        addon1 = addon_factory(created=self.days_ago(31))
        addon1_v1 = addon1.current_version
        addon1_v1.update(needs_human_review=True)
        version_factory(addon=addon1, needs_human_review=True)
        version_factory(addon=addon1)
        version_factory(addon=addon1, channel=amo.CHANNEL_UNLISTED)
        AddonApprovalsCounter.objects.create(
            addon=addon1, counter=1, last_human_review=self.days_ago(1)
        )

        # Has 1 listed and 1 unlisted versions, both needing human review.
        addon2 = addon_factory(
            created=self.days_ago(15), version_kw={'needs_human_review': True}
        )
        addon2.current_version
        version_factory(
            addon=addon2, channel=amo.CHANNEL_UNLISTED, needs_human_review=True
        )

        # Has 2 unlisted versions, 1 needing human review. Needs admin content
        # review but that shouldn't matter.
        addon3 = addon_factory(
            created=self.days_ago(7),
            version_kw={
                'channel': amo.CHANNEL_UNLISTED,
                'needs_human_review': True,
            },
        )
        addon3.versions.get()
        version_factory(addon=addon3, channel=amo.CHANNEL_UNLISTED)
        AddonReviewerFlags.objects.create(addon=addon3, needs_admin_content_review=True)

        # Needs admin code review, so wouldn't show up for regular reviewers.
        addon4 = addon_factory(
            created=self.days_ago(1), version_kw={'needs_human_review': True}
        )
        AddonReviewerFlags.objects.create(addon=addon4, needs_admin_code_review=True)

        self.expected_addons = [addon1, addon2, addon3]

    def test_results(self):
        self.generate_files()
        with self.assertNumQueries(14):
            response = self.client.get(self.url)
        assert response.status_code == 200

        expected = []
        # addon1
        addon = self.expected_addons[0]
        expected.append(
            (
                'Listed versions needing human review (2)',
                reverse('reviewers.review', args=[addon.pk]),
            )
        )
        # addon2
        addon = self.expected_addons[1]
        expected.append(
            (
                'Listed versions needing human review (1)',
                reverse('reviewers.review', args=[addon.pk]),
            )
        )
        expected.append(
            (
                'Unlisted versions needing human review (1)',
                reverse('reviewers.review', args=['unlisted', addon.pk]),
            )
        )
        # addon3
        addon = self.expected_addons[2]
        expected.append(
            (
                'Unlisted versions needing human review (1)',
                reverse('reviewers.review', args=['unlisted', addon.pk]),
            )
        )

        doc = pq(response.content)
        links = doc('#addon-queue tr.addon-row td a:not(.app-icon)')
        # Number of expected links is not equal to len(self.expected_addons)
        # because we display a review link for each channel that has versions
        # needing review per add-on, and addon2 has both unlisted and listed
        # versions needing review.
        assert len(links) == 4
        check_links(expected, links, verify=False)

    def test_only_viewable_with_specific_permission(self):
        # content reviewer does not have access.
        self.user.groupuser_set.all().delete()  # Remove all permissions
        self.grant_permission(self.user, 'Addons:ContentReview')
        response = self.client.get(self.url)
        assert response.status_code == 403

        # Regular user doesn't have access.
        self.client.logout()
        self.client.force_login(UserProfile.objects.get(email='regular@mozilla.com'))
        response = self.client.get(self.url)
        assert response.status_code == 403

    def test_queue_layout(self):
        self.generate_files()

        self._test_queue_layout(
            'Flagged By Scanners',
            tab_position=1,
            total_addons=3,
            total_queues=4,
            per_page=1,
        )

    def test_queue_layout_admin(self):
        # Admins should see the extra add-on that needs admin content review.
        self.login_as_admin()
        self.generate_files()

        self._test_queue_layout(
            'Flagged By Scanners',
            tab_position=2,
            total_addons=4,
            total_queues=10,
            per_page=1,
        )


class TestPendingRejectionReviewQueue(QueueTest):
    fixtures = ['base/users']

    def setUp(self):
        super().setUp()
        self.url = reverse('reviewers.queue_pending_rejection')

    def generate_files(self):
        addon1 = addon_factory(created=self.days_ago(4))
        version_review_flags_factory(
            version=addon1.versions.get(),
            pending_rejection=datetime.now() + timedelta(days=1),
        )

        addon2 = addon_factory(
            created=self.days_ago(5),
            status=amo.STATUS_NOMINATED,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        version_review_flags_factory(
            version=addon2.versions.get(),
            pending_rejection=datetime.now() + timedelta(days=2),
        )

        unlisted_addon = addon_factory(
            name='Has a version pending rejection but it is not the current',
        )
        pending_version1 = version_factory(
            addon=unlisted_addon,
            created=self.days_ago(1),
            version='0.1',
            channel=amo.CHANNEL_UNLISTED,
        )
        version_review_flags_factory(
            version=pending_version1, pending_rejection=datetime.now()
        )
        pending_version2 = version_factory(
            addon=unlisted_addon,
            created=self.days_ago(1),
            version='0.2',
            channel=amo.CHANNEL_UNLISTED,
        )
        version_review_flags_factory(
            version=pending_version2, pending_rejection=datetime.now()
        )
        version_factory(
            addon=unlisted_addon, version='0.3', channel=amo.CHANNEL_UNLISTED
        )

        # Extra add-ons without pending rejection, they shouldn't appear.
        addon_factory()

        # Addon 2 has an older creation date, but what matters for the ordering
        # is the pending rejection deadline.
        self.expected_addons = [unlisted_addon, addon1, addon2]

    def test_results(self):
        self.login_as_admin()
        self.generate_files()
        self._test_results(dont_expect_version_number=True)


class ReviewBase(QueueTest):
    def setUp(self):
        super(QueueTest, self).setUp()
        self.login_as_reviewer()
        self.addons = {}

        self.addon = self.generate_file('Public')
        self.version = self.addon.current_version
        self.file = self.version.file
        self.reviewer = UserProfile.objects.get(username='reviewer')
        self.reviewer.update(display_name='A Reviêwer')
        self.url = reverse('reviewers.review', args=[self.addon.pk])
        self.listed_url = reverse('reviewers.review', args=['listed', self.addon.pk])

        AddonUser.objects.create(addon=self.addon, user_id=999)

    def get_addon(self):
        return Addon.objects.get(pk=self.addon.pk)

    def get_dict(self, **kw):
        data = {
            'operating_systems': 'win',
            'applications': 'something',
            'comments': 'something',
        }
        data.update(kw)
        return data


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
            addon=self.addon,
            channel=amo.CHANNEL_LISTED,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        self.addon.update(status=amo.STATUS_NOMINATED, slug='awaiting')
        self.url = reverse('reviewers.review', args=('unlisted', self.addon.pk))
        self.grant_permission(self.reviewer, 'Addons:ReviewUnlisted')
        assert self.client.get(self.url).status_code == 200

    def test_review_unlisted_while_a_listed_version_is_awaiting_review_viewer(self):
        self.make_addon_unlisted(self.addon)
        version_factory(
            addon=self.addon,
            channel=amo.CHANNEL_LISTED,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        self.addon.update(status=amo.STATUS_NOMINATED, slug='awaiting')
        self.url = reverse('reviewers.review', args=('unlisted', self.addon.pk))
        self.grant_permission(self.reviewer, 'ReviewerTools:ViewUnlisted')
        assert self.client.get(self.url).status_code == 200

    def test_needs_unlisted_reviewer_for_only_unlisted(self):
        self.addon.versions.update(channel=amo.CHANNEL_UNLISTED)
        self.addon.update_version()
        self.url = reverse('reviewers.review', args=('unlisted', self.addon.pk))
        assert self.client.head(self.url).status_code == 403

        # Adding a listed version makes it pass @reviewer_addon_view_factory
        # decorator that only depends on the addon being purely unlisted or
        # not, but still fail the check inside the view because we're looking
        # at the unlisted channel specifically.
        version_factory(addon=self.addon, channel=amo.CHANNEL_LISTED, version='9.9')
        assert self.client.head(self.url).status_code == 403
        assert self.client.post(self.url).status_code == 403

        # It works with the right permission.
        self.grant_permission(self.reviewer, 'Addons:ReviewUnlisted')
        assert self.client.head(self.url).status_code == 200

    def test_needs_unlisted_viewer_for_only_unlisted(self):
        self.addon.versions.update(channel=amo.CHANNEL_UNLISTED)
        self.addon.update_version()
        self.url = reverse('reviewers.review', args=('unlisted', self.addon.pk))
        assert self.client.head(self.url).status_code == 403

        # Adding a listed version makes it pass @reviewer_addon_view_factory
        # decorator that only depends on the addon being purely unlisted or
        # not, but still fail the check inside the view because we're looking
        # at the unlisted channel specifically.
        version_factory(addon=self.addon, channel=amo.CHANNEL_LISTED, version='9.9')
        assert self.client.head(self.url).status_code == 403
        assert self.client.post(self.url).status_code == 403

        # It works with the right permission.
        self.grant_permission(self.reviewer, 'ReviewerTools:ViewUnlisted')
        assert self.client.head(self.url).status_code == 200

    def test_dont_need_unlisted_reviewer_for_mixed_channels(self):
        version_factory(addon=self.addon, channel=amo.CHANNEL_UNLISTED, version='9.9')

        assert self.addon.find_latest_version(channel=amo.CHANNEL_UNLISTED)
        assert self.addon.current_version.channel == amo.CHANNEL_LISTED
        assert self.client.head(self.url).status_code == 200
        self.grant_permission(self.reviewer, 'Addons:ReviewUnlisted')
        assert self.client.head(self.url).status_code == 200
        self.grant_permission(self.reviewer, 'ReviewerTools:ViewUnlisted')
        assert self.client.head(self.url).status_code == 200

    def test_need_correct_reviewer_for_promoted_addon(self):
        self.make_addon_promoted(self.addon, RECOMMENDED)
        self.file.update(status=amo.STATUS_AWAITING_REVIEW)
        response = self.client.get(self.url)
        assert response.status_code == 200
        choices = list(dict(response.context['form'].fields['action'].choices).keys())
        expected_choices = ['reply', 'super', 'comment']
        assert choices == expected_choices

        doc = pq(response.content)
        assert doc('.is_promoted')
        for entry in doc('.is_promoted').items():
            assert entry.text() == (
                "This is a Recommended add-on. You don't have permission to review it."
            )

        self.grant_permission(self.reviewer, 'Addons:RecommendedReview')
        response = self.client.get(self.url)
        assert response.status_code == 200
        choices = list(dict(response.context['form'].fields['action'].choices).keys())
        expected_choices = [
            'public',
            'reject',
            'reject_multiple_versions',
            'reply',
            'super',
            'comment',
        ]
        assert choices == expected_choices

        doc = pq(response.content)
        assert doc('.is_promoted')
        for entry in doc('.is_promoted').items():
            assert entry.text() == ('This is a Recommended add-on.')

        # Change to a different class of promoted addon
        self.make_addon_promoted(self.addon, SPOTLIGHT)

        response = self.client.get(self.url)
        assert response.status_code == 200
        choices = list(dict(response.context['form'].fields['action'].choices).keys())
        expected_choices = ['super', 'comment']
        assert choices == expected_choices

        doc = pq(response.content)
        assert doc('.is_promoted')
        for entry in doc('.is_promoted').items():
            assert entry.text() == (
                "This is a Spotlight add-on. You don't have permission to review it."
            )

        self.grant_permission(self.reviewer, 'Reviews:Admin')
        response = self.client.get(self.url)
        assert response.status_code == 200
        choices = list(dict(response.context['form'].fields['action'].choices).keys())
        expected_choices = [
            'public',
            'reject',
            'reject_multiple_versions',
            'unreject_multiple_versions',
            'reply',
            'super',
            'comment',
        ]
        assert choices == expected_choices

        doc = pq(response.content)
        assert doc('.is_promoted')
        for entry in doc('.is_promoted').items():
            assert entry.text() == ('This is a Spotlight add-on.')

    def test_not_recommendable(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('h2.addon').text() == 'Review Public 0.1 (Listed)'
        assert not doc('.is_promoted')

    def test_not_flags(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert len(response.context['flags']) == 0

    def test_flag_needs_admin_code_review(self):
        AddonReviewerFlags.objects.create(
            addon=self.addon, needs_admin_code_review=True
        )
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert len(response.context['flags']) == 1

    def test_info_comments_requested(self):
        response = self.client.post(self.url, {'action': 'reply'})
        assert response.context['form'].errors['comments'][0] == (
            'This field is required.'
        )

    def test_whiteboard_url(self):
        # Listed review.
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert (
            doc('#whiteboard_form').attr('action')
            == f'/en-US/reviewers/whiteboard/listed/{self.addon.pk}'
        )
        assert doc('#id_whiteboard-public')
        assert doc('#id_whiteboard-private')

        # Content review.
        self.grant_permission(self.reviewer, 'Addons:ContentReview')
        AutoApprovalSummary.objects.create(
            version=self.addon.current_version, verdict=amo.AUTO_APPROVED
        )
        self.url = reverse('reviewers.review', args=['content', self.addon.pk])
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert (
            doc('#whiteboard_form').attr('action')
            == f'/en-US/reviewers/whiteboard/content/{self.addon.pk}'
        )

        # Unlisted review.
        self.grant_permission(self.reviewer, 'Addons:ReviewUnlisted')
        version_factory(addon=self.addon, channel=amo.CHANNEL_UNLISTED)
        self.url = reverse('reviewers.review', args=['unlisted', self.addon.pk])
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert (
            doc('#whiteboard_form').attr('action')
            == f'/en-US/reviewers/whiteboard/unlisted/{self.addon.pk}'
        )

        # Listed review, but deleted.
        self.addon.delete()
        self.url = reverse('reviewers.review', args=['listed', self.addon.pk])
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert (
            doc('#whiteboard_form').attr('action')
            == f'/en-US/reviewers/whiteboard/listed/{self.addon.pk}'
        )

    def test_whiteboard_for_static_themes(self):
        self.grant_permission(self.reviewer, 'Addons:ThemeReview')
        self.addon.update(type=amo.ADDON_STATICTHEME)
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert (
            doc('#whiteboard_form').attr('action')
            == f'/en-US/reviewers/whiteboard/listed/{self.addon.pk}'
        )
        assert doc('#id_whiteboard-public')
        assert not doc('#id_whiteboard-private')

    def test_comment(self):
        response = self.client.post(
            self.url, {'action': 'comment', 'comments': 'hello sailor'}
        )
        assert response.status_code == 302
        assert len(mail.outbox) == 0

        comment_version = amo.LOG.COMMENT_VERSION
        assert ActivityLog.objects.filter(action=comment_version.id).count() == 1

    def test_reviewer_reply(self):
        reason = ReviewActionReason.objects.create(name='reason 1', is_active=True)
        response = self.client.post(
            self.url,
            {'action': 'reply', 'comments': 'hello sailor', 'reasons': [reason.id]},
        )
        assert response.status_code == 302
        assert len(mail.outbox) == 1
        self.assertTemplateUsed(response, 'activity/emails/from_reviewer.txt')

    def test_super_review_requested(self):
        response = self.client.post(
            self.url, {'action': 'super', 'comments': 'hello sailor'}
        )
        assert response.status_code == 302

    def test_reviewer_reply_canned_response(self):
        reason = ReviewActionReason.objects.create(name='reason 1', is_active=True)
        response = self.client.post(
            self.url,
            {
                'action': 'reply',
                'comments': 'hello sailor',
                'canned_response': 'foo',
                'reasons': [reason.id],
            },
        )
        assert response.status_code == 302
        assert len(mail.outbox) == 1
        self.assertTemplateUsed(response, 'activity/emails/from_reviewer.txt')

    def test_page_title(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('title').text() == ('%s – Add-ons for Firefox' % self.addon.name)

    def test_files_shown(self):
        response = self.client.get(self.url)
        assert response.status_code == 200

        items = pq(response.content)('#versions-history .files .file-info')
        assert items.length == 1

        file_ = self.version.file
        expected = [
            (file_.get_absolute_url(attachment=True)),
            (
                'Validation',
                reverse('devhub.file_validation', args=[self.addon.slug, file_.id]),
            ),
            ('Contents', None),
        ]
        check_links(expected, items.find('a'), verify=False)

    def test_item_history(self, channel=amo.CHANNEL_LISTED):
        self.addons['something'] = addon_factory(
            status=amo.STATUS_APPROVED,
            name='something',
            version_kw={'version': '0.2', 'channel': channel},
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
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
            assert (
                td.find('th')
                .text()
                .startswith({'public': 'Approved', 'reply': 'Reviewer Reply'}[action])
            )
            reviewer_name = td.find('td a').text()
            assert (reviewer_name == self.reviewer.name) or (
                reviewer_name == self.other_reviewer.name
            )

    def test_item_history_pagination(self):
        addon = self.addons['Public']
        addon.current_version.update(created=self.days_ago(366))
        for i in range(0, 10):
            # Add versions 1.0 to 1.9
            version_factory(
                addon=addon, version=f'1.{i}', created=self.days_ago(365 - i)
            )
        # Since we're testing queries, also include an author change that will
        # be displayed in the "important changes" log.
        author = self.addon.addonuser_set.get()
        core.set_user(author.user)
        ActivityLog.create(
            amo.LOG.ADD_USER_WITH_ROLE,
            author.user,
            str(author.get_role_display()),
            self.addon,
        )
        with self.assertNumQueries(55):
            # FIXME: obviously too high, but it's a starting point.
            # Potential further optimizations:
            # - Remove trivial... and not so trivial duplicates
            # - Group similar queries
            # - Try to do counts of things on different page in a single query
            # - Remove useless things like user add-ons and collection
            # - Make some joins
            #
            # 1. user
            # 2. savepoint
            # 3. groups
            # 4. add-on by slug
            # 5. add-on translations
            # 6. add-on categories
            # 7. current version + file
            # 8. current version translations
            # 9. current version applications versions
            # 10. authors
            # 11. previews
            # 12. autoapprovalsummary for current version
            # 13. promoted info for the add-on
            # 14. latest version + file
            # 15. latest version translations
            # 16. latest version (repeated because different status filter)
            # 17. latest version translations (repeated because different qs)
            # 18. addon reviewer flags
            # 19. version reviewer flags
            # 20. version reviewer flags (repeated)
            # 21. autoapprovalsummary (repeated)
            # 22. addonreusedguid
            # 23. blocklist
            # 24. canned responses
            # 25. abuse reports count against user or addon
            # 26. low ratings count
            # 27. base version pk for comparison
            # 28. count of all versions in channel
            # 29. paginated list of versions in channel
            # 30. scanner results for paginated list of versions
            # 31. translations for  paginated list of versions
            # 32. applications versions for  paginated list of versions
            # 33. files for  paginated list of versions
            # 34. activity log for  paginated list of versions
            # 35. ready for auto-approval info for  paginated list of versions
            # 36. versionreviewer flags exists to find out if pending rejection
            # 37. count versions needing human review on other pages
            # 38. count versions needing human review by mad on other pages
            # 39. count versions pending rejection on other pages
            # 40. whiteboard
            # 41. reviewer subscriptions for listed
            # 42. reviewer subscriptions for unlisted
            # 43. release savepoint (?)
            # 44. config for motd
            # 45. count add-ons the user is a developer of
            # 46. config for site notice
            # 47. translations for... (?! id=1)
            # 48. important activity log about the add-on
            # 49. user for the activity (from the ActivityLog foreignkey)
            # 50. user for the activity (from the ActivityLog arguments)
            # 51. add-on for the activity
            # 52. translation for the add-on for the activity
            # 53. select all versions in channel for versions dropdown widget
            # 54. reviewer reasons for the reason dropdown
            # 55. select users by role for this add-on (?)
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
            version='0.3',
            addon=self.addon,
            channel=amo.CHANNEL_UNLISTED,
            file_kw={'status': amo.STATUS_APPROVED},
        )
        self.test_item_history()

    def test_item_history_with_unlisted_review_page(self):
        self.addon.versions.update(channel=amo.CHANNEL_UNLISTED)
        self.version.reload()
        # Throw in an listed version to be ignored.
        version_factory(
            version='0.3',
            addon=self.addon,
            channel=amo.CHANNEL_LISTED,
            file_kw={'status': amo.STATUS_APPROVED},
        )
        self.url = reverse('reviewers.review', args=['unlisted', self.addon.pk])
        self.grant_permission(self.reviewer, 'Addons:ReviewUnlisted')
        self.test_item_history(channel=amo.CHANNEL_UNLISTED)

    def test_item_history_with_unlisted_review_page_viewer(self):
        self.addon.versions.update(channel=amo.CHANNEL_UNLISTED)
        self.version.reload()
        # Throw in an listed version to be ignored.
        version_factory(
            version='0.3',
            addon=self.addon,
            channel=amo.CHANNEL_LISTED,
            file_kw={'status': amo.STATUS_APPROVED},
        )
        self.url = reverse('reviewers.review', args=['unlisted', self.addon.pk])
        self.grant_permission(self.reviewer, 'ReviewerTools:ViewUnlisted')
        self.test_item_history(channel=amo.CHANNEL_UNLISTED)

    def test_item_history_compat_ordered(self):
        """Make sure that apps in compatibility are ordered."""
        av = AppVersion.objects.all()[0]
        v = self.addon.versions.all()[0]

        ApplicationsVersions.objects.create(
            version=v, application=amo.ANDROID.id, min=av, max=av
        )

        assert self.addon.versions.count() == 1
        url = reverse('reviewers.review', args=[self.addon.pk])

        response = self.client.get(url)
        assert response.status_code == 200
        doc = pq(response.content)
        icons = doc('.listing-body .app-icon')
        assert icons.eq(0).attr('title') == 'Firefox for Android'
        assert icons.eq(1).attr('title') == 'Firefox'

    def test_item_history_weight(self):
        """Make sure the weight is shown on the review page"""
        AutoApprovalSummary.objects.create(
            version=self.version,
            verdict=amo.AUTO_APPROVED,
            weight=326,
            code_weight=126,
            metadata_weight=200,
            weight_info={'fôo': 42, 'bär': 84, 'oof': 105, 'rab': 95},
        )
        self.grant_permission(self.reviewer, 'Addons:Review')
        url = reverse('reviewers.review', args=[self.addon.pk])
        response = self.client.get(url)
        assert response.status_code == 200
        doc = pq(response.content)
        weight = doc('.listing-body .file-weight')
        assert weight.text() == 'Code Weight: 126\nMetadata Weight: 200'
        assert weight.attr['title'] == 'bär: 84\nfôo: 42\noof: 105\nrab: 95'

    def test_maliciousness_score(self):
        self.grant_permission(self.reviewer, 'Addons:Review')
        url = reverse('reviewers.review', args=[self.addon.pk])
        # Without a score.
        response = self.client.get(url)
        assert response.status_code == 200
        doc = pq(response.content)
        score = doc('.listing-body .maliciousness-score')
        assert score.text() == 'Maliciousness Score: n/a ?'
        # With a score.
        ScannerResult.objects.create(version=self.version, scanner=MAD, score=0.1)
        response = self.client.get(url)
        assert response.status_code == 200
        doc = pq(response.content)
        score = doc('.listing-body .maliciousness-score')
        assert score.text() == 'Maliciousness Score: 10% ?'

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
        assert (
            'Approved'
            in doc('#versions-history .review-files .listing-header .light').text()
        )

    def test_item_history_comment(self):
        # Add Comment.
        self.client.post(self.url, {'action': 'comment', 'comments': 'hello sailor'})

        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)('#versions-history .review-files')
        assert doc('th').eq(1).text() == 'Commented'
        assert doc('.history-comment').text() == 'hello sailor'

    def test_item_history_pending_rejection(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)('#versions-history .review-files')
        assert doc('.pending-rejection') == []
        version_review_flags_factory(
            version=self.version,
            pending_rejection=datetime.now() + timedelta(hours=1, minutes=1),
        )
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)('#versions-history .review-files')
        assert doc('.pending-rejection').text() == (
            '· Scheduled for rejection in 1\xa0hour'
        )

    def test_item_history_pending_rejection_but_latest_is_unreviewed(self):
        # Adding a non-pending rejection as the latest version shouldn't change
        # anything if it's public.
        version_review_flags_factory(
            version=self.version,
            pending_rejection=datetime.now() + timedelta(hours=1, minutes=1),
        )
        self.addon.current_version.update(created=self.days_ago(366))
        latest_version = version_factory(addon=self.addon)
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)('#versions-history .review-files')
        assert doc('.pending-rejection').text() == (
            '· Scheduled for rejection in 1\xa0hour'
        )
        # If the latest version is not pending rejection and unreviewed, we
        # won't automatically reject versions pending rejection even if the
        # deadline has passed - so the message changes.
        latest_version.file.update(status=amo.STATUS_AWAITING_REVIEW)
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)('#versions-history .review-files')
        assert doc('.pending-rejection').text() == (
            '· Pending Rejection on review of new version'
        )

    def test_item_history_pending_rejection_other_pages(self):
        self.addon.current_version.update(created=self.days_ago(366))
        for i in range(0, 10):
            # Add versions 1.0 to 1.9. Schedule a couple for future rejection
            # (the date doesn't matter).
            version = version_factory(
                addon=self.addon, version=f'1.{i}', created=self.days_ago(365 - i)
            )
            if not bool(i % 5):
                version_review_flags_factory(
                    version=version, pending_rejection=datetime.now()
                )

        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        ths = doc('#versions-history tr.listing-header th')
        assert ths.length == 10
        # Original version should not be there any more, it's on the second
        # page. Versions on the page should be displayed in chronological order
        # Versions 1.0, and 1.5 are pending rejection.
        assert 'Scheduled for rejection in' in ths.eq(0).text()
        assert 'Scheduled for rejection in' in ths.eq(5).text()

        # Make sure the message doesn't appear on the rest of the versions.
        for num in [1, 2, 3, 4, 6, 7, 8, 9]:
            assert 'Scheduled for rejection in' not in ths.eq(num).text()

        # There are no other versions pending rejection in other pages.
        span = doc('#review-files-header .other-pending-rejection')
        assert span.length == 0

        # Load the second page. This time there should be a message indicating
        # there are flagged versions in other pages.
        response = self.client.get(self.url, {'page': 2})
        assert response.status_code == 200
        doc = pq(response.content)
        span = doc('#review-files-header .other-pending-rejection')
        assert span.length == 1
        assert span.text() == '2 versions pending rejection on other pages.'

    def test_files_in_item_history(self):
        data = {
            'action': 'public',
            'operating_systems': 'win',
            'applications': 'something',
            'comments': 'something',
        }
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
            ('Admin Page', reverse('admin:addons_addon_change', args=[self.addon.id])),
            ('Statistics', reverse('stats.overview', args=[self.addon.id])),
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
            (
                'Unlisted Review Page',
                reverse('reviewers.review', args=('unlisted', self.addon.id)),
            ),
            ('Edit', self.addon.get_dev_url()),
            ('Admin Page', reverse('admin:addons_addon_change', args=[self.addon.id])),
            ('Statistics', reverse('stats.overview', args=[self.addon.id])),
        ]
        check_links(expected, doc('#actions-addon a'), verify=False)

    def test_mixed_channels_action_links_as_admin(self):
        self.make_addon_unlisted(self.addon)
        version_factory(
            addon=self.addon,
            channel=amo.CHANNEL_LISTED,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        self.addon.update(status=amo.STATUS_NOMINATED)
        self.login_as_admin()
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        expected = [
            ('View Product Page', self.addon.get_url_path()),
            (
                'Unlisted Review Page',
                reverse('reviewers.review', args=('unlisted', self.addon.id)),
            ),
            ('Edit', self.addon.get_dev_url()),
            ('Admin Page', reverse('admin:addons_addon_change', args=[self.addon.id])),
            ('Statistics', reverse('stats.overview', args=[self.addon.id])),
        ]
        check_links(expected, doc('#actions-addon a'), verify=False)

    def test_mixed_channels_action_links_as_admin_on_unlisted_review(self):
        self.make_addon_unlisted(self.addon)
        version_factory(
            addon=self.addon,
            channel=amo.CHANNEL_LISTED,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        self.addon.update(status=amo.STATUS_NOMINATED)
        self.login_as_admin()
        self.url = reverse('reviewers.review', args=('unlisted', self.addon.pk))
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        expected = [
            ('View Product Page', self.addon.get_url_path()),
            ('Listed Review Page', reverse('reviewers.review', args=(self.addon.id,))),
            ('Edit', self.addon.get_dev_url()),
            ('Admin Page', reverse('admin:addons_addon_change', args=[self.addon.id])),
            ('Statistics', reverse('stats.overview', args=[self.addon.id])),
        ]
        check_links(expected, doc('#actions-addon a'), verify=False)

    def test_mixed_channels_action_links_as_admin_deleted_addon(self):
        self.make_addon_unlisted(self.addon)
        version_factory(
            addon=self.addon,
            channel=amo.CHANNEL_LISTED,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        self.addon.update(status=amo.STATUS_NOMINATED)
        self.addon.delete()
        self.login_as_admin()
        self.url = reverse('reviewers.review', args=('listed', self.addon.id))
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        expected = [
            (
                'Unlisted Review Page',
                reverse('reviewers.review', args=('unlisted', self.addon.id)),
            ),
            ('Admin Page', reverse('admin:addons_addon_change', args=[self.addon.id])),
            ('Statistics', reverse('stats.overview', args=[self.addon.id])),
        ]
        check_links(expected, doc('#actions-addon a'), verify=False)

    def test_mixed_channels_action_links_as_admin_unlisted_deleted_addon(self):
        self.make_addon_unlisted(self.addon)
        version_factory(
            addon=self.addon,
            channel=amo.CHANNEL_LISTED,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        self.addon.update(status=amo.STATUS_NOMINATED)
        self.addon.delete()
        self.login_as_admin()
        self.url = reverse('reviewers.review', args=('unlisted', self.addon.id))
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        expected = [
            ('Listed Review Page', reverse('reviewers.review', args=(self.addon.id,))),
            ('Admin Page', reverse('admin:addons_addon_change', args=[self.addon.id])),
            ('Statistics', reverse('stats.overview', args=[self.addon.id])),
        ]
        check_links(expected, doc('#actions-addon a'), verify=False)

    def test_mixed_channels_action_links_as_regular_reviewer(self):
        self.make_addon_unlisted(self.addon)
        version_factory(
            addon=self.addon,
            channel=amo.CHANNEL_LISTED,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
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
        self.grant_permission(self.reviewer, 'Addons:ReviewUnlisted')
        self.login_as_reviewer()
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        subscribe_listed_input = doc('#notify_new_listed_versions')[0]
        assert 'checked' not in subscribe_listed_input.attrib
        subscribe_unlisted_input = doc('#notify_new_unlisted_versions')[0]
        assert 'checked' not in subscribe_unlisted_input.attrib

        ReviewerSubscription.objects.create(
            addon=self.addon, user=self.reviewer, channel=amo.CHANNEL_LISTED
        )
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        subscribe_input = doc('#notify_new_listed_versions')[0]
        assert subscribe_input.attrib['checked'] == 'checked'

        ReviewerSubscription.objects.create(
            addon=self.addon, user=self.reviewer, channel=amo.CHANNEL_UNLISTED
        )
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        subscribe_input = doc('#notify_new_unlisted_versions')[0]
        assert subscribe_input.attrib['checked'] == 'checked'

    def test_extra_actions_token(self):
        self.login_as_reviewer()
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        token = doc('#extra-review-actions').attr('data-session-id')
        assert token == self.client.session.session_key

    def test_extra_actions_not_for_reviewers(self):
        AddonReviewerFlags.objects.create(
            addon=self.addon,
            auto_approval_disabled=True,
            needs_admin_code_review=True,
            needs_admin_content_review=True,
            needs_admin_theme_review=True,
            auto_approval_delayed_until=datetime.now() + timedelta(hours=1),
        )
        version_review_flags_factory(
            version=self.addon.current_version, pending_rejection=datetime.now()
        )
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
        assert not doc('#disable_auto_approval_unlisted')
        assert not doc('#enable_auto_approval_unlisted')
        assert not doc('#disable_auto_approval_until_next_approval')
        assert not doc('#enable_auto_approval_until_next_approval')
        assert not doc('#disable_auto_approval_until_next_approval_unlisted')
        assert not doc('#enable_auto_approval_until_next_approval_unlisted')
        assert not doc('#clear_auto_approval_delayed_until')
        assert not doc('#clear_pending_rejections')
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
            addon=self.addon, auto_approval_delayed_until=self.days_ago(1)
        )
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)

        # Still not present because it's in the past.
        assert not doc('#clear_auto_approval_delayed_until')

        flags.update(auto_approval_delayed_until=datetime.now() + timedelta(hours=24))
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

    def test_resubmission_buttons_are_displayed_for_deleted_addons_and_denied_guid(
        self,
    ):  # noqa
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
        assert not doc('#edit_addon_blocklistsubmission')
        assert doc('#block_addon')[0].attrib.get('href') == (
            reverse('admin:blocklist_block_addaddon', args=(self.addon.id,))
        )

        Block.objects.create(addon=self.addon, updated_by=user_factory())
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert not doc('#block_addon')
        assert doc('#edit_addon_block')
        assert not doc('#edit_addon_blocklistsubmission')
        assert doc('#edit_addon_block')[0].attrib.get('href') == (
            reverse('admin:blocklist_block_addaddon', args=(self.addon.id,))
        )

        # If the guid is in a pending submission we show a link to that instead
        subm = BlocklistSubmission.objects.create(input_guids=self.addon.guid)
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert not doc('#block_addon')
        assert not doc('#edit_addon_block')
        blocklistsubmission_block = doc('#edit_addon_blocklistsubmission')
        assert blocklistsubmission_block
        assert blocklistsubmission_block[0].attrib.get('href') == (
            reverse('admin:blocklist_blocklistsubmission_change', args=(subm.id,))
        )

    def test_admin_block_actions_deleted_addon(self):
        # Use the id for the review page url because deleting the add-on will
        # delete the slug as well.
        self.url = reverse('reviewers.review', args=[self.addon.id])
        self.addon.delete()
        self.test_admin_block_actions()

    def test_unflag_option_forflagged_as_admin(self):
        self.login_as_admin()
        AddonReviewerFlags.objects.create(
            addon=self.addon, needs_admin_code_review=True
        )
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
            needs_admin_content_review=True,
        )
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
            needs_admin_theme_review=True,
        )
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#clear_admin_code_review').length == 0
        assert doc('#clear_admin_content_review').length == 0
        assert doc('#clear_admin_theme_review').length == 1

    def test_disable_auto_approval_as_admin(self):
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

        # They should be absent on static themes, which are not auto-approved.
        self.addon.update(type=amo.ADDON_STATICTHEME)
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert not doc('#disable_auto_approval')
        assert not doc('#enable_auto_approval')

    def test_disable_auto_approval_unlisted_as_admin(self):
        self.login_as_admin()
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#disable_auto_approval_unlisted')
        elem = doc('#disable_auto_approval_unlisted')[0]
        assert 'hidden' not in elem.getparent().attrib.get('class', '')

        assert doc('#enable_auto_approval_unlisted')
        elem = doc('#enable_auto_approval_unlisted')[0]
        assert 'hidden' in elem.getparent().attrib.get('class', '')

        # Still present for dictionaries
        self.addon.update(type=amo.ADDON_DICT)
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#disable_auto_approval_unlisted')
        assert doc('#enable_auto_approval_unlisted')

        # They should be absent on static themes, which are not auto-approved.
        self.addon.update(type=amo.ADDON_STATICTHEME)
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert not doc('#disable_auto_approval_unlisted')
        assert not doc('#enable_auto_approval_unlisted')

    def test_enable_auto_approval_as_admin(self):
        self.login_as_admin()
        AddonReviewerFlags.objects.create(addon=self.addon, auto_approval_disabled=True)
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#disable_auto_approval')
        elem = doc('#disable_auto_approval')[0]
        assert 'hidden' in elem.getparent().attrib.get('class', '')

        assert doc('#enable_auto_approval')
        elem = doc('#enable_auto_approval')[0]
        assert 'hidden' not in elem.getparent().attrib.get('class', '')

        # They should be absent on static themes, which are not auto-approved.
        self.addon.update(type=amo.ADDON_STATICTHEME)
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert not doc('#disable_auto_approval')
        assert not doc('#enable_auto_approval')

    def test_enable_auto_approval_unlisted_as_admin(self):
        self.login_as_admin()
        AddonReviewerFlags.objects.create(
            addon=self.addon, auto_approval_disabled_unlisted=True
        )
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#disable_auto_approval_unlisted')
        elem = doc('#disable_auto_approval_unlisted')[0]
        assert 'hidden' in elem.getparent().attrib.get('class', '')

        assert doc('#enable_auto_approval_unlisted')
        elem = doc('#enable_auto_approval_unlisted')[0]
        assert 'hidden' not in elem.getparent().attrib.get('class', '')

        # They should be absent on static themes, which are not auto-approved.
        self.addon.update(type=amo.ADDON_STATICTHEME)
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert not doc('#disable_auto_approval_unlisted')
        assert not doc('#enable_auto_approval_unlisted')

    def test_disable_auto_approval_until_next_approval_unlisted_as_admin(self):
        self.login_as_admin()
        AddonReviewerFlags.objects.create(
            addon=self.addon, auto_approval_disabled_until_next_approval_unlisted=True
        )
        unlisted_url = reverse('reviewers.review', args=['unlisted', self.addon.pk])
        response = self.client.get(unlisted_url)
        assert response.status_code == 200
        doc = pq(response.content)
        # Button to disable auto approval until next approval is hidden since
        # the flag is already true.
        assert doc('#disable_auto_approval_until_next_approval_unlisted')
        elem = doc('#disable_auto_approval_until_next_approval_unlisted')[0]
        assert 'hidden' in elem.getparent().attrib.get('class', '')

        # Button to re-enable auto-approval is shown.
        assert doc('#enable_auto_approval_until_next_approval_unlisted')
        elem = doc('#enable_auto_approval_until_next_approval_unlisted')[0]
        assert 'hidden' not in elem.getparent().attrib.get('class', '')

        # They both should be absent on the listed review page, since those
        # are for listed only.
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        # Button to disable auto approval until next approval is hidden since
        # the flag is already true.
        assert not doc('#disable_auto_approval_until_next_approval_unlisted')
        assert not doc('#enable_auto_approval_until_next_approval_unlisted')

    def test_disable_auto_approval_until_next_approval_as_admin(self):
        self.login_as_admin()
        AddonReviewerFlags.objects.create(
            addon=self.addon, auto_approval_disabled_until_next_approval=True
        )
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        # Button to disable auto approval until next approval is hidden since
        # the flag is already true.
        assert doc('#disable_auto_approval_until_next_approval')
        elem = doc('#disable_auto_approval_until_next_approval')[0]
        assert 'hidden' in elem.getparent().attrib.get('class', '')

        # Button to re-enable auto-approval is shown.
        assert doc('#enable_auto_approval_until_next_approval')
        elem = doc('#enable_auto_approval_until_next_approval')[0]
        assert 'hidden' not in elem.getparent().attrib.get('class', '')

        # They both should be absent on the unlisted review page, since those
        # are for listed only.
        unlisted_url = reverse('reviewers.review', args=['unlisted', self.addon.pk])
        response = self.client.get(unlisted_url)
        assert response.status_code == 200
        doc = pq(response.content)
        # Button to disable auto approval until next approval is hidden since
        # the flag is already true.
        assert not doc('#disable_auto_approval_until_next_approval')
        assert not doc('#enable_auto_approval_until_next_approval')

        # They both should be absent on static themes, which are not
        # auto-approved.
        self.addon.update(type=amo.ADDON_STATICTHEME)
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert not doc('#disable_auto_approval_until_next_approval')
        assert not doc('#enable_auto_approval_until_next_approval')

    def test_clear_pending_rejections_as_admin(self):
        self.login_as_admin()
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert not doc('#clear_pending_rejections')

        version_review_flags_factory(
            version=self.addon.current_version, pending_rejection=datetime.now()
        )
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#clear_pending_rejections')

    def test_no_public(self):
        assert self.version.file.status == amo.STATUS_APPROVED

        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)

        validation = doc.find('.files')
        assert validation.find('a').eq(1).text() == 'Validation'
        assert validation.find('a').eq(2).text() == 'Contents'

        assert validation.find('a').length == 3

    def test_version_deletion(self):
        """
        Make sure that we still show review history for deleted versions.
        """
        # Add a new version to the add-on.
        addon = addon_factory(
            status=amo.STATUS_NOMINATED,
            name='something',
            version_kw={'version': '0.2'},
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )

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
        response = self.client.post(
            self.url, {'action': 'comment', 'comments': 'hello sailor'}
        )
        assert response.status_code == 302
        self.assert3xx(response, self.listed_url, status_code=302)

        self.version.delete()
        # Regular reviewer can still see it since the deleted version was
        # listed.
        assert self.client.get(self.url).status_code == 200
        response = self.client.post(
            self.url, {'action': 'comment', 'comments': 'hello sailor'}
        )
        assert response.status_code == 302
        self.assert3xx(response, self.listed_url, status_code=302)

        # Now they need unlisted permission cause we can't find a listed
        # version, even deleted.
        self.version.delete(hard=True)
        assert self.client.get(self.url).status_code == 403

        # Unlisted viewers can view but not submit reviews.
        self.grant_permission(self.reviewer, 'ReviewerTools:ViewUnlisted')
        assert self.client.get(self.url).status_code == 200
        response = self.client.post(
            self.url, {'action': 'comment', 'comments': 'hello sailor'}
        )
        assert response.status_code == 302

        # Unlisted reviewers can submit reviews.
        self.grant_permission(self.reviewer, 'Addons:ReviewUnlisted')
        assert self.client.get(self.url).status_code == 200
        response = self.client.post(
            self.url, {'action': 'comment', 'comments': 'hello sailor'}
        )
        assert response.status_code == 302
        self.assert3xx(response, self.listed_url, status_code=302)

    def test_addon_deleted(self):
        """The review page should still load for deleted addons."""
        self.addon.delete()
        self.url = reverse('reviewers.review', args=[self.addon.pk])

        assert self.client.get(self.url).status_code == 200
        response = self.client.post(
            self.url, {'action': 'comment', 'comments': 'hello sailor'}
        )
        assert response.status_code == 302
        self.assert3xx(response, self.listed_url, status_code=302)

    @mock.patch('olympia.reviewers.utils.sign_file')
    def review_version(self, version, url, mock_sign):
        reason = ReviewActionReason.objects.create(name='reason 1', is_active=True)
        if version.channel == amo.CHANNEL_LISTED:
            version.file.update(status=amo.STATUS_AWAITING_REVIEW)
            action = 'public'
        else:
            action = 'reply'

        data = {
            'action': action,
            'operating_systems': 'win',
            'applications': 'something',
            'comments': 'something',
            'reasons': [reason.id],
        }

        self.client.post(url, data)

        if version.channel == amo.CHANNEL_LISTED:
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
        eula_url = reverse('reviewers.eula', args=(self.addon.pk,))
        self.assertContains(response, eula_url + '"')

        # The url should pass on the channel param so the backlink works
        self.make_addon_unlisted(self.addon)
        self.login_as_admin()
        unlisted_url = reverse('reviewers.review', args=['unlisted', self.addon.pk])
        response = self.client.get(unlisted_url)
        assert response.status_code == 200
        eula_url = reverse('reviewers.eula', args=(self.addon.pk,))
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
        privacy_url = reverse('reviewers.privacy', args=(self.addon.pk,))
        self.assertContains(response, privacy_url + '"')

        self.make_addon_unlisted(self.addon)
        self.login_as_admin()
        unlisted_url = reverse('reviewers.review', args=['unlisted', self.addon.pk])
        response = self.client.get(unlisted_url)
        assert response.status_code == 200
        privacy_url = reverse('reviewers.privacy', args=(self.addon.pk,))
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
        key = f'review_viewing:{self.addon.id}'
        assert cache.get(key) == self.reviewer.id

        self.client.post(self.url, {'action': 'comment', 'comments': 'hello sailor'})
        # Processing a review should instantly clear the review lock on it.
        assert cache.get(key) is None

    def test_viewing_queue(self):
        response = self.client.post(
            reverse('reviewers.review_viewing'), {'addon_id': self.addon.id}
        )
        data = json.loads(response.content)
        assert data['current'] == self.reviewer.id
        assert data['current_name'] == self.reviewer.name
        assert data['is_user'] == 1

        # Now, login as someone else and test.
        self.login_as_admin()
        response = self.client.get(
            reverse('reviewers.queue_viewing'), {'addon_ids': '%s,4242' % self.addon.id}
        )
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data[str(self.addon.id)] == self.reviewer.name

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
        assert info.find('a')[0].text == 'Download'
        assert b'Compatibility' not in response.content

    def test_compare_link(self):
        first_file = self.addon.current_version.file
        first_file.update(status=amo.STATUS_APPROVED)
        self.addon.current_version.update(created=self.days_ago(2))
        first_version_pk = self.addon.current_version.pk

        new_version = version_factory(addon=self.addon, version='0.2')
        self.addon.update(_current_version=new_version)
        assert self.addon.current_version == new_version

        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert response.context['base_version_pk']
        links = doc('#versions-history .file-info .compare')

        expected = [
            code_manager_url(
                'compare',
                addon_id=self.addon.pk,
                base_version_id=first_version_pk,
                version_id=new_version.pk,
            ),
        ]

        check_links(expected, links, verify=False)

    def test_compare_link_auto_approved_ignored(self):
        first_file = self.addon.current_version.file
        first_file.update(status=amo.STATUS_APPROVED)
        self.addon.current_version.update(created=self.days_ago(3))
        first_version_pk = self.addon.current_version.pk

        interim_version = version_factory(addon=self.addon, version='0.2')
        interim_version.update(created=self.days_ago(2))
        AutoApprovalSummary.objects.create(
            version=interim_version, verdict=amo.AUTO_APPROVED
        )

        new_version = version_factory(addon=self.addon, version='0.3')

        self.addon.update(_current_version=new_version)
        assert self.addon.current_version == new_version

        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert response.context['base_version_pk']
        links = doc('#versions-history .file-info .compare')
        # Comparison should be between the last version and the first,
        # ignoring the interim version because it was auto-approved and not
        # manually confirmed by a human.
        expected = [
            code_manager_url(
                'compare',
                addon_id=self.addon.pk,
                base_version_id=first_version_pk,
                version_id=new_version.pk,
            ),
        ]
        check_links(expected, links, verify=False)

    def test_compare_link_auto_approved_but_confirmed_not_ignored(self):
        first_file = self.addon.current_version.file
        first_file.update(status=amo.STATUS_APPROVED)
        self.addon.current_version.update(created=self.days_ago(3))

        confirmed_version = version_factory(addon=self.addon, version='0.2')
        confirmed_version.update(created=self.days_ago(2))
        AutoApprovalSummary.objects.create(
            verdict=amo.AUTO_APPROVED, version=confirmed_version, confirmed=True
        )

        interim_version = version_factory(addon=self.addon, version='0.3')
        interim_version.update(created=self.days_ago(1))
        AutoApprovalSummary.objects.create(
            version=interim_version, verdict=amo.AUTO_APPROVED
        )

        new_version = version_factory(addon=self.addon, version='0.4')

        self.addon.update(_current_version=new_version)
        assert self.addon.current_version == new_version

        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert response.context['base_version_pk']
        links = doc('#versions-history .file-info .compare')
        # Comparison should be between the last version and the second,
        # ignoring the third version because it was auto-approved and not
        # manually confirmed by a human (the second was auto-approved but
        # was manually confirmed).
        expected = [
            code_manager_url(
                'compare',
                addon_id=self.addon.pk,
                base_version_id=confirmed_version.pk,
                version_id=new_version.pk,
            ),
        ]
        check_links(expected, links, verify=False)

    def test_compare_link_not_auto_approved_but_confirmed(self):
        first_file = self.addon.current_version.file
        first_file.update(status=amo.STATUS_APPROVED)
        self.addon.current_version.update(created=self.days_ago(3))

        confirmed_version = version_factory(addon=self.addon, version='0.2')
        confirmed_version.update(created=self.days_ago(2))
        AutoApprovalSummary.objects.create(
            verdict=amo.NOT_AUTO_APPROVED, version=confirmed_version
        )

        new_version = version_factory(addon=self.addon, version='0.3')

        self.addon.update(_current_version=new_version)
        assert self.addon.current_version == new_version

        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert response.context['base_version_pk']
        links = doc('#versions-history .file-info .compare')
        # Comparison should be between the last version and the second,
        # because second was approved by human before auto-approval ran on it
        expected = [
            code_manager_url(
                'compare',
                addon_id=self.addon.pk,
                base_version_id=confirmed_version.pk,
                version_id=new_version.pk,
            ),
        ]
        check_links(expected, links, verify=False)

    def test_download_sources_link(self):
        version = self.addon.current_version
        tdir = temp.gettempdir()
        source_file = temp.NamedTemporaryFile(suffix='.zip', dir=tdir, mode='r+')
        source_file.write('a' * (2**21))
        source_file.seek(0)
        version.source.save(os.path.basename(source_file.name), DjangoFile(source_file))
        version.save()

        url = reverse('reviewers.review', args=[self.addon.pk])

        # Admin reviewer: able to download sources.
        user = UserProfile.objects.get(email='admin@mozilla.com')
        self.client.force_login(user)
        response = self.client.get(url, follow=True)
        assert response.status_code == 200
        assert b'Download files' in response.content

        # Standard reviewer: should know that sources were provided.
        user = UserProfile.objects.get(email='reviewer@mozilla.com')
        self.client.force_login(user)
        response = self.client.get(url, follow=True)
        assert response.status_code == 200
        assert b'The developer has provided source code.' in response.content

    def test_translations(self):
        self.addon.name = {
            'de': None,
            'en-CA': 'English Translation',
            'en-GB': 'English Translation',  # Duplicate
            'es': '',
            'fr': 'Traduction En Français',
        }
        self.addon.save()
        response = self.client.get(self.url)
        doc = pq(response.content)
        translations = sorted(li.text_content() for li in doc('#name-translations li'))
        expected = [
            'English (Canadian), English (British): English Translation',
            'English (US): Public',
            'Français: Traduction En Français',
        ]
        assert translations == expected

    @mock.patch('olympia.reviewers.utils.sign_file')
    def test_approve_recommended_addon(self, mock_sign_file):
        reason = ReviewActionReason.objects.create(name='reason 1', is_active=True)
        self.version.file.update(status=amo.STATUS_AWAITING_REVIEW)
        self.addon.update(status=amo.STATUS_NOMINATED)
        self.make_addon_promoted(self.addon, RECOMMENDED)
        self.grant_permission(self.reviewer, 'Addons:RecommendedReview')
        response = self.client.post(
            self.url,
            {'action': 'public', 'comments': 'all good', 'reasons': [reason.id]},
        )
        assert response.status_code == 302
        self.assert3xx(response, self.listed_url)
        addon = self.get_addon()
        assert addon.status == amo.STATUS_APPROVED
        assert addon.current_version
        assert addon.current_version.file.status == amo.STATUS_APPROVED
        assert addon.current_version.promoted_approvals.filter(
            group_id=RECOMMENDED.id
        ).exists()
        assert mock_sign_file.called

    @mock.patch('olympia.reviewers.utils.sign_file')
    def test_reasons_optional_for_approve(self, mock_sign_file):
        self.version.file.update(status=amo.STATUS_AWAITING_REVIEW)
        self.addon.update(status=amo.STATUS_NOMINATED)
        self.grant_permission(self.reviewer, 'Addons:RecommendedReview')
        response = self.client.post(
            self.url,
            {'action': 'public', 'comments': 'all good'},
        )
        assert response.status_code == 302
        assert mock_sign_file.called

    @mock.patch('olympia.reviewers.utils.sign_file')
    def test_admin_flagged_addon_actions_as_admin(self, mock_sign_file):
        reason = ReviewActionReason.objects.create(name='reason 1', is_active=True)
        self.version.file.update(status=amo.STATUS_AWAITING_REVIEW)
        self.addon.update(status=amo.STATUS_NOMINATED)
        AddonReviewerFlags.objects.create(
            addon=self.addon, needs_admin_code_review=True
        )
        self.login_as_admin()
        response = self.client.post(
            self.url, self.get_dict(action='public', reasons=[reason.id]), follow=True
        )
        assert response.status_code == 200
        addon = self.get_addon()
        assert self.version == addon.current_version
        assert addon.status == amo.STATUS_APPROVED
        assert addon.current_version.file.status == (amo.STATUS_APPROVED)

        assert mock_sign_file.called

    def test_admin_flagged_addon_actions_as_reviewer(self):
        self.version.file.update(status=amo.STATUS_AWAITING_REVIEW)
        self.addon.update(status=amo.STATUS_NOMINATED)
        AddonReviewerFlags.objects.create(
            addon=self.addon, needs_admin_code_review=True
        )
        self.login_as_reviewer()
        response = self.client.post(self.url, self.get_dict(action='public'))
        assert response.status_code == 200  # Form error.
        # The add-on status must not change as non-admin reviewers are not
        # allowed to review admin-flagged add-ons.
        addon = self.get_addon()
        assert addon.status == amo.STATUS_NOMINATED
        assert self.version == addon.current_version
        assert addon.current_version.file.status == (amo.STATUS_AWAITING_REVIEW)
        assert response.context['form'].errors['action'] == (
            ['Select a valid choice. public is not one of the available choices.']
        )

        # Same if it's the content review flag.
        flags = AddonReviewerFlags.objects.get(addon=self.addon)
        flags.update(needs_admin_content_review=True, needs_admin_code_review=False)
        response = self.client.post(self.url, self.get_dict(action='public'))
        assert response.status_code == 200  # Form error.
        addon = self.get_addon()
        assert addon.status == amo.STATUS_NOMINATED
        assert self.version == addon.current_version
        assert addon.current_version.file.status == (amo.STATUS_AWAITING_REVIEW)
        assert response.context['form'].errors['action'] == (
            ['Select a valid choice. public is not one of the available choices.']
        )

    def test_admin_flagged_addon_actions_as_content_reviewer(self):
        AddonReviewerFlags.objects.create(
            addon=self.addon, needs_admin_code_review=True
        )
        summary = AutoApprovalSummary.objects.create(
            version=self.addon.current_version, verdict=amo.AUTO_APPROVED
        )
        GroupUser.objects.filter(user=self.reviewer).all().delete()
        self.grant_permission(self.reviewer, 'Addons:ContentReview')
        content_url = reverse('reviewers.review', args=['content', self.addon.pk])
        response = self.client.post(
            content_url, self.get_dict(action='approve_content')
        )
        assert response.status_code == 302
        summary.reload()
        assert summary.confirmed is None  # We're only doing a content review.
        assert (
            ActivityLog.objects.filter(action=amo.LOG.CONFIRM_AUTO_APPROVED.id).count()
            == 0
        )
        assert (
            ActivityLog.objects.filter(action=amo.LOG.APPROVE_CONTENT.id).count() == 1
        )
        a_log = ActivityLog.objects.filter(action=amo.LOG.APPROVE_CONTENT.id).get()
        assert a_log.details['version'] == self.addon.current_version.version
        assert a_log.details['comments'] == ''
        self.assert3xx(response, content_url)

    def test_approve_content_content_review(self):
        GroupUser.objects.filter(user=self.reviewer).all().delete()
        content_url = reverse('reviewers.review', args=['content', self.addon.pk])
        summary = AutoApprovalSummary.objects.create(
            version=self.addon.current_version, verdict=amo.AUTO_APPROVED
        )
        self.grant_permission(self.reviewer, 'Addons:ContentReview')
        response = self.client.post(
            content_url,
            {
                'action': 'approve_content',
                'comments': 'ignore me this action does not support comments',
            },
        )
        assert response.status_code == 302
        summary.reload()
        assert summary.confirmed is None  # We're only doing a content review.
        assert (
            ActivityLog.objects.filter(action=amo.LOG.CONFIRM_AUTO_APPROVED.id).count()
            == 0
        )
        assert (
            ActivityLog.objects.filter(action=amo.LOG.APPROVE_CONTENT.id).count() == 1
        )
        a_log = ActivityLog.objects.filter(action=amo.LOG.APPROVE_CONTENT.id).get()
        assert a_log.details['version'] == self.addon.current_version.version
        assert a_log.details['comments'] == ''
        self.assert3xx(response, content_url)

    def test_cant_contentreview_if_admin_content_review_flag_is_set(self):
        GroupUser.objects.filter(user=self.reviewer).all().delete()
        content_url = reverse('reviewers.review', args=['content', self.addon.pk])
        AutoApprovalSummary.objects.create(
            version=self.addon.current_version, verdict=amo.AUTO_APPROVED
        )
        AddonReviewerFlags.objects.create(
            addon=self.addon, needs_admin_content_review=True
        )
        self.grant_permission(self.reviewer, 'Addons:ContentReview')
        response = self.client.post(
            content_url,
            {
                'action': 'approve_content',
                'comments': 'ignore me this action does not support comments',
            },
        )
        assert response.status_code == 200  # Form error
        assert (
            ActivityLog.objects.filter(action=amo.LOG.APPROVE_CONTENT.id).count() == 0
        )

    def test_content_review_redirect_if_only_permission(self):
        GroupUser.objects.filter(user=self.reviewer).all().delete()
        self.grant_permission(self.reviewer, 'Addons:ContentReview')
        content_url = reverse('reviewers.review', args=['content', self.addon.pk])
        response = self.client.get(self.url)
        assert response.status_code == 302
        self.assert3xx(response, content_url)

        response = self.client.post(self.url, {'action': 'anything'})
        assert response.status_code == 302
        self.assert3xx(response, content_url)

    def test_dont_content_review_redirect_if_theme_reviewer_only(self):
        GroupUser.objects.filter(user=self.reviewer).all().delete()
        self.grant_permission(self.reviewer, 'Addons:ThemeReview')
        self.grant_permission(self.reviewer, 'Addons:ContentReview')
        self.addon.update(type=amo.ADDON_STATICTHEME)
        response = self.client.get(self.url)
        assert response.status_code == 200

    def test_cant_postreview_if_admin_content_review_flag_is_set(self):
        AddonReviewerFlags.objects.create(
            addon=self.addon, needs_admin_content_review=True
        )
        self.grant_permission(self.reviewer, 'Addons:Review')
        for action in ['approve_content', 'reject_multiple_versions']:
            response = self.client.post(self.url, self.get_dict(action=action))
            assert response.status_code == 200  # Form error.
            # The add-on status must not change as non-admin reviewers are not
            # allowed to review admin-flagged add-ons.
            addon = self.get_addon()
            assert addon.status == amo.STATUS_APPROVED
            assert self.version == addon.current_version
            assert addon.current_version.file.status == (amo.STATUS_APPROVED)
            assert response.context['form'].errors['action'] == (
                [
                    'Select a valid choice. %s is not one of the available '
                    'choices.' % action
                ]
            )
            assert (
                ActivityLog.objects.filter(
                    action=amo.LOG.CONFIRM_AUTO_APPROVED.id
                ).count()
                == 0
            )
            assert (
                ActivityLog.objects.filter(action=amo.LOG.REJECT_VERSION.id).count()
                == 0
            )
            assert (
                ActivityLog.objects.filter(action=amo.LOG.APPROVE_VERSION.id).count()
                == 0
            )

    def test_cant_review_static_theme_if_admin_theme_review_flag_is_set(self):
        self.version.file.update(status=amo.STATUS_AWAITING_REVIEW)
        self.addon.update(type=amo.ADDON_STATICTHEME, status=amo.STATUS_NOMINATED)
        AddonReviewerFlags.objects.create(
            addon=self.addon, needs_admin_theme_review=True
        )
        self.grant_permission(self.reviewer, 'Addons:ThemeReview')
        for action in ['public', 'reject']:
            response = self.client.post(self.url, self.get_dict(action=action))
            assert response.status_code == 200  # Form error.
            # The add-on status must not change as non-admin reviewers are not
            # allowed to review admin-flagged add-ons.
            addon = self.get_addon()
            assert addon.status == amo.STATUS_NOMINATED
            assert self.version == addon.current_version
            assert addon.current_version.file.status == (amo.STATUS_AWAITING_REVIEW)
            assert response.context['form'].errors['action'] == (
                [
                    'Select a valid choice. %s is not one of the available '
                    'choices.' % action
                ]
            )
            assert (
                ActivityLog.objects.filter(action=amo.LOG.REJECT_VERSION.id).count()
                == 0
            )
            assert (
                ActivityLog.objects.filter(action=amo.LOG.APPROVE_VERSION.id).count()
                == 0
            )

    @mock.patch('olympia.reviewers.utils.sign_file')
    def test_admin_can_review_statictheme_if_admin_theme_review_flag_set(
        self, mock_sign_file
    ):
        reason = ReviewActionReason.objects.create(name='reason 1', is_active=True)
        self.version.file.update(status=amo.STATUS_AWAITING_REVIEW)
        self.addon.update(type=amo.ADDON_STATICTHEME, status=amo.STATUS_NOMINATED)
        AddonReviewerFlags.objects.create(
            addon=self.addon, needs_admin_theme_review=True
        )
        self.grant_permission(self.reviewer, 'Addons:ThemeReview')
        self.grant_permission(self.reviewer, 'Reviews:Admin')
        response = self.client.post(
            self.url,
            {'action': 'public', 'comments': 'it`s good', 'reasons': [reason.id]},
        )
        assert response.status_code == 302
        assert self.get_addon().status == amo.STATUS_APPROVED
        assert mock_sign_file.called

    def test_admin_can_contentreview_if_admin_content_review_flag_is_set(self):
        GroupUser.objects.filter(user=self.reviewer).all().delete()
        content_url = reverse('reviewers.review', args=['content', self.addon.pk])
        summary = AutoApprovalSummary.objects.create(
            version=self.addon.current_version, verdict=amo.AUTO_APPROVED
        )
        AddonReviewerFlags.objects.create(
            addon=self.addon, needs_admin_content_review=True
        )
        self.grant_permission(self.reviewer, 'Addons:ContentReview')
        self.grant_permission(self.reviewer, 'Reviews:Admin')
        response = self.client.post(
            content_url,
            {
                'action': 'approve_content',
                'comments': 'ignore me this action does not support comments',
            },
        )
        assert response.status_code == 302
        summary.reload()
        assert summary.confirmed is None  # We're only doing a content review.
        assert (
            ActivityLog.objects.filter(action=amo.LOG.CONFIRM_AUTO_APPROVED.id).count()
            == 0
        )
        assert (
            ActivityLog.objects.filter(action=amo.LOG.APPROVE_CONTENT.id).count() == 1
        )
        a_log = ActivityLog.objects.filter(action=amo.LOG.APPROVE_CONTENT.id).get()
        assert a_log.details['version'] == self.addon.current_version.version
        assert a_log.details['comments'] == ''
        self.assert3xx(response, content_url)

    def test_confirm_auto_approval_with_permission(self):
        summary = AutoApprovalSummary.objects.create(
            version=self.addon.current_version, verdict=amo.AUTO_APPROVED
        )
        GroupUser.objects.filter(user=self.reviewer).all().delete()
        self.grant_permission(self.reviewer, 'Addons:Review')
        response = self.client.post(
            self.url,
            {
                'action': 'confirm_auto_approved',
                'comments': 'ignore me this action does not support comments',
            },
        )
        summary.reload()
        assert response.status_code == 302
        assert summary.confirmed is True
        assert (
            ActivityLog.objects.filter(action=amo.LOG.CONFIRM_AUTO_APPROVED.id).count()
            == 1
        )
        a_log = ActivityLog.objects.filter(
            action=amo.LOG.CONFIRM_AUTO_APPROVED.id
        ).get()
        assert a_log.details['version'] == self.addon.current_version.version
        assert a_log.details['comments'] == ''
        self.assert3xx(response, self.listed_url)

    @mock.patch('olympia.reviewers.utils.sign_file')
    def test_approve_multiple_versions(self, sign_file_mock):
        self.url = reverse('reviewers.review', args=('unlisted', self.addon.pk))
        reason = ReviewActionReason.objects.create(name='reason 1', is_active=True)
        old_version = self.version
        old_version.update(needs_human_review=True, channel=amo.CHANNEL_UNLISTED)
        old_version.file.update(status=amo.STATUS_AWAITING_REVIEW)
        self.version = version_factory(
            addon=self.addon,
            version='3.0',
            channel=amo.CHANNEL_UNLISTED,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        GroupUser.objects.filter(user=self.reviewer).all().delete()
        self.grant_permission(self.reviewer, 'Addons:Review')
        self.grant_permission(self.reviewer, 'Addons:ReviewUnlisted')

        response = self.client.post(
            self.url,
            {
                'action': 'approve_multiple_versions',
                'comments': 'multi approve!',
                'reasons': [reason.id],
                'versions': [old_version.pk, self.version.pk],
            },
        )

        assert response.status_code == 302
        for version in [old_version, self.version]:
            version.reload()
            assert not version.needs_human_review
            file_ = version.file.reload()
            assert file_.status == amo.STATUS_APPROVED
            assert not version.pending_rejection

        sign_file_mock.assert_has_calls(
            (mock.call(old_version.file), mock.call(self.version.file))
        )

    @mock.patch('olympia.reviewers.utils.sign_file')
    def test_reasons_optional_for_multiple_approve(self, sign_file_mock):
        self.url = reverse('reviewers.review', args=('unlisted', self.addon.pk))
        old_version = self.version
        old_version.update(needs_human_review=True, channel=amo.CHANNEL_UNLISTED)
        old_version.file.update(status=amo.STATUS_AWAITING_REVIEW)
        self.version = version_factory(
            addon=self.addon,
            version='3.0',
            channel=amo.CHANNEL_UNLISTED,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        GroupUser.objects.filter(user=self.reviewer).all().delete()
        self.grant_permission(self.reviewer, 'Addons:Review')
        self.grant_permission(self.reviewer, 'Addons:ReviewUnlisted')

        response = self.client.post(
            self.url,
            {
                'action': 'approve_multiple_versions',
                'comments': 'multi approve!',
                'versions': [old_version.pk, self.version.pk],
            },
        )

        assert response.status_code == 302
        for version in [old_version, self.version]:
            version.reload()
            assert not version.needs_human_review
            file_ = version.file.reload()
            assert file_.status == amo.STATUS_APPROVED
            assert not version.pending_rejection

        sign_file_mock.assert_has_calls(
            (mock.call(old_version.file), mock.call(self.version.file))
        )

    def test_reject_multiple_versions(self):
        reason = ReviewActionReason.objects.create(name='reason 1', is_active=True)
        old_version = self.version
        old_version.update(needs_human_review=True)
        self.version = version_factory(addon=self.addon, version='3.0')
        AutoApprovalSummary.objects.create(
            version=self.addon.current_version, verdict=amo.AUTO_APPROVED
        )
        GroupUser.objects.filter(user=self.reviewer).all().delete()
        self.grant_permission(self.reviewer, 'Addons:Review')

        response = self.client.post(
            self.url,
            {
                'action': 'reject_multiple_versions',
                'comments': 'multireject!',
                'reasons': [reason.id],
                'versions': [old_version.pk, self.version.pk],
            },
        )

        assert response.status_code == 302
        for version in [old_version, self.version]:
            version.reload()
            assert not version.needs_human_review
            file_ = version.file.reload()
            assert file_.status == amo.STATUS_DISABLED
            assert not version.pending_rejection

    def test_reject_multiple_versions_with_no_delay(self):
        reason = ReviewActionReason.objects.create(name='reason 1', is_active=True)
        old_version = self.version
        old_version.update(needs_human_review=True)
        self.version = version_factory(addon=self.addon, version='3.0')
        AutoApprovalSummary.objects.create(
            version=self.addon.current_version, verdict=amo.AUTO_APPROVED
        )
        GroupUser.objects.filter(user=self.reviewer).all().delete()
        self.grant_permission(self.reviewer, 'Addons:Review')

        response = self.client.post(
            self.url,
            {
                'action': 'reject_multiple_versions',
                'comments': 'multireject!',
                'reasons': [reason.id],
                'versions': [old_version.pk, self.version.pk],
                'delayed_rejection': 'False',
                'delayed_rejection_days': (  # Should be ignored.
                    REVIEWER_DELAYED_REJECTION_PERIOD_DAYS_DEFAULT,
                ),
            },
        )

        assert response.status_code == 302
        for version in [old_version, self.version]:
            version.reload()
            assert not version.needs_human_review
            file_ = version.file.reload()
            assert file_.status == amo.STATUS_DISABLED
            assert not version.pending_rejection

    def test_reject_multiple_versions_with_delay(self):
        reason = ReviewActionReason.objects.create(name='reason 1', is_active=True)
        old_version = self.version
        old_version.update(needs_human_review=True)
        self.version = version_factory(addon=self.addon, version='3.0')
        AutoApprovalSummary.objects.create(
            version=self.addon.current_version, verdict=amo.AUTO_APPROVED
        )
        GroupUser.objects.filter(user=self.reviewer).all().delete()
        self.grant_permission(self.reviewer, 'Addons:Review')

        response = self.client.post(
            self.url,
            {
                'action': 'reject_multiple_versions',
                'comments': 'multireject with delay!',
                'reasons': [reason.id],
                'versions': [old_version.pk, self.version.pk],
                'delayed_rejection': 'True',
                'delayed_rejection_days': (
                    REVIEWER_DELAYED_REJECTION_PERIOD_DAYS_DEFAULT
                ),
            },
        )

        in_the_future = datetime.now() + timedelta(
            days=REVIEWER_DELAYED_REJECTION_PERIOD_DAYS_DEFAULT
        )
        assert response.status_code == 302
        for version in [old_version, self.version]:
            version.reload()
            # The versions no longer need human review...
            assert not version.needs_human_review
            file_ = version.file
            # ... But their status shouldn't have changed yet ...
            assert file_.status == amo.STATUS_APPROVED
            # ... Because they are now pending rejection.
            assert version.pending_rejection
            self.assertCloseToNow(version.pending_rejection, now=in_the_future)

    def test_unreject_multiple_versions(self):
        old_version = self.version
        version_factory(addon=self.addon, version='2.99')
        old_version.file.update(status=amo.STATUS_DISABLED)
        self.version = version_factory(
            addon=self.addon, version='3.0', file_kw={'status': amo.STATUS_DISABLED}
        )
        GroupUser.objects.filter(user=self.reviewer).all().delete()
        self.grant_permission(self.reviewer, 'Addons:Review')
        self.grant_permission(self.reviewer, 'Reviews:Admin')
        assert self.addon.status == amo.STATUS_APPROVED

        response = self.client.post(
            self.url,
            {
                'action': 'unreject_multiple_versions',
                'versions': [old_version.pk, self.version.pk],
            },
        )

        assert response.status_code == 302
        for version in [old_version, self.version]:
            file_ = version.file.reload()
            assert file_.status == amo.STATUS_AWAITING_REVIEW
        assert self.addon.reload().status == amo.STATUS_APPROVED

    def test_unreject_multiple_versions_to_nominated(self):
        old_version = self.version
        old_version.file.update(status=amo.STATUS_DISABLED)
        self.version = version_factory(
            addon=self.addon, version='3.0', file_kw={'status': amo.STATUS_DISABLED}
        )
        GroupUser.objects.filter(user=self.reviewer).all().delete()
        self.grant_permission(self.reviewer, 'Addons:Review')
        self.grant_permission(self.reviewer, 'Reviews:Admin')
        assert self.addon.status == amo.STATUS_NULL

        response = self.client.post(
            self.url,
            {
                'action': 'unreject_multiple_versions',
                'versions': [old_version.pk, self.version.pk],
            },
        )

        assert response.status_code == 302
        for version in [old_version, self.version]:
            file_ = version.file.reload()
            assert file_.status == amo.STATUS_AWAITING_REVIEW
        assert self.addon.reload().status == amo.STATUS_NOMINATED

    def test_unreject_multiple_versions_with_unlisted(self):
        old_version = self.version
        old_version.file.update(status=amo.STATUS_DISABLED)
        self.version = version_factory(
            addon=self.addon, version='3.0', file_kw={'status': amo.STATUS_DISABLED}
        )
        self.make_addon_unlisted(self.addon)
        GroupUser.objects.filter(user=self.reviewer).all().delete()
        self.grant_permission(self.reviewer, 'Addons:Review')
        self.grant_permission(self.reviewer, 'Reviews:Admin')
        self.grant_permission(self.reviewer, 'Addons:ReviewUnlisted')
        assert self.addon.status == amo.STATUS_NULL

        unlisted_url = reverse('reviewers.review', args=['unlisted', self.addon.pk])
        response = self.client.post(
            unlisted_url,
            {
                'action': 'unreject_multiple_versions',
                'versions': [old_version.pk, self.version.pk],
            },
        )

        assert response.status_code == 302
        for version in [old_version, self.version]:
            file_ = version.file.reload()
            assert file_.status == amo.STATUS_AWAITING_REVIEW
        assert self.addon.reload().status == amo.STATUS_NULL

    def test_block_multiple_versions(self):
        self.url = reverse('reviewers.review', args=('unlisted', self.addon.pk))
        old_version = self.version
        old_version.update(needs_human_review=True)
        self.version = version_factory(addon=self.addon, version='3.0')
        self.make_addon_unlisted(self.addon)
        self.grant_permission(self.reviewer, 'Addons:ReviewUnlisted')
        self.grant_permission(self.reviewer, 'Reviews:Admin')
        self.grant_permission(self.reviewer, 'Blocklist:Create')

        response = self.client.post(
            self.url,
            {
                'action': 'block_multiple_versions',
                'comments': 'multiblock!',  # should be ignored anyway
                'versions': [old_version.pk, self.version.pk],
            },
            follow=True,
        )

        new_block_url = reverse(
            'admin:blocklist_blocklistsubmission_add'
        ) + '?guids={}&min_version={}&max_version={}'.format(
            self.addon.guid,
            old_version.version,
            self.version.version,
        )
        self.assertRedirects(response, new_block_url)

    def test_important_changes_log(self):
        # Activity logs related to user changes should be displayed.
        # Create an activy log for each of the following: user addition, role
        # change and deletion.
        author = self.addon.addonuser_set.get()
        core.set_user(author.user)
        ActivityLog.create(
            amo.LOG.ADD_USER_WITH_ROLE,
            author.user,
            str(author.get_role_display()),
            self.addon,
        )
        ActivityLog.create(
            amo.LOG.CHANGE_USER_WITH_ROLE,
            author.user,
            str(author.get_role_display()),
            self.addon,
        )
        ActivityLog.create(
            amo.LOG.REMOVE_USER_WITH_ROLE,
            author.user,
            str(author.get_role_display()),
            self.addon,
        )
        ActivityLog.create(amo.LOG.FORCE_DISABLE, self.addon)
        ActivityLog.create(
            amo.LOG.FORCE_ENABLE,
            self.addon,
        )

        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert 'important_changes_log' in response.context
        important_changes_log = response.context['important_changes_log']
        actions = [log.action for log in important_changes_log]
        assert actions == [
            amo.LOG.ADD_USER_WITH_ROLE.id,
            amo.LOG.CHANGE_USER_WITH_ROLE.id,
            amo.LOG.REMOVE_USER_WITH_ROLE.id,
            amo.LOG.FORCE_DISABLE.id,
            amo.LOG.FORCE_ENABLE.id,
        ]

        # Make sure the logs are displayed in the page.
        important_changes = doc('#important-changes-history li')
        assert len(important_changes) == 5
        assert '(Owner) added to ' in important_changes[0].text_content()
        assert 'class' not in important_changes[1].attrib
        assert 'role changed to Owner for ' in important_changes[1].text_content()
        assert 'class' not in important_changes[1].attrib
        assert '(Owner) removed from ' in important_changes[2].text_content()
        assert 'class' not in important_changes[2].attrib
        assert (
            'regularuser التطب force-disabled Public.'
            in important_changes[3].text_content()
        )
        assert important_changes[3].attrib['class'] == 'reviewer-review-action'
        assert (
            'regularuser التطب force-enabled Public.'
            in important_changes[4].text_content()
        )
        assert important_changes[4].attrib['class'] == 'reviewer-review-action'

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

        FileValidation.objects.create(
            file=self.file, validation=json.dumps(amo.VALIDATOR_SKELETON_RESULTS)
        )

        response = self.client.get(self.url)
        assert response.status_code == 200

        assert not validate.called

    def test_review_is_review_listed(self):
        review_page = self.client.get(reverse('reviewers.review', args=[self.addon.pk]))
        listed_review_page = self.client.get(
            reverse('reviewers.review', args=['listed', self.addon.pk])
        )
        assert (
            pq(review_page.content)('#versions-history').text()
            == pq(listed_review_page.content)('#versions-history').text()
        )

    def test_approvals_info(self):
        approval_info = AddonApprovalsCounter.objects.create(
            addon=self.addon, last_human_review=datetime.now(), counter=42
        )
        AutoApprovalSummary.objects.create(
            version=self.version, verdict=amo.AUTO_APPROVED
        )
        self.grant_permission(self.reviewer, 'Addons:Review')
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
        self.grant_permission(self.reviewer, 'Addons:Review')
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert not doc('.auto_approval')

    def test_permissions_display(self):
        permissions = ['bookmarks', 'high', 'voltage']
        optional_permissions = ['optional', 'high', 'voltage']
        WebextPermission.objects.create(
            optional_permissions=optional_permissions,
            permissions=permissions,
            file=self.file,
        )
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        info = doc('#versions-history .file-info div')
        assert info.eq(1).text() == 'Permissions: ' + ', '.join(permissions)
        assert info.eq(2).text() == 'Optional permissions: ' + ', '.join(
            optional_permissions
        )

    def test_abuse_reports(self):
        report = AbuseReport.objects.create(
            guid=self.addon.guid,
            message='Et mël mazim ludus.',
            country_code='FR',
            client_id='4815162342',
            addon_name='Nâme',
            addon_summary='Not used here',
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
            addon_install_source_url='https://source.example.com/',
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
            'Install origin / source',
            'Category',
            'Date',
            'Reporter',
            'Nâme 42.0',  # We use the name as submitted in the abuse report.
            'Firefox for Android fr_FR Løst OS 20040922',
            '1\xa0day ago',
            'Origin: https://example.com/',
            'Method: Direct link',
            'Source: Unknown',
            'Source URL: https://source.example.com/',
            '',
            'Hateful, violent, or illegal content',
            created_at,
            'anonymous [FR]',
            'Et mël mazim ludus.',
        ]

        assert doc('.abuse_reports').text().split('\n') == expected

        self.addon.delete()
        self.url = reverse('reviewers.review', args=[self.addon.id])
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('.abuse_reports')
        assert doc('.abuse_reports').text().split('\n') == expected

    def test_abuse_reports_unlisted_addon(self):
        user = UserProfile.objects.get(email='reviewer@mozilla.com')
        self.grant_permission(user, 'Addons:ReviewUnlisted')
        self.login_as_reviewer()
        self.make_addon_unlisted(self.addon)
        self.test_abuse_reports()

    def test_abuse_reports_unlisted_addon_viewer(self):
        user = UserProfile.objects.get(email='reviewer@mozilla.com')
        self.grant_permission(user, 'ReviewerTools:ViewUnlisted')
        self.login_as_reviewer()
        self.make_addon_unlisted(self.addon)
        self.test_abuse_reports()

    def test_abuse_reports_developers(self):
        report = AbuseReport.objects.create(
            user=self.addon.listed_authors[0], message='Foo, Bâr!', country_code='DE'
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
            'Install origin / source',
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

    def test_abuse_reports_developers_unlisted_addon_viewer(self):
        user = UserProfile.objects.get(email='reviewer@mozilla.com')
        self.grant_permission(user, 'ReviewerTools:ViewUnlisted')
        self.login_as_reviewer()
        self.make_addon_unlisted(self.addon)
        self.test_abuse_reports_developers()

    def test_user_ratings(self):
        user = user_factory()
        rating = Rating.objects.create(
            body='Lôrem ipsum dolor',
            rating=3,
            ip_address='10.5.6.7',
            addon=self.addon,
            user=user,
        )
        created_at = format_date(rating.created)
        Rating.objects.create(  # Review with no body, ignored.
            rating=1, addon=self.addon, user=user_factory()
        )
        Rating.objects.create(  # Reply to a review, ignored.
            body='Replyyyyy', reply_to=rating, addon=self.addon, user=user_factory()
        )
        Rating.objects.create(  # Review with high rating,, ignored.
            body='Qui platônem temporibus in',
            rating=5,
            addon=self.addon,
            user=user_factory(),
        )
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('.user_ratings')
        assert doc('.user_ratings').text() == (
            '%s on %s [10.5.6.7]\n'
            'Rated 3 out of 5 stars\nLôrem ipsum dolor'
            % (
                user.name,
                created_at,
            )
        )
        # Addon details box contains the rating but link is absent
        assert doc('.addon-rating')
        assert not doc('.addon-rating a')

    def test_review_moderator_addon_rating_present(self):
        user = user_factory()
        Rating.objects.create(
            body='Lôrem ipsum dolor',
            rating=3,
            ip_address='10.5.6.7',
            addon=self.addon,
            user=user,
        )

        self.grant_permission(self.reviewer, 'Ratings:Moderate')

        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('.addon-rating a')
        rating_url = '{}?addon={}'.format(
            reverse_ns('admin:ratings_rating_changelist'), self.addon.pk
        )
        assert doc('.addon-rating a').attr['href'] == rating_url

        self.reviewer.update(email='reviewer@nonmozilla.com')

        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert not doc('.addon-rating a')

    def test_user_ratings_unlisted_addon(self):
        user = UserProfile.objects.get(email='reviewer@mozilla.com')
        self.grant_permission(user, 'Addons:ReviewUnlisted')
        self.login_as_reviewer()
        self.make_addon_unlisted(self.addon)
        self.test_user_ratings()

    def test_user_ratings_unlisted_addon_viewer(self):
        user = UserProfile.objects.get(email='reviewer@mozilla.com')
        self.grant_permission(user, 'ReviewerTools:ViewUnlisted')
        self.login_as_reviewer()
        self.make_addon_unlisted(self.addon)
        self.test_user_ratings()

    def test_data_value_attributes(self):
        AutoApprovalSummary.objects.create(
            verdict=amo.AUTO_APPROVED, version=self.version
        )
        self.grant_permission(self.reviewer, 'Addons:Review')
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)

        expected_actions_values = [
            'confirm_auto_approved|',
            'reject_multiple_versions|',
            'reply|',
            'super|',
            'comment|',
        ]
        assert [
            act.attrib['data-value'] for act in doc('.data-toggle.review-actions-desc')
        ] == expected_actions_values

        assert (
            doc('select#id_versions.data-toggle')[0].attrib['data-value']
            == 'reject_multiple_versions|'
        )

        assert (
            doc('select#id_versions.data-toggle option')[0].text
            == f'{self.version.version} - Auto-approved, not Confirmed'
        )

        assert (
            doc('.data-toggle.review-comments')[0].attrib['data-value']
            == 'reject_multiple_versions|reply|super|comment|'
        )

        assert (
            doc('.data-toggle.review-actions-reasons')[0].attrib['data-value']
            == 'reject_multiple_versions|reply|'
        )

        # We don't have approve/reject actions so these have an empty
        # data-value.
        assert doc('.data-toggle.review-files')[0].attrib['data-value'] == '|'
        assert doc('.data-toggle.review-tested')[0].attrib['data-value'] == '|'
        elm = doc('.data-toggle.review-delayed-rejection')[0]
        assert elm.attrib['data-value'] == 'reject_multiple_versions|'

    def test_data_value_attributes_unlisted(self):
        self.version.update(channel=amo.CHANNEL_UNLISTED)
        AutoApprovalSummary.objects.create(
            verdict=amo.AUTO_APPROVED, version=self.version
        )
        self.grant_permission(self.reviewer, 'Addons:ReviewUnlisted')
        unlisted_url = reverse('reviewers.review', args=['unlisted', self.addon.pk])
        response = self.client.get(unlisted_url)

        assert response.status_code == 200
        doc = pq(response.content)

        expected_actions_values = [
            'approve_multiple_versions|',
            'reject_multiple_versions|',
            'block_multiple_versions|',
            'confirm_multiple_versions|',
            'reply|',
            'super|',
            'comment|',
        ]
        assert [
            act.attrib['data-value'] for act in doc('.data-toggle.review-actions-desc')
        ] == expected_actions_values

        assert (
            doc('select#id_versions.data-toggle')[0].attrib['data-value']
            == 'approve_multiple_versions|'
            'reject_multiple_versions|'
            'block_multiple_versions|'
            'confirm_multiple_versions|'
        )

        assert (
            doc('.data-toggle.review-comments')[0].attrib['data-value']
            == 'approve_multiple_versions|reject_multiple_versions|reply|super|comment|'
        )

        assert (
            doc('.data-toggle.review-actions-reasons')[0].attrib['data-value']
            == 'approve_multiple_versions|reject_multiple_versions|reply|'
        )

        # We don't have approve/reject actions so these have an empty
        # data-value.
        assert doc('.data-toggle.review-files')[0].attrib['data-value'] == '|'
        assert doc('.data-toggle.review-tested')[0].attrib['data-value'] == '|'
        # Unlisted versions can't be rejected with a delay so the data-value of
        # the field is empty as well.
        elm = doc('.data-toggle.review-delayed-rejection')[0]
        assert elm.attrib['data-value'] == '|'

    def test_no_data_value_attributes_unlisted_for_viewer(self):
        self.version.update(channel=amo.CHANNEL_UNLISTED)
        AutoApprovalSummary.objects.create(
            verdict=amo.AUTO_APPROVED, version=self.version
        )
        unlisted_viewer = user_factory(email='unlisted_viewer@mozilla.com')
        self.grant_permission(unlisted_viewer, 'ReviewerTools:ViewUnlisted')
        self.client.logout()
        self.client.force_login(unlisted_viewer)
        unlisted_url = reverse('reviewers.review', args=['unlisted', self.addon.pk])
        response = self.client.get(unlisted_url)

        assert response.status_code == 200
        doc = pq(response.content)

        assert not doc('.data-toggle.review-actions-desc')
        assert not doc('select#id_versions.data-toggle')[0]
        assert doc('.data-toggle.review-comments')[0].attrib['data-value'] == '|'
        assert doc('.data-toggle.review-actions-reasons')[0].attrib['data-value'] == '|'
        assert doc('.data-toggle.review-files')[0].attrib['data-value'] == '|'
        assert doc('.data-toggle.review-tested')[0].attrib['data-value'] == '|'
        elm = doc('.data-toggle.review-delayed-rejection')[0]
        assert elm.attrib['data-value'] == '|'

    def test_data_value_attributes_unreviewed(self):
        self.file.update(status=amo.STATUS_AWAITING_REVIEW)
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)

        expected_actions_values = [
            'public|',
            'reject|',
            'reject_multiple_versions|',
            'reply|',
            'super|',
            'comment|',
        ]
        assert [
            act.attrib['data-value'] for act in doc('.data-toggle.review-actions-desc')
        ] == expected_actions_values

        assert 'data-value' not in doc('select#id_versions.data-toggle')[0]

        assert (
            doc('.data-toggle.review-comments')[0].attrib['data-value']
            == 'public|reject|reject_multiple_versions|reply|super|comment|'
        )
        assert (
            doc('.data-toggle.review-files')[0].attrib['data-value'] == 'public|reject|'
        )
        assert (
            doc('.data-toggle.review-tested')[0].attrib['data-value']
            == 'public|reject|'
        )
        assert (
            doc('.data-toggle.review-actions-reasons')[0].attrib['data-value']
            == 'public|reject|reject_multiple_versions|reply|'
        )

    def test_data_value_attributes_static_theme(self):
        self.addon.update(type=amo.ADDON_STATICTHEME)
        self.file.update(status=amo.STATUS_AWAITING_REVIEW)
        self.grant_permission(self.reviewer, 'Addons:ThemeReview')
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)

        expected_actions_values = [
            'public|',
            'reject|',
            'reject_multiple_versions|',
            'reply|',
            'super|',
            'comment|',
        ]
        assert [
            act.attrib['data-value'] for act in doc('.data-toggle.review-actions-desc')
        ] == expected_actions_values

        assert 'data-value' not in doc('select#id_versions.data-toggle')[0]

        assert (
            doc('.data-toggle.review-comments')[0].attrib['data-value']
            == 'public|reject|reject_multiple_versions|reply|super|comment|'
        )
        # we don't show files, reasons, and tested with for any static theme actions
        assert doc('.data-toggle.review-files')[0].attrib['data-value'] == '|'
        assert doc('.data-toggle.review-actions-reasons')[0].attrib['data-value'] == '|'
        assert doc('.data-toggle.review-tested')[0].attrib['data-value'] == '|'

    def test_post_review_ignore_disabled(self):
        # Though the latest version will be disabled, the add-on is public and
        # was auto-approved so the confirmation action is available.
        AutoApprovalSummary.objects.create(
            verdict=amo.AUTO_APPROVED, version=self.version
        )
        version_factory(addon=self.addon, file_kw={'status': amo.STATUS_DISABLED})
        self.grant_permission(self.reviewer, 'Addons:Review')
        response = self.client.get(self.url)
        assert response.status_code == 200
        expected_actions = [
            'confirm_auto_approved',
            'reject_multiple_versions',
            'reply',
            'super',
            'comment',
        ]
        assert [action[0] for action in response.context['actions']] == expected_actions

    def test_content_review_ignore_disabled(self):
        # Though the latest version will be disabled, the add-on is public and
        # was auto-approved so the content approval action is available.
        AutoApprovalSummary.objects.create(
            verdict=amo.AUTO_APPROVED, version=self.version
        )
        version_factory(addon=self.addon, file_kw={'status': amo.STATUS_DISABLED})
        self.grant_permission(self.reviewer, 'Addons:ContentReview')
        self.url = reverse('reviewers.review', args=['content', self.addon.pk])
        response = self.client.get(self.url)
        assert response.status_code == 200
        expected_actions = [
            'approve_content',
            'reject_multiple_versions',
            'reply',
            'super',
            'comment',
        ]
        assert [action[0] for action in response.context['actions']] == expected_actions

    def test_static_theme_backgrounds(self):
        self.addon.update(type=amo.ADDON_STATICTHEME)
        self.grant_permission(self.reviewer, 'Addons:ThemeReview')

        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        backgrounds_div = doc('div.all-backgrounds')
        assert backgrounds_div.attr('data-backgrounds-url') == (
            reverse(
                'reviewers.theme_background_images',
                args=[self.addon.current_version.id],
            )
        )

    def test_original_guid(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert b'Original Add-on ID' not in response.content

    def test_addons_sharing_guid_shown(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert b'Add-on(s) sharing same ID' not in response.content
        assert b'Original Add-on ID' not in response.content

        old_one = addon_factory(status=amo.STATUS_DELETED)
        old_two = addon_factory(status=amo.STATUS_DELETED)
        old_other = addon_factory(status=amo.STATUS_DELETED)
        old_noguid = addon_factory(status=amo.STATUS_DELETED)
        old_one.addonguid.update(guid='reuse@')
        old_two.addonguid.update(guid='reuse@')
        old_other.addonguid.update(guid='other@')
        old_noguid.addonguid.update(guid='')
        self.addon.addonguid.update(guid='reuse@')

        response = self.client.get(self.url)
        assert response.status_code == 200
        assert b'Add-on(s) sharing same ID' in response.content
        expected = [
            (f'{old_one}', reverse('reviewers.review', args=[old_one.id])),
            (f'{old_two}', reverse('reviewers.review', args=[old_two.id])),
        ]
        doc = pq(response.content)
        check_links(expected, doc('.addon-addons-sharing-guid a'), verify=False)

        assert b'Original Add-on ID' in response.content
        assert doc('.addon-guid td').text() == self.addon.guid
        assert doc('.addon-original-guid td').text() == self.addon.addonguid.guid

        # Test unlisted review pages link to unlisted review pages.
        self.make_addon_unlisted(self.addon)
        self.login_as_admin()
        response = self.client.get(
            reverse('reviewers.review', args=['unlisted', self.addon.pk])
        )
        assert response.status_code == 200
        expected = [
            (
                f'{old_one}',
                reverse('reviewers.review', args=['unlisted', old_one.id]),
            ),
            (
                f'{old_two}',
                reverse('reviewers.review', args=['unlisted', old_two.id]),
            ),
        ]
        doc = pq(response.content)
        check_links(expected, doc('.addon-addons-sharing-guid a'), verify=False)

        # It shouldn't happen nowadays, but make sure an empty guid isn't
        # considered.
        self.addon.addonguid.update(guid='')
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert b'Add-on(s) sharing same ID' not in response.content

    def test_versions_that_are_flagged_by_scanners_are_highlighted(self):
        self.addon.current_version.update(created=self.days_ago(366))
        customs_rule = ScannerRule.objects.create(name='ringo', scanner=CUSTOMS)
        yara_rule = ScannerRule.objects.create(name='star', scanner=YARA)
        for i in range(0, 10):
            # Add versions 1.0 to 1.9. Flag a few of them as needing human
            # review.
            matched_yara_rule = not bool(i % 3)
            matched_customs_rule = not bool(i % 3) and not bool(i % 2)
            version = version_factory(
                addon=self.addon,
                version=f'1.{i}',
                needs_human_review=matched_yara_rule or matched_customs_rule,
                created=self.days_ago(365 - i),
            )
            if matched_yara_rule:
                ScannerResult.objects.create(
                    scanner=yara_rule.scanner,
                    version=version,
                    results=[{'rule': yara_rule.name}],
                )
            if matched_customs_rule:
                ScannerResult.objects.create(
                    scanner=customs_rule.scanner,
                    version=version,
                    results={'matchedResults': [customs_rule.name]},
                )
        # Delete ActivityLog to make the query count easier to follow. We have
        # other tests for the ActivityLog related stuff.
        ActivityLog.objects.for_addons(self.addon).delete()
        with self.assertNumQueries(51):
            # See test_item_history_pagination() for more details about the
            # queries count. What's important here is that the extra versions
            # and scanner results don't cause extra queries.
            response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        tds = doc('#versions-history .review-files td.files')
        assert tds.length == 10
        # Original version should not be there any more, it's on the second
        # page. Versions on the page should be displayed in chronological order
        # Versions 1.0, 1.3, 1.6, 1.9 are flagged for human review.
        assert 'Flagged by scanners' in tds.eq(0).text()
        assert 'Flagged by scanners' in tds.eq(3).text()
        assert 'Flagged by scanners' in tds.eq(6).text()
        assert 'Flagged by scanners' in tds.eq(9).text()

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

    def test_versions_that_are_flagged_by_scanners_are_highlighted_admin(self):
        self.login_as_admin()
        self.addon.current_version.update(created=self.days_ago(366))
        customs_rule = ScannerRule.objects.create(name='ringo', scanner=CUSTOMS)
        yara_rule = ScannerRule.objects.create(name='star', scanner=YARA)
        for i in range(0, 10):
            # Add versions 1.0 to 1.9. Flag a few of them as needing human
            # review.
            matched_yara_rule = not bool(i % 3)
            matched_customs_rule = not bool(i % 3) and not bool(i % 2)
            version = version_factory(
                addon=self.addon,
                version=f'1.{i}',
                needs_human_review=matched_yara_rule or matched_customs_rule,
                created=self.days_ago(365 - i),
            )
            if matched_yara_rule:
                ScannerResult.objects.create(
                    scanner=yara_rule.scanner,
                    version=version,
                    results=[{'rule': yara_rule.name}],
                )
            if matched_customs_rule:
                ScannerResult.objects.create(
                    scanner=customs_rule.scanner,
                    version=version,
                    results={'matchedResults': [customs_rule.name]},
                )

        with self.assertNumQueries(53):
            # See test_item_history_pagination() for more details about the
            # queries count. What's important here is that the extra versions
            # and scanner results don't cause extra queries.
            # There are 2 extra queries caused by additional stuff available to
            # admins, but not more.
            response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        tds = doc('#versions-history .review-files td.files')
        assert tds.length == 10
        # Original version should not be there any more, it's on the second
        # page. Versions on the page should be displayed in chronological order
        # Versions 1.0, 1.3, 1.6, 1.9 are flagged for human review.
        assert 'Flagged by scanners (yara, customs)' in tds.eq(0).text()
        assert 'Flagged by scanners (yara)' in tds.eq(3).text()
        assert 'Flagged by scanners (yara, customs)' in tds.eq(6).text()
        assert 'Flagged by scanners (yara)' in tds.eq(9).text()
        # We're an admin so not only does the text mention the scanner name, but there
        # should be a link to the scanner result page. Let's check one.
        scanner_results = self.addon.versions.get(version='1.0').scannerresults.all()
        links = tds.eq(0).find('.risk-high a')
        for i, result in enumerate(scanner_results):
            assert links[i].attrib['href'] == reverse(
                'admin:scanners_scannerresult_change', args=(result.pk,)
            )

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

    def test_versions_that_needs_human_review_are_highlighted(self):
        self.addon.current_version.update(created=self.days_ago(366))
        for i in range(0, 10):
            # Add versions 1.0 to 1.9. Flag a few of them as needing human
            # review.
            version = version_factory(
                addon=self.addon, version=f'1.{i}', created=self.days_ago(365 - i)
            )
            version_review_flags_factory(
                version=version, needs_human_review_by_mad=not bool(i % 3)
            )

        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        tds = doc('#versions-history .review-files td.files')
        assert tds.length == 10
        # Original version should not be there any more, it's on the second
        # page. Versions on the page should be displayed in chronological order
        # Versions 1.0, 1.3, 1.6, 1.9 are flagged for human review.
        assert 'Flagged for human review' in tds.eq(0).text()
        assert 'Flagged for human review' in tds.eq(3).text()
        assert 'Flagged for human review' in tds.eq(6).text()
        assert 'Flagged for human review' in tds.eq(9).text()

        # There are no other flagged versions in the other page.
        span = doc('#review-files-header .risk-medium')
        assert span.length == 0

        # Load the second page. This time there should be a message indicating
        # there are flagged versions in other pages.
        response = self.client.get(self.url, {'page': 2})
        assert response.status_code == 200
        doc = pq(response.content)
        span = doc('#review-files-header .risk-medium')
        assert span.length == 1
        assert span.text() == '4 versions flagged for human review on other pages.'

    def test_blocked_versions(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert b'Blocked' not in response.content

        block = Block.objects.create(guid=self.addon.guid, updated_by=user_factory())
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

        block_reason = 'Very bad addon!'
        block.update(max_version='98', reason=block_reason)
        block_activity_log_save(obj=block, change=False)
        response = self.client.get(self.url)
        span = pq(response.content)('#versions-history .blocked-version')
        assert span.text() == 'Blocked'
        assert span.length == 1
        assert block_reason in (
            pq(response.content)('#versions-history .history-comment').text()
        )

    def test_redirect_after_review_unlisted(self):
        reason = ReviewActionReason.objects.create(name='reason 1', is_active=True)
        self.url = reverse('reviewers.review', args=('unlisted', self.addon.pk))
        self.version = version_factory(addon=self.addon, version='3.0')
        self.make_addon_unlisted(self.addon)
        self.grant_permission(self.reviewer, 'Addons:ReviewUnlisted')

        response = self.client.post(
            self.url,
            {
                'action': 'reply',
                'comments': 'Reply!',
                'reasons': [reason.id],
            },
            follow=True,
        )

        self.assertRedirects(response, self.url)

    def test_version_mismatch(self):
        response = self.client.get(self.url)
        assert (
            bytes(
                '<input type="hidden" name="version_pk" '
                f'value="{self.addon.current_version.pk}"/>',
                'utf-8',
            )
            in response.content
        )
        data = {
            'action': 'comment',
            'comments': 'random comment',
            'version_pk': self.addon.current_version.pk,
        }
        # A new version is created between the page being rendered and form submitted.
        version_factory(addon=self.addon)

        response = self.client.post(self.url, data, follow=True)
        assert response.status_code == 200
        self.assertFormError(
            response,
            'form',
            'version_pk',
            'Version mismatch - the latest version has changed!',
        )
        assert b'Version mismatch' in response.content
        assert (
            bytes(
                '<input type="hidden" name="version_pk" '
                f'value="{self.addon.current_version.pk}"/>',
                'utf-8',
            )
            in response.content
        )

        response = self.client.post(
            self.url, {**data, 'version_pk': self.addon.current_version.pk}, follow=True
        )
        self.assert3xx(response, self.listed_url)


class TestAbuseReportsView(ReviewerTest):
    def setUp(self):
        self.addon_developer = user_factory()
        self.addon = addon_factory(name='Flôp', users=[self.addon_developer])
        self.url = reverse('reviewers.abuse_reports', args=[self.addon.pk])
        self.login_as_reviewer()

    def test_abuse_reports(self):
        report = AbuseReport.objects.create(
            guid=self.addon.guid,
            message='Et mël mazim ludus.',
            country_code='FR',
            client_id='4815162342',
            addon_name='Nâme',
            addon_summary='Not used here',
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
            addon_install_source_url='https://source.example.com/',
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
            'Install origin / source',
            'Category',
            'Date',
            'Reporter',
            'Nâme 42.0',  # We use the name as submitted in the abuse report.
            'Firefox for Android fr_FR Løst OS 20040922',
            '1\xa0day ago',
            'Origin: https://example.com/',
            'Method: Direct link',
            'Source: Unknown',
            'Source URL: https://source.example.com/',
            '',
            'Hateful, violent, or illegal content',
            created_at,
            'anonymous [FR]',
            'Et mël mazim ludus.',
        ]

        assert doc('.abuse_reports').text().split('\n') == expected

        self.addon.delete()
        self.url = reverse('reviewers.abuse_reports', args=[self.addon.id])
        assert response.status_code == 200
        doc = pq(response.content)
        assert len(doc('.abuse_reports')) == 1
        assert doc('.abuse_reports').text().split('\n') == expected

    def test_queries(self):
        AbuseReport.objects.create(guid=self.addon.guid, message='One')
        AbuseReport.objects.create(guid=self.addon.guid, message='Two')
        AbuseReport.objects.create(guid=self.addon.guid, message='Three')
        AbuseReport.objects.create(user=self.addon_developer, message='Four')
        with self.assertNumQueries(18):
            # - 2 savepoint/release savepoint
            # - 2 for user and groups
            # - 1 for the add-on
            # - 1 for its translations
            # - 6 for the add-on / current version default transformer
            # - 1 for reviewer motd config
            # - 1 for site notice config
            # - 1 for add-ons from logged in user
            # - 1 for finding the original guid
            # - 1 for abuse reports count (pagination)
            # - 1 for the abuse reports
            response = self.client.get(self.url)
        assert response.status_code == 200


class TestReviewPending(ReviewBase):
    def setUp(self):
        super().setUp()
        self.file = self.version.file
        self.file.update(
            status=amo.STATUS_AWAITING_REVIEW,
        )
        self.addon.update(status=amo.STATUS_APPROVED)

    @mock.patch('olympia.reviewers.utils.sign_file')
    def test_pending_to_public(self, mock_sign):
        reason = ReviewActionReason.objects.create(name='reason 1', is_active=True)
        assert self.version.file.status == amo.STATUS_AWAITING_REVIEW

        response = self.client.post(
            self.url, self.get_dict(action='public', reasons=[reason.id])
        )
        assert self.get_addon().status == amo.STATUS_APPROVED
        self.assert3xx(response, self.listed_url)

        assert self.version.file.reload().status == amo.STATUS_APPROVED

        assert mock_sign.called

    def test_auto_approval_summary_with_post_review(self):
        AutoApprovalSummary.objects.create(
            version=self.version,
            verdict=amo.NOT_AUTO_APPROVED,
            is_locked=True,
        )
        self.grant_permission(self.reviewer, 'Addons:Review')
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        # Locked by a reviewer is shown.
        assert len(doc('.auto_approval li')) == 1
        assert doc('.auto_approval li').eq(0).text() == ('Is locked by a reviewer')

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

        response = self.client.post(
            reverse('reviewers.save_motd'), {'motd': "I'm a sneaky reviewer"}
        )
        assert response.status_code == 403

    def test_motd_edit_group(self):
        user = UserProfile.objects.get(email='reviewer@mozilla.com')
        group = Group.objects.create(
            name='Add-on Reviewer MOTD', rules='AddonReviewerMOTD:Edit'
        )
        GroupUser.objects.create(user=user, group=group)
        self.login_as_reviewer()
        response = self.client.post(
            reverse('reviewers.save_motd'), {'motd': 'I am the keymaster.'}
        )
        assert response.status_code == 302
        assert get_config('reviewers_review_motd') == 'I am the keymaster.'

    def test_form_errors(self):
        self.login_as_admin()
        response = self.client.post(self.get_url(save=True))
        doc = pq(response.content)
        assert doc('#reviewer-motd .errorlist').text() == ('This field is required.')


class TestStatusFile(ReviewBase):
    def get_file(self):
        return self.version.file

    def check_status(self, expected):
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#versions-history .file-info div').text() == (
            f'{expected} Permissions: None Optional permissions: None'
        )

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
    def test_whiteboard_addition(self):
        public_whiteboard_info = 'Public whiteboard info.'
        private_whiteboard_info = 'Private whiteboard info.'
        url = reverse('reviewers.whiteboard', args=['listed', self.addon.pk])
        self.client.force_login(
            UserProfile.objects.get(email='regular@mozilla.com')
        )  # No permissions.
        response = self.client.post(
            url,
            {
                'whiteboard-private': private_whiteboard_info,
                'whiteboard-public': public_whiteboard_info,
            },
        )
        assert response.status_code == 403  # Not a reviewer.

        self.login_as_reviewer()
        response = self.client.post(
            url,
            {
                'whiteboard-private': private_whiteboard_info,
                'whiteboard-public': public_whiteboard_info,
            },
        )
        self.assert3xx(
            response, reverse('reviewers.review', args=('listed', self.addon.pk))
        )

        whiteboard = self.addon.whiteboard.reload()
        assert whiteboard.public == public_whiteboard_info
        assert whiteboard.private == private_whiteboard_info

    def test_whiteboard_addition_content_review(self):
        public_whiteboard_info = 'Public whiteboard info for content.'
        private_whiteboard_info = 'Private whiteboard info for content.'
        url = reverse('reviewers.whiteboard', args=['content', self.addon.pk])
        self.client.force_login(
            UserProfile.objects.get(email='regular@mozilla.com')
        )  # No permissions.
        response = self.client.post(
            url,
            {
                'whiteboard-private': private_whiteboard_info,
                'whiteboard-public': public_whiteboard_info,
            },
        )
        assert response.status_code == 403  # Not a reviewer.

        self.login_as_reviewer()

        response = self.client.post(
            url,
            {
                'whiteboard-private': private_whiteboard_info,
                'whiteboard-public': public_whiteboard_info,
            },
        )
        self.assert3xx(
            response, reverse('reviewers.review', args=('content', self.addon.pk))
        )
        addon = self.addon.reload()
        assert addon.whiteboard.public == public_whiteboard_info
        assert addon.whiteboard.private == private_whiteboard_info

        public_whiteboard_info = 'New content for public'
        private_whiteboard_info = 'New content for private'
        user = UserProfile.objects.get(email='reviewer@mozilla.com')
        self.grant_permission(user, 'Addons:ContentReview')
        response = self.client.post(
            url,
            {
                'whiteboard-private': private_whiteboard_info,
                'whiteboard-public': public_whiteboard_info,
            },
        )
        self.assert3xx(
            response, reverse('reviewers.review', args=('content', self.addon.pk))
        )

        whiteboard = self.addon.whiteboard.reload()
        assert whiteboard.public == public_whiteboard_info
        assert whiteboard.private == private_whiteboard_info

    def test_whiteboard_addition_unlisted_addon(self):
        self.make_addon_unlisted(self.addon)
        public_whiteboard_info = 'Public whiteboard info unlisted.'
        private_whiteboard_info = 'Private whiteboard info unlisted.'
        url = reverse('reviewers.whiteboard', args=['unlisted', self.addon.pk])

        self.client.force_login(
            UserProfile.objects.get(email='regular@mozilla.com')
        )  # No permissions.
        response = self.client.post(
            url,
            {
                'whiteboard-private': private_whiteboard_info,
                'whiteboard-public': public_whiteboard_info,
            },
        )
        assert response.status_code == 403  # Not a reviewer.

        self.login_as_reviewer()
        response = self.client.post(
            url,
            {
                'whiteboard-private': private_whiteboard_info,
                'whiteboard-public': public_whiteboard_info,
            },
        )
        # Not an unlisted reviewer, raise PermissionDenied
        assert response.status_code == 403  # Not an unlisted reviewer.

        # Now the addon is not purely unlisted, but because we've requested the
        # unlisted channel we'll still get an error - this time it's a 403 from
        # the view itself
        version_factory(addon=self.addon, version='9.99', channel=amo.CHANNEL_LISTED)
        response = self.client.post(
            url,
            {
                'whiteboard-private': private_whiteboard_info,
                'whiteboard-public': public_whiteboard_info,
            },
        )
        assert response.status_code == 403

        # Everything works once you have permission.
        user = UserProfile.objects.get(email='reviewer@mozilla.com')
        self.grant_permission(user, 'Addons:ReviewUnlisted')
        response = self.client.post(
            url,
            {
                'whiteboard-private': private_whiteboard_info,
                'whiteboard-public': public_whiteboard_info,
            },
        )
        self.assert3xx(
            response, reverse('reviewers.review', args=('unlisted', self.addon.pk))
        )
        whiteboard = self.addon.whiteboard.reload()
        assert whiteboard.public == public_whiteboard_info
        assert whiteboard.private == private_whiteboard_info

    def test_delete_empty(self):
        url = reverse('reviewers.whiteboard', args=['listed', self.addon.pk])
        response = self.client.post(
            url, {'whiteboard-private': '', 'whiteboard-public': ''}
        )
        self.assert3xx(
            response, reverse('reviewers.review', args=('listed', self.addon.pk))
        )
        assert not Whiteboard.objects.filter(pk=self.addon.pk)


class TestWhiteboardDeleted(TestWhiteboard):
    def setUp(self):
        super().setUp()
        self.addon.delete()


class TestLeaderboard(ReviewerTest):
    fixtures = ['base/users']

    def setUp(self):
        super().setUp()
        self.url = reverse('reviewers.leaderboard')

        self.user = UserProfile.objects.get(email='reviewer@mozilla.com')
        self.login_as_reviewer()
        core.set_user(self.user)

    def _award_points(self, user, score):
        ReviewerScore.objects.create(
            user=user, note_key=amo.REVIEWED_MANUAL, score=score, note='Thing.'
        )

    def test_leaderboard_ranks(self):
        other_reviewer = UserProfile.objects.create(
            username='other_reviewer',
            display_name='',  # No display_name, will fall back on name.
            email='other_reviewer@mozilla.com',
        )
        self.grant_permission(
            other_reviewer,
            'Addons:Review',
            name='Reviewers: Add-ons',  # The name of the group matters here.
        )

        users = (
            self.user,
            UserProfile.objects.get(email='theme_reviewer@mozilla.com'),
            other_reviewer,
        )

        self._award_points(users[0], amo.REVIEWED_LEVELS[0]['points'] - 1)
        self._award_points(users[1], amo.REVIEWED_LEVELS[0]['points'] + 1)
        self._award_points(users[2], amo.REVIEWED_LEVELS[0]['points'] + 2)

        def get_cells():
            doc = pq(self.client.get(self.url).content.decode('utf-8'))

            cells = doc(
                '#leaderboard > tbody > tr > .name, '
                '#leaderboard > tbody > tr > .level'
            )

            return [cells.eq(i).text() for i in range(0, cells.length)]

        assert get_cells() == (
            [
                users[2].name,
                users[1].name,
                str(amo.REVIEWED_LEVELS[0]['name']),
                users[0].name,
            ]
        )

        self._award_points(users[0], 1)

        assert get_cells() == (
            [
                users[2].name,
                users[1].name,
                users[0].name,
                str(amo.REVIEWED_LEVELS[0]['name']),
            ]
        )

        self._award_points(users[0], -1)
        self._award_points(
            users[2],
            (amo.REVIEWED_LEVELS[1]['points'] - amo.REVIEWED_LEVELS[0]['points']),
        )

        assert get_cells() == (
            [
                users[2].name,
                str(amo.REVIEWED_LEVELS[1]['name']),
                users[1].name,
                str(amo.REVIEWED_LEVELS[0]['name']),
                users[0].name,
            ]
        )


class TestXssOnAddonName(amo.tests.TestXss):
    def test_reviewers_abuse_report_page(self):
        url = reverse('reviewers.abuse_reports', args=[self.addon.pk])
        self.assertNameAndNoXSS(url)

    def test_reviewers_review_page(self):
        url = reverse('reviewers.review', args=[self.addon.pk])
        self.assertNameAndNoXSS(url)


class TestPolicyView(ReviewerTest):
    def setUp(self):
        super().setUp()
        self.addon = addon_factory()
        self.eula_url = reverse('reviewers.eula', args=[self.addon.pk])
        self.privacy_url = reverse('reviewers.privacy', args=[self.addon.pk])
        self.login_as_reviewer()
        self.review_url = reverse(
            'reviewers.review',
            args=(
                'listed',
                self.addon.pk,
            ),
        )

    def test_eula(self):
        assert not bool(self.addon.eula)
        response = self.client.get(self.eula_url)
        assert response.status_code == 404

        self.addon.eula = 'Eulá!'
        self.addon.save()
        assert bool(self.addon.eula)
        response = self.client.get(self.eula_url)
        assert response.status_code == 200
        self.assertContains(response, f'{self.addon.name} – EULA')
        self.assertContains(response, 'End-User License Agreement')
        self.assertContains(response, 'Eulá!')
        self.assertContains(response, str(self.review_url))

    def test_eula_with_channel(self):
        self.make_addon_unlisted(self.addon)
        unlisted_review_url = reverse(
            'reviewers.review',
            args=(
                'unlisted',
                self.addon.pk,
            ),
        )
        self.addon.eula = 'Eulá!'
        self.addon.save()
        assert bool(self.addon.eula)
        response = self.client.get(self.eula_url + '?channel=unlisted')
        assert response.status_code == 403

        user = UserProfile.objects.get(email='regular@mozilla.com')
        self.grant_permission(user, 'Addons:ReviewUnlisted')
        self.client.force_login(user)
        response = self.client.get(self.eula_url + '?channel=unlisted')
        assert response.status_code == 200
        self.assertContains(response, 'Eulá!')
        self.assertContains(response, str(unlisted_review_url))

    def test_privacy(self):
        assert not bool(self.addon.privacy_policy)
        response = self.client.get(self.privacy_url)
        assert response.status_code == 404

        self.addon.privacy_policy = 'Prívacy Pólicy?'
        self.addon.save()
        assert bool(self.addon.privacy_policy)
        response = self.client.get(self.privacy_url)
        assert response.status_code == 200
        self.assertContains(response, f'{self.addon.name} – Privacy Policy')
        self.assertContains(response, 'Privacy Policy')
        self.assertContains(response, 'Prívacy Pólicy?')
        self.assertContains(response, str(self.review_url))

    def test_privacy_with_channel(self):
        self.make_addon_unlisted(self.addon)
        unlisted_review_url = reverse(
            'reviewers.review',
            args=(
                'unlisted',
                self.addon.pk,
            ),
        )
        self.addon.privacy_policy = 'Prívacy Pólicy?'
        self.addon.save()
        assert bool(self.addon.privacy_policy)
        response = self.client.get(self.privacy_url + '?channel=unlisted')
        assert response.status_code == 403

        user = UserProfile.objects.get(email='regular@mozilla.com')
        self.grant_permission(user, 'Addons:ReviewUnlisted')
        self.client.force_login(user)
        response = self.client.get(self.privacy_url + '?channel=unlisted')
        assert response.status_code == 200
        self.assertContains(response, 'Prívacy Pólicy?')
        self.assertContains(response, str(unlisted_review_url))


class TestAddonReviewerViewSet(TestCase):
    client_class = APITestClientSessionID

    def setUp(self):
        super().setUp()
        self.user = user_factory()
        self.addon = addon_factory()
        self.subscribe_url_listed = reverse_ns(
            'reviewers-addon-subscribe-listed', kwargs={'pk': self.addon.pk}
        )
        self.unsubscribe_url_listed = reverse_ns(
            'reviewers-addon-unsubscribe-listed', kwargs={'pk': self.addon.pk}
        )
        self.subscribe_url_unlisted = reverse_ns(
            'reviewers-addon-subscribe-unlisted', kwargs={'pk': self.addon.pk}
        )
        self.unsubscribe_url_unlisted = reverse_ns(
            'reviewers-addon-unsubscribe-unlisted', kwargs={'pk': self.addon.pk}
        )
        self.enable_url = reverse_ns(
            'reviewers-addon-enable', kwargs={'pk': self.addon.pk}
        )
        self.disable_url = reverse_ns(
            'reviewers-addon-disable', kwargs={'pk': self.addon.pk}
        )
        self.flags_url = reverse_ns(
            'reviewers-addon-flags', kwargs={'pk': self.addon.pk}
        )
        self.deny_resubmission_url = reverse_ns(
            'reviewers-addon-deny-resubmission', kwargs={'pk': self.addon.pk}
        )
        self.allow_resubmission_url = reverse_ns(
            'reviewers-addon-allow-resubmission', kwargs={'pk': self.addon.pk}
        )
        self.clear_pending_rejections_url = reverse_ns(
            'reviewers-addon-clear-pending-rejections', kwargs={'pk': self.addon.pk}
        )

    def test_subscribe_not_logged_in(self):
        response = self.client.post(self.subscribe_url_listed)
        assert response.status_code == 401
        response = self.client.post(self.subscribe_url_unlisted)
        assert response.status_code == 401

    def test_subscribe_no_rights(self):
        self.client.login_api(self.user)
        response = self.client.post(self.subscribe_url_listed)
        assert response.status_code == 403
        response = self.client.post(self.subscribe_url_unlisted)
        assert response.status_code == 403

    def test_subscribe_addon_does_not_exist(self):
        self.grant_permission(self.user, 'Addons:Review')
        self.client.login_api(self.user)
        self.subscribe_url_listed = reverse_ns(
            'reviewers-addon-subscribe-listed', kwargs={'pk': self.addon.pk + 42}
        )
        response = self.client.post(self.subscribe_url_listed)
        assert response.status_code == 404

        self.subscribe_url_listed = self.subscribe_url_listed.replace(
            f'{self.addon.pk + 42}', 'NaN'
        )
        response = self.client.post(self.subscribe_url_listed)
        assert response.status_code == 404

    def test_subscribe_already_subscribed_listed(self):
        ReviewerSubscription.objects.create(
            user=self.user, addon=self.addon, channel=amo.CHANNEL_LISTED
        )
        self.grant_permission(self.user, 'Addons:Review')
        self.client.login_api(self.user)
        response = self.client.post(self.subscribe_url_listed)
        assert response.status_code == 202
        assert ReviewerSubscription.objects.count() == 1

    def test_subscribe_already_subscribed_unlisted(self):
        ReviewerSubscription.objects.create(
            user=self.user, addon=self.addon, channel=amo.CHANNEL_UNLISTED
        )
        self.grant_permission(self.user, 'Addons:ReviewUnlisted')
        self.client.login_api(self.user)
        response = self.client.post(self.subscribe_url_unlisted)
        assert response.status_code == 202
        assert ReviewerSubscription.objects.count() == 1

    def test_subscribe_already_subscribed_unlisted_viewer(self):
        ReviewerSubscription.objects.create(
            user=self.user, addon=self.addon, channel=amo.CHANNEL_UNLISTED
        )
        self.grant_permission(self.user, 'ReviewerTools:ViewUnlisted')
        self.client.login_api(self.user)
        response = self.client.post(self.subscribe_url_unlisted)
        assert response.status_code == 202
        assert ReviewerSubscription.objects.count() == 1

    def test_subscribe(self):
        self.grant_permission(self.user, 'Addons:Review')
        self.client.login_api(self.user)
        subscribe_url = reverse_ns(
            'reviewers-addon-subscribe', kwargs={'pk': self.addon.pk}
        )
        response = self.client.post(subscribe_url)
        assert response.status_code == 202
        assert ReviewerSubscription.objects.count() == 1

    def test_subscribe_listed(self):
        self.grant_permission(self.user, 'Addons:Review')
        self.client.login_api(self.user)
        response = self.client.post(self.subscribe_url_listed)
        assert response.status_code == 202
        assert ReviewerSubscription.objects.count() == 1

    def test_subscribe_unlisted(self):
        self.grant_permission(self.user, 'Addons:ReviewUnlisted')
        self.client.login_api(self.user)
        response = self.client.post(self.subscribe_url_unlisted)
        assert response.status_code == 202
        assert ReviewerSubscription.objects.count() == 1

    def test_subscribe_unlisted_viewer(self):
        self.grant_permission(self.user, 'ReviewerTools:ViewUnlisted')
        self.client.login_api(self.user)
        response = self.client.post(self.subscribe_url_unlisted)
        assert response.status_code == 202
        assert ReviewerSubscription.objects.count() == 1

    def test_unsubscribe_not_logged_in(self):
        response = self.client.post(self.unsubscribe_url_listed)
        assert response.status_code == 401
        response = self.client.post(self.unsubscribe_url_unlisted)
        assert response.status_code == 401

    def test_unsubscribe_no_rights(self):
        self.client.login_api(self.user)
        response = self.client.post(self.unsubscribe_url_listed)
        assert response.status_code == 403
        response = self.client.post(self.unsubscribe_url_unlisted)
        assert response.status_code == 403

    def test_unsubscribe_addon_does_not_exist(self):
        self.grant_permission(self.user, 'Addons:Review')
        self.client.login_api(self.user)
        self.subscribe_url_listed = reverse_ns(
            'reviewers-addon-subscribe-listed', kwargs={'pk': self.addon.pk + 42}
        )
        response = self.client.post(self.subscribe_url_listed)
        assert response.status_code == 404

        self.subscribe_url_listed = self.subscribe_url_listed.replace(
            f'{self.addon.pk + 42}', 'NaN'
        )
        response = self.client.post(self.subscribe_url_listed)
        assert response.status_code == 404

    def test_unsubscribe_not_subscribed(self):
        self.grant_permission(self.user, 'Addons:Review')
        self.client.login_api(self.user)
        response = self.client.post(self.unsubscribe_url_listed)
        assert response.status_code == 202
        assert ReviewerSubscription.objects.count() == 0

        self.grant_permission(self.user, 'Addons:ReviewUnlisted')
        self.client.login_api(self.user)
        response = self.client.post(self.unsubscribe_url_unlisted)
        assert response.status_code == 202
        assert ReviewerSubscription.objects.count() == 0

    def test_unsubscribe(self):
        ReviewerSubscription.objects.create(
            user=self.user, addon=self.addon, channel=amo.CHANNEL_LISTED
        )
        self.grant_permission(self.user, 'Addons:Review')
        self.client.login_api(self.user)
        unsubscribe_url = reverse_ns(
            'reviewers-addon-unsubscribe', kwargs={'pk': self.addon.pk}
        )
        response = self.client.post(unsubscribe_url)
        assert response.status_code == 202
        assert ReviewerSubscription.objects.count() == 0

    def test_unsubscribe_listed(self):
        ReviewerSubscription.objects.create(
            user=self.user, addon=self.addon, channel=amo.CHANNEL_LISTED
        )
        self.grant_permission(self.user, 'Addons:Review')
        self.client.login_api(self.user)
        response = self.client.post(self.unsubscribe_url_listed)
        assert response.status_code == 202
        assert ReviewerSubscription.objects.count() == 0

    def test_unsubscribe_unlisted(self):
        ReviewerSubscription.objects.create(
            user=self.user, addon=self.addon, channel=amo.CHANNEL_UNLISTED
        )
        self.grant_permission(self.user, 'Addons:ReviewUnlisted')
        self.client.login_api(self.user)
        response = self.client.post(self.unsubscribe_url_unlisted)
        assert response.status_code == 202
        assert ReviewerSubscription.objects.count() == 0

    def test_unsubscribe_unlisted_viewer(self):
        ReviewerSubscription.objects.create(
            user=self.user, addon=self.addon, channel=amo.CHANNEL_UNLISTED
        )
        self.grant_permission(self.user, 'ReviewerTools:ViewUnlisted')
        self.client.login_api(self.user)
        response = self.client.post(self.unsubscribe_url_unlisted)
        assert response.status_code == 202
        assert ReviewerSubscription.objects.count() == 0

    def test_unsubscribe_dont_touch_another(self):
        another_user = user_factory()
        another_addon = addon_factory()
        ReviewerSubscription.objects.create(
            user=self.user, addon=self.addon, channel=amo.CHANNEL_LISTED
        )
        ReviewerSubscription.objects.create(
            user=self.user, addon=another_addon, channel=amo.CHANNEL_LISTED
        )
        ReviewerSubscription.objects.create(
            user=another_user, addon=self.addon, channel=amo.CHANNEL_LISTED
        )
        self.grant_permission(self.user, 'Addons:Review')
        self.client.login_api(self.user)
        response = self.client.post(self.unsubscribe_url_listed)
        assert response.status_code == 202
        assert ReviewerSubscription.objects.count() == 2
        assert not ReviewerSubscription.objects.filter(
            addon=self.addon, user=self.user
        ).exists()

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
            'reviewers-addon-enable', kwargs={'pk': self.addon.pk + 42}
        )
        response = self.client.post(self.enable_url)
        assert response.status_code == 404

        self.enable_url = self.enable_url.replace(f'{self.addon.pk + 42}', 'NaN')
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
        assert activity_log.action == amo.LOG.FORCE_ENABLE.id
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
        assert activity_log.action == amo.LOG.FORCE_ENABLE.id
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
        self.addon.current_version.file.update(status=amo.STATUS_AWAITING_REVIEW)
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
            'reviewers-addon-disable', kwargs={'pk': self.addon.pk + 42}
        )
        response = self.client.post(self.disable_url)
        assert response.status_code == 404

        self.disable_url = self.disable_url.replace(f'{self.addon.pk + 42}', 'NaN')
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
        assert activity_log.action == amo.LOG.FORCE_DISABLE.id
        assert activity_log.arguments[0] == self.addon

    def test_patch_flags_not_logged_in(self):
        response = self.client.patch(self.flags_url, {'auto_approval_disabled': True})
        assert response.status_code == 401

    def test_patch_flags_no_permissions(self):
        self.client.login_api(self.user)
        response = self.client.patch(self.flags_url, {'auto_approval_disabled': True})
        assert response.status_code == 403

        # Being a reviewer is not enough.
        self.grant_permission(self.user, 'Addons:Review')
        response = self.client.patch(self.flags_url, {'auto_approval_disabled': True})
        assert response.status_code == 403

    def test_patch_flags_addon_does_not_exist(self):
        self.grant_permission(self.user, 'Reviews:Admin')
        self.client.login_api(self.user)
        self.flags_url = reverse_ns(
            'reviewers-addon-flags', kwargs={'pk': self.addon.pk + 42}
        )
        response = self.client.patch(self.flags_url, {'auto_approval_disabled': True})
        assert response.status_code == 404

        self.flags_url = self.flags_url.replace(f'{self.addon.pk + 42}', 'NaN')
        response = self.client.post(self.flags_url)
        assert response.status_code == 404

    def test_patch_flags_no_flags_yet_still_works_transparently(self):
        assert not AddonReviewerFlags.objects.filter(addon=self.addon).exists()
        self.grant_permission(self.user, 'Reviews:Admin')
        self.client.login_api(self.user)
        response = self.client.patch(self.flags_url, {'auto_approval_disabled': True})
        assert response.status_code == 200
        assert AddonReviewerFlags.objects.filter(addon=self.addon).exists()
        reviewer_flags = AddonReviewerFlags.objects.get(addon=self.addon)
        assert reviewer_flags.auto_approval_disabled
        assert ActivityLog.objects.count() == 0

    def test_patch_flags_change_everything(self):
        AddonReviewerFlags.objects.create(
            addon=self.addon,
            auto_approval_disabled=True,
            auto_approval_disabled_unlisted=True,
            auto_approval_delayed_until=self.days_ago(42),
        )
        self.grant_permission(self.user, 'Reviews:Admin')
        self.client.login_api(self.user)
        data = {
            'auto_approval_disabled': False,
            'auto_approval_disabled_unlisted': False,
            'auto_approval_disabled_until_next_approval': True,
            'auto_approval_disabled_until_next_approval_unlisted': True,
            'auto_approval_delayed_until': None,
            'needs_admin_code_review': True,
            'needs_admin_content_review': True,
            'needs_admin_theme_review': True,
        }
        response = self.client.patch(self.flags_url, data)
        assert response.status_code == 200
        assert AddonReviewerFlags.objects.filter(addon=self.addon).exists()
        reviewer_flags = AddonReviewerFlags.objects.get(addon=self.addon)
        assert reviewer_flags.auto_approval_disabled is False
        assert reviewer_flags.auto_approval_disabled_unlisted is False
        assert reviewer_flags.auto_approval_disabled_until_next_approval is True
        assert (
            reviewer_flags.auto_approval_disabled_until_next_approval_unlisted is True
        )
        assert reviewer_flags.auto_approval_delayed_until is None
        assert reviewer_flags.needs_admin_code_review is True
        assert reviewer_flags.needs_admin_content_review is True
        assert reviewer_flags.needs_admin_theme_review is True

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

    def test_clear_pending_rejections(self):
        self.grant_permission(self.user, 'Reviews:Admin')
        self.client.login_api(self.user)
        version_factory(addon=self.addon)
        for version in self.addon.versions.all():
            version_review_flags_factory(
                version=version,
                pending_rejection=datetime.now() + timedelta(days=7),
                pending_rejection_by=user_factory(),
                pending_content_rejection=False,
            )
        response = self.client.post(self.clear_pending_rejections_url)
        assert response.status_code == 202
        assert not VersionReviewerFlags.objects.filter(
            version__addon=self.addon, pending_rejection__isnull=False
        ).exists()
        assert not VersionReviewerFlags.objects.filter(
            version__addon=self.addon, pending_rejection_by__isnull=False
        ).exists()
        assert not VersionReviewerFlags.objects.filter(
            version__addon=self.addon, pending_content_rejection__isnull=False
        ).exists()


class TestAddonReviewerViewSetJsonValidation(TestCase):
    client_class = APITestClientSessionID
    fixtures = ['devhub/addon-validation-1']

    def setUp(self):
        super().setUp()
        self.user = user_factory()
        file_validation = FileValidation.objects.get(pk=1)
        self.file = file_validation.file
        self.addon = self.file.version.addon
        self.url = reverse_ns(
            'reviewers-addon-json-file-validation',
            kwargs={'pk': self.addon.pk, 'file_id': self.file.pk},
        )

    def test_reviewer_can_see_json_results(self):
        self.grant_permission(self.user, 'Addons:Review')
        self.client.login_api(self.user)
        assert self.client.get(self.url).status_code == 200

    def test_deleted_addon(self):
        self.grant_permission(self.user, 'Addons:Review')
        self.client.login_api(self.user)

        self.addon.delete()
        assert self.client.get(self.url).status_code == 200

    def test_unlisted_reviewer_can_see_results_for_unlisted(self):
        self.grant_permission(self.user, 'Addons:ReviewUnlisted')
        self.client.login_api(self.user)
        self.make_addon_unlisted(self.addon)
        assert self.client.get(self.url).status_code == 200

    def test_unlisted_viewer_can_see_results_for_unlisted(self):
        self.grant_permission(self.user, 'ReviewerTools:ViewUnlisted')
        self.client.login_api(self.user)
        self.make_addon_unlisted(self.addon)
        assert self.client.get(self.url).status_code == 200

    def test_non_reviewer_cannot_see_json_results(self):
        self.client.login_api(self.user)
        assert self.client.get(self.url).status_code == 403

    @mock.patch.object(acl, 'is_reviewer', lambda user, addon: False)
    def test_wrong_type_of_reviewer_cannot_see_json_results(self):
        self.grant_permission(self.user, 'Addons:Review')
        self.client.login_api(self.user)
        assert self.client.get(self.url).status_code == 403

    def test_non_unlisted_reviewer_cannot_see_results_for_unlisted(self):
        self.grant_permission(self.user, 'Addons:Review')
        self.client.login_api(self.user)
        self.make_addon_unlisted(self.addon)
        assert self.client.get(self.url).status_code == 403


class AddonReviewerViewSetPermissionMixin:
    __test__ = False

    def test_disabled_version_reviewer(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)
        self.version.file.update(status=amo.STATUS_DISABLED)
        self._test_url()

    def test_author(self):
        user = UserProfile.objects.create(username='author')
        AddonUser.objects.create(user=user, addon=self.addon)
        self.client.login_api(user)
        response = self.client.get(self.url)
        assert response.status_code == 403

    def test_disabled_version_admin(self):
        user = UserProfile.objects.create(username='admin')
        self.grant_permission(user, '*:*')
        self.client.login_api(user)
        self.version.file.update(status=amo.STATUS_DISABLED)
        self._test_url()

    def test_disabled_version_user(self):
        user = UserProfile.objects.create(username='simpleuser')
        self.client.login_api(user)
        self.version.file.update(status=amo.STATUS_DISABLED)
        response = self.client.get(self.url)
        assert response.status_code == 403

    def test_deleted_version_reviewer(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
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

    def test_deleted_version_user(self):
        user = UserProfile.objects.create(username='simpleuser')
        self.client.login_api(user)
        self.version.delete()
        response = self.client.get(self.url)
        assert response.status_code == 404

    def test_unlisted_version_reviewer(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)
        self.version.update(channel=amo.CHANNEL_UNLISTED)
        response = self.client.get(self.url)
        assert response.status_code == 404

    def test_unlisted_version_unlisted_reviewer(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:ReviewUnlisted')
        self.client.login_api(user)
        self.version.update(channel=amo.CHANNEL_UNLISTED)
        self._test_url()

    def test_unlisted_version_unlisted_viewer(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'ReviewerTools:ViewUnlisted')
        self.client.login_api(user)
        self.version.update(channel=amo.CHANNEL_UNLISTED)
        self._test_url()

    def test_unlisted_version_admin(self):
        user = UserProfile.objects.create(username='admin')
        self.grant_permission(user, '*:*')
        self.client.login_api(user)
        self.version.update(channel=amo.CHANNEL_UNLISTED)
        self._test_url()

    def test_unlisted_version_user(self):
        user = UserProfile.objects.create(username='simpleuser')
        self.client.login_api(user)
        self.version.update(channel=amo.CHANNEL_UNLISTED)
        response = self.client.get(self.url)
        assert response.status_code == 404


class TestReviewAddonVersionViewSetDetail(
    TestCase, AddonReviewerViewSetPermissionMixin
):
    client_class = APITestClientSessionID
    __test__ = True

    def setUp(self):
        super().setUp()

        # TODO: Most of the initial setup could be moved to
        # setUpTestData but unfortunately paths are setup in pytest via a
        # regular autouse fixture that has function-scope so functions in
        # setUpTestData doesn't use proper paths (cgrebs)
        self.addon = addon_factory(
            name='My Addôn',
            slug='my-addon',
            file_kw={'filename': 'webextension_no_id.xpi'},
        )

        extract_version_to_git(self.addon.current_version.pk)

        self.version = self.addon.current_version
        self.version.refresh_from_db()

        self._set_tested_url()

    def _test_url(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        result = json.loads(response.content)
        assert result['id'] == self.version.pk
        assert result['file']['id'] == self.version.file.pk

        # part of manifest.json
        assert '"name": "Beastify"' in result['file']['content']

    def _set_tested_url(self):
        self.url = reverse_ns(
            'reviewers-versions-detail',
            kwargs={'addon_pk': self.addon.pk, 'pk': self.version.pk},
        )

    def test_anonymous(self):
        response = self.client.get(self.url)
        assert response.status_code == 401

    def test_requested_file(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)

        with self.assertNumQueries(9):
            # - 2 savepoints because tests
            # - 2 user and groups
            # - 2 add-on and translations
            # - 1 add-on author check
            # - 1 version + file
            # - 1 file validation
            response = self.client.get(self.url + '?file=README.md&lang=en-US')
        assert response.status_code == 200
        result = json.loads(response.content)

        assert result['addon']['name'] == {'en-US': str(self.addon.name)}

        assert result['file']['content'] == '# beastify\n'
        assert result['file_entries'] is not None

        # make sure the correct download url is correctly generated
        assert result['file']['download_url'] == absolutify(
            reverse(
                'reviewers.download_git_file',
                kwargs={'version_id': self.version.pk, 'filename': 'README.md'},
            )
        )

    def test_non_existent_requested_file_returns_404(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)

        response = self.client.get(self.url + '?file=UNKNOWN_FILE')
        assert response.status_code == 404

    def test_requested_file_contains_whitespace(self):
        new_version = version_factory(
            addon=self.addon,
            file_kw={'filename': 'webextension_no_id.xpi'},
        )

        repo = AddonGitRepository.extract_and_commit_from_version(new_version)

        apply_changes(repo, new_version, '(function() {})\n', 'content script.js')

        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)

        url = reverse_ns(
            'reviewers-versions-detail',
            kwargs={'addon_pk': self.addon.pk, 'pk': new_version.pk},
        )

        response = self.client.get(url + '?file=content script.js')
        assert response.status_code == 200
        result = json.loads(response.content)

        assert result['file']['content'] == '(function() {})\n'

        # make sure the correct download url is correctly generated
        assert result['file']['download_url'] == absolutify(
            reverse(
                'reviewers.download_git_file',
                kwargs={'version_id': new_version.pk, 'filename': 'content script.js'},
            )
        )

    def test_version_get_not_found(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)
        self.url = reverse_ns(
            'reviewers-versions-detail',
            kwargs={'addon_pk': self.addon.pk, 'pk': self.version.file.pk + 42},
        )
        response = self.client.get(self.url)
        assert response.status_code == 404

        self.url = self.url.replace(f'{self.addon.pk + 42}', 'NaN')
        response = self.client.get(self.url)
        assert response.status_code == 404

    def test_addon_get_not_found(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)
        self.url = reverse_ns(
            'reviewers-versions-detail',
            kwargs={'addon_pk': self.addon.pk + 42, 'pk': self.version.file.pk},
        )
        response = self.client.get(self.url)
        assert response.status_code == 404

        self.url = self.url.replace(f'{self.version.file.pk + 42}', 'NaN')
        response = self.client.get(self.url)
        assert response.status_code == 404

    def test_mixed_channel_only_listed_without_unlisted_perm(self):
        user = UserProfile.objects.create(username='admin')

        # User doesn't have ReviewUnlisted permission
        self.grant_permission(user, 'Addons:Review')

        self.client.login_api(user)

        # Add an unlisted version to the mix
        unlisted_version = version_factory(
            addon=self.addon, channel=amo.CHANNEL_UNLISTED
        )

        # Now the add-on has both, listed and unlisted versions
        # but only reviewers with Addons:ReviewUnlisted are able
        # to see them
        url = reverse_ns(
            'reviewers-versions-detail',
            kwargs={'addon_pk': self.addon.pk, 'pk': self.version.pk},
        )

        response = self.client.get(url)
        assert response.status_code == 200

        url = reverse_ns(
            'reviewers-versions-detail',
            kwargs={'addon_pk': self.addon.pk, 'pk': unlisted_version.pk},
        )

        response = self.client.get(url)
        assert response.status_code == 404

    def test_file_only_requested_file(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)

        with self.assertNumQueries(9):
            # - 2 savepoints because tests
            # - 2 user and groups
            # - 2 add-on and translations
            # - 1 add-on author check
            # - 1 version + file
            # - 1 file validation
            response = self.client.get(
                self.url + '?file=README.md&lang=en-US&file_only=true'
            )
        assert response.status_code == 200
        result = json.loads(response.content)

        assert result['id'] == self.version.pk
        assert result['file']['content'] == '# beastify\n'

        # make sure the correct download url is correctly generated
        assert result['file']['download_url'] == absolutify(
            reverse(
                'reviewers.download_git_file',
                kwargs={'version_id': self.version.pk, 'filename': 'README.md'},
            )
        )

        # make sure we only returned `id` and `file` properties
        assert len(result.keys()) == 2

    def test_file_only_false(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)

        response = self.client.get(
            self.url + '?file=README.md&lang=en-US&file_only=false'
        )
        result = json.loads(response.content)

        assert result['id'] == self.version.pk
        assert result['file']['content'] == '# beastify\n'

        # make sure we returned more than just the `id` and `file` properties
        assert len(result.keys()) > 2

    def test_deleted_addon(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.grant_permission(user, 'Addons:ViewDeleted')
        self.client.login_api(user)

        self.addon.delete()
        response = self.client.get(self.url)
        assert response.status_code == 200
        result = json.loads(response.content)
        assert result['id'] == self.version.pk


class TestReviewAddonVersionViewSetList(TestCase):
    client_class = APITestClientSessionID

    def setUp(self):
        super().setUp()

        self.addon = addon_factory(
            name='My Addôn',
            slug='my-addon',
            file_kw={'filename': 'webextension_no_id.xpi'},
        )

        extract_version_to_git(self.addon.current_version.pk)

        self.version = self.addon.current_version
        self.version.refresh_from_db()

        self._set_tested_url()

    def _test_url(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        result = json.loads(response.content)
        assert result == [
            {
                'version': self.version.version,
                'id': self.version.id,
                'channel': 'listed',
            }
        ]

    def _set_tested_url(self):
        self.url = reverse_ns(
            'reviewers-versions-list', kwargs={'addon_pk': self.addon.pk}
        )

    def test_anonymous(self):
        response = self.client.get(self.url)
        assert response.status_code == 401

    def test_invalid_addon(self):
        self.url = reverse_ns(
            'reviewers-versions-list', kwargs={'addon_pk': self.addon.pk + 42}
        )
        response = self.client.get(self.url)
        assert response.status_code == 404

        self.url = self.url.replace(f'{self.addon.pk + 42}', 'NaN')
        response = self.client.get(self.url)
        assert response.status_code == 404

    def test_permissions_reviewer(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)
        self._test_url()

    def test_permissions_author(self):
        user = UserProfile.objects.create(username='author')
        AddonUser.objects.create(user=user, addon=self.addon)
        self.client.login_api(user)
        response = self.client.get(self.url)
        assert response.status_code == 403

    def test_permissions_disabled_version_admin(self):
        user = UserProfile.objects.create(username='admin')
        self.grant_permission(user, '*:*')
        self.client.login_api(user)
        self.version.file.update(status=amo.STATUS_DISABLED)
        self._test_url()

    def test_permissions_disabled_version_user(self):
        user = UserProfile.objects.create(username='simpleuser')
        self.client.login_api(user)
        self.version.file.update(status=amo.STATUS_DISABLED)
        response = self.client.get(self.url)
        assert response.status_code == 403

    def test_show_only_listed_without_unlisted_permission(self):
        user = UserProfile.objects.create(username='admin')

        # User doesn't have ReviewUnlisted permission
        self.grant_permission(user, 'Addons:Review')

        self.client.login_api(user)

        version_factory(addon=self.addon, channel=amo.CHANNEL_UNLISTED)

        response = self.client.get(self.url)
        assert response.status_code == 200
        result = json.loads(response.content)

        assert result == [
            {
                'version': self.version.version,
                'id': self.version.id,
                'channel': 'listed',
            },
        ]

    def test_show_listed_and_unlisted_with_permissions(self):
        user = UserProfile.objects.create(username='admin')

        # User doesn't have Review permission
        self.grant_permission(user, 'Addons:ReviewUnlisted')

        self.client.login_api(user)

        unlisted_version = version_factory(
            addon=self.addon, channel=amo.CHANNEL_UNLISTED
        )

        with self.assertNumQueries(8):
            # - 2 savepoints because of tests
            # - 2 user and groups
            # - 1 add-on
            # - 1 add-on translations (not needed, could be avoided, but we
            #     currently re-use the same get_addon_object() implementation
            #     for other APIs where we do need the add-on name)
            # - 1 versions exists to figure out if add-on is listed
            # - 1 versions
            response = self.client.get(self.url)

        assert response.status_code == 200
        result = json.loads(response.content)

        assert result == [
            {
                'version': unlisted_version.version,
                'id': unlisted_version.id,
                'channel': 'unlisted',
            },
            {
                'version': self.version.version,
                'id': self.version.id,
                'channel': 'listed',
            },
        ]


class TestDraftCommentViewSet(TestCase):
    client_class = APITestClientSessionID

    def setUp(self):
        super().setUp()

        self.addon = addon_factory(
            name='My Addôn',
            slug='my-addon',
            file_kw={'filename': 'webextension_no_id.xpi'},
        )

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

        url = reverse_ns(
            'reviewers-versions-draft-comment-list',
            kwargs={'addon_pk': self.addon.pk, 'version_pk': self.version.pk},
        )

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
            'version_id': self.version.pk,
            'user': json.loads(
                json.dumps(
                    BaseUserSerializer(user, context={'request': request}).data,
                    cls=amo.utils.AMOJSONEncoder,
                )
            ),
        }

    def test_list_queries(self):
        user = user_factory(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)
        DraftComment.objects.create(
            version=self.version,
            comment='test1',
            user=user,
            lineno=0,
            filename='manifest.json',
        )
        DraftComment.objects.create(
            version=self.version,
            comment='test2',
            user=user,
            lineno=1,
            filename='manifest.json',
        )
        DraftComment.objects.create(
            version=self.version,
            comment='test3',
            user=user,
            lineno=2,
            filename='manifest.json',
        )
        url = reverse_ns(
            'reviewers-versions-draft-comment-list',
            kwargs={'addon_pk': self.addon.pk, 'version_pk': self.version.pk},
        )
        with self.assertNumQueries(9):
            # - 2 savepoints because of tests
            # - 2 user and groups
            # - 2 addon and translations
            # - 1 version
            # - 1 count
            # - 1 drafts
            response = self.client.get(url, {'lang': 'en-US'})
        assert response.json()['count'] == 3

    def test_list_invalid_addon(self):
        user = user_factory(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)
        url = reverse_ns(
            'reviewers-versions-draft-comment-list',
            kwargs={'addon_pk': self.addon.pk + 42, 'version_pk': self.version.pk},
        )
        response = self.client.get(url)
        assert response.status_code == 404

        url = url.replace(f'{self.addon.pk + 42}', 'NaN')
        response = self.client.get(url)
        assert response.status_code == 404

    def test_list_invalid_version(self):
        user = user_factory(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)
        url = reverse_ns(
            'reviewers-versions-draft-comment-list',
            kwargs={'addon_pk': self.addon.pk, 'version_pk': self.version.pk + 42},
        )
        response = self.client.get(url)
        assert response.status_code == 404

        url = url.replace(f'{self.version.pk + 42}', 'NaN')
        response = self.client.get(url)
        assert response.status_code == 404

    def test_create_retrieve_and_update(self):
        user = user_factory(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)

        data = {
            'comment': 'Some really fancy comment',
            'lineno': 20,
            'filename': 'manifest.json',
        }

        url = reverse_ns(
            'reviewers-versions-draft-comment-list',
            kwargs={'addon_pk': self.addon.pk, 'version_pk': self.version.pk},
        )

        response = self.client.post(url, data)
        assert response.status_code == 201

        comment = DraftComment.objects.first()

        response = self.client.get(url)

        assert response.json()['count'] == 1
        assert response.json()['results'][0]['comment'] == 'Some really fancy comment'

        url = reverse_ns(
            'reviewers-versions-draft-comment-detail',
            kwargs={
                'addon_pk': self.addon.pk,
                'version_pk': self.version.pk,
                'pk': comment.pk,
            },
        )

        response = self.client.patch(url, {'comment': 'Updated comment!'})

        assert response.status_code == 200

        response = self.client.get(url)

        assert response.json()['comment'] == 'Updated comment!'
        assert response.json()['lineno'] == 20

        response = self.client.patch(url, {'lineno': 18})

        assert response.status_code == 200

        response = self.client.get(url)

        assert response.json()['lineno'] == 18

        # Patch two fields at the same time
        response = self.client.patch(
            url, {'lineno': 16, 'filename': 'new_manifest.json'}
        )

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

        url = reverse_ns(
            'reviewers-versions-draft-comment-list',
            kwargs={'addon_pk': self.addon.pk, 'version_pk': self.version.pk},
        )

        response = self.client.post(url, data)
        comment_id = response.json()['id']

        assert response.status_code == 201

        url = reverse_ns(
            'reviewers-versions-draft-comment-detail',
            kwargs={
                'addon_pk': self.addon.pk,
                'version_pk': self.version.pk,
                'pk': comment_id,
            },
        )

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
            version=self.version,
            comment='test',
            user=user,
            lineno=0,
            filename='manifest.json',
        )

        url = reverse_ns(
            'reviewers-versions-draft-comment-detail',
            kwargs={
                'addon_pk': self.addon.pk,
                'version_pk': self.version.pk,
                'pk': comment.pk,
            },
        )

        response = self.client.delete(url)
        assert response.status_code == 204

        assert DraftComment.objects.first() is None

    def test_canned_response_and_comment_not_together(self):
        user = user_factory(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)

        canned_response = CannedResponse.objects.create(
            name='Terms of services',
            response="doesn't regard our terms of services",
            category=amo.CANNED_RESPONSE_CATEGORY_OTHER,
            type=amo.CANNED_RESPONSE_TYPE_ADDON,
        )

        data = {
            'comment': 'Some really fancy comment',
            'canned_response': canned_response.pk,
            'lineno': 20,
            'filename': 'manifest.json',
        }

        url = reverse_ns(
            'reviewers-versions-draft-comment-list',
            kwargs={
                'addon_pk': self.addon.pk,
                'version_pk': self.version.pk,
            },
        )

        response = self.client.post(url, data)
        assert response.status_code == 400
        assert (
            str(response.data['comment'][0])
            == "You can't submit a comment if `canned_response` is defined."
        )

    def test_doesnt_allow_empty_comment(self):
        user = user_factory(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)

        data = {
            'comment': '',
            'lineno': 20,
            'filename': 'manifest.json',
        }

        url = reverse_ns(
            'reviewers-versions-draft-comment-list',
            kwargs={
                'addon_pk': self.addon.pk,
                'version_pk': self.version.pk,
            },
        )

        response = self.client.post(url, data)
        assert response.status_code == 400
        assert str(response.data['comment'][0]) == "You can't submit an empty comment."

    def test_disallow_lineno_without_filename(self):
        user = user_factory(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)

        data = {
            'comment': 'Some really fancy comment',
            'lineno': 20,
            'filename': None,
        }

        url = reverse_ns(
            'reviewers-versions-draft-comment-list',
            kwargs={
                'addon_pk': self.addon.pk,
                'version_pk': self.version.pk,
            },
        )

        response = self.client.post(url, data)
        assert response.status_code == 400
        assert (
            str(response.data['comment'][0])
            == "You can't submit a line number without associating it to a "
            'filename.'
        )

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

        url = reverse_ns(
            'reviewers-versions-draft-comment-list',
            kwargs={
                'addon_pk': self.addon.pk,
                'version_pk': self.version.pk,
            },
        )

        response = self.client.post(url, data)
        assert response.status_code == 201

    def test_canned_response(self):
        user = user_factory(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)

        canned_response = CannedResponse.objects.create(
            name='Terms of services',
            response="doesn't regard our terms of services",
            category=amo.CANNED_RESPONSE_CATEGORY_OTHER,
            type=amo.CANNED_RESPONSE_TYPE_ADDON,
        )

        data = {
            'canned_response': canned_response.pk,
            'lineno': 20,
            'filename': 'manifest.json',
        }

        url = reverse_ns(
            'reviewers-versions-draft-comment-list',
            kwargs={
                'addon_pk': self.addon.pk,
                'version_pk': self.version.pk,
            },
        )

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
            'canned_response': json.loads(
                json.dumps(
                    CannedResponseSerializer(canned_response).data,
                    cls=amo.utils.AMOJSONEncoder,
                )
            ),
            'version_id': self.version.id,
            'user': json.loads(
                json.dumps(
                    BaseUserSerializer(user, context={'request': request}).data,
                    cls=amo.utils.AMOJSONEncoder,
                )
            ),
        }

    def test_delete_not_comment_owner(self):
        user = user_factory(username='reviewer')
        self.grant_permission(user, 'Addons:Review')

        comment = DraftComment.objects.create(
            version=self.version,
            comment='test',
            user=user,
            lineno=0,
            filename='manifest.json',
        )

        # Let's login as someone else who is also a reviewer
        other_reviewer = user_factory(username='reviewer2')

        # Let's give the user admin permissions which doesn't help
        self.grant_permission(other_reviewer, '*:*')

        self.client.login_api(other_reviewer)

        url = reverse_ns(
            'reviewers-versions-draft-comment-detail',
            kwargs={
                'addon_pk': self.addon.pk,
                'version_pk': self.version.pk,
                'pk': comment.pk,
            },
        )

        response = self.client.delete(url)
        assert response.status_code == 404

    def test_disabled_version_user(self):
        user = user_factory(username='simpleuser')
        self.client.login_api(user)
        self.version.file.update(status=amo.STATUS_DISABLED)

        data = {
            'comment': 'Some really fancy comment',
            'lineno': 20,
            'filename': 'manifest.json',
        }

        url = reverse_ns(
            'reviewers-versions-draft-comment-list',
            kwargs={'addon_pk': self.addon.pk, 'version_pk': self.version.pk},
        )

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

        url = reverse_ns(
            'reviewers-versions-draft-comment-list',
            kwargs={'addon_pk': self.addon.pk, 'version_pk': self.version.pk},
        )

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

        url = reverse_ns(
            'reviewers-versions-draft-comment-list',
            kwargs={'addon_pk': self.addon.pk, 'version_pk': self.version.pk},
        )

        response = self.client.post(url, data)
        assert response.status_code == 404

    def test_deleted_version_reviewer_who_can_view_deleted_versions(self):
        user = user_factory(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.grant_permission(user, 'Addons:ViewDeleted')
        AddonUser.objects.create(user=user, addon=self.addon)
        self.client.login_api(user)
        self.version.delete()

        url = reverse_ns(
            'reviewers-versions-draft-comment-list',
            kwargs={'addon_pk': self.addon.pk, 'version_pk': self.version.pk},
        )

        response = self.client.get(url)
        assert response.status_code == 200

        data = {
            'comment': 'Some really fancy comment',
            'lineno': 20,
            'filename': 'manifest.json',
        }

        response = self.client.post(url, data)
        assert response.status_code == 201

        assert DraftComment.objects.count() == 1

    def test_deleted_version_user(self):
        user = user_factory(username='simpleuser')
        self.client.login_api(user)
        self.version.delete()

        data = {
            'comment': 'Some really fancy comment',
            'lineno': 20,
            'filename': 'manifest.json',
        }

        url = reverse_ns(
            'reviewers-versions-draft-comment-list',
            kwargs={'addon_pk': self.addon.pk, 'version_pk': self.version.pk},
        )

        response = self.client.post(url, data)
        assert response.status_code == 404

    def test_unlisted_version_reviewer(self):
        user = user_factory(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)
        self.version.update(channel=amo.CHANNEL_UNLISTED)

        data = {
            'comment': 'Some really fancy comment',
            'lineno': 20,
            'filename': 'manifest.json',
        }

        url = reverse_ns(
            'reviewers-versions-draft-comment-list',
            kwargs={'addon_pk': self.addon.pk, 'version_pk': self.version.pk},
        )

        response = self.client.post(url, data)
        assert response.status_code == 403

    def test_unlisted_version_user(self):
        user = user_factory(username='simpleuser')
        self.client.login_api(user)
        self.version.update(channel=amo.CHANNEL_UNLISTED)

        data = {
            'comment': 'Some really fancy comment',
            'lineno': 20,
            'filename': 'manifest.json',
        }

        url = reverse_ns(
            'reviewers-versions-draft-comment-list',
            kwargs={'addon_pk': self.addon.pk, 'version_pk': self.version.pk},
        )

        response = self.client.post(url, data)
        assert response.status_code == 403

    def test_not_reviewer_or_admin(self):
        reviewer_user = user_factory(username='reviewer')
        self.grant_permission(reviewer_user, 'Addons:Review')
        # Create a comment from a reviewer.
        comment = DraftComment.objects.create(
            version=self.version,
            comment='test1',
            user=reviewer_user,
            lineno=0,
            filename='manifest.json',
        )

        user = user_factory(username='simpleuser')
        self.client.login_api(user)
        url = reverse_ns(
            'reviewers-versions-draft-comment-list',
            kwargs={'addon_pk': self.addon.pk, 'version_pk': self.version.pk},
        )

        # Should not be able to retrieve comments.
        response = self.client.get(url)
        assert response.status_code == 403

        # Should not be able to add comments.
        data = {
            'comment': 'Some really fancy comment',
            'lineno': 20,
            'filename': 'manifest.json',
        }
        response = self.client.post(url, data)
        assert response.status_code == 403

        # Should not be able to edit comments.
        url = reverse_ns(
            'reviewers-versions-draft-comment-detail',
            kwargs={
                'addon_pk': self.addon.pk,
                'version_pk': self.version.pk,
                'pk': comment.pk,
            },
        )

        response = self.client.patch(url, {'comment': 'Updated comment!'})
        assert response.status_code == 403

        # Should not be able to delete comments.
        response = self.client.delete(url)
        assert response.status_code == 403

    def test_deleted_addon(self):
        user = user_factory(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.grant_permission(user, 'Addons:ViewDeleted')
        self.client.login_api(user)

        DraftComment.objects.create(
            version=self.version,
            comment='test',
            user=user,
            lineno=0,
            filename='manifest.json',
        )

        url = reverse_ns(
            'reviewers-versions-draft-comment-list',
            kwargs={'addon_pk': self.addon.pk, 'version_pk': self.version.pk},
        )

        self.addon.delete()
        response = self.client.get(url)
        assert response.status_code == 200
        assert response.json()['count'] == 1


class TestReviewAddonVersionCompareViewSet(
    TestCase, AddonReviewerViewSetPermissionMixin
):
    client_class = APITestClientSessionID
    __test__ = True

    def setUp(self):
        super().setUp()

        self.addon = addon_factory(
            name='My Addôn',
            slug='my-addon',
            file_kw={'filename': 'webextension_no_id.xpi'},
        )

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
        assert result['file']['id'] == self.version.file.pk
        assert result['file']['diff']['path'] == 'manifest.json'

        change = result['file']['diff']['hunks'][0]['changes'][3]

        assert '"name": "Beastify"' in change['content']
        assert change['type'] == 'insert'

    def _set_tested_url(self):
        self.url = reverse_ns(
            'reviewers-versions-compare-detail',
            kwargs={
                'addon_pk': self.addon.pk,
                'version_pk': self.version.pk,
                'pk': self.compare_to_version.pk,
            },
        )

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

    def test_requested_file_contains_whitespace(self):
        new_version = version_factory(
            addon=self.addon,
            file_kw={'filename': 'webextension_no_id.xpi'},
        )

        repo = AddonGitRepository.extract_and_commit_from_version(new_version)

        apply_changes(repo, new_version, '(function() {})\n', 'content script.js')

        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)

        url = reverse_ns(
            'reviewers-versions-compare-detail',
            kwargs={
                'addon_pk': self.addon.pk,
                'version_pk': self.version.pk,
                'pk': new_version.pk,
            },
        )

        response = self.client.get(url + '?file=content script.js')
        assert response.status_code == 200
        result = json.loads(response.content)
        change = result['file']['diff']['hunks'][0]['changes'][0]

        assert result['file']['diff']['path'] == 'content script.js'
        assert change['content'] == '(function() {})'
        assert change['type'] == 'insert'

    def test_version_get_not_found(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)
        self.url = reverse_ns(
            'reviewers-versions-compare-detail',
            kwargs={
                'addon_pk': self.addon.pk,
                'version_pk': self.version.pk + 42,
                'pk': self.compare_to_version.pk,
            },
        )
        response = self.client.get(self.url)
        assert response.status_code == 404

        self.url = self.url.replace(f'{self.version.pk + 42}', 'NaN')
        response = self.client.get(self.url)
        assert response.status_code == 404

        self.url = reverse_ns(
            'reviewers-versions-compare-detail',
            kwargs={
                'addon_pk': self.addon.pk,
                'version_pk': self.version.pk,
                'pk': self.compare_to_version.pk + 42,
            },
        )
        response = self.client.get(self.url)
        assert response.status_code == 404

        self.url = self.url.replace(f'{self.compare_to_version.pk + 42}', 'NaN')
        response = self.client.get(self.url)
        assert response.status_code == 404

    def test_compare_basic(self):
        new_version = version_factory(
            addon=self.addon,
            file_kw={'filename': 'webextension_no_id.xpi'},
        )

        repo = AddonGitRepository.extract_and_commit_from_version(new_version)

        apply_changes(repo, new_version, '{"id": "random"}\n', 'manifest.json')
        apply_changes(repo, new_version, 'Updated readme\n', 'README.md')

        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)

        self.url = reverse_ns(
            'reviewers-versions-compare-detail',
            kwargs={
                'addon_pk': self.addon.pk,
                'version_pk': self.version.pk,
                'pk': new_version.pk,
            },
        )

        with self.assertNumQueries(8):
            # - 2 savepoints because of tests
            # - 2 user and groups
            # - 2 add-on and translations
            # - 1 add-on author check
            # - 1 all file validation
            response = self.client.get(self.url + '?file=README.md&lang=en-US')
        assert response.status_code == 200

        result = json.loads(response.content)

        assert result['addon']['name'] == {'en-US': str(self.addon.name)}

        assert result['file']['diff']['path'] == 'README.md'
        assert result['file']['diff']['hunks'][0]['changes'] == [
            {
                'content': '# beastify',
                'new_line_number': -1,
                'old_line_number': 1,
                'type': 'delete',
            },
            {
                'content': 'Updated readme',
                'new_line_number': 1,
                'old_line_number': -1,
                'type': 'insert',
            },
        ]
        assert result['file_entries'] is not None

    def test_compare_with_deleted_file(self):
        new_version = version_factory(
            addon=self.addon,
            file_kw={'filename': 'webextension_no_id.xpi'},
        )

        repo = AddonGitRepository.extract_and_commit_from_version(new_version)

        deleted_file = 'README.md'
        apply_changes(repo, new_version, '', deleted_file, delete=True)

        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)

        self.url = reverse_ns(
            'reviewers-versions-compare-detail',
            kwargs={
                'addon_pk': self.addon.pk,
                'version_pk': self.version.pk,
                'pk': new_version.pk,
            },
        )

        response = self.client.get(self.url + '?file=' + deleted_file)
        assert response.status_code == 200
        result = json.loads(response.content)
        assert result['file']['download_url'] is None

    def test_dont_servererror_on_binary_file(self):
        """Regression test for
        https://github.com/mozilla/addons-server/issues/11712"""
        new_version = version_factory(
            addon=self.addon,
            file_kw={
                'filename': 'webextension_no_id.xpi',
            },
        )

        repo = AddonGitRepository.extract_and_commit_from_version(new_version)
        apply_changes(repo, new_version, EMPTY_PNG, 'foo.png')

        next_version = version_factory(
            addon=self.addon,
            file_kw={
                'filename': 'webextension_no_id.xpi',
            },
        )

        repo = AddonGitRepository.extract_and_commit_from_version(next_version)
        apply_changes(repo, next_version, EMPTY_PNG, 'foo.png')

        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)

        self.url = reverse_ns(
            'reviewers-versions-compare-detail',
            kwargs={
                'addon_pk': self.addon.pk,
                'version_pk': new_version.pk,
                'pk': next_version.pk,
            },
        )

        response = self.client.get(self.url + '?file=foo.png')
        assert response.status_code == 200
        result = json.loads(response.content)
        assert result['file']['download_url']

    def test_compare_with_deleted_version(self):
        new_version = version_factory(
            addon=self.addon,
            file_kw={'filename': 'webextension_no_id.xpi'},
        )

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

        self.url = reverse_ns(
            'reviewers-versions-compare-detail',
            kwargs={
                'addon_pk': self.addon.pk,
                'version_pk': self.version.pk,
                'pk': new_version.pk,
            },
        )

        response = self.client.get(self.url)
        assert response.status_code == 200
        result = json.loads(response.content)
        assert result['file']['download_url']

    def test_file_only_requested_file(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)

        response = self.client.get(self.url + '?file=README.md&file_only=true')
        assert response.status_code == 200
        result = json.loads(response.content)

        assert result['id'] == self.version.pk
        assert result['file']['diff']['path'] == 'README.md'
        change = result['file']['diff']['hunks'][0]['changes'][0]

        assert change['content'] == '# beastify'
        assert change['type'] == 'insert'

        # make sure we only returned `id` and `file` properties
        assert len(result.keys()) == 2

    def test_file_only_false(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.login_api(user)

        response = self.client.get(self.url + '?file=README.md&file_only=false')
        assert response.status_code == 200
        result = json.loads(response.content)

        assert result['id'] == self.version.pk

        # make sure we returned more than just the `id` and `file` properties
        assert len(result.keys()) > 2


class TestDownloadGitFileView(TestCase):
    def setUp(self):
        super().setUp()

        self.addon = addon_factory(
            name='My Addôn',
            slug='my-addon',
            file_kw={'filename': 'webextension_no_id.xpi'},
        )

        extract_version_to_git(self.addon.current_version.pk)

        self.version = self.addon.current_version
        self.version.refresh_from_db()

    def test_download_basic(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.force_login(user)

        url = reverse(
            'reviewers.download_git_file',
            kwargs={'version_id': self.version.pk, 'filename': 'manifest.json'},
        )

        response = self.client.get(url)
        assert response.status_code == 200
        assert response['Content-Disposition'] == 'attachment; filename="manifest.json"'

        content = response.content.decode('utf-8')
        assert content.startswith('{')
        assert '"manifest_version": 2' in content

    @override_settings(CSP_REPORT_ONLY=False)
    def test_download_respects_csp(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.force_login(user)

        url = reverse(
            'reviewers.download_git_file',
            kwargs={'version_id': self.version.pk, 'filename': 'manifest.json'},
        )

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
        assert 'report-uri' in response['content-security-policy']

        # Other properties that we defined by default aren't set
        assert 'style-src' not in response['content-security-policy']
        assert 'font-src' not in response['content-security-policy']
        assert 'frame-src' not in response['content-security-policy']
        assert 'child-src' not in response['content-security-policy']

    def test_download_emoji_filename(self):
        new_version = version_factory(
            addon=self.addon,
            file_kw={'filename': 'webextension_no_id.xpi'},
        )

        repo = AddonGitRepository.extract_and_commit_from_version(new_version)

        apply_changes(repo, new_version, '\n', '😀❤.txt')

        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.force_login(user)

        url = reverse(
            'reviewers.download_git_file',
            kwargs={'version_id': new_version.pk, 'filename': '😀❤.txt'},
        )

        response = self.client.get(url)
        assert response.status_code == 200
        assert (
            response['Content-Disposition']
            == "attachment; filename*=utf-8''%F0%9F%98%80%E2%9D%A4.txt"
        )

    def test_download_notfound(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.force_login(user)

        url = reverse(
            'reviewers.download_git_file',
            kwargs={'version_id': self.version.pk, 'filename': 'doesnotexist.json'},
        )

        response = self.client.get(url)
        assert response.status_code == 404

    def _test_url_success(self):
        url = reverse(
            'reviewers.download_git_file',
            kwargs={'version_id': self.version.pk, 'filename': 'manifest.json'},
        )

        response = self.client.get(url)
        assert response.status_code == 200

        content = response.content.decode('utf-8')
        assert content.startswith('{')
        assert '"manifest_version": 2' in content

    def test_disabled_version_reviewer(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.force_login(user)
        self.version.file.update(status=amo.STATUS_DISABLED)
        self._test_url_success()

    def test_disabled_version_author(self):
        user = UserProfile.objects.create(username='author')
        AddonUser.objects.create(user=user, addon=self.addon)
        self.client.force_login(user)
        self.version.file.update(status=amo.STATUS_DISABLED)
        self._test_url_success()

    def test_disabled_version_admin(self):
        user = UserProfile.objects.create(username='admin')
        self.grant_permission(user, '*:*')
        self.client.force_login(user)
        self.version.file.update(status=amo.STATUS_DISABLED)
        self._test_url_success()

    def test_disabled_version_user_but_not_author(self):
        user = UserProfile.objects.create(username='simpleuser')
        self.client.force_login(user)
        self.version.file.update(status=amo.STATUS_DISABLED)

        url = reverse(
            'reviewers.download_git_file',
            kwargs={'version_id': self.version.pk, 'filename': 'manifest.json'},
        )

        response = self.client.get(url)
        assert response.status_code == 403

    def test_unlisted_version_reviewer(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:Review')
        self.client.force_login(user)
        self.version.update(channel=amo.CHANNEL_UNLISTED)

        url = reverse(
            'reviewers.download_git_file',
            kwargs={'version_id': self.version.pk, 'filename': 'manifest.json'},
        )

        response = self.client.get(url)
        assert response.status_code == 404

    def test_unlisted_version_unlisted_reviewer(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'Addons:ReviewUnlisted')
        self.client.force_login(user)
        self.version.update(channel=amo.CHANNEL_UNLISTED)
        self._test_url_success()

    def test_unlisted_version_unlisted_viewer(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'ReviewerTools:ViewUnlisted')
        self.client.force_login(user)
        self.version.update(channel=amo.CHANNEL_UNLISTED)
        self._test_url_success()

    def test_unlisted_version_author(self):
        user = UserProfile.objects.create(username='author')
        AddonUser.objects.create(user=user, addon=self.addon)
        self.client.force_login(user)
        self.version.update(channel=amo.CHANNEL_UNLISTED)
        self._test_url_success()

    def test_unlisted_version_admin(self):
        user = UserProfile.objects.create(username='admin')
        self.grant_permission(user, '*:*')
        self.client.force_login(user)
        self.version.update(channel=amo.CHANNEL_UNLISTED)
        self._test_url_success()

    def test_unlisted_version_user_but_not_author(self):
        user = UserProfile.objects.create(username='simpleuser')
        self.client.force_login(user)
        self.version.update(channel=amo.CHANNEL_UNLISTED)

        url = reverse(
            'reviewers.download_git_file',
            kwargs={'version_id': self.version.pk, 'filename': 'manifest.json'},
        )

        response = self.client.get(url)
        assert response.status_code == 404


class TestCannedResponseViewSet(TestCase):
    client_class = APITestClientSessionID

    def setUp(self):
        super().setUp()

        self.canned_response = CannedResponse.objects.create(
            name='Terms of services',
            response="doesn't regard our terms of services",
            category=amo.CANNED_RESPONSE_CATEGORY_OTHER,
            type=amo.CANNED_RESPONSE_TYPE_ADDON,
        )

        self.url = reverse_ns('reviewers-canned-response-list')

    def _test_url(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        result = json.loads(response.content)
        category = self.canned_response.category
        assert result == [
            {
                'id': self.canned_response.id,
                'title': self.canned_response.name,
                'response': self.canned_response.response,
                'category': amo.CANNED_RESPONSE_CATEGORY_CHOICES[category],
            }
        ]

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

    def test_unlisted_viewer(self):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, 'ReviewerTools:ViewUnlisted')
        self.client.login_api(user)
        self._test_url()


class TestThemeBackgroundImages(ReviewBase):
    def setUp(self):
        super().setUp()
        self.addon = addon_factory(
            type=amo.ADDON_STATICTHEME,
            file_kw={
                'filename': os.path.join(
                    settings.ROOT,
                    'src/olympia/devhub/tests/addons/static_theme_tiled.zip',
                )
            },
        )
        self.url = reverse(
            'reviewers.theme_background_images', args=[self.addon.current_version.id]
        )

    def test_not_reviewer(self):
        user_factory(email='irregular@mozilla.com')
        self.client.force_login(UserProfile.objects.get(email='irregular@mozilla.com'))
        response = self.client.post(self.url, follow=True)
        assert response.status_code == 403

    def test_no_header_image(self):
        self.addon.current_version.file.update(file='')
        response = self.client.post(self.url, follow=True)
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data == {}

    def test_header_images(self):
        with open(
            os.path.join(
                settings.ROOT,
                'src/olympia/devhub/tests/addons/static_theme_tiled.zip',
            ),
            'rb',
        ) as src:
            file_ = self.addon.current_version.file
            file_.file = DjangoFile(src)
            file_.save()
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


class TestMadQueue(QueueTest):
    fixtures = ['base/users']

    def setUp(self):
        super().setUp()
        self.url = reverse('reviewers.queue_mad')

        # This add-on should be listed once, even with two versions.
        listed_addon = addon_factory(created=self.days_ago(15))
        version_review_flags_factory(
            version=version_factory(addon=listed_addon, channel=amo.CHANNEL_LISTED),
            needs_human_review_by_mad=True,
        )
        version_review_flags_factory(
            version=version_factory(addon=listed_addon, channel=amo.CHANNEL_LISTED),
            needs_human_review_by_mad=True,
        )

        # This add-on should be listed once, even with two versions.
        unlisted_addon = addon_factory(created=self.days_ago(5))
        version_review_flags_factory(
            version=version_factory(addon=unlisted_addon, channel=amo.CHANNEL_UNLISTED),
            needs_human_review_by_mad=True,
        )
        version_review_flags_factory(
            version=version_factory(addon=unlisted_addon, channel=amo.CHANNEL_UNLISTED),
            needs_human_review_by_mad=True,
        )

        # This add-on should not be listed, because the latest version is not
        # flagged.
        listed_addon_previous = addon_factory(created=self.days_ago(15))
        version_review_flags_factory(
            version=version_factory(
                addon=listed_addon_previous, channel=amo.CHANNEL_LISTED
            ),
            needs_human_review_by_mad=True,
        )
        version_review_flags_factory(
            version=version_factory(
                addon=listed_addon_previous, channel=amo.CHANNEL_LISTED
            ),
            needs_human_review_by_mad=False,
        )

        unflagged_addon = addon_factory()
        version_factory(addon=unflagged_addon)

        version_review_flags_factory(
            version=version_factory(addon=addon_factory()),
            needs_human_review_by_mad=False,
        )

        # Needs admin code review, so wouldn't show up for regular reviewers.
        addon_admin_only = addon_factory(created=self.days_ago(1))
        version_review_flags_factory(
            version=version_factory(addon=addon_admin_only),
            needs_human_review_by_mad=True,
        )
        AddonReviewerFlags.objects.create(
            addon=addon_admin_only,
            needs_admin_code_review=True,
        )

        # Mixed listed and unlisted versions. Should not show up in queue.
        mixed_addon = addon_factory(created=self.days_ago(5))
        version_review_flags_factory(
            version=version_factory(addon=mixed_addon, channel=amo.CHANNEL_UNLISTED),
            needs_human_review_by_mad=False,
        )
        version_review_flags_factory(
            version=version_factory(addon=mixed_addon, channel=amo.CHANNEL_LISTED),
            needs_human_review_by_mad=True,
        )
        version_review_flags_factory(
            version=version_factory(addon=mixed_addon, channel=amo.CHANNEL_LISTED),
            needs_human_review_by_mad=False,
        )

        # Mixed listed and unlisted versions. Only the unlisted should show up.
        mixed_addon2 = addon_factory(created=self.days_ago(4))
        version_review_flags_factory(
            version=version_factory(addon=mixed_addon2, channel=amo.CHANNEL_UNLISTED),
            needs_human_review_by_mad=True,
        )
        version_review_flags_factory(
            version=version_factory(addon=mixed_addon2, channel=amo.CHANNEL_LISTED),
            needs_human_review_by_mad=True,
        )
        version_review_flags_factory(
            version=version_factory(addon=mixed_addon2, channel=amo.CHANNEL_LISTED),
            needs_human_review_by_mad=False,
        )

        # Mixed listed and unlisted versions. Both channels should show up.
        mixed_addon_both = addon_factory(created=self.days_ago(2))
        version_review_flags_factory(
            version=version_factory(
                addon=mixed_addon_both, channel=amo.CHANNEL_UNLISTED
            ),
            needs_human_review_by_mad=True,
        )
        version_review_flags_factory(
            version=version_factory(addon=mixed_addon_both, channel=amo.CHANNEL_LISTED),
            needs_human_review_by_mad=True,
        )

        self.expected_addons = [
            listed_addon,
            unlisted_addon,
            mixed_addon2,
            mixed_addon_both,
        ]

    def test_results(self):
        with self.assertNumQueries(14):
            # That's a lot of queries. Some of them are unfortunately scaling
            # with the number of add-ons in the queue.
            # - 2 for savepoints because we're in tests
            # - 2 for user/groups
            # - 1 for the current queue count for pagination purposes
            # - 2 for the addons in the queue, their files and the number of
            #     flagged versions they have in each channel (regardless of
            #     how many are in the queue - that's the important bit)
            # - 2 for config items (motd / site notice)
            # - 1 for my add-ons in user menu
            # - 4 for reviewer scores and user stuff displayed above the queue
            response = self.client.get(self.url)
        assert response.status_code == 200

        # listed
        expected = []
        addon = self.expected_addons[0]
        expected.append(
            ('Listed version', reverse('reviewers.review', args=[addon.pk]))
        )
        # unlisted
        addon = self.expected_addons[1]
        expected.append(
            (
                'Unlisted versions (2)',
                reverse('reviewers.review', args=['unlisted', addon.pk]),
            )
        )
        # mixed, only unlisted flagged
        addon = self.expected_addons[2]
        expected.append(
            (
                'Unlisted versions (1)',
                reverse('reviewers.review', args=['unlisted', addon.pk]),
            )
        )
        # mixed, both channels flagged
        addon = self.expected_addons[3]
        expected.append(
            ('Listed version', reverse('reviewers.review', args=[addon.pk]))
        )
        expected.append(
            (
                'Unlisted versions (1)',
                reverse('reviewers.review', args=['unlisted', addon.pk]),
            )
        )

        doc = pq(response.content)
        links = doc('#addon-queue tr.addon-row td a:not(.app-icon)')
        assert len(links) == len(expected)
        check_links(expected, links, verify=False)

    def test_only_viewable_with_specific_permission(self):
        # Content reviewer does not have access.
        self.user.groupuser_set.all().delete()  # Remove all permissions
        self.grant_permission(self.user, 'Addons:ContentReview')
        response = self.client.get(self.url)
        assert response.status_code == 403

        # Regular user doesn't have access.
        self.client.logout()
        self.client.force_login(UserProfile.objects.get(email='regular@mozilla.com'))
        response = self.client.get(self.url)
        assert response.status_code == 403

    def test_queue_layout(self):
        self._test_queue_layout(
            'Flagged for Human Review',
            tab_position=2,
            total_addons=4,
            total_queues=4,
            per_page=1,
        )

    def test_queue_layout_admin(self):
        # Admins should see the extra add-on that needs admin content review.
        self.grant_permission(self.user, 'Reviews:Admin')

        self._test_queue_layout(
            'Flagged for Human Review',
            tab_position=2,
            total_addons=5,
            total_queues=5,
            per_page=1,
        )
