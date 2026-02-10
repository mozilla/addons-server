import io
import json
import os
import time
import uuid
from collections import OrderedDict
from datetime import datetime, timedelta
from unittest import mock

from django.conf import settings
from django.core import mail
from django.core.cache import cache
from django.core.files import temp
from django.core.files.base import ContentFile, File as DjangoFile
from django.db import connection, reset_queries
from django.template import defaultfilters
from django.test.client import RequestFactory
from django.test.utils import override_settings
from django.urls import reverse
from django.utils.formats import localize

import responses
import time_machine
from lxml.html import HTMLParser, fromstring
from pyquery import PyQuery as pq
from waffle.testutils import override_switch

from olympia import amo, core, ratings
from olympia.abuse.models import AbuseReport, CinderJob, CinderPolicy, ContentDecision
from olympia.access import acl
from olympia.access.models import Group, GroupUser
from olympia.activity.models import ActivityLog, AttachmentLog
from olympia.addons.models import (
    Addon,
    AddonApprovalsCounter,
    AddonReviewerFlags,
    AddonUser,
    DeniedGuid,
)
from olympia.amo.templatetags.jinja_helpers import (
    format_date,
    format_datetime,
)
from olympia.amo.tests import (
    APITestClientJWT,
    APITestClientSessionID,
    TestCase,
    addon_factory,
    block_factory,
    check_links,
    collection_factory,
    formset,
    initial,
    reverse_ns,
    user_factory,
    version_factory,
    version_review_flags_factory,
)
from olympia.blocklist.models import Block, BlocklistSubmission, BlockType, BlockVersion
from olympia.blocklist.utils import block_activity_log_save
from olympia.constants.abuse import DECISION_ACTIONS
from olympia.constants.promoted import PROMOTED_GROUP_CHOICES
from olympia.constants.reviewers import REVIEWER_DELAYED_REJECTION_PERIOD_DAYS_DEFAULT
from olympia.constants.scanners import CUSTOMS, YARA
from olympia.files.models import File, FileValidation, WebextPermission
from olympia.ratings.models import Rating, RatingFlag
from olympia.reviewers.models import (
    AutoApprovalSummary,
    NeedsHumanReview,
    ReviewActionReason,
    ReviewerSubscription,
    Whiteboard,
)
from olympia.reviewers.templatetags.jinja_helpers import to_dom_id
from olympia.reviewers.views import queue
from olympia.scanners.models import ScannerResult, ScannerRule
from olympia.stats.utils import VERSION_ADU_LIMIT
from olympia.users.models import UserProfile
from olympia.versions.models import (
    ApplicationsVersions,
    AppVersion,
)
from olympia.versions.utils import get_review_due_date
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
        ActivityLog.objects.create(amo.LOG.APPROVE_RATING, review, review.addon).update(
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
        for _i in range(2):
            ActivityLog.objects.create(amo.LOG.APPROVE_RATING, review, review.addon)
            ActivityLog.objects.create(amo.LOG.DELETE_RATING, review.id, review.addon)
        response = self.client.get(self.url, {'filter': 'deleted'})
        assert response.status_code == 200
        assert pq(response.content)('tbody tr').length == 2

    def test_no_results(self):
        response = self.client.get(self.url, {'end': '2004-01-01'})
        assert response.status_code == 200
        assert b'"no-results"' in response.content

    def test_moderation_log_detail(self):
        review = self.make_review()
        ActivityLog.objects.create(amo.LOG.APPROVE_RATING, review, review.addon)
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
            ActivityLog.objects.create(
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
        ActivityLog.objects.create(
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
        self.make_an_approval(amo.LOG.APPROVE_LISTING_CONTENT, addon=addon_factory())
        self.make_an_approval(amo.LOG.REJECT_LISTING_CONTENT, addon=addon_factory())
        self.make_an_approval(amo.LOG.REJECT_CONTENT, addon=addon_factory())
        with self.assertNumQueries(14):
            response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        rows = doc('tbody tr')
        assert rows.filter(':not(.hide)').length == 5

    def test_xss(self):
        a = Addon.objects.all()[0]
        a.name = '<script>alert("xss")</script>'
        a.save()
        ActivityLog.objects.create(
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
        with time_machine.travel('2017-08-01 10:00', tick=False):
            self.make_approvals()

        # Make sure we show the stuff we just made.
        response = self.client.get(self.url, {'start': '2017-07-31'})
        assert response.status_code == 200

        doc = pq(response.content)('#log-listing tbody')

        assert doc('tr:not(.hide)').length == 2
        assert doc('tr.hide').eq(0).text() == 'youwin'

    def test_start_default_filter(self):
        with time_machine.travel('2017-07-31 10:00', tick=False):
            self.make_approvals()

        with time_machine.travel('2017-08-01 10:00', tick=False):
            addon = Addon.objects.first()

            ActivityLog.objects.create(
                amo.LOG.REJECT_VERSION,
                addon,
                addon.current_version,
                user=self.get_user(),
                details={'comments': 'youwin'},
            )

        # Make sure the default 'start' to the 1st of a month works properly
        with time_machine.travel('2017-08-03 11:00', tick=False):
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

    def test_comment_logs(self):
        self.make_an_approval(amo.LOG.REVIEWER_PRIVATE_COMMENT)
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert pq(response.content)('#log-listing tbody td').eq(1).html().strip() == (
            '<a href="/en-US/reviewers/review/3615">Delicious Bookmarks</a> '
            'Version 2.1.072 reviewer comment.'
        )

    def test_content_approval(self):
        self.make_an_approval(amo.LOG.APPROVE_LISTING_CONTENT)
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert pq(response.content)('#log-listing tbody td').eq(1).html().strip() == (
            '<a href="/en-US/reviewers/review-content/3615">Delicious Bookmarks</a> '
            'listing content approved.'
        )

    def test_approval_multiple_versions(self):
        addon = Addon.objects.get(pk=3615)
        self.make_addon_unlisted(addon)
        self.grant_permission(self.user, 'Addons:ReviewUnlisted')
        version_factory(addon=addon, channel=amo.CHANNEL_UNLISTED, version='3.0')
        ActivityLog.objects.create(
            amo.LOG.CONFIRM_AUTO_APPROVED,
            addon,
            *list(addon.versions.all()),
            user=self.user,
            details={'comments': 'I like this'},
        )
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert pq(response.content)('#log-listing tbody td').eq(1).html().strip() == (
            '<a href="/en-US/reviewers/review-unlisted/3615">Delicious Bookmarks</a> '
            'Versions 3.0, 2.1.072 auto-approval confirmed.'
        )

    def test_rejection_multiple_versions(self):
        addon = Addon.objects.get(pk=3615)
        version_factory(addon=addon, version='3.2.1')
        ActivityLog.objects.create(
            amo.LOG.REJECT_VERSION,
            addon,
            *list(addon.versions.all()),
            user=self.user,
            details={'comments': 'I do not like this'},
        )
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert pq(response.content)('#log-listing tbody td').eq(1).html().strip() == (
            '<a href="/en-US/reviewers/review/3615">Delicious Bookmarks</a> '
            'Versions 3.2.1, 2.1.072 rejected.'
        )

    def test_content_version_rejection(self):
        self.make_an_approval(amo.LOG.REJECT_CONTENT)
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert pq(response.content)('#log-listing tbody td').eq(1).html().strip() == (
            '<a href="/en-US/reviewers/review-content/3615">Delicious Bookmarks</a> '
            'Version 2.1.072 content rejected.'
        )

    def test_content_listing_rejection(self):
        addon = Addon.objects.get(pk=3615)
        version_factory(addon=addon, version='3.2.1')
        ActivityLog.objects.create(
            amo.LOG.REJECT_LISTING_CONTENT,
            addon,
            user=self.user,
            details={'comments': 'I do not like this'},
        )
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert pq(response.content)('#log-listing tbody td').eq(1).html().strip() == (
            '<a href="/en-US/reviewers/review-content/3615">Delicious Bookmarks</a> '
            'listing content rejected.'
        )

    @time_machine.travel('2017-08-03', tick=False)
    def test_review_url(self):
        self.login_as_admin()
        addon = addon_factory()
        unlisted_version = version_factory(addon=addon, channel=amo.CHANNEL_UNLISTED)

        ActivityLog.objects.create(
            amo.LOG.APPROVE_VERSION,
            addon,
            addon.current_version,
            user=self.get_user(),
            details={'comments': 'foo'},
        )

        response = self.client.get(self.url)
        assert response.status_code == 200
        url = reverse('reviewers.review', args=[addon.pk])
        link = pq(response.content)('#log-listing tbody tr[data-addonid] a').eq(0)
        assert link.attr('href') == url

        entry = ActivityLog.objects.create(
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
        assert pq(response.content)('#log-listing tr td a').eq(0).attr('href') == url

    def test_review_url_force_disable(self):
        self.login_as_reviewer()
        addon = addon_factory()

        ActivityLog.objects.create(
            amo.LOG.FORCE_DISABLE,
            addon,
            user=self.get_user(),
        )

        response = self.client.get(self.url)
        assert response.status_code == 200
        url = reverse('reviewers.review', args=[addon.pk])

        link = pq(response.content)('#log-listing tbody tr[data-addonid] a').eq(0)
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

    def test_super_admin_all_permissions(self):
        # Create a lot of add-ons to test the queue counts.
        user_factory(pk=settings.TASK_USER_ID)
        # Recommended extensions
        version = addon_factory(
            promoted_id=PROMOTED_GROUP_CHOICES.RECOMMENDED,
            status=amo.STATUS_NOMINATED,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        ).versions.get()
        version.needshumanreview_set.create(
            reason=NeedsHumanReview.REASONS.BELONGS_TO_PROMOTED_GROUP
        )
        version = version_factory(
            addon=addon_factory(
                promoted_id=PROMOTED_GROUP_CHOICES.RECOMMENDED,
                version_kw={'promotion_approved': False},
            ),
            promotion_approved=True,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        version.needshumanreview_set.create(
            reason=NeedsHumanReview.REASONS.BELONGS_TO_PROMOTED_GROUP
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
        version = version_factory(
            addon=addon_factory(reviewer_flags={'auto_approval_disabled': True}),
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        version.needshumanreview_set.create(
            reason=NeedsHumanReview.REASONS.AUTO_APPROVAL_DISABLED
        )
        version = addon_factory(
            status=amo.STATUS_NOMINATED,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
            reviewer_flags={
                'auto_approval_disabled': True,
            },
        ).versions.get()
        version.needshumanreview_set.create(
            reason=NeedsHumanReview.REASONS.AUTO_APPROVAL_DISABLED
        )
        # Auto-approved and Content Review.
        addon1 = addon_factory()
        AddonApprovalsCounter.reset_for_addon(addon=addon1)
        AutoApprovalSummary.objects.create(
            version=addon1.current_version, verdict=amo.AUTO_APPROVED
        )

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

        # a held decision
        ContentDecision.objects.create(
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON, addon=addon1
        )

        admins_group = Group.objects.create(name='Admins', rules='*:*')
        GroupUser.objects.create(user=self.user, group=admins_group)

        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert len(doc('.dashboard h3')) == 7  # All sections are present.
        expected_links = [
            reverse('reviewers.queue_extension'),
            reverse('reviewers.reviewlog'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Guide',
            reverse('reviewers.queue_content_review'),
            reverse('reviewers.queue_theme'),
            reverse('reviewers.reviewlog'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Themes/Guidelines',
            reverse('reviewers.queue_moderated'),
            reverse('reviewers.ratings_moderation_log'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Guide/Moderation',
            reverse('reviewers.motd'),
            reverse('reviewers.queue_pending_rejection'),
            reverse('reviewers.queue_decisions'),
        ]
        links = [link.attrib['href'] for link in doc('.dashboard a')]
        assert links == expected_links
        # pre-approval addons
        assert doc('.dashboard a')[0].text == 'Manual Review (4)'
        # content review
        assert doc('.dashboard a')[3].text == 'Content Review (7)'
        # themes
        assert doc('.dashboard a')[4].text == 'Awaiting Review (2)'
        # user ratings moderation
        assert doc('.dashboard a')[7].text == 'Ratings Awaiting Moderation (1)'
        # admin tools
        assert doc('.dashboard a')[11].text == 'Add-ons Pending Rejection (1)'
        assert (
            doc('.dashboard a')[12].text == 'Held Decisions for 2nd Level Approval (1)'
        )

    def test_can_see_all_through_reviewer_view_all_permission(self):
        self.grant_permission(self.user, 'ReviewerTools:View')
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert len(doc('.dashboard h3')) == 7  # All sections are present.
        expected_links = [
            reverse('reviewers.queue_extension'),
            reverse('reviewers.reviewlog'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Guide',
            reverse('reviewers.queue_content_review'),
            reverse('reviewers.queue_theme'),
            reverse('reviewers.reviewlog'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Themes/Guidelines',
            reverse('reviewers.queue_moderated'),
            reverse('reviewers.ratings_moderation_log'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Guide/Moderation',
            reverse('reviewers.motd'),
            reverse('reviewers.queue_pending_rejection'),
            reverse('reviewers.queue_decisions'),
        ]
        links = [link.attrib['href'] for link in doc('.dashboard a')]
        assert links == expected_links

    def test_regular_reviewer(self):
        user_factory(pk=settings.TASK_USER_ID)
        # Create some add-ons to test the queue counts.
        version = addon_factory(
            status=amo.STATUS_NOMINATED,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
            reviewer_flags={'auto_approval_disabled': True},
        ).versions.get()
        version.needshumanreview_set.create(
            reason=NeedsHumanReview.REASONS.AUTO_APPROVAL_DISABLED
        )
        version = version_factory(
            addon=addon_factory(reviewer_flags={'auto_approval_disabled': True}),
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        version.needshumanreview_set.create(
            reason=NeedsHumanReview.REASONS.AUTO_APPROVAL_DISABLED
        )
        version = version_factory(
            addon=addon_factory(reviewer_flags={'auto_approval_disabled': True}),
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        version.needshumanreview_set.create(
            reason=NeedsHumanReview.REASONS.AUTO_APPROVAL_DISABLED
        )
        # These two are auto-approved and will be ignored.
        addon_factory(
            status=amo.STATUS_NOMINATED,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        version_factory(
            addon=addon_factory(),
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        # This is a static theme so won't be shown
        addon_factory(
            status=amo.STATUS_NOMINATED,
            type=amo.ADDON_STATICTHEME,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        # Create an add-on to test the post-review queue count.
        addon = addon_factory()
        AddonApprovalsCounter.reset_for_addon(addon=addon)
        AutoApprovalSummary.objects.create(
            version=addon.current_version, verdict=amo.AUTO_APPROVED
        )

        # Grant user the permission to see only the legacy/post add-ons section
        self.grant_permission(self.user, 'Addons:Review')

        # Test.
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert len(doc('.dashboard h3')) == 1
        expected_links = [
            reverse('reviewers.queue_extension'),
            reverse('reviewers.reviewlog'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Guide',
        ]
        links = [link.attrib['href'] for link in doc('.dashboard a')]
        assert links == expected_links
        assert doc('.dashboard a')[0].text == 'Manual Review (3)'

    def test_content_reviewer(self):
        # Create an add-on to test the queue count.
        addon = addon_factory()
        AddonApprovalsCounter.reset_for_addon(addon=addon)
        AutoApprovalSummary.objects.create(
            version=addon.current_version, verdict=amo.AUTO_APPROVED
        )
        # This one has been content reviewed already.
        already_content_reviewed = addon_factory()
        AddonApprovalsCounter.approve_content_for_addon(addon=already_content_reviewed)
        AutoApprovalSummary.objects.create(
            version=already_content_reviewed.current_version, verdict=amo.AUTO_APPROVED
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

    def test_static_theme_reviewer(self):
        # Create some static themes to test the queue counts.
        addon_factory(
            name='Nominated theme',
            status=amo.STATUS_NOMINATED,
            type=amo.ADDON_STATICTHEME,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        version_factory(
            addon=addon_factory(name='Updated theme', type=amo.ADDON_STATICTHEME),
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        version_factory(
            addon=addon_factory(
                name='Other updated theme',
                type=amo.ADDON_STATICTHEME,
            ),
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        # This is an extension so won't be shown
        addon_factory(
            name='Nominated extension',
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
            reverse('reviewers.queue_theme'),
            reverse('reviewers.reviewlog'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Themes/Guidelines',
        ]
        links = [link.attrib['href'] for link in doc('.dashboard a')]
        assert links == expected_links
        assert doc('.dashboard a')[0].text == 'Awaiting Review (3)'

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
            reverse('reviewers.queue_extension'),
            reverse('reviewers.reviewlog'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Guide',
            reverse('reviewers.queue_moderated'),
            reverse('reviewers.ratings_moderation_log'),
            'https://wiki.mozilla.org/Add-ons/Reviewers/Guide/Moderation',
        ]
        links = [link.attrib['href'] for link in doc('.dashboard a')]
        assert links == expected_links
        assert doc('.dashboard a')[0].text == 'Manual Review (0)'
        assert 'target' not in doc('.dashboard a')[0].attrib
        assert doc('.dashboard a')[3].text == ('Ratings Awaiting Moderation (0)')
        assert 'target' not in doc('.dashboard a')[4].attrib
        assert doc('.dashboard a')[5].text == 'Moderation Guide'
        assert doc('.dashboard a')[5].attrib['target'] == '_blank'
        assert doc('.dashboard a')[5].attrib['rel'] == 'noopener noreferrer'

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
        self.expected_versions = {}
        self.channel_name = 'listed' if self.listed else 'unlisted'

    def generate_files(
        self,
        subset=None,
        files=None,
        auto_approve_disabled=False,
        addon_type=amo.ADDON_EXTENSION,
    ):
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
                            'due_date': self.days_ago(2),
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
                            'due_date': self.days_ago(1),
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
                            'due_date': self.days_ago(0),
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
                            'due_date': self.days_ago(-1),
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
                            'version': '0.1',
                        },
                        'status': amo.STATUS_APPROVED,
                    },
                ),
            ]
        )
        results = OrderedDict()
        reviewer_flags = (
            {
                (
                    'auto_approval_disabled'
                    if self.listed
                    else 'auto_approval_disabled_unlisted'
                ): True
            }
            if auto_approve_disabled
            else None
        )
        for name, attrs in files.items():
            if not subset or name in subset:
                version_kw = attrs.pop('version_kw', {})
                version_kw['channel'] = channel
                file_kw = attrs.pop('file_kw', {})
                results[name] = addon_factory(
                    name=name,
                    version_kw=version_kw,
                    file_kw=file_kw,
                    type=addon_type,
                    reviewer_flags=reviewer_flags,
                    **attrs,
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

    def get_addon_expected_version(self, addon):
        if self.listed:
            channel = amo.CHANNEL_LISTED
        else:
            channel = amo.CHANNEL_UNLISTED
        return addon.find_latest_version(channel=channel)

    def get_expected_addons_by_names(
        self, names, auto_approve_disabled=False, addon_type=amo.ADDON_EXTENSION
    ):
        expected_addons = []
        files = self.generate_files(
            auto_approve_disabled=auto_approve_disabled, addon_type=addon_type
        )
        for name in sorted(names):
            if name in files:
                expected_addons.append(files[name])
        # Make sure all elements have been added
        assert len(expected_addons) == len(names)
        return expected_addons

    def get_expected_versions(self, addons):
        return {addon: self.get_addon_expected_version(addon) for addon in addons}

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
        for _idx, addon in enumerate(self.expected_addons):
            if self.channel_name == 'unlisted' or dont_expect_version_number:
                # In unlisted queue we don't display latest version number.
                name = str(addon.name)
            else:
                expected_version = self.expected_versions[addon]
                if self.channel_name == 'content':
                    channel = [self.channel_name]
                elif expected_version.channel == amo.CHANNEL_LISTED:
                    # We typically don't include the channel name if it's the
                    # default one, 'listed'.
                    channel = []
                else:
                    channel = ['unlisted']
                name = f'{str(addon.name)} {expected_version.version}'
            url = reverse('reviewers.review', args=channel + [addon.pk])
            expected.append((name, url))
        doc = pq(response.content)
        rows = doc('#addon-queue tr.addon-row')
        assert len(rows) == len(self.expected_addons)
        links = doc('#addon-queue tr.addon-row td a:not(.app-icon)')
        assert len(links) == len(self.expected_addons)
        check_links(expected, links)
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
        expected = ['Add-on', 'Due Date', 'Reasons', 'Flags', 'Type']
        assert [pq(th).text() for th in doc('#addon-queue tr th')[1:]] == (expected)

    def test_no_results(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert pq(response.content)('.queue-outer .no-results').length == 1

    def test_paginator_when_many_pages(self):
        # 'Pending One' and 'Pending Two' should be the only add-ons in
        # the pending queue, but we'll generate them all for good measure.
        self.generate_files(auto_approve_disabled=True)

        response = self.client.get(self.url, {'per_page': 1})
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('.pagination').length == 2
        assert doc('.data-grid-top .num-results').text() == ('Results 1\u20131 of 4')
        assert doc('.data-grid-bottom .num-results').text() == ('Results 1\u20131 of 4')

    def test_flags_promoted(self):
        addon = addon_factory(name='Firefox Fún')
        version_factory(
            addon=addon,
            version='1.1',
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
            due_date=datetime.now() + timedelta(hours=24),
        )
        self.make_addon_promoted(addon, PROMOTED_GROUP_CHOICES.LINE)

        r = self.client.get(reverse('reviewers.queue_extension'))

        rows = pq(r.content)('#addon-queue tr.addon-row')
        assert rows.length == 1
        assert rows.attr('data-addon') == str(addon.id)
        assert rows.find('td').eq(1).text() == 'Firefox Fún 1.1'
        assert rows.find('.ed-sprite-promoted-line').length == 1

    def test_flags_abuse_report_forwarded_from_cinder(self):
        addon = addon_factory(name='Firefox Fún')
        version = version_factory(
            addon=addon,
            version='1.1',
            file_kw={'status': amo.STATUS_APPROVED},
            due_date=datetime.now() + timedelta(hours=24),
        )
        NeedsHumanReview.objects.create(
            reason=NeedsHumanReview.REASONS.CINDER_ESCALATION, version=version
        )

        r = self.client.get(reverse('reviewers.queue_extension'))

        rows = pq(r.content)('#addon-queue tr.addon-row')
        assert rows.length == 1
        assert rows.attr('data-addon') == str(addon.id)
        assert rows.find('td').eq(1).text() == 'Firefox Fún 1.1'
        assert rows.find('.ed-sprite-needs-human-review-cinder-escalation').length == 1

    def test_flags_appeal_forwarded_from_cinder(self):
        addon = addon_factory(name='Firefox Fún')
        version = version_factory(
            addon=addon,
            version='1.1',
            file_kw={'status': amo.STATUS_APPROVED},
            due_date=datetime.now() + timedelta(hours=24),
        )
        NeedsHumanReview.objects.create(
            reason=NeedsHumanReview.REASONS.CINDER_APPEAL_ESCALATION, version=version
        )

        r = self.client.get(reverse('reviewers.queue_extension'))

        rows = pq(r.content)('#addon-queue tr.addon-row')
        assert rows.length == 1
        assert rows.attr('data-addon') == str(addon.id)
        assert rows.find('td').eq(1).text() == 'Firefox Fún 1.1'
        assert (
            rows.find('.ed-sprite-needs-human-review-cinder-appeal-escalation').length
            == 1
        )

    def test_tabnav_permissions(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        links = doc('.tabnav li a').map(lambda i, e: e.attrib['href'])
        expected = [reverse('reviewers.queue_extension')]
        assert links == expected

        self.grant_permission(self.user, 'Ratings:Moderate')
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        links = doc('.tabnav li a').map(lambda i, e: e.attrib['href'])
        expected = [
            reverse('reviewers.queue_extension'),
            reverse('reviewers.queue_moderated'),
        ]
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
        expected.append(reverse('reviewers.queue_pending_rejection'))
        assert links == expected

        self.grant_permission(self.user, 'Addons:HighImpactApprove')
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        links = doc('.tabnav li a').map(lambda i, e: e.attrib['href'])
        expected.append(reverse('reviewers.queue_decisions'))
        assert links == expected

    @override_settings(DEBUG=True)
    def test_queue_is_never_executing_the_full_query(self):
        """Test that queue() is paginating without accidentally executing the
        full query."""
        self.grant_permission(self.user, 'Addons:ContentReview')
        request = RequestFactory().get('/')
        request.user = self.user

        self.generate_files()
        qs = Addon.objects.all().no_transforms()

        # Execute the queryset we're passing to the queue() so that we have
        # the exact query to compare to later (we can't use str(qs.query) to do
        # that, it has subtle differences in representation because of the way
        # params are passed for the lang=lang hack).
        reset_queries()
        list(qs)
        assert len(connection.queries) == 1
        full_query = connection.queries[0]['sql']

        reset_queries()
        response = queue(request, 'queue_content_review')
        response.render()
        assert connection.queries
        assert full_query not in [item['sql'] for item in connection.queries]
        assert response.status_code == 200
        doc = pq(response.content)
        assert len(doc('#addon-queue tr.addon-row')) == qs.count()

        request = RequestFactory().get('/', {'per_page': 2})
        request.user = self.user
        reset_queries()
        response = queue(request, 'queue_content_review')
        response.render()
        assert connection.queries
        assert full_query not in [item['sql'] for item in connection.queries]
        assert response.status_code == 200
        doc = pq(response.content)
        assert len(doc('#addon-queue tr.addon-row')) == 2

        request = RequestFactory().get('/', {'per_page': 2, 'page': 2})
        request.user = self.user
        reset_queries()
        response = queue(request, 'queue_content_review')
        response.render()
        assert connection.queries
        assert full_query not in [item['sql'] for item in connection.queries]
        assert response.status_code == 200
        doc = pq(response.content)
        assert len(doc('#addon-queue tr.addon-row')) == 2


class TestExtensionQueue(QueueTest):
    def setUp(self):
        super().setUp()
        # Don't generate add-ons in setUp for this class, its tests are too
        # different from one another, otherwise it would create duplicate as
        # the tests each make their own calls to generate what they need.
        self.url = reverse('reviewers.queue_extension')

    def test_results(self):
        self.expected_addons = self.get_expected_addons_by_names(
            ['Pending One', 'Pending Two', 'Nominated One', 'Nominated Two'],
            auto_approve_disabled=True,
        )
        self.expected_versions = self.get_expected_versions(self.expected_addons)
        with self.assertNumQueries(16):
            # - 2 for savepoints because we're in tests
            # - 2 for user/groups
            # - 1 for the due date cut off config
            # - 1 for the current queue count for pagination purposes
            # - 3 for the addons in the queue, their translations and the
            #     versions (regardless of how many are in the queue - that's
            #     the important bit)
            # - 2 for config items (motd / site notice)
            # - 1 for my add-ons in user menu
            # - 4 for promoted group queries
            self._test_results()

    def test_results_two_versions(self):
        self.expected_addons = self.get_expected_addons_by_names(
            ['Pending One', 'Pending Two', 'Nominated One', 'Nominated Two'],
            auto_approve_disabled=True,
        )
        self.expected_versions = self.get_expected_versions(self.expected_addons)
        version1 = self.addons['Nominated One'].versions.all()[0]
        version2 = self.addons['Nominated Two'].versions.all()[0]
        file_ = version2.file

        # Create another version for Nominated Two, v0.2, by "cloning" v0.1.
        # Its creation date must be more recent than v0.1 for version ordering to work.
        # Its due date must be coherent with that, but also not cause the queue order to
        # change with respect to the other add-ons.
        version2.created = version2.created + timedelta(minutes=1)
        version2_due_date = version2.due_date + timedelta(minutes=1)
        version2.due_date = version2_due_date
        version2.pk = None
        version2.version = '0.2'
        version2.save()

        # Associate v0.2 it with a file.
        file_.pk = None
        file_.version = version2
        file_.save()

        # disable old files like Version.from_upload() would.
        version2.disable_old_files()
        version2.update(due_date=version2_due_date)

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
        check_links(expected, doc('#addon-queue tr.addon-row td a:not(.app-icon)'))

    def test_queue_layout(self):
        self.expected_addons = self.get_expected_addons_by_names(
            ['Pending One', 'Pending Two', 'Nominated One', 'Nominated Two'],
            auto_approve_disabled=True,
        )
        self.expected_versions = self.get_expected_versions(self.expected_addons)
        self._test_queue_layout(
            '🛠️ Manual Review', tab_position=0, total_addons=4, total_queues=1
        )

    def test_empty_name(self):
        self.get_expected_addons_by_names(
            ['Nominated One'],
            auto_approve_disabled=True,
        )
        addon = self.addons['Nominated One']
        addon.name = '  '
        addon.save()

        response = self.client.get(self.url)

        url = reverse('reviewers.review', args=[addon.pk])
        doc = pq(response.content)
        links = doc('#addon-queue tr.addon-row td a:not(.app-icon)')
        a_href = links.eq(0)

        assert a_href.text() == f'[{addon.id}] 0.1'
        assert a_href.attr('href') == url

    def test_webextension_with_auto_approval_delayed_and_no_triage_permission(self):
        self.generate_files()
        AddonReviewerFlags.objects.create(
            addon=self.addons['Pending One'],
            auto_approval_delayed_until=datetime.now() + timedelta(hours=24),
        ).addon.current_version.needshumanreview_set.create(
            reason=NeedsHumanReview.REASONS.AUTO_APPROVAL_DISABLED
        )
        AddonReviewerFlags.objects.create(
            addon=self.addons['Nominated One'],
            auto_approval_delayed_until=datetime.now() + timedelta(hours=24),
        ).addon.current_version.needshumanreview_set.create(
            reason=NeedsHumanReview.REASONS.AUTO_APPROVAL_DISABLED
        )
        AddonReviewerFlags.objects.create(
            addon=self.addons['Pending Two'],
            auto_approval_delayed_until=None,
            auto_approval_disabled=True,
        ).addon.current_version.needshumanreview_set.create(
            reason=NeedsHumanReview.REASONS.AUTO_APPROVAL_DISABLED
        )
        AddonReviewerFlags.objects.create(
            addon=self.addons['Nominated Two'],
            auto_approval_delayed_until=None,
            auto_approval_disabled=True,
        ).addon.current_version.needshumanreview_set.create(
            reason=NeedsHumanReview.REASONS.AUTO_APPROVAL_DISABLED
        )
        self.expected_addons = [
            self.addons['Nominated Two'],
            self.addons['Pending Two'],
        ]
        self.expected_versions = self.get_expected_versions(self.expected_addons)
        self._test_results()

    def test_webextension_with_auto_approval_delayed_with_triage_permission(self):
        self.grant_permission(self.user, 'Addons:TriageDelayed')
        self.generate_files()
        AddonReviewerFlags.objects.create(
            addon=self.addons['Pending One'],
            auto_approval_delayed_until=datetime.now() + timedelta(hours=24),
        ).addon.current_version.needshumanreview_set.create(
            reason=NeedsHumanReview.REASONS.AUTO_APPROVAL_DISABLED
        )
        AddonReviewerFlags.objects.create(
            addon=self.addons['Nominated One'],
            auto_approval_delayed_until=datetime.now() + timedelta(hours=24),
        ).addon.current_version.needshumanreview_set.create(
            reason=NeedsHumanReview.REASONS.AUTO_APPROVAL_DISABLED
        )
        AddonReviewerFlags.objects.create(
            addon=self.addons['Pending Two'],
            auto_approval_delayed_until=None,
        ).addon.current_version.reset_due_date()
        AddonReviewerFlags.objects.create(
            addon=self.addons['Nominated Two'],
            auto_approval_delayed_until=None,
        ).addon.current_version.reset_due_date()
        self.expected_addons = [
            self.addons['Nominated One'],
            self.addons['Pending One'],
        ]
        self.expected_versions = self.get_expected_versions(self.expected_addons)
        doc = self._test_results()
        rows = doc('#addon-queue tr.addon-row')
        for row in rows:
            assert (
                NeedsHumanReview.REASONS.AUTO_APPROVAL_DISABLED.label
                in row.text_content()
            )

    def test_promoted_addon_in_pre_review_group_does_show_up(self):
        self.generate_files()

        self.expected_addons = [
            self.addons['Nominated One'],
            self.addons['Pending One'],
            self.addons['Pending Two'],
        ]
        for addon in self.addons.values():
            if addon in self.expected_addons:
                addon.current_version.needshumanreview_set.create(
                    reason=NeedsHumanReview.REASONS.BELONGS_TO_PROMOTED_GROUP
                )
            else:
                addon.current_version.reset_due_date()
        self.expected_versions = self.get_expected_versions(self.expected_addons)
        # These are the same due_dates we default to in generate_files()
        # (they were reset since the add-ons were not originally promoted when
        # created).
        self.addons['Nominated One'].current_version.update(due_date=self.days_ago(2))
        self.addons['Pending One'].current_version.update(due_date=self.days_ago(0))
        self.addons['Pending Two'].current_version.update(due_date=self.days_ago(-1))

        doc = self._test_results()
        rows = doc('#addon-queue tr.addon-row')
        for row in rows:
            assert (
                NeedsHumanReview.REASONS.BELONGS_TO_PROMOTED_GROUP.label
                in row.text_content()
            )

    def test_static_theme_filtered_out(self):
        self.generate_files(auto_approve_disabled=True)
        self.addons['Pending Two'].update(type=amo.ADDON_STATICTHEME)
        self.addons['Nominated Two'].update(type=amo.ADDON_STATICTHEME)

        # Static Theme shouldn't be shown
        self.expected_addons = [
            self.addons['Nominated One'],
            self.addons['Pending One'],
        ]
        self.expected_versions = self.get_expected_versions(self.expected_addons)
        self._test_results()

        # Even if you have that permission also
        self.grant_permission(self.user, 'Addons:ThemeReview')
        self._test_results()

    def test_pending_rejection_filtered_out(self):
        self.generate_files(auto_approve_disabled=True)
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
        self.expected_versions = self.get_expected_versions(self.expected_addons)
        self._test_results()

    def _setup_queue_with_long_due_dates(self):
        addon_names = self.expected_addons = self.generate_files()
        for addon in addon_names:
            AddonReviewerFlags.objects.create(
                addon=self.addons[addon],
                auto_approval_disabled=True,
            )
            if self.addons[addon].current_version.file.status != amo.STATUS_APPROVED:
                self.addons[addon].current_version.needshumanreview_set.create(
                    reason=NeedsHumanReview.REASONS.AUTO_APPROVAL_DISABLED
                )
        due_date_cutoff_default = amo.config_keys.UPCOMING_DUE_DATE_CUT_OFF_DAYS.default
        self.addons['Nominated One'].current_version.update(
            due_date=get_review_due_date(
                starting=datetime.now()
                + timedelta(days=due_date_cutoff_default, seconds=1)
            )
        )
        self.addons['Pending Two'].current_version.update(
            due_date=get_review_due_date(
                starting=datetime.now()
                + timedelta(days=due_date_cutoff_default, seconds=2)
            )
        )

    def test_long_due_dates_filtered_out(self):
        self._setup_queue_with_long_due_dates()
        self.expected_addons = [
            self.addons['Nominated Two'],
            self.addons['Pending One'],
        ]
        self.expected_versions = self.get_expected_versions(self.expected_addons)
        self._test_results()

    def test_long_due_dates_shown_with_permission(self):
        # self.grant_permission(self.user, 'Addons:AllDueDates')
        self.grant_permission(self.user, '*:*')
        self._setup_queue_with_long_due_dates()
        self.expected_addons = [
            self.addons['Nominated Two'],
            self.addons['Pending One'],
            self.addons['Nominated One'],
            self.addons['Pending Two'],
        ]
        self.expected_versions = self.get_expected_versions(self.expected_addons)
        self._test_results()

    def test_due_date_reason_filter_form(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        # the form is present
        assert doc('#addon-queue-filter-form').length
        # and all the checkboxes are checked by default if there are not GET params
        assert doc(
            '#addon-queue-filter-form input[type="checkbox"]:checked'
        ).length == len(NeedsHumanReview.REASONS)

    def test_due_date_reason_filtering(self):
        self.url += '?due_date_reasons=needs_human_review_abuse_addon_violation'
        self.expected_addons = self.get_expected_addons_by_names(
            ['Pending One', 'Nominated Two'],
            auto_approve_disabled=True,
        )
        self.expected_versions = self.get_expected_versions(self.expected_addons)
        for _, version in self.expected_versions.items():
            NeedsHumanReview.objects.create(
                version=version, reason=NeedsHumanReview.REASONS.ABUSE_ADDON_VIOLATION
            )
        self._test_results()

    def test_due_date_reason_with_two_filters(self):
        # test with two filters applied
        self.url += (
            '?due_date_reasons=needs_human_review_abuse_addon_violation'
            '&due_date_reasons=needs_human_review_developer_reply'
        )
        self.expected_addons = self.get_expected_addons_by_names(
            ['Pending One', 'Nominated One', 'Nominated Two'],
            auto_approve_disabled=True,
        )
        self.expected_versions = self.get_expected_versions(self.expected_addons)
        # pending one and nominated one have a report
        for _, version in list(self.expected_versions.items())[0:2]:
            NeedsHumanReview.objects.create(
                version=version, reason=NeedsHumanReview.REASONS.ABUSE_ADDON_VIOLATION
            )
        # and nominated one and nominated two have a developer reply
        for _, version in list(self.expected_versions.items())[1:]:
            NeedsHumanReview.objects.create(
                version=version, reason=NeedsHumanReview.REASONS.DEVELOPER_REPLY
            )
        doc = self._test_results()
        rows = doc('#addon-queue tr.addon-row')
        assert (
            NeedsHumanReview.REASONS.ABUSE_ADDON_VIOLATION.label
            in rows[0].text_content()
        )
        assert NeedsHumanReview.REASONS.DEVELOPER_REPLY.label in rows[1].text_content()
        assert (
            NeedsHumanReview.REASONS.ABUSE_ADDON_VIOLATION.label
            in rows[1].text_content()
        )
        assert NeedsHumanReview.REASONS.DEVELOPER_REPLY.label in rows[2].text_content()

    def test_different_due_dates_correct_one_is_shown_when_filtering(self):
        self.url += '?due_date_reasons=needs_human_review_developer_reply'
        self.expected_addons = self.get_expected_addons_by_names(
            ['Pending One', 'Public'],
        )
        # Create a NHR that would be filtered out and not inherited on
        # "Pending One" first version with an old due date, then make a new
        # version with a NHR that we are going to filter for, and a different
        # due date. That new version and due date should be the ones shown.
        self.addons['Pending One'].current_version.needshumanreview_set.create(
            reason=NeedsHumanReview.REASONS.ABUSE_ADDON_VIOLATION
        )
        self.addons['Pending One'].current_version.update(due_date=self.days_ago(42))
        self.expected_versions = self.get_expected_versions(self.expected_addons)
        self.expected_versions[self.addons['Pending One']] = version_factory(
            addon=self.addons['Pending One'], version='0.2'
        )
        for version in self.expected_versions.values():
            version.needshumanreview_set.create(
                reason=NeedsHumanReview.REASONS.DEVELOPER_REPLY
            )
            version.update(due_date=self.days_ago(1))

        self.expected_versions[self.addons['Pending One']]
        doc = self._test_results()
        rows = doc('#addon-queue tr.addon-row')
        assert '1\xa0day ago' in rows[0].text_content()


class TestThemeQueue(QueueTest):
    def setUp(self):
        super().setUp()
        # These should be the only ones present.
        self.expected_addons = self.get_expected_addons_by_names(
            ['Nominated One', 'Nominated Two', 'Pending One', 'Pending Two'],
            addon_type=amo.ADDON_STATICTHEME,
        )
        self.expected_versions = self.get_expected_versions(self.expected_addons)
        self.url = reverse('reviewers.queue_theme')
        GroupUser.objects.filter(user=self.user).delete()
        self.grant_permission(self.user, 'Addons:ThemeReview')

    def test_results(self):
        with self.assertNumQueries(15):
            # - 2 for savepoints because we're in tests
            # - 2 for user/groups
            # - 1 for the current queue count for pagination purposes
            # - 3 for the addons in the queue, their translations and the
            #     versions (regardless of how many are in the queue - that's
            #     the important bit)
            # - 2 for config items (motd / site notice)
            # - 1 for my add-ons in user menu
            # - 4 for promoted group queries
            self._test_results()

    def test_queue_ordering_by_due_date(self):
        # Bump pending one to the top by making the due date of its version
        # very old, like they have been waiting for a while.
        version = self.addons['Pending One'].versions.all()[0]
        version.update(due_date=self.days_ago(365))
        response = self.client.get(self.url)
        assert response.status_code == 200
        expected = [
            (
                'Pending One 0.1',
                reverse('reviewers.review', args=[self.addons['Pending One'].pk]),
            ),
            (
                'Nominated One 0.1',
                reverse('reviewers.review', args=[self.addons['Nominated One'].pk]),
            ),
            (
                'Nominated Two 0.1',
                reverse('reviewers.review', args=[self.addons['Nominated Two'].pk]),
            ),
            (
                'Pending Two 0.1',
                reverse('reviewers.review', args=[self.addons['Pending Two'].pk]),
            ),
        ]
        doc = pq(response.content)
        check_links(expected, doc('#addon-queue tr.addon-row td a:not(.app-icon)'))

    def test_results_two_versions(self):
        version1 = self.addons['Nominated One'].versions.all()[0]
        version2 = self.addons['Nominated Two'].versions.all()[0]
        file_ = version2.file

        # Create another version for Nominated Two, v0.2, by "cloning" v0.1.
        # Its creation date must be more recent than v0.1 for version ordering
        # to work. Its due date must be coherent with that, but also
        # not cause the queue order to change with respect to the other
        # add-ons.
        version2.created = version2.created + timedelta(minutes=1)
        version2.due_date = version2.due_date + timedelta(minutes=1)
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
        check_links(expected, doc('#addon-queue tr.addon-row td a:not(.app-icon)'))

    def test_queue_layout(self):
        self._test_queue_layout(
            '🎨 Themes', tab_position=0, total_addons=2, total_queues=1
        )

    def test_extensions_filtered_out(self):
        self.addons['Nominated Two'].update(type=amo.ADDON_EXTENSION)

        # Extension shouldn't be shown
        self.expected_addons = [
            self.addons['Nominated One'],
            self.addons['Pending One'],
            self.addons['Pending Two'],
        ]
        self._test_results()

        # Even if you have that permission also
        self.grant_permission(self.user, 'Addons:Review')
        self._test_results()

    def test_redirects_old_urls(self):
        self.assertRedirects(
            self.client.get('/en-US/reviewers/queue/theme_new'),
            self.url,
            status_code=301,
        )
        self.assertRedirects(
            self.client.get('/en-US/reviewers/queue/theme_updates'),
            self.url,
            status_code=301,
        )


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

    def get_addon_expected_version(self, addon):
        """Method used by get_expected_versions() to fetch the versions that
        the queue is supposed to display. Overridden here because in our case,
        it's not necessarily the latest available version - we display the
        current public version instead (which is not guaranteed to be the
        latest auto-approved one, but good enough) for this page."""
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

        # Those should appear in the queue
        # Has not been auto-approved.
        addon1 = addon_factory(name='Addôn 1', created=self.days_ago(4))

        # Has not been auto-approved either, only dry run.
        addon2 = addon_factory(name='Addôn 2', created=self.days_ago(3))
        AutoApprovalSummary.objects.create(
            version=addon2.current_version,
            verdict=amo.WOULD_HAVE_BEEN_AUTO_APPROVED,
        )

        # This one has never been content-reviewed.
        addon3 = addon_factory(
            name='Addön 3',
            created=self.days_ago(2),
        )
        AutoApprovalSummary.objects.create(
            version=addon3.current_version, verdict=amo.AUTO_APPROVED, confirmed=True
        )
        AddonApprovalsCounter.objects.create(addon=addon3, last_content_review=None)

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
        self.expected_versions = self.get_expected_versions(self.expected_addons)

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
            # - 2 for the addons in the queue, their translations and the
            #     versions (regardless of how many are in the queue - that's
            #     the important bit)
            # - 2 for config items (motd / site notice)
            # - 1 for my add-ons in user menu
            # - 4 for promoted group queries
            self._test_results()

    def test_queue_layout(self):
        self.login_with_permission()
        self.generate_files()

        self._test_queue_layout(
            'Content Review', tab_position=0, total_addons=4, total_queues=1, per_page=1
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
        pending_version_unlisted_addon = version_factory(
            addon=unlisted_addon,
            created=self.days_ago(1),
            version='0.2',
            channel=amo.CHANNEL_UNLISTED,
        )
        version_review_flags_factory(
            version=pending_version_unlisted_addon,
            pending_rejection=datetime.now() - timedelta(hours=1),
        )
        version_factory(
            addon=unlisted_addon, version='0.3', channel=amo.CHANNEL_UNLISTED
        )

        # Extra add-ons without pending rejection, they shouldn't appear.
        addon_factory()

        # Addon 2 has an older creation date, but what matters for the ordering
        # is the pending rejection deadline.
        self.expected_addons = [unlisted_addon, addon1, addon2]
        self.expected_versions = {
            unlisted_addon: pending_version_unlisted_addon,
            addon1: addon1.current_version,
            addon2: addon2.current_version,
        }

    def test_results(self):
        self.login_as_admin()
        self.generate_files()
        with self.assertNumQueries(14):
            # - 2 for savepoints because we're in tests
            # - 2 for user/groups
            # - 1 for the current queue count for pagination purposes
            # - 3 for the addons in the queue, their translations and the
            #     versions (regardless of how many are in the queue - that's
            #     the important bit)
            # - 2 for config items (motd / site notice)
            # - 1 for my add-ons in user menu
            # - 3 for promoted group queries
            self._test_results()


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
        self.addon_author = UserProfile.objects.get(pk=999)
        AddonUser.objects.create(addon=self.addon, user_id=self.addon_author.pk)

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
        self.make_addon_promoted(self.addon, PROMOTED_GROUP_CHOICES.RECOMMENDED)
        self.file.update(status=amo.STATUS_AWAITING_REVIEW)
        response = self.client.get(self.url)
        assert response.status_code == 200
        choices = list(dict(response.context['form'].fields['action'].choices).keys())
        expected_choices = ['reply', 'comment']
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
            'set_needs_human_review_multiple_versions',
            'reply',
            'request_legal_review',
            'comment',
        ]
        assert choices == expected_choices

        doc = pq(response.content)
        assert doc('.is_promoted')
        for entry in doc('.is_promoted').items():
            assert entry.text() == ('This is a Recommended add-on.')

        # Change to a different class of promoted addon
        self.addon.promotedaddon.all().delete()
        self.make_addon_promoted(self.addon, PROMOTED_GROUP_CHOICES.SPOTLIGHT)

        response = self.client.get(self.url)
        assert response.status_code == 200
        choices = list(dict(response.context['form'].fields['action'].choices).keys())
        expected_choices = ['comment']
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
            'change_or_clear_pending_rejection_multiple_versions',
            'clear_needs_human_review_multiple_versions',
            'set_needs_human_review_multiple_versions',
            'reply',
            'disable_addon',
            'request_legal_review',
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

        comment_version = amo.LOG.REVIEWER_PRIVATE_COMMENT
        assert ActivityLog.objects.filter(action=comment_version.id).count() == 1

    @mock.patch('olympia.reviewers.utils.report_decision_to_cinder_and_notify.delay')
    def test_resolve_reports_job(self, resolve_mock):
        cinder_job = CinderJob.objects.create(
            job_id='123', target_addon=self.addon, resolvable_in_reviewer_tools=True
        )
        policy = CinderPolicy.objects.create(
            uuid='x',
            expose_in_reviewer_tools=True,
            enforcement_actions=[DECISION_ACTIONS.AMO_IGNORE.api_value],
        )
        AbuseReport.objects.create(
            guid=self.addon.guid,
            location=AbuseReport.LOCATION.BOTH,
            reason=AbuseReport.REASONS.POLICY_VIOLATION,
            cinder_job=cinder_job,
            reporter_email='foo@baa.com',
        )
        response = self.client.post(
            self.url,
            {
                'action': 'resolve_reports_job',
                'cinder_jobs_to_resolve': [cinder_job.id],
                'cinder_policies': [policy.id],
            },
        )
        assert response.status_code == 302

        activity_log_qs = ActivityLog.objects.filter(
            action=amo.LOG.RESOLVE_CINDER_JOB_WITH_NO_ACTION.id
        )
        assert activity_log_qs.count() == 1
        decision = ContentDecision.objects.get()
        resolve_mock.assert_called_once_with(
            decision_id=decision.id, notify_owners=True
        )
        assert decision.activities.all().get() == activity_log_qs.get()
        assert decision.action == DECISION_ACTIONS.AMO_IGNORE
        self.assertCloseToNow(decision.action_date)

    @mock.patch('olympia.reviewers.utils.report_decision_to_cinder_and_notify.delay')
    def test_resolve_appeal_job(self, resolve_mock):
        appeal_job1 = CinderJob.objects.create(
            job_id='1', resolvable_in_reviewer_tools=True, target_addon=self.addon
        )
        ContentDecision.objects.create(
            appeal_job=appeal_job1,
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
            addon=self.addon,
        )
        ContentDecision.objects.create(
            appeal_job=appeal_job1,
            action=DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON,
            addon=self.addon,
        )

        appeal_job2 = CinderJob.objects.create(
            job_id='2', resolvable_in_reviewer_tools=True, target_addon=self.addon
        )
        ContentDecision.objects.create(
            appeal_job=appeal_job2,
            action=DECISION_ACTIONS.AMO_APPROVE,
            addon=self.addon,
        )

        response = self.client.post(
            self.url,
            {
                'action': 'resolve_appeal_job',
                'comments': 'Nope',
                'cinder_jobs_to_resolve': [appeal_job1.id, appeal_job2.id],
                'appeal_action': ['deny'],
            },
        )
        assert response.status_code == 302

        activity_log_qs = ActivityLog.objects.filter(action=amo.LOG.DENY_APPEAL_JOB.id)
        assert activity_log_qs.count() == 2
        assert ContentDecision.objects.count() == 5  # 2 new
        assert ContentDecision.objects.filter(action_date__isnull=False).count() == 2
        decision2, decision1 = list(
            ContentDecision.objects.filter(action_date__isnull=False)
        )
        log1, log2 = list(activity_log_qs.all())
        assert decision1.activities.get() == log1
        assert decision1.action == DECISION_ACTIONS.AMO_DISABLE_ADDON
        assert decision2.activities.get() == log2
        assert decision2.action == DECISION_ACTIONS.AMO_APPROVE
        assert resolve_mock.call_count == 2

    @mock.patch('olympia.reviewers.utils.report_decision_to_cinder_and_notify.delay')
    def test_request_legal_review(self, report_mock):
        appeal_job = CinderJob.objects.create(
            job_id='1', resolvable_in_reviewer_tools=True, target_addon=self.addon
        )
        ContentDecision.objects.create(
            appeal_job=appeal_job,
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
            addon=self.addon,
        )
        ContentDecision.objects.create(
            appeal_job=appeal_job,
            action=DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON,
            addon=self.addon,
        )
        create_request = responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}create_report',
            json={'job_id': uuid.uuid4().hex},
            status=201,
        )

        response = self.client.post(
            self.url,
            {
                'action': 'request_legal_review',
                'comments': 'Nope',
                'cinder_jobs_to_resolve': [appeal_job.id],
            },
        )
        assert response.status_code == 302

        activity_log_qs = ActivityLog.objects.filter(action=amo.LOG.REQUEST_LEGAL.id)
        assert activity_log_qs.count() == 1
        decision = ContentDecision.objects.last()
        report_mock.assert_called_once_with(decision_id=decision.id, notify_owners=True)
        assert decision.activities.all().get() == activity_log_qs.get()
        assert decision.action == DECISION_ACTIONS.AMO_LEGAL_FORWARD
        self.assertCloseToNow(decision.action_date)
        assert create_request.call_count == 1

    def test_reviewer_reply(self):
        reason = ReviewActionReason.objects.create(
            name='reason 1', is_active=True, canned_response='reason'
        )
        response = self.client.post(
            self.url,
            {
                'action': 'reply',
                'comments': 'hello sailor',
                'reasons': [reason.id],
                'versions': [self.version.pk],
            },
        )
        assert response.status_code == 302
        assert len(mail.outbox) == 1
        self.assertTemplateUsed(response, 'activity/emails/from_reviewer.txt')

    def test_attachment_input(self):
        self.client.post(
            self.url,
            {
                'action': 'reply',
                'comments': 'hello sailor',
                'versions': [self.version.pk],
            },
        )
        # A regular reply does not create an AttachmentLog.
        assert AttachmentLog.objects.count() == 0
        text = 'babys first build log'
        response = self.client.post(
            self.url,
            {
                'action': 'reply',
                'comments': 'hello sailor',
                'versions': [self.version.pk],
                'attachment_input': text,
            },
        )
        assert response.status_code == 302
        assert AttachmentLog.objects.count() == 1
        attachment_log = AttachmentLog.objects.first()
        file_content = attachment_log.file.read().decode('utf-8')
        assert file_content == text

    def test_attachment_valid_upload(self):
        assert AttachmentLog.objects.count() == 0
        text = "I'm a text file"
        attachment = ContentFile(text, name='attachment.txt')
        response = self.client.post(
            self.url,
            {
                'action': 'reply',
                'comments': 'hello sailor',
                'versions': [self.version.pk],
                'attachment_file': attachment,
            },
        )
        assert response.status_code == 302
        assert AttachmentLog.objects.count() == 1
        attachment_log = AttachmentLog.objects.first()
        file_content = attachment_log.file.read().decode('utf-8')
        assert file_content == text

    @override_switch('enable-activity-log-attachments', active=True)
    def test_attachment_invalid_upload(self):
        assert AttachmentLog.objects.count() == 0
        attachment = ContentFile("I'm not a text file", name='attachment.png')
        response = self.client.post(
            self.url,
            {
                'action': 'reply',
                'comments': 'hello sailor',
                'versions': [self.version.pk],
                'attachment_file': attachment,
            },
        )
        assert response.status_code != 302
        assert AttachmentLog.objects.count() == 0
        self.assertIn(
            'Unsupported file type, please upload a file (.txt, .zip)',
            response.content.decode('utf-8'),
        )

    @override_switch('enable-activity-log-attachments', active=True)
    def test_attachment_invalid_zip_upload(self):
        # A file disguised to be a .zip should fail.
        assert AttachmentLog.objects.count() == 0
        attachment = ContentFile("I'm an evil text file", name='attachment.zip')
        response = self.client.post(
            self.url,
            {
                'action': 'reply',
                'comments': 'hello sailor',
                'attachment_file': attachment,
            },
        )
        assert response.status_code != 302
        assert AttachmentLog.objects.count() == 0
        self.assertIn(
            'Invalid or broken archive.',
            response.content.decode('utf-8'),
        )

    @override_switch('enable-activity-log-attachments', active=True)
    def test_attachment_large_upload(self):
        # Any file greater than the limit should be rejected.
        assert AttachmentLog.objects.count() == 0
        file_buffer = io.BytesIO(b'0' * (settings.MAX_UPLOAD_SIZE + 1))
        attachment = DjangoFile(file_buffer, name='im_too_big.txt')
        response = self.client.post(
            self.url,
            {
                'action': 'reply',
                'comments': 'hello sailor',
                'attachment_file': attachment,
            },
        )
        assert response.status_code != 302
        assert AttachmentLog.objects.count() == 0
        self.assertIn(
            'File too large.',
            response.content.decode('utf-8'),
        )

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
                'Validation results',
                reverse('devhub.file_validation', args=[self.addon.slug, file_.id]),
            ),
            ('Open in VSC', None),
        ]
        check_links(expected, items.find('a'))

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
        ActivityLog.objects.create(
            amo.LOG.ADD_USER_WITH_ROLE,
            author.user,
            str(author.get_role_display()),
            self.addon,
        )
        with self.assertNumQueries(60):
            # FIXME: obviously too high, but it's a starting point.
            # Potential further optimizations:
            # - Remove trivial... and not so trivial duplicates
            # - Group similar queries
            # - Try to do counts of things on different page in a single query
            # - Remove useless things like user add-ons and collection
            # - Make some joins
            #
            # 1. savepoint
            # 2. user
            # 3. groups
            # 4. add-on by slug
            # 5. add-on translations
            # 6. add-on categories
            # 7. current version + file
            # 8. current version translations
            # 9. current version applications versions
            # 10. add current_authors property to the addon instance
            # 11. previews
            # 12. latest version in channel + file
            # 13. latest versions translations
            # 14. latest version in channel not disabled + file
            # 15. latest version in channel not disabled translations
            # 16. promoted groups
            # 17  version reviewer flags for current version
            # 18. version reviewer flags for latest version
            # 19. version autoapprovalsummary
            # 20. blocklist
            # 21. cinderjob exists
            # 22. fetch promoted groups of current version
            # 23. waffle switch for cinder_policy_review_reasons_enabled
            # 24. addonreusedguid
            # 25. abuse reports count against user or addon
            # 26. low ratings count
            # 27. base version pk for comparison
            # 28. count of all versions in channel
            # 29. paginated list of versions in channel
            # 30. scanner results for paginated list of versions
            # 31. translations for paginated list of versions
            # 32. applications versions for paginated list of versions
            # 33. activity log for paginated list of versions
            # 34. unreviewed versions in other channel
            # 35. count versions needing human review on other pages
            # 36. count versions pending rejection on other pages
            # 37. versionreviewer flags exists to find out if pending rejection
            # 38. fetch promoted groups of current version (repeated)
            # 39. whiteboard
            # 40. count add-ons the user is a developer of
            # 41. something to do with due_date?
            # 42. reviewer subscriptions for listed
            # 43. reviewer subscriptions for unlisted
            # 44. config for motd
            # 45. release savepoint (?)
            # 46. select users by role for this add-on (?)
            # 47. config for site notice
            # 48. fetch promoted groups of current version (repeated)?
            # 49. other add-ons with same guid
            # 50. translations for... (?! id=1)
            # 51. important activity log about the add-on
            # 52. user for the activity (from the ActivityLog foreignkey)
            # 53. user for the activity (from the ActivityLog arguments)
            # 54. add-on for the activity
            # 55. translation for the add-on for the activity
            # 56. waffle switch enable-activity-log-attachments
            # 57. select all versions in channel for versions dropdown widget
            # 58. reviewer reasons for the reason dropdown
            # 59. cinder policies for the policy dropdown
            # 60. unresolved DSA related abuse reports
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
        version = self.addon.versions.all()[0]

        ApplicationsVersions.objects.create(
            version=version,
            application=amo.ANDROID.id,
            min=AppVersion.objects.get_or_create(
                application=amo.ANDROID.id,
                version=amo.MIN_VERSION_FENIX_GENERAL_AVAILABILITY,
            )[0],
            max=AppVersion.objects.get_or_create(
                application=amo.ANDROID.id,
                version=amo.DEFAULT_WEBEXT_MAX_VERSION,
            )[0],
        )

        assert self.addon.versions.count() == 1
        url = reverse('reviewers.review', args=[self.addon.pk])

        response = self.client.get(url)
        assert response.status_code == 200
        doc = pq(response.content)
        icons = doc('.listing-body .app-icon')
        assert icons.eq(0).attr('title') == 'Firefox for Android'
        assert icons.eq(1).attr('title') == 'Firefox'

    def test_item_history_unreviewed_version_in_unlisted_queue(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert not doc('#unreviewed-other-queue .unreviewed-versions-warning')

        version_factory(
            addon=self.addon,
            channel=amo.CHANNEL_UNLISTED,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
            due_date=datetime.now() + timedelta(hours=1, minutes=1),
        )
        self.addon.update_version()
        assert self.addon.versions.filter(channel=amo.CHANNEL_UNLISTED).count() == 1

        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#unreviewed-other-queue .unreviewed-versions-warning')
        assert doc('#unreviewed-other-queue .unreviewed-versions-warning').text() == (
            'This add-on has 1 or more versions with a due date in another channel.'
        )

    def test_item_history_unreviewed_version_in_listed_queue(self):
        self.addon.versions.update(channel=amo.CHANNEL_UNLISTED)
        self.addon.update_version()
        assert self.addon.versions.filter(channel=amo.CHANNEL_UNLISTED).count() == 1

        self.grant_permission(self.reviewer, 'Addons:ReviewUnlisted')

        unlisted_url = reverse('reviewers.review', args=['unlisted', self.addon.pk])
        response = self.client.get(unlisted_url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert not doc('#unreviewed-other-queue .unreviewed-versions-warning')

        version_factory(
            addon=self.addon,
            channel=amo.CHANNEL_LISTED,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
            due_date=datetime.now() + timedelta(hours=1, minutes=1),
        )
        self.addon.update_version()
        assert self.addon.versions.filter(channel=amo.CHANNEL_LISTED).count() == 1

        response = self.client.get(unlisted_url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#unreviewed-other-queue .unreviewed-versions-warning')
        assert doc('#unreviewed-other-queue .unreviewed-versions-warning').text() == (
            'This add-on has 1 or more versions with a due date in another channel.'
        )

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

    def test_item_history_activities_with_version_no_details_because_alone(self):
        version = self.addon.versions.all()[0]
        core.set_user(UserProfile.objects.get(pk=settings.TASK_USER_ID))
        ActivityLog.objects.create(
            amo.LOG.FORCE_ENABLE,
            self.addon,
            version,
            details={
                'comments': 'Some comment at force enabling',
                'versions': [version.version],
            },
        )
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        details = doc('#versions-history #version-0_1 + tr .activity details')
        assert not details

    def test_item_history_activities_with_version_details(self):
        version1 = self.addon.versions.all()[0]
        version2 = version_factory(addon=self.addon)
        core.set_user(UserProfile.objects.get(pk=settings.TASK_USER_ID))
        ActivityLog.objects.create(
            amo.LOG.FORCE_ENABLE,
            self.addon,
            version1,
            version2,
            details={
                'comments': 'Some comment at force enabling',
                'versions': [version1.version, version2.version],
            },
        )
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        details = doc('#versions-history #version-0_1 + tr .activity details')
        assert details
        lis = details.find('li')
        assert lis[0].text == version1.version
        assert lis[1].text == version2.version

    def test_item_history_header(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert (
            'Approved'
            in doc('#versions-history .review-files .listing-header .light').text()
        )

    @override_switch('enable-activity-log-attachments', active=True)
    def test_item_history_comment(self):
        # Add Comment.
        self.client.post(self.url, {'action': 'comment', 'comments': 'hello sailor'})
        # Add reply with an attachment.
        self.client.post(
            self.url,
            {
                'action': 'reply',
                'comments': 'hello again sailor',
                'versions': [self.version.pk],
                'attachment_input': 'build log',
            },
        )
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert pq(response.content)('#id_attachment_file').attr('data-max-upload-size')
        doc = pq(response.content)('#versions-history .review-files')
        assert doc('th').eq(1).text() == 'Commented'
        assert doc('.history-comment').eq(0).text() == 'hello sailor'
        assert doc('.history-comment').eq(1).text() == 'hello again sailor'
        assert len(doc('.download-reply-attachment')) == 1

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

    def test_item_history_policy_text(self):
        def check_entry(parent):
            assert parent('.activity th').eq(0).text() == 'Force disabled'
            assert parent('.history-comment').length == 3  # comments + 2 policies
            assert parent('li.history-comment').eq(0).text() == 'Text for policy'
            assert parent('li.history-comment').eq(1).text() == 'Another policy'
            assert parent('pre.history-comment').eq(0).text() == 'reasoning!'

        ActivityLog.objects.create(
            amo.LOG.FORCE_DISABLE,
            self.addon,
            self.version,
            details={
                'comments': 'reasoning!',
                'policy_texts': ['Text for policy', 'Another policy'],
            },
            user=self.reviewer,
        )
        response = self.client.get(self.url)
        assert response.status_code == 200
        # the policy text should be in the version history
        version_history = pq(response.content)('#versions-history .review-files')
        check_entry(version_history)
        # and because it's a force disable, in the important changes too
        version_history = pq(response.content)('#important-changes-history')
        check_entry(version_history)

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
        assert items.find('a.reviewers-install').text() == 'Download file'

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
        check_links(expected, doc('#actions-addon a'))

    def test_action_links_as_admin_on_content_review(self):
        self.login_as_admin()
        self.url = reverse('reviewers.review', args=('content', self.addon.pk))
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        expected = [
            ('View Product Page', self.addon.get_url_path()),
            ('Listed Review Page', reverse('reviewers.review', args=(self.addon.id,))),
            ('Edit', self.addon.get_dev_url()),
            ('Admin Page', reverse('admin:addons_addon_change', args=[self.addon.id])),
            ('Statistics', reverse('stats.overview', args=[self.addon.id])),
            (
                'Author(s) Admin List Page',
                reverse('admin:users_userprofile_changelist')
                + f'?q={self.addon_author.id}',
            ),
        ]
        check_links(expected, doc('#actions-addon a'))

    def test_action_links_as_admin(self):
        self.login_as_admin()
        another_author = user_factory()
        self.addon.authors.add(another_author)
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        expected = [
            ('View Product Page', self.addon.get_url_path()),
            (
                'Content Review Page',
                reverse('reviewers.review', args=('content', self.addon.id)),
            ),
            ('Edit', self.addon.get_dev_url()),
            ('Admin Page', reverse('admin:addons_addon_change', args=[self.addon.id])),
            ('Statistics', reverse('stats.overview', args=[self.addon.id])),
            (
                'Author(s) Admin List Page',
                reverse('admin:users_userprofile_changelist')
                + f'?q={self.addon_author.id},{another_author.id}',
            ),
        ]
        check_links(expected, doc('#actions-addon a'))

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
            (
                'Author(s) Admin List Page',
                reverse('admin:users_userprofile_changelist')
                + f'?q={self.addon_author.id}',
            ),
        ]
        check_links(expected, doc('#actions-addon a'))

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
                'Content Review Page',
                reverse('reviewers.review', args=('content', self.addon.id)),
            ),
            (
                'Unlisted Review Page',
                reverse('reviewers.review', args=('unlisted', self.addon.id)),
            ),
            ('Edit', self.addon.get_dev_url()),
            ('Admin Page', reverse('admin:addons_addon_change', args=[self.addon.id])),
            ('Statistics', reverse('stats.overview', args=[self.addon.id])),
            (
                'Author(s) Admin List Page',
                reverse('admin:users_userprofile_changelist')
                + f'?q={self.addon_author.id}',
            ),
        ]
        check_links(expected, doc('#actions-addon a'))

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
            (
                'Content Review Page',
                reverse('reviewers.review', args=('content', self.addon.id)),
            ),
            ('Edit', self.addon.get_dev_url()),
            ('Admin Page', reverse('admin:addons_addon_change', args=[self.addon.id])),
            ('Statistics', reverse('stats.overview', args=[self.addon.id])),
            (
                'Author(s) Admin List Page',
                reverse('admin:users_userprofile_changelist')
                + f'?q={self.addon_author.id}',
            ),
        ]
        check_links(expected, doc('#actions-addon a'))

    def test_mixed_channels_action_links_as_admin_on_content_review(self):
        self.make_addon_unlisted(self.addon)
        version_factory(
            addon=self.addon,
            channel=amo.CHANNEL_LISTED,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        self.addon.update(status=amo.STATUS_NOMINATED)
        self.login_as_admin()
        self.url = reverse('reviewers.review', args=('content', self.addon.pk))
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        expected = [
            ('View Product Page', self.addon.get_url_path()),
            ('Listed Review Page', reverse('reviewers.review', args=(self.addon.id,))),
            (
                'Unlisted Review Page',
                reverse('reviewers.review', args=('unlisted', self.addon.id)),
            ),
            ('Edit', self.addon.get_dev_url()),
            ('Admin Page', reverse('admin:addons_addon_change', args=[self.addon.id])),
            ('Statistics', reverse('stats.overview', args=[self.addon.id])),
            (
                'Author(s) Admin List Page',
                reverse('admin:users_userprofile_changelist')
                + f'?q={self.addon_author.id}',
            ),
        ]
        check_links(expected, doc('#actions-addon a'))

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
                'Content Review Page',
                reverse('reviewers.review', args=('content', self.addon.id)),
            ),
            (
                'Unlisted Review Page',
                reverse('reviewers.review', args=('unlisted', self.addon.id)),
            ),
            ('Admin Page', reverse('admin:addons_addon_change', args=[self.addon.id])),
            ('Statistics', reverse('stats.overview', args=[self.addon.id])),
            (
                'Author(s) Admin List Page',
                reverse('admin:users_userprofile_changelist')
                + f'?q={self.addon_author.id}',
            ),
        ]
        check_links(expected, doc('#actions-addon a'))

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
            (
                'Content Review Page',
                reverse('reviewers.review', args=('content', self.addon.id)),
            ),
            ('Admin Page', reverse('admin:addons_addon_change', args=[self.addon.id])),
            ('Statistics', reverse('stats.overview', args=[self.addon.id])),
            (
                'Author(s) Admin List Page',
                reverse('admin:users_userprofile_changelist')
                + f'?q={self.addon_author.id}',
            ),
        ]
        check_links(expected, doc('#actions-addon a'))

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
            (
                'Content Review Page',
                reverse('reviewers.review', args=('content', self.addon.id)),
            ),
        ]
        check_links(expected, doc('#actions-addon a'))

    def test_admin_links_as_non_admin(self):
        self.login_as_reviewer()
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        expected = [
            ('View Product Page', self.addon.get_url_path()),
            (
                'Content Review Page',
                reverse('reviewers.review', args=('content', self.addon.id)),
            ),
        ]
        check_links(expected, doc('#actions-addon a'))

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
            auto_approval_delayed_until=datetime.now() + timedelta(hours=1),
        )
        version_review_flags_factory(
            version=self.addon.current_version, pending_rejection=datetime.now()
        )
        self.login_as_reviewer()
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
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
        assert not doc('#clear_auto_approval_delayed_until_unlisted')
        assert not doc('#clear_pending_rejections')
        assert not doc('#deny_resubmission')
        assert not doc('#allow_resubmission')

    def test_extra_actions_admin(self):
        self.login_as_admin()
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)

        # Not present because it hasn't been set yet
        assert not doc('#clear_auto_approval_delayed_until')
        assert not doc('#clear_auto_approval_delayed_until_unlisted')

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
        assert not doc('#clear_auto_approval_delayed_until_unlisted')

        flags.update(auto_approval_delayed_until_unlisted=self.days_ago(42))
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        # Present even though it is in the past.
        assert doc('#clear_auto_approval_delayed_until_unlisted')
        # Listed flag should still be there however, that delay has changed.
        assert doc('#clear_auto_approval_delayed_until')

        flags.update(
            auto_approval_delayed_until_unlisted=datetime.now() + timedelta(hours=24)
        )
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#clear_auto_approval_delayed_until')  # Is still there.
        assert doc('#clear_auto_approval_delayed_until_unlisted')  # Is still there.

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

        # If the guid is in a pending submission we show a link to that too
        subm = BlocklistSubmission.objects.create(input_guids=self.addon.guid)
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert not doc('#block_addon')
        assert doc('#edit_addon_block')
        blocklistsubmission_block = doc('#edit_addon_blocklistsubmission')
        assert blocklistsubmission_block
        assert blocklistsubmission_block[0].attrib.get('href') == (
            reverse('admin:blocklist_blocklistsubmission_change', args=(subm.id,))
        )

    def test_admin_block_actions_deleted_addon(self):
        # Use the id for the review page url because deleting the add-on will
        # delete the slug as well.
        self.url = reverse('reviewers.review', args=[self.addon.id])
        self.addon.update(status=amo.STATUS_DELETED)
        self.addon.versions.update(deleted=True)
        self.test_admin_block_actions()

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

    def test_no_public(self):
        assert self.version.file.status == amo.STATUS_APPROVED

        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)

        validation = doc.find('.files')
        assert validation.find('a').eq(1).text() == 'Validation results'
        assert validation.find('a').eq(2).text() == 'Open in VSC'

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
        reason = ReviewActionReason.objects.create(
            name='reason 1', is_active=True, canned_response='reason'
        )
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
            'versions': [version.pk],
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

    def test_assay_link(self):
        self.addon.current_version.update()
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        assay_info = doc('#versions-history .file-info .assay')
        assert assay_info[0].text.strip() == 'Open in VSC'
        assert (
            assay_info.attr['href']
            == f'vscode://mozilla.assay/review/{self.addon.guid}/{self.addon.current_version.version}'
        )

    def _setup_source(self):
        version = self.addon.current_version
        tdir = temp.gettempdir()
        source_file = temp.NamedTemporaryFile(suffix='.zip', dir=tdir, mode='r+')
        source_file.write('a' * (2**21))
        source_file.seek(0)
        version.source.save(os.path.basename(source_file.name), DjangoFile(source_file))
        version.save()

    def test_download_sources_link(self):
        self._setup_source()
        url = reverse('reviewers.review', args=[self.addon.pk])

        # Admin user: able to download sources.
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

        # A reviewer with source code view access should be able to download too
        self.grant_permission(user, ':'.join(amo.permissions.ADDONS_SOURCE_DOWNLOAD))
        self.client.force_login(user)
        response = self.client.get(url, follow=True)
        assert response.status_code == 200
        assert b'Download files' in response.content

    @override_settings(SOURCE_BUILDER_VIEWER_URL='https://source.builder/')
    @override_switch('enable-source-builder', active=True)
    def test_source_builder_link(self):
        self._setup_source()
        url = reverse('reviewers.review', args=[self.addon.pk])

        response = self.client.get(url)
        assert response.status_code == 200
        doc = pq(response.content)
        builder_link = doc('#versions-history td.files .source-builder')
        assert builder_link[0].text == 'Source Builder'
        assert (
            builder_link.attr['href']
            == f'https://source.builder/?addon_id={self.addon.id}&version_id={self.addon.current_version.id}'
        )

    @override_settings(SOURCE_BUILDER_VIEWER_URL='https://source.builder/')
    @override_switch('enable-source-builder', active=False)
    def test_no_source_link_if_waffle_off(self):
        self._setup_source()
        url = reverse('reviewers.review', args=[self.addon.pk])

        response = self.client.get(url)
        assert response.status_code == 200
        doc = pq(response.content)
        assert not doc('#versions-history td.files .source-builder')

    def test_translations(self):
        self.addon.name = {
            'de': None,
            'en-CA': 'English Translation',
            'en-GB': 'English Translation',  # Duplicate
            'es-ES': '',
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
        reason = ReviewActionReason.objects.create(
            name='reason 1', is_active=True, canned_response='reason'
        )
        self.version.file.update(status=amo.STATUS_AWAITING_REVIEW)
        self.addon.update(status=amo.STATUS_NOMINATED)
        self.make_addon_promoted(self.addon, PROMOTED_GROUP_CHOICES.RECOMMENDED)
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
        assert addon.current_version.promoted_versions.filter(
            promoted_group__group_id=PROMOTED_GROUP_CHOICES.RECOMMENDED
        ).exists()
        assert mock_sign_file.called

    @mock.patch('olympia.reviewers.utils.sign_file')
    def test_approve_addon_for_unlisted_pre_review_promoted_groups(
        self, mock_sign_file
    ):
        reason = ReviewActionReason.objects.create(
            name='reason 1', is_active=True, canned_response='reason'
        )
        self.version.file.update(status=amo.STATUS_AWAITING_REVIEW)
        self.addon.update(status=amo.STATUS_NULL)
        self.make_addon_promoted(self.addon, PROMOTED_GROUP_CHOICES.NOTABLE)
        self.make_addon_unlisted(self.addon)
        self.grant_permission(self.reviewer, 'Addons:Review')
        self.grant_permission(self.reviewer, 'Addons:ReviewUnlisted')
        unlisted_url = reverse('reviewers.review', args=['unlisted', self.addon.pk])
        response = self.client.post(
            unlisted_url,
            {
                'action': 'approve_multiple_versions',
                'comments': 'all good',
                'reasons': [reason.id],
                'versions': [self.version.id],
            },
        )
        assert response.status_code == 302
        self.assert3xx(response, unlisted_url)
        self.version.file.reload()
        assert self.version.file.status == amo.STATUS_APPROVED
        assert self.version.promoted_versions.filter(
            promoted_group__group_id=PROMOTED_GROUP_CHOICES.NOTABLE
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

    def test_approve_listing_content_review(self):
        GroupUser.objects.filter(user=self.reviewer).all().delete()
        content_url = reverse('reviewers.review', args=['content', self.addon.pk])
        summary = AutoApprovalSummary.objects.create(
            version=self.addon.current_version, verdict=amo.AUTO_APPROVED
        )
        self.grant_permission(self.reviewer, 'Addons:ContentReview')
        response = self.client.post(
            content_url,
            {
                'action': 'approve_listing_content',
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
            ActivityLog.objects.filter(
                action=amo.LOG.APPROVE_LISTING_CONTENT.id
            ).count()
            == 1
        )
        a_log = ActivityLog.objects.filter(
            action=amo.LOG.APPROVE_LISTING_CONTENT.id
        ).get()
        assert a_log.details['comments'] == ''
        assert (
            AddonApprovalsCounter.objects.get(addon=self.addon).last_content_review_pass
            is True
        )
        self.assert3xx(response, content_url)

    def test_approve_rejected_listing_content_review(self):
        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}create_decision',
            json={'uuid': uuid.uuid4().hex},
            status=201,
        )
        assert AddonApprovalsCounter.objects.update_or_create(
            addon=self.addon, defaults={'last_content_review_pass': False}
        )
        self.addon.update(status=amo.STATUS_REJECTED)
        GroupUser.objects.filter(user=self.reviewer).all().delete()
        content_url = reverse('reviewers.review', args=['content', self.addon.pk])
        self.grant_permission(self.reviewer, 'Addons:ContentReview')
        response = self.client.post(
            content_url,
            {
                'action': 'approve_rejected_listing_content',
                'comments': 'ignore me this action does not support comments',
            },
        )
        assert response.status_code == 302
        assert (
            ActivityLog.objects.filter(
                action=amo.LOG.APPROVE_REJECTED_LISTING_CONTENT.id
            ).count()
            == 1
        )
        a_log = ActivityLog.objects.filter(
            action=amo.LOG.APPROVE_REJECTED_LISTING_CONTENT.id
        ).get()
        assert a_log.details['comments'] == ''
        assert (
            AddonApprovalsCounter.objects.get(addon=self.addon).last_content_review_pass
            is True
        )
        self.assert3xx(response, content_url)

    @override_switch('enable-content-rejection', active=True)
    @override_switch('cinder_policy_review_reasons_enabled', active=True)
    def test_reject_listing_content_review(self):
        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}create_decision',
            json={'uuid': uuid.uuid4().hex},
            status=201,
        )
        GroupUser.objects.filter(user=self.reviewer).all().delete()
        content_url = reverse('reviewers.review', args=['content', self.addon.pk])
        summary = AutoApprovalSummary.objects.create(
            version=self.addon.current_version, verdict=amo.AUTO_APPROVED
        )
        policy = CinderPolicy.objects.create(
            uuid='x',
            expose_in_reviewer_tools=True,
            enforcement_actions=[DECISION_ACTIONS.AMO_APPROVE.api_value],
        )
        self.grant_permission(self.reviewer, 'Addons:ContentReview')

        response = self.client.post(
            content_url,
            {
                'action': 'reject_listing_content',
                'cinder_policies': [policy.id],
                'comments': 'Reject does support comments',
            },
        )

        assert response.status_code == 302, response.context['form'].errors
        summary.reload()
        assert summary.confirmed is None  # We're only doing a content review.
        assert (
            ActivityLog.objects.filter(action=amo.LOG.CONFIRM_AUTO_APPROVED.id).count()
            == 0
        )
        assert (
            ActivityLog.objects.filter(action=amo.LOG.REJECT_LISTING_CONTENT.id).count()
            == 1
        )
        a_log = ActivityLog.objects.filter(
            action=amo.LOG.REJECT_LISTING_CONTENT.id
        ).get()
        assert a_log.details['comments'] == 'Reject does support comments'
        self.assert3xx(response, content_url)
        assert (
            AddonApprovalsCounter.objects.get(addon=self.addon).last_content_review_pass
            is False
        )
        assert (
            responses.calls[0].request.url
            == f'{settings.CINDER_SERVER_URL}create_decision'
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
        reason = ReviewActionReason.objects.create(
            name='reason 1', is_active=True, canned_response='reason'
        )
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
        # This matters because `version` is used in the formatting string - it
        # shouldn't be `versions` plural.
        assert a_log.details['version'] == self.addon.current_version.version
        assert a_log.details['comments'] == ''
        self.assert3xx(response, self.listed_url)

    @mock.patch('olympia.reviewers.utils.sign_file')
    def test_approve_multiple_versions(self, sign_file_mock):
        self.url = reverse('reviewers.review', args=('unlisted', self.addon.pk))
        reason = ReviewActionReason.objects.create(
            name='reason 1', is_active=True, canned_response='reason'
        )
        old_version = self.version
        old_version.update(channel=amo.CHANNEL_UNLISTED)
        NeedsHumanReview.objects.create(version=old_version)
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
            assert not version.needshumanreview_set.filter(is_active=True).exists()
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
        old_version.update(channel=amo.CHANNEL_UNLISTED)
        NeedsHumanReview.objects.create(version=old_version)
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
            assert not version.needshumanreview_set.filter(is_active=True)
            file_ = version.file.reload()
            assert file_.status == amo.STATUS_APPROVED
            assert not version.pending_rejection

        sign_file_mock.assert_has_calls(
            (mock.call(old_version.file), mock.call(self.version.file))
        )

    def test_reject_multiple_versions(self):
        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}create_decision',
            json={'uuid': uuid.uuid4().hex},
            status=201,
        )
        reason = ReviewActionReason.objects.create(
            name='reason 1', is_active=True, canned_response='reason'
        )
        old_version = self.version
        NeedsHumanReview.objects.create(version=old_version)
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
            },
        )

        assert response.status_code == 302
        for version in [old_version, self.version]:
            version.reload()
            assert not version.needshumanreview_set.filter(is_active=True)
            file_ = version.file.reload()
            assert file_.status == amo.STATUS_DISABLED
            assert not version.pending_rejection

    def test_reject_multiple_versions_with_no_delay(self):
        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}create_decision',
            json={'uuid': uuid.uuid4().hex},
            status=201,
        )
        reason = ReviewActionReason.objects.create(
            name='reason 1', is_active=True, canned_response='reason'
        )
        old_version = self.version
        NeedsHumanReview.objects.create(version=old_version)
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
            assert not version.needshumanreview_set.filter(is_active=True)
            file_ = version.file.reload()
            assert file_.status == amo.STATUS_DISABLED
            assert not version.pending_rejection

    def test_reject_multiple_versions_with_delay(self):
        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}create_decision',
            json={'uuid': uuid.uuid4().hex},
            status=201,
        )
        reason = ReviewActionReason.objects.create(
            name='reason 1', is_active=True, canned_response='reason'
        )
        old_version = self.version
        NeedsHumanReview.objects.create(version=old_version)
        self.version = version_factory(addon=self.addon, version='3.0')
        AutoApprovalSummary.objects.create(
            version=self.addon.current_version, verdict=amo.AUTO_APPROVED
        )
        GroupUser.objects.filter(user=self.reviewer).all().delete()
        self.grant_permission(self.reviewer, 'Addons:Review,Reviews:Admin')

        in_the_future = datetime.now() + timedelta(
            days=REVIEWER_DELAYED_REJECTION_PERIOD_DAYS_DEFAULT, hours=1
        )

        response = self.client.post(
            self.url,
            {
                'action': 'reject_multiple_versions',
                'comments': 'multireject with delay!',
                'reasons': [reason.id],
                'versions': [old_version.pk, self.version.pk],
                'delayed_rejection': 'True',
                'delayed_rejection_date': in_the_future.isoformat()[:16],
            },
        )

        assert response.status_code == 302
        for version in [old_version, self.version]:
            version.reload()
            # The versions no longer need human review...
            assert not version.needshumanreview_set.filter(is_active=True)
            file_ = version.file
            # ... But their status shouldn't have changed yet ...
            assert file_.status == amo.STATUS_APPROVED
            # ... Because they are now pending rejection.
            assert version.pending_rejection
            self.assertCloseToNow(version.pending_rejection, now=in_the_future)

    @override_switch('cinder_policy_review_reasons_enabled', active=True)
    def test_reject_with_policy_selection(self):
        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}create_decision',
            json={'uuid': uuid.uuid4().hex},
            status=201,
        )
        policy = CinderPolicy.objects.create(
            uuid='123-reject',
            name='Bad thing',
            expose_in_reviewer_tools=True,
            enforcement_actions=[
                DECISION_ACTIONS.AMO_DISABLE_ADDON.api_value,
                'some-other-action',
            ],
            text='Policy with {PLACEHOLDER} and {another} not {MISSING}',
        )
        old_version = self.version
        NeedsHumanReview.objects.create(version=old_version)
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
                'cinder_policies': [policy.id],
                'versions': [old_version.pk, self.version.pk],
                'delayed_rejection': 'False',
                f'policy_values_{policy.id}_PLACEHOLDER': 'bad things',
                f'policy_values_{policy.id}_another': 'stuff!',
            },
        )

        assert response.status_code == 302
        for version in [old_version, self.version]:
            version.reload()
            assert not version.needshumanreview_set.filter(is_active=True)
            file_ = version.file.reload()
            assert file_.status == amo.STATUS_DISABLED
            assert not version.pending_rejection
        decision = ContentDecision.objects.first()
        assert list(decision.policies.all()) == [policy]
        assert decision.metadata[ContentDecision.POLICY_DYNAMIC_VALUES] == {
            policy.uuid: {
                'PLACEHOLDER': 'bad things',
                'another': 'stuff!',
            }
        }
        alog = ActivityLog.objects.filter(contentdecisionlog__decision=decision).get()
        assert alog.details['policy_texts'] == [
            'Bad thing: Policy with bad things and stuff! not {MISSING}'
        ]

    @override_switch('cinder_policy_review_reasons_enabled', active=True)
    def test_form_error_persists_placeholder_values(self):
        policy = CinderPolicy.objects.create(
            uuid='123-reject',
            name='Bad thing',
            expose_in_reviewer_tools=True,
            enforcement_actions=[
                DECISION_ACTIONS.AMO_DISABLE_ADDON.api_value,
                'some-other-action',
            ],
            text='Policy with {PLACEHOLDER} and {another} not {MISSING}',
        )
        self.version = version_factory(addon=self.addon, version='3.0')
        GroupUser.objects.filter(user=self.reviewer).all().delete()
        self.grant_permission(self.reviewer, 'Addons:Review')

        response = self.client.post(
            self.url,
            {
                'action': 'reject_multiple_versions',
                'comments': 'multireject!',
                'cinder_policies': [policy.id],
                # not sending versions - should be an error
                'delayed_rejection': 'False',
                f'policy_values_{policy.id}_PLACEHOLDER': 'bad things',
                f'policy_values_{policy.id}_another': 'stuff!',
            },
        )

        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#id_policy_values_0').attr.name == (
            f'policy_values_{policy.id}_PLACEHOLDER'
        )
        assert doc('#id_policy_values_0').attr.value == 'bad things'
        assert doc('#id_policy_values_1').attr.name == (
            f'policy_values_{policy.id}_another'
        )
        assert doc('#id_policy_values_1').attr.value == 'stuff!'

    def test_change_pending_rejection_date(self):
        self.grant_permission(self.reviewer, 'Addons:Review,Reviews:Admin')
        old_version = self.version
        in_the_future = datetime.now() + timedelta(hours=1)
        in_the_future2 = datetime.now() + timedelta(days=2, hours=1)
        self.version = version_factory(addon=self.addon, version='3.0')
        for version in (old_version, self.version):
            version_review_flags_factory(
                version=version,
                pending_rejection=in_the_future,
                pending_rejection_by=self.reviewer,
                pending_content_rejection=False,
            )
            NeedsHumanReview.objects.create(version=version)

        response = self.client.post(
            self.url,
            {
                'action': 'change_or_clear_pending_rejection_multiple_versions',
                'versions': [old_version.pk, self.version.pk],
                'delayed_rejection': 'True',
                'delayed_rejection_date': in_the_future2.isoformat()[:16],
            },
        )
        assert response.status_code == 302
        for version in [old_version, self.version]:
            version.reload()
            version.reviewerflags.reload()
            # NeedsHumanReview was *not* cleared.
            assert version.needshumanreview_set.filter(is_active=True)
            file_ = version.file
            # ... But their status shouldn't have changed yet ...
            assert file_.status == amo.STATUS_APPROVED
            # ... Because they are still pending rejection, with the new date.
            assert version.pending_rejection
            self.assertCloseToNow(version.pending_rejection, now=in_the_future2)

    def test_unreject_latest_version(self):
        old_version = self.version
        version_factory(addon=self.addon, version='2.99')
        old_version.file.update(status=amo.STATUS_DISABLED)
        self.version = version_factory(
            addon=self.addon,
            version='3.0',
            human_review_date=datetime.now(),
            file_kw={'status': amo.STATUS_DISABLED},
        )
        GroupUser.objects.filter(user=self.reviewer).all().delete()
        self.grant_permission(self.reviewer, 'Addons:Review')
        self.grant_permission(self.reviewer, 'Reviews:Admin')
        assert self.addon.status == amo.STATUS_APPROVED

        response = self.client.post(self.url, {'action': 'unreject_latest_version'})

        assert response.status_code == 302
        assert old_version.file.reload().status == amo.STATUS_DISABLED
        assert self.version.file.reload().status == amo.STATUS_AWAITING_REVIEW
        assert self.addon.reload().status == amo.STATUS_APPROVED

    def test_unreject_latest_version_to_nominated(self):
        old_version = self.version
        old_version.file.update(status=amo.STATUS_DISABLED)
        self.version = version_factory(
            addon=self.addon,
            version='3.0',
            human_review_date=datetime.now(),
            file_kw={'status': amo.STATUS_DISABLED},
        )
        GroupUser.objects.filter(user=self.reviewer).all().delete()
        self.grant_permission(self.reviewer, 'Addons:Review')
        self.grant_permission(self.reviewer, 'Reviews:Admin')
        assert self.addon.status == amo.STATUS_NULL

        response = self.client.post(self.url, {'action': 'unreject_latest_version'})

        assert response.status_code == 302
        assert old_version.file.reload().status == amo.STATUS_DISABLED
        assert self.version.file.reload().status == amo.STATUS_AWAITING_REVIEW
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
        NeedsHumanReview.objects.create(version=old_version)
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
        ) + '?guids={}&v={}&v={}'.format(
            self.addon.guid, old_version.pk, self.version.pk
        )
        self.assertRedirects(response, new_block_url)

    def test_clear_needs_human_review(self):
        old_version = self.version
        NeedsHumanReview.objects.create(version=old_version)
        self.version = version_factory(addon=self.addon)
        NeedsHumanReview.objects.create(version=self.version)

        GroupUser.objects.filter(user=self.reviewer).all().delete()
        self.grant_permission(self.reviewer, 'Addons:Review')

        response = self.client.post(
            self.url,
            {
                'comments': 'this does not need human review anymore!',
                'versions': [old_version.pk, self.version.pk],
                'action': 'clear_needs_human_review_multiple_versions',
            },
        )
        # the action needs an admin
        assert response.status_code == 200
        assert self.version.needshumanreview_set.filter(is_active=True).exists()
        assert old_version.needshumanreview_set.filter(is_active=True).exists()

        self.grant_permission(self.reviewer, 'Reviews:Admin')
        response = self.client.post(
            self.url,
            {
                'comments': 'this does not need human review anymore!',
                'versions': [old_version.pk, self.version.pk],
                'action': 'clear_needs_human_review_multiple_versions',
            },
        )
        assert response.status_code == 302
        assert not self.version.needshumanreview_set.filter(is_active=True).exists()
        assert not old_version.needshumanreview_set.filter(is_active=True).exists()

    def test_clear_needs_human_review_deleted_addon(self):
        self.addon.delete()
        self.test_clear_needs_human_review()

    def test_block_multiple_versions_deleted_addon(self):
        self.addon.delete()
        self.test_block_multiple_versions()

    def test_important_changes_log(self):
        # Activity logs related to authorship and specific reviewer/admin
        # changes applying to the entire add-on should be shown in important
        # changes log section.
        author = self.addon.addonuser_set.get()
        core.set_user(author.user)
        expected_activities = [
            ActivityLog.objects.create(
                amo.LOG.ADD_USER_WITH_ROLE,
                author.user,
                str(author.get_role_display()),
                self.addon,
            ),
            ActivityLog.objects.create(
                amo.LOG.CHANGE_USER_WITH_ROLE,
                author.user,
                str(author.get_role_display()),
                self.addon,
            ),
            ActivityLog.objects.create(
                amo.LOG.REMOVE_USER_WITH_ROLE,
                author.user,
                str(author.get_role_display()),
                self.addon,
            ),
            ActivityLog.objects.create(
                amo.LOG.REQUEST_LEGAL,
                self.addon,
                details={'comments': 'Some comment for legal'},
            ),
            ActivityLog.objects.create(amo.LOG.FORCE_DISABLE, self.addon),
            ActivityLog.objects.create(
                amo.LOG.FORCE_ENABLE,
                self.addon,
                details={'comments': 'Some comment at force enabling'},
            ),
            ActivityLog.objects.create(
                amo.LOG.ENABLE_AUTO_APPROVAL,
                self.addon,
                details={
                    'channel': amo.CHANNEL_LISTED,
                    'comments': 'enabled auto-approval on listed',
                },
            ),
            ActivityLog.objects.create(
                amo.LOG.DISABLE_AUTO_APPROVAL,
                self.addon,
                details={
                    'channel': amo.CHANNEL_UNLISTED,
                    'comments': 'disabled auto-approval on unlisted',
                },
            ),
            ActivityLog.objects.create(
                amo.LOG.APPROVE_LISTING_CONTENT,
                self.addon,
            ),
            ActivityLog.objects.create(
                amo.LOG.REJECT_LISTING_CONTENT,
                self.addon,
            ),
            ActivityLog.objects.create(
                amo.LOG.HELD_ACTION_REJECT_LISTING_CONTENT,
                self.addon,
            ),
        ]

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
            amo.LOG.REQUEST_LEGAL.id,
            amo.LOG.FORCE_DISABLE.id,
            amo.LOG.FORCE_ENABLE.id,
            amo.LOG.ENABLE_AUTO_APPROVAL.id,
            amo.LOG.DISABLE_AUTO_APPROVAL.id,
            amo.LOG.APPROVE_LISTING_CONTENT.id,
            amo.LOG.REJECT_LISTING_CONTENT.id,
            amo.LOG.HELD_ACTION_REJECT_LISTING_CONTENT.id,
        ]

        # Make sure the logs are displayed in the page.
        important_changes = doc('#important-changes-history table.activity tr')
        assert len(important_changes) == len(actions)

        for i, activity in enumerate(expected_activities):
            change = doc(f'#important-changes-history .activity tr:nth-child({i + 1})')
            assert (
                f'By {activity.user.name} on {format_datetime(activity.created)}'
                in change[0].text_content()
            )
            if activity.details and activity.details.get('comments'):
                assert activity.details['comments'] in change.html()
            else:
                assert activity.to_string('reviewer')
                assert activity.to_string('reviewer') in change.html()

        change_text = doc('#important-changes-history .activity tr:nth-child(7)').text()
        assert change_text.startswith('Auto-Approval enabled (Listed)')
        change_text = doc('#important-changes-history .activity tr:nth-child(8)').text()
        assert change_text.startswith('Auto-Approval disabled (Unlisted)')

    def test_important_changes_log_with_versions_attached(self):
        version1 = self.addon.versions.get()
        version2 = version_factory(addon=self.addon)
        author = self.addon.addonuser_set.get()
        core.set_user(author.user)
        ActivityLog.objects.create(
            amo.LOG.FORCE_ENABLE,
            self.addon,
            version1,
            version2,
            details={
                'comments': 'Some comment at force enabling',
                'versions': [version1.version, version2.version],
            },
        )
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        important_changes = doc('#important-changes-history table.activity tr')
        assert len(important_changes) == 1
        details = doc('#important-changes-history .activity tr:nth-child(1) details')
        assert details
        lis = details.find('li')
        assert len(lis) == 2
        assert lis[0].text == version1.version
        assert lis[1].text == version2.version

    def test_important_changes_log_with_only_one_version_attached(self):
        version = self.addon.versions.get()
        author = self.addon.addonuser_set.get()
        core.set_user(author.user)
        ActivityLog.objects.create(
            amo.LOG.FORCE_ENABLE,
            self.addon,
            version,
            details={
                'comments': 'Some comment at force enabling',
                'versions': [version.version],
            },
        )
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        important_changes = doc('#important-changes-history table.activity tr')
        assert len(important_changes) == 1
        details = doc('#important-changes-history .activity tr:nth-child(1) details')
        assert details
        lis = details.find('li')
        assert len(lis) == 1
        assert lis[0].text == version.version

    def test_important_changes_log_with_too_many_versions_attached(self):
        author = self.addon.addonuser_set.get()
        core.set_user(author.user)
        MAX_MOCK = 5
        ActivityLog.objects.create(
            amo.LOG.FORCE_ENABLE,
            self.addon,
            details={
                'comments': 'Some comment at force enabling',
                'versions': [f'{i}.0' for i in range(1, MAX_MOCK + 2)],
            },
        )
        with mock.patch('olympia.reviewers.views.MAX_VERSIONS_SHOWN_INLINE', MAX_MOCK):
            response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        important_changes = doc('#important-changes-history table.activity tr')
        assert len(important_changes) == 1
        details = doc('#important-changes-history .activity tr:nth-child(1) details')
        assert details
        lis = details.find('li')
        assert len(lis) == MAX_MOCK + 1
        for i, li in enumerate(lis[:MAX_MOCK], start=1):
            assert li.text == f'{i}.0'
        assert lis[MAX_MOCK].text == '...'

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
        host_permissions = ['https://example.com', 'https://mozilla.com']
        permissions = ['bookmarks', 'high', 'voltage']
        optional_permissions = ['optional', 'high', 'voltage']
        WebextPermission.objects.create(
            host_permissions=host_permissions,
            optional_permissions=optional_permissions,
            permissions=permissions,
            file=self.file,
        )
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        info = doc('#versions-history div.file-permissions')
        assert info.eq(0).text() == 'Permissions:\n' + ', '.join(permissions)
        assert info.eq(1).text() == 'Optional permissions:\n' + ', '.join(
            optional_permissions
        )
        assert info.eq(2).text() == 'Host permissions:\n' + ', '.join(host_permissions)

    def test_abuse_reports(self):
        report = AbuseReport.objects.create(
            guid=self.addon.guid,
            message='Et mël mazim ludus.',
            country_code='FR',
            client_id='4815162342',
            addon_name='Nâme',
            addon_summary='Not used here',
            addon_version=amo.DEFAULT_WEBEXT_MIN_VERSION,
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
            # We use the name as submitted in the abuse report.
            f'Nâme {amo.DEFAULT_WEBEXT_MIN_VERSION}',
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
            'confirm_auto_approved',
            'reject_multiple_versions',
            'set_needs_human_review_multiple_versions',
            'reply',
            'request_legal_review',
            'comment',
        ]
        assert [
            act.attrib['data-value'] for act in doc('.data-toggle.review-actions-desc')
        ] == expected_actions_values

        assert doc('select#id_versions.data-toggle')[0].attrib['data-value'].split(
            ' '
        ) == [
            'reject_multiple_versions',
            'set_needs_human_review_multiple_versions',
            'reply',
        ]

        assert (
            doc('select#id_versions.data-toggle option')[0].text
            == f'{self.version.version} - Auto-approved, not Confirmed'
        )

        assert doc('.data-toggle.review-comments')[0].attrib['data-value'].split(
            ' '
        ) == [
            'reject_multiple_versions',
            'set_needs_human_review_multiple_versions',
            'reply',
            'request_legal_review',
            'comment',
        ]

        assert doc('.data-toggle.review-actions-reasons')[0].attrib['data-value'].split(
            ' '
        ) == ['reject_multiple_versions', 'reply']

        assert doc('.data-toggle.review-delayed-rejection')[0].attrib[
            'data-value'
        ].split(' ') == [
            'reject_multiple_versions',
        ]

        # We don't have approve/reject actions so these have an empty
        # data-value.
        assert doc('.data-toggle.review-files')[0].attrib['data-value'] == ''
        assert doc('.data-toggle.review-tested')[0].attrib['data-value'] == ''

    def test_test_data_value_attributes_admin(self):
        AutoApprovalSummary.objects.create(
            verdict=amo.AUTO_APPROVED, version=self.version
        )
        self.grant_permission(self.reviewer, 'Addons:Review,Reviews:Admin')
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)

        expected_actions_values = [
            'confirm_auto_approved',
            'reject_multiple_versions',
            'change_or_clear_pending_rejection_multiple_versions',
            'clear_needs_human_review_multiple_versions',
            'set_needs_human_review_multiple_versions',
            'disable_auto_approval',
            'reply',
            'disable_addon',
            'request_legal_review',
            'comment',
        ]
        assert [
            act.attrib['data-value'] for act in doc('.data-toggle.review-actions-desc')
        ] == expected_actions_values

        assert doc('select#id_versions.data-toggle')[0].attrib['data-value'].split(
            ' '
        ) == [
            'reject_multiple_versions',
            'change_or_clear_pending_rejection_multiple_versions',
            'clear_needs_human_review_multiple_versions',
            'set_needs_human_review_multiple_versions',
            'reply',
        ]

        assert (
            doc('select#id_versions.data-toggle option')[0].text
            == f'{self.version.version} - Auto-approved, not Confirmed'
        )

        assert doc('.data-toggle.review-comments')[0].attrib['data-value'].split(
            ' '
        ) == [
            'reject_multiple_versions',
            'set_needs_human_review_multiple_versions',
            'disable_auto_approval',
            'reply',
            'disable_addon',
            'request_legal_review',
            'comment',
        ]

        assert doc('.data-toggle.review-actions-reasons')[0].attrib['data-value'].split(
            ' '
        ) == [
            'reject_multiple_versions',
            'reply',
            'disable_addon',
        ]

        assert doc('.data-toggle.review-delayed-rejection')[0].attrib[
            'data-value'
        ].split(' ') == [
            'reject_multiple_versions',
            'change_or_clear_pending_rejection_multiple_versions',
        ]

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
            'approve_multiple_versions',
            'reject_multiple_versions',
            'block_multiple_versions',
            'confirm_multiple_versions',
            'set_needs_human_review_multiple_versions',
            'reply',
            'request_legal_review',
            'comment',
        ]
        assert [
            act.attrib['data-value'] for act in doc('.data-toggle.review-actions-desc')
        ] == expected_actions_values

        assert doc('select#id_versions.data-toggle')[0].attrib['data-value'].split(
            ' '
        ) == [
            'approve_multiple_versions',
            'reject_multiple_versions',
            'block_multiple_versions',
            'confirm_multiple_versions',
            'set_needs_human_review_multiple_versions',
            'reply',
        ]

        assert doc('.data-toggle.review-comments')[0].attrib['data-value'].split(
            ' '
        ) == [
            'approve_multiple_versions',
            'reject_multiple_versions',
            'set_needs_human_review_multiple_versions',
            'reply',
            'request_legal_review',
            'comment',
        ]

        assert doc('.data-toggle.review-actions-reasons')[0].attrib['data-value'].split(
            ' '
        ) == ['approve_multiple_versions', 'reject_multiple_versions', 'reply']

        # We don't have approve/reject actions so these have an empty
        # data-value.
        assert doc('.data-toggle.review-files')[0].attrib['data-value'] == ''
        assert doc('.data-toggle.review-tested')[0].attrib['data-value'] == ''

        assert doc('.data-toggle.review-delayed-rejection')[0].attrib[
            'data-value'
        ].split(' ') == [
            'reject_multiple_versions',
        ]

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
        assert doc('.data-toggle.review-comments')[0].attrib['data-value'] == ''
        assert doc('.data-toggle.review-actions-reasons')[0].attrib['data-value'] == ''
        assert doc('.data-toggle.review-files')[0].attrib['data-value'] == ''
        assert doc('.data-toggle.review-tested')[0].attrib['data-value'] == ''

        # Viewer won't see delayed rejection inputs, need a reviewer.
        assert not doc('.data-toggle.review-delayed-rejection')

    def test_data_value_attributes_unreviewed(self):
        self.file.update(status=amo.STATUS_AWAITING_REVIEW)
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)

        expected_actions_values = [
            'public',
            'reject',
            'reject_multiple_versions',
            'set_needs_human_review_multiple_versions',
            'reply',
            'request_legal_review',
            'comment',
        ]
        assert [
            act.attrib['data-value'] for act in doc('.data-toggle.review-actions-desc')
        ] == expected_actions_values

        assert 'data-value' not in doc('select#id_versions.data-toggle')[0]

        assert doc('.data-toggle.review-comments')[0].attrib['data-value'].split(
            ' '
        ) == [
            'public',
            'reject',
            'reject_multiple_versions',
            'set_needs_human_review_multiple_versions',
            'reply',
            'request_legal_review',
            'comment',
        ]
        assert doc('.data-toggle.review-files')[0].attrib['data-value'].split(' ') == [
            'public',
            'reject',
        ]
        assert doc('.data-toggle.review-tested')[0].attrib['data-value'].split(' ') == [
            'public',
            'reject',
        ]
        assert doc('.data-toggle.review-actions-reasons')[0].attrib['data-value'].split(
            ' '
        ) == ['public', 'reject', 'reject_multiple_versions', 'reply']

    def test_data_value_attributes_static_theme(self):
        self.addon.update(type=amo.ADDON_STATICTHEME)
        self.file.update(status=amo.STATUS_AWAITING_REVIEW)
        self.grant_permission(self.reviewer, 'Addons:ThemeReview')
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)

        expected_actions_values = [
            'public',
            'reject',
            'reject_multiple_versions',
            'set_needs_human_review_multiple_versions',
            'reply',
            'request_admin_review',
            'request_legal_review',
            'comment',
        ]
        assert [
            act.attrib['data-value'] for act in doc('.data-toggle.review-actions-desc')
        ] == expected_actions_values

        assert 'data-value' not in doc('select#id_versions.data-toggle')[0]

        assert doc('.data-toggle.review-comments')[0].attrib['data-value'].split(
            ' '
        ) == [
            'public',
            'reject',
            'reject_multiple_versions',
            'set_needs_human_review_multiple_versions',
            'reply',
            'request_admin_review',
            'request_legal_review',
            'comment',
        ]
        # we don't show files, reasons, and tested with for any static theme actions
        assert doc('.data-toggle.review-files')[0].attrib['data-value'] == ''
        assert doc('.data-toggle.review-actions-reasons')[0].attrib['data-value'].split(
            ' '
        ) == ['reject', 'reject_multiple_versions']
        assert doc('.data-toggle.review-tested')[0].attrib['data-value'] == ''

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
            'set_needs_human_review_multiple_versions',
            'reply',
            'request_legal_review',
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
            'approve_listing_content',
            'reject_multiple_versions',
            'set_needs_human_review_multiple_versions',
            'reply',
            'request_legal_review',
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
        check_links(expected, doc('.addon-addons-sharing-guid a'))

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
        check_links(expected, doc('.addon-addons-sharing-guid a'))

        # It shouldn't happen nowadays, but make sure an empty guid isn't
        # considered.
        self.addon.addonguid.update(guid='')
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert b'Add-on(s) sharing same ID' not in response.content

    def test_versions_that_are_flagged_by_scanners_are_highlighted(self):
        self.login_as_reviewer()
        self.addon.current_version.update(created=self.days_ago(366))
        customs_rule = ScannerRule.objects.create(name='ringo', scanner=CUSTOMS)
        yara_rule = ScannerRule.objects.create(name='star', scanner=YARA)
        now = datetime.now()
        for i in range(0, 10):
            # Add versions 1.0 to 1.9. Some of them will have yara matching
            # rules, some of them customs matching rules, and some also have
            # the needing human review flag.
            matched_yara_rule = not bool(i % 3)
            matched_customs_rule = not bool(i % 3) and not bool(i % 2)
            needs_human_review = not bool(i % 5)
            due_date = now + timedelta(days=i) if needs_human_review else None
            version = version_factory(
                addon=self.addon,
                version=f'1.{i}',
                created=self.days_ago(365 - i),
                due_date=due_date,
            )
            if needs_human_review:
                NeedsHumanReview.objects.create(version=version)

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
                    results={'matchedRules': [customs_rule.name]},
                )

        with self.assertNumQueries(61):
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
        # Versions 1.0, 1.3, 1.6, 1.9 have scanner results. Header is displayed
        # only once for each.
        assert tds.eq(0).text().count('Scanners results:') == 1
        assert tds.eq(3).text().count('Scanners results:') == 1
        assert tds.eq(6).text().count('Scanners results:') == 1
        assert tds.eq(9).text().count('Scanners results:') == 1
        # There should be a link to the scanner result page. Let's check one.
        scanner_results = self.addon.versions.get(version='1.0').scannerresults.all()
        links = tds.eq(0).find('.scanners-results a.result-link')
        for i, result in enumerate(scanner_results):
            assert links[i].attrib['href'] == reverse(
                'admin:scanners_scannerresult_change', args=(result.pk,)
            )

        # A due date should be shown on the 2 versions that have needs_human_review set.
        tds = doc('#versions-history .review-files tr.listing-header td.due_date')
        for j in [0, 5]:
            due_date = defaultfilters.date(
                self.addon.versions.get(version=f'1.{j}').due_date,
                settings.DATETIME_FORMAT,
            )
            assert tds.eq(j).text() == f'Review due by {due_date}'
        # Rest don't have one.
        for k in [1, 2, 3, 4, 6, 7, 8, 9]:
            assert tds.eq(k).text() == ''

        # There are no other flagged versions in the other page.
        span = doc('#review-files-header .risk-high')
        assert span.length == 0

        # Load the second page. This time there should be a message indicating
        # there are versions with a due date on other pages, since
        # needs_human_review forces a due date to be set.
        response = self.client.get(self.url, {'page': 2})
        assert response.status_code == 200
        doc = pq(response.content)
        span = doc('#review-files-header .risk-high')
        assert span.length == 1
        assert span.text() == '2 versions with a due date on other pages.'

    def test_blocked_versions(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert b'Blocked' not in response.content

        block = block_factory(guid=self.addon.guid, updated_by=user_factory())
        response = self.client.get(self.url)
        assert b'Blocked' in response.content
        span = pq(response.content)('#versions-history .blocked-version')
        assert span.text() == '🛑 Hard-Blocked'
        assert span.length == 1  # addon only has 1 version

        blockversion = BlockVersion.objects.create(
            block=block,
            version=version_factory(addon=self.addon, version='99'),
            block_type=BlockType.SOFT_BLOCKED,
        )
        response = self.client.get(self.url)
        span = pq(response.content)('#versions-history .blocked-version')
        assert span.text() == '🛑 Hard-Blocked ⚠️ Soft-Blocked'
        assert span.length == 2  # a new version is blocked too

        block_reason = 'Very bad addon!'
        blockversion.delete()
        block.update(reason=block_reason)
        block_activity_log_save(
            obj=block,
            change=False,
            submission_obj=BlocklistSubmission(
                changed_version_ids=[blockversion.version_id]
            ),
        )
        response = self.client.get(self.url)
        span = pq(response.content)('#versions-history .blocked-version')
        assert span.text() == '🛑 Hard-Blocked'
        assert span.length == 1
        assert 'Version Blocked' in (
            pq(response.content)('#versions-history .activity').text()
        )

    def test_redirect_after_review_unlisted(self):
        reason = ReviewActionReason.objects.create(
            name='reason 1', is_active=True, canned_response='reason'
        )
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
                'versions': [self.version.pk],
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

    def test_links_to_developer_profile(self):
        author = self.addon.authors.all()[0]
        response = self.client.get(self.url)
        self.assertContains(response, author.name)
        self.assertContains(
            response, reverse('reviewers.developer_profile', args=(author.id,))
        )

        another_author = user_factory()
        AddonUser.objects.create(addon=self.addon, user=another_author)
        unlisted_author = user_factory()
        AddonUser.objects.create(addon=self.addon, user=unlisted_author, listed=False)

        response = self.client.get(self.url)
        self.assertContains(response, another_author.name)
        author_profile_url = reverse('reviewers.developer_profile', args=(author.id,))
        another_profile_url = reverse(
            'reviewers.developer_profile', args=(another_author.id,)
        )
        unlisted_profile_url = reverse(
            'reviewers.developer_profile', args=(unlisted_author.id,)
        )

        self.assertContains(
            response,
            f'<a href="{author_profile_url}">{author.name}</a>,',
        )
        self.assertContains(
            response,
            f'<a href="{another_profile_url}">{another_author.name}</a>,',
        )
        self.assertContains(
            response,
            f'<a href="{unlisted_profile_url}"'
            f'class="is_unlisted">{unlisted_author.name}</a>',
        )

    def test_links_to_developer_admin_page(self):
        self.login_as_admin()
        author_admin_url = reverse(
            'admin:users_userprofile_change', args=(self.addon_author.id,)
        )
        author_profile_url = reverse(
            'reviewers.developer_profile', args=(self.addon_author.id,)
        )

        another_author = user_factory()
        another_author_admin_url = reverse(
            'admin:users_userprofile_change', args=(another_author.id,)
        )
        another_author_profile_url = reverse(
            'reviewers.developer_profile', args=(another_author.id,)
        )
        AddonUser.objects.create(addon=self.addon, user=another_author)

        response = self.client.get(self.url)

        self.assertContains(
            response,
            f'<a href="{author_profile_url}">{self.addon_author.name}</a>'
            f' [<a href="{author_admin_url}">admin</a>],',
        )
        self.assertContains(
            response,
            f'<a href="{another_author_profile_url}">{another_author.name}</a>'
            f' [<a href="{another_author_admin_url}">admin</a>]',
        )

    def test_displayed_metadata(self):
        response = self.client.get(self.url)
        self.assertContains(response, self.addon.summary)
        self.assertContains(
            response, f'<strong>{self.addon.get_status_display()}</strong>'
        )

    def test_resolve_abuse_reports_checkbox(self):
        AbuseReport.objects.create(
            guid=self.addon.guid,
            location=AbuseReport.LOCATION.ADDON,
            reason=AbuseReport.REASONS.POLICY_VIOLATION,
            cinder_job=CinderJob.objects.create(
                job_id='999', target_addon=self.addon, resolvable_in_reviewer_tools=True
            ),
            message='Its baaaad',
        )
        response = self.client.get(self.url)
        self.assertContains(response, 'Show detail on 1 reports')
        self.assertContains(response, 'Its baaaad')

    @mock.patch('olympia.reviewers.utils.report_decision_to_cinder_and_notify.delay')
    def test_abuse_reports_resolved_as_disable_addon_with_disable_action(
        self, mock_resolve_task
    ):
        self.grant_permission(self.reviewer, 'Reviews:Admin')
        reason = ReviewActionReason.objects.create(
            name='reason 1',
            is_active=True,
            canned_response='reason',
            cinder_policy=CinderPolicy.objects.create(),
        )
        self.addon.update(status=amo.STATUS_APPROVED)
        cinder_job = CinderJob.objects.create(
            job_id='123', target_addon=self.addon, resolvable_in_reviewer_tools=True
        )
        AbuseReport.objects.create(
            guid=self.addon.guid,
            location=AbuseReport.LOCATION.BOTH,
            reason=AbuseReport.REASONS.POLICY_VIOLATION,
            cinder_job=cinder_job,
        )
        AbuseReport.objects.create(
            guid=self.addon.guid,
            location=AbuseReport.LOCATION.ADDON,
            reason=AbuseReport.REASONS.POLICY_VIOLATION,
            cinder_job=cinder_job,
        )

        self.client.post(
            self.url,
            self.get_dict(
                action='disable_addon',
                reasons=[reason.id],
                cinder_jobs_to_resolve=[cinder_job.id],
            ),
        )
        assert self.get_addon().status == amo.STATUS_DISABLED
        log_entry = ActivityLog.objects.get(action=amo.LOG.FORCE_DISABLE.id)
        decision = ContentDecision.objects.get()
        mock_resolve_task.assert_called_once_with(
            decision_id=decision.id, notify_owners=True
        )
        assert decision.activities.all().get() == log_entry
        assert decision.action == DECISION_ACTIONS.AMO_DISABLE_ADDON
        self.assertCloseToNow(decision.action_date)

    @mock.patch('olympia.reviewers.utils.report_decision_to_cinder_and_notify.delay')
    @mock.patch('olympia.reviewers.utils.sign_file')
    def test_abuse_reports_resolved_as_approve_with_approve_latest_version_action(
        self, sign_file_mock, mock_resolve_task
    ):
        self.version = version_factory(
            addon=self.addon, file_kw={'status': amo.STATUS_AWAITING_REVIEW}
        )
        self.grant_permission(self.reviewer, 'Reviews:Admin')
        cinder_job = CinderJob.objects.create(
            job_id='123', target_addon=self.addon, resolvable_in_reviewer_tools=True
        )
        AbuseReport.objects.create(
            guid=self.addon.guid,
            location=AbuseReport.LOCATION.BOTH,
            reason=AbuseReport.REASONS.POLICY_VIOLATION,
            cinder_job=cinder_job,
        )
        AbuseReport.objects.create(
            guid=self.addon.guid,
            location=AbuseReport.LOCATION.ADDON,
            reason=AbuseReport.REASONS.POLICY_VIOLATION,
            cinder_job=cinder_job,
        )
        self.client.post(
            self.url,
            self.get_dict(
                action='public',
                cinder_jobs_to_resolve=[cinder_job.id],
            ),
        )

        log_entry = ActivityLog.objects.get(action=amo.LOG.APPROVE_VERSION.id)
        decision = ContentDecision.objects.get()
        mock_resolve_task.assert_called_once_with(
            decision_id=decision.id, notify_owners=True
        )
        assert decision.activities.all().get() == log_entry
        assert decision.action == DECISION_ACTIONS.AMO_APPROVE_VERSION
        self.assertCloseToNow(decision.action_date)

    def test_force_enable_shows_versions_to_reenabled(self):
        v1 = self.addon.current_version
        v2 = version_factory(addon=self.addon)
        was_approved = version_factory(addon=self.addon)
        was_awaiting_review = version_factory(
            addon=self.addon, channel=amo.CHANNEL_UNLISTED
        )
        self.addon.update(status=amo.STATUS_DISABLED)
        v1.file.update(
            status=amo.STATUS_DISABLED,
            original_status=amo.STATUS_APPROVED,
            # We don't want to re-enable a version the developer disabled
            status_disabled_reason=File.STATUS_DISABLED_REASONS.DEVELOPER,
        )
        v2.file.update(
            status=amo.STATUS_DISABLED,
            original_status=amo.STATUS_APPROVED,
            # we also don't want to re-enable a version we rejected
            status_disabled_reason=File.STATUS_DISABLED_REASONS.NONE,
        )
        was_approved.file.update(
            status=amo.STATUS_DISABLED,
            original_status=amo.STATUS_APPROVED,
            # but we do want to re-enable a version we only disabled with the addon
            status_disabled_reason=File.STATUS_DISABLED_REASONS.ADDON_DISABLE,
        )
        was_awaiting_review.file.update(
            status=amo.STATUS_DISABLED,
            original_status=amo.STATUS_AWAITING_REVIEW,
            # awaiting review versions could also be re-enabled
            status_disabled_reason=File.STATUS_DISABLED_REASONS.ADDON_DISABLE,
        )

        response = self.client.get(self.url)
        # Only the two disabled versions that have status_disabled_reason=ADDON_DISABLE
        # will be re-enabled.
        self.assertContains(response, '2 version(s) will be re-enabled:')
        doc = pq(response.content)
        items = doc('li.version-that-would-be-reenabled')
        assert len(items) == 2
        approved_li = items[1].text_content()
        awaiting_li = items[0].text_content()
        assert was_approved.version in approved_li
        assert was_awaiting_review.version in awaiting_li
        assert '-> Approved' in approved_li
        assert '-> Awaiting Review' in awaiting_li
        assert 'Listed' in approved_li
        assert 'Unlisted' in awaiting_li

        assert len(doc('li.version-that-would-be-reenabled.overflow-message')) == 0
        assert doc('li.version-that-would-be-reenabled a').eq(1).attr.href == reverse(
            'reviewers.review_version_redirect',
            args=[self.addon.id, was_approved.version],
        )
        assert doc('li.version-that-would-be-reenabled a').eq(0).attr.href == reverse(
            'reviewers.review_version_redirect',
            args=[self.addon.id, was_awaiting_review.version],
        )

    def test_force_enable_shows_versions_to_reenabled_too_many(self):
        MAX_MOCK = 5
        self.addon.update(status=amo.STATUS_DISABLED)
        # +2 for an unambigious assertion on the number of li items
        version_count = MAX_MOCK + 2
        for _ in range(0, version_count):
            version_factory(
                addon=self.addon,
                file_kw={
                    'status': amo.STATUS_DISABLED,
                    'original_status': amo.STATUS_APPROVED,
                    'status_disabled_reason': (
                        File.STATUS_DISABLED_REASONS.ADDON_DISABLE
                    ),
                },
            )
        with mock.patch('olympia.reviewers.views.MAX_VERSIONS_SHOWN_INLINE', MAX_MOCK):
            response = self.client.get(self.url)
        self.assertContains(response, f'{version_count} version(s) will be re-enabled:')
        doc = pq(response.content)
        items = doc('li.version-that-would-be-reenabled')
        assert len(items) == MAX_MOCK + 1  # + 1 for the overflow li
        assert '...' in items[-1].text_content()

    @override_switch('cinder_policy_review_reasons_enabled', active=True)
    def test_comments_when_using_policies_rather_than_reasons(self):
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert doc('.review-comments textarea')
        assert doc('.review-comments textarea[rows="2"]')
        assert not doc('.review-comments details[open] textarea')

        with override_switch('cinder_policy_review_reasons_enabled', active=False):
            response = self.client.get(self.url)
            doc = pq(response.content)
            assert doc('.review-comments textarea')
            assert not doc('.review-comments textarea[rows="2"]')
            assert doc('.review-comments details[open] textarea')

    def test_policy_text_rendered(self):
        CinderPolicy.objects.create(uuid='not-exposed', name='not exposed')
        policy_fixed = CinderPolicy.objects.create(
            uuid='no-enforcement',
            name='no enforcement',
            expose_in_reviewer_tools=True,
            text='Something something',
        )
        policy_dynamic = CinderPolicy.objects.create(
            uuid='4-rejections',
            name='for rejections',
            expose_in_reviewer_tools=True,
            enforcement_actions=[
                DECISION_ACTIONS.AMO_DISABLE_ADDON.api_value,
                'some-other-action',
            ],
            text='Policy with {PLACEHOLDER} and {"EDGE&case }',
        )
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert len(doc('.policy-texts div')) == 2

        assert doc(f'#policy-text-{policy_fixed.id}[hidden]')
        assert doc(f'#policy-text-{policy_fixed.id}').text() == 'Something something'
        assert not doc(f'#policy-text-{policy_fixed.id} input')

        assert doc(f'#policy-text-{policy_dynamic.id}[hidden]')
        assert doc(f'#policy-text-{policy_dynamic.id}').text() == 'Policy with and'
        assert doc(f'#policy-text-{policy_dynamic.id} input')
        assert doc(f'#policy-text-{policy_dynamic.id} input').eq(0).attr['name'] == (
            f'policy_values_{policy_dynamic.id}_PLACEHOLDER'
        )
        assert doc(f'#policy-text-{policy_dynamic.id} input').eq(1).attr['name'] == (
            f'policy_values_{policy_dynamic.id}_"EDGE&case '
        )
        # pyquery is escaping the name - check it's encoded in the raw html
        assert f'"policy_values_{policy_dynamic.id}_&quot;EDGE&amp;case "'.encode() in (
            response.content
        )


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
            addon_version=amo.DEFAULT_WEBEXT_MIN_VERSION,
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
            # We use the name as submitted in the abuse report.
            f'Nâme {amo.DEFAULT_WEBEXT_MIN_VERSION}',
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
        reason = ReviewActionReason.objects.create(
            name='reason 1', is_active=True, canned_response='reason'
        )
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
        assert get_config(amo.config_keys.REVIEWERS_MOTD) == 'I am the keymaster.'

    def test_form_errors(self):
        self.login_as_admin()
        response = self.client.post(self.get_url(save=True))
        doc = pq(response.content)
        assert doc('#reviewer-motd .errorlist').text() == ('This field is required.')


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

    def test_whiteboard_private_too_long(self):
        url = reverse('reviewers.whiteboard', args=['listed', self.addon.pk])
        user = UserProfile.objects.get(email='reviewer@mozilla.com')
        self.client.force_login(user)
        response = self.client.post(
            url,
            {
                'whiteboard-private': 'ï' * 100001,
                'whiteboard-public': 'û',
            },
        )
        # That view doesn't handle errors, it's an XHR call.
        assert response.status_code == 403

    def test_whiteboard_public_too_long(self):
        url = reverse('reviewers.whiteboard', args=['listed', self.addon.pk])
        user = UserProfile.objects.get(email='reviewer@mozilla.com')
        self.client.force_login(user)
        response = self.client.post(
            url,
            {
                'whiteboard-private': 'ï',
                'whiteboard-public': 'û' * 100001,
            },
        )
        # That view doesn't handle errors, it's an XHR call.
        assert response.status_code == 403

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


class TestDeveloperProfile(ReviewerTest):
    def setUp(self):
        super().setUp()
        self.developer = user_factory()
        self.addon = addon_factory(users=(self.developer,))
        self.login_as_reviewer()
        self.url = reverse(
            'reviewers.developer_profile',
            args=(self.developer.pk,),
        )

    def test_basic(self):
        response = self.client.get(self.url)
        assert response.status_code == 200

        self.assertContains(response, f'User #{self.developer.id} – Reviewer Tools')
        self.assertContains(
            response,
            'Developer profile for User: '
            f'<a href="{self.developer.get_url_path()}">'
            f'{self.developer.id} {self.developer.name}</a>',
        )
        self.assertContains(response, f'&lt;{self.developer.email}&gt;')

        self.assertContains(response, self.addon.get_url_path())
        self.assertContains(response, self.addon.guid)
        self.assertContains(response, 'Extension')
        self.assertContains(response, 'Approved')
        self.assertContains(response, 'Owner')

    def test_is_admin(self):
        self.login_as_admin()
        response = self.client.get(self.url)
        assert response.status_code == 200
        developer_admin_url = reverse(
            'admin:users_userprofile_change', args=(self.developer.id,)
        )
        expected_link = f'<a href="{developer_admin_url}">User Admin Page</a>'
        self.assertContains(response, expected_link)

    def test_deleted_owner(self):
        self.addon.addonuser_set.get(user=self.developer).delete()
        response = self.client.get(self.url)
        assert response.status_code == 200

        self.assertContains(response, f'User #{self.developer.id} – Reviewer Tools')
        self.assertContains(
            response,
            'Developer profile for User: '
            f'<a href="{self.developer.get_url_path()}">'
            f'{self.developer.id} {self.developer.name}</a>',
        )
        self.assertContains(response, f'&lt;{self.developer.email}&gt;')

        self.assertContains(response, self.addon.get_url_path())
        self.assertContains(response, self.addon.guid)
        self.assertContains(response, '(Deleted)')

    def test_deleted_addon(self):
        self.addon.delete()
        response = self.client.get(self.url)
        assert response.status_code == 200

        self.assertContains(response, f'User #{self.developer.id} – Reviewer Tools')
        self.assertContains(
            response,
            'Developer profile for User: '
            f'<a href="{self.developer.get_url_path()}">'
            f'{self.developer.id} {self.developer.name}</a>',
        )
        self.assertContains(response, f'&lt;{self.developer.email}&gt;')
        self.assertContains(response, self.addon.guid)
        self.assertNotContains(response, f'">{self.addon.id}: {self.addon.name}</a>')
        self.assertContains(response, f'{self.addon.id}: {self.addon.name}')
        self.assertContains(response, 'Owner')

    def test_deleted_user(self):
        AddonUser.objects.create(addon=self.addon, user=user_factory())
        self.developer.delete()
        response = self.client.get(self.url)
        assert response.status_code == 200
        self.assertContains(response, f'User #{self.developer.id} – Reviewer Tools')
        self.assertContains(
            response,
            'Developer profile for User: '
            f'<a href="{self.developer.get_url_path()}">'
            f'{self.developer.id} {self.developer.name}</a>',
        )
        self.assertContains(response, f'&lt;{self.developer.email}&gt;')

        self.assertContains(response, self.addon.get_url_path())
        self.assertContains(response, self.addon.guid)
        self.assertContains(response, 'Extension')
        self.assertContains(response, 'Approved')
        self.assertContains(response, '(Deleted)')


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
        self.flags_url = reverse_ns(
            'reviewers-addon-flags', kwargs={'pk': self.addon.pk}
        )
        self.deny_resubmission_url = reverse_ns(
            'reviewers-addon-deny-resubmission', kwargs={'pk': self.addon.pk}
        )
        self.allow_resubmission_url = reverse_ns(
            'reviewers-addon-allow-resubmission', kwargs={'pk': self.addon.pk}
        )
        self.due_date_url = reverse_ns(
            'reviewers-addon-due-date', kwargs={'pk': self.addon.pk}
        )
        self.set_needs_human_review_url = reverse_ns(
            'reviewers-addon-set-needs-human-review', kwargs={'pk': self.addon.pk}
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

    def test_patch_flags_only_save_changed(self):
        instance = AddonReviewerFlags.objects.create(addon=self.addon)
        self.grant_permission(self.user, 'Reviews:Admin')
        self.client.login_api(self.user)
        with mock.patch(
            'olympia.reviewers.views.AddonReviewerFlags.objects.get_or_create',
        ) as mocked_get_or_create:
            # Force a fake race condition by modifying a flag on the instance
            # the serializer receives that wasn't passed in the PATCH call.
            instance.auto_approval_disabled_unlisted = True
            mocked_get_or_create.return_value = instance, False
            response = self.client.patch(
                self.flags_url, {'auto_approval_disabled': True}
            )
            # Make sure our mock was correctly called.
            assert mocked_get_or_create.call_count == 1
        assert response.status_code == 200
        assert AddonReviewerFlags.objects.filter(addon=self.addon).exists()
        reviewer_flags = AddonReviewerFlags.objects.get(addon=self.addon)
        # That flag should have been saved.
        assert reviewer_flags.auto_approval_disabled
        # That flag we forced to set on the instance earlier should not have
        # been saved in the database as it wasn't part of the request data.
        assert reviewer_flags.auto_approval_disabled_unlisted is None
        assert ActivityLog.objects.count() == 0

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
            auto_approval_delayed_until_unlisted=self.days_ago(0),
        )
        self.grant_permission(self.user, 'Reviews:Admin')
        self.client.login_api(self.user)
        data = {
            'auto_approval_disabled': False,
            'auto_approval_disabled_unlisted': False,
            'auto_approval_disabled_until_next_approval': True,
            'auto_approval_disabled_until_next_approval_unlisted': True,
            'auto_approval_delayed_until': None,
            'auto_approval_delayed_until_unlisted': None,
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
        assert reviewer_flags.auto_approval_delayed_until_unlisted is None

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

    def test_due_date(self):
        user_factory(pk=settings.TASK_USER_ID)
        self.grant_permission(self.user, 'Reviews:Admin')
        self.client.login_api(self.user)
        version = self.addon.current_version
        NeedsHumanReview.objects.create(version=version)
        assert version.due_date
        new_due_date = datetime.now() - timedelta(weeks=1)
        response = self.client.post(
            self.due_date_url,
            data={
                'version': version.id,
                'due_date': new_due_date.isoformat(timespec='seconds'),
            },
        )
        assert response.status_code == 202
        version.reload()
        self.assertCloseToNow(version.due_date, now=new_due_date)

    def test_set_needs_human_review(self):
        self.grant_permission(self.user, 'Reviews:Admin')
        self.client.login_api(self.user)
        version = self.addon.current_version
        assert not version.needshumanreview_set.exists()
        response = self.client.post(
            self.set_needs_human_review_url, data={'version': version.id}
        )
        assert response.status_code == 202
        version.reload()
        assert version.needshumanreview_set.filter(is_active=True).count() == 1
        assert (
            version.needshumanreview_set.get().reason
            == version.needshumanreview_set.model.REASONS.MANUALLY_SET_BY_REVIEWER
        )
        assert (
            ActivityLog.objects.filter(action=amo.LOG.NEEDS_HUMAN_REVIEW_AUTOMATIC.id)
            .get()
            .user
            == self.user
        )
        # We strip off the milliseconds in the response
        assert response.data == {
            'due_date': version.due_date.isoformat(timespec='seconds')
        }


class TestAddonReviewerViewSetJsonValidation(TestCase):
    client_class = APITestClientSessionID
    fixtures = ['devhub/addon-validation-1']

    def setUp(self):
        super().setUp()
        self.user = user_factory(read_dev_agreement=self.days_ago(0))
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
        assert self.client.get(self.url).status_code in [
            401,
            403,
        ]  # JWT auth is a 401; web auth is 403

    @mock.patch.object(acl, 'is_reviewer', lambda user, addon: False)
    def test_wrong_type_of_reviewer_cannot_see_json_results(self):
        self.grant_permission(self.user, 'Addons:Review')
        self.client.login_api(self.user)
        assert self.client.get(self.url).status_code in [
            401,
            403,
        ]  # JWT auth is a 401; web auth is 403

    def test_non_unlisted_reviewer_cannot_see_results_for_unlisted(self):
        self.grant_permission(self.user, 'Addons:Review')
        self.client.login_api(self.user)
        self.make_addon_unlisted(self.addon)
        assert self.client.get(self.url).status_code in [
            401,
            403,
        ]  # JWT auth is a 401; web auth is 403


class TestAddonReviewerViewSetJsonValidationJWT(TestAddonReviewerViewSetJsonValidation):
    client_class = APITestClientJWT


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


class TestUsagePerVersion(ReviewerTest):
    def setUp(self):
        super().setUp()
        self.addon = addon_factory()
        self.login_as_reviewer()
        self.url = reverse(
            'reviewers.usage_per_version',
            args=(self.addon.pk,),
        )

    @mock.patch(
        'olympia.reviewers.views.get_average_daily_users_per_version_from_bigquery'
    )
    def test_empty(self, get_adu_per_version_mock):
        get_adu_per_version_mock.return_value = []
        response = self.client.get(self.url)

        get_adu_per_version_mock.assert_called_once_with(self.addon)
        assert response.status_code == 200
        assert response.json() == {'adus': []}

    @mock.patch(
        'olympia.reviewers.views.get_average_daily_users_per_version_from_bigquery'
    )
    def test_basic(self, get_adu_per_version_mock):
        get_adu_per_version_mock.return_value = [
            ('1.1', 394),
            ('2', 450),
            ('3.4545', 9999),
        ]
        response = self.client.get(self.url)

        assert response.status_code == 200
        assert response.json() == {
            'adus': [['1.1', '394'], ['2', '450'], ['3.4545', '9,999']]
        }

    def test_not_reviewer(self):
        user_factory(email='irregular@mozilla.com')
        self.client.force_login(UserProfile.objects.get(email='irregular@mozilla.com'))
        response = self.client.post(self.url, follow=True)
        assert response.status_code == 403

    @override_switch('disable-bigquery', active=True)
    @mock.patch(
        'olympia.reviewers.views.get_average_daily_users_per_version_from_bigquery'
    )
    def test_bigquery_disabled(self, get_adu_per_version_mock):
        get_adu_per_version_mock.return_value = [('123', 456)]
        response = self.client.get(self.url)

        assert response.status_code == 503
        assert response.json() == {}

    def test_review_page_html(self):
        version = self.addon.current_version
        review_url = reverse('reviewers.review', args=[self.addon.pk])
        response = self.client.get(review_url)
        assert response.status_code == 200
        doc = pq(response.content)
        # the version id as the anchor
        assert doc(f'#version-{to_dom_id(version.version)}.listing-header')
        assert doc('.version-adu').attr('data-version-string') == version.version
        # url to the usage_per_version view, and what the max results will be
        addon_div = doc('#addon')
        assert addon_div.attr('data-versions-adu-url') == self.url
        assert addon_div.attr('data-versions-adu-max-results') == str(VERSION_ADU_LIMIT)
        # url to the review_version_redirect
        assert addon_div.attr('data-review-version-url') == reverse(
            'reviewers.review_version_redirect', args=(self.addon.id, '__')
        )


class TestReviewVersionRedirect(ReviewerTest):
    def login_as_reviewer(self):
        self.grant_permission(
            UserProfile.objects.get(email='reviewer@mozilla.com'),
            'Addons:ReviewUnlisted',
        )
        return super().login_as_reviewer()

    def test_responses(self):
        addon = addon_factory()
        listed = addon.current_version
        unlisted = version_factory(addon=addon, channel=amo.CHANNEL_UNLISTED)
        deleted = version_factory(addon=addon)
        deleted.delete()
        addon_factory()  # another addon with a version that should be ignored

        def redirect_url(version):
            return reverse(
                'reviewers.review_version_redirect', args=(addon.id, version.version)
            )

        review_url_listed = reverse('reviewers.review', args=('listed', addon.id))
        review_url_unlisted = reverse('reviewers.review', args=('unlisted', addon.id))

        assert self.client.get(redirect_url(listed)).status_code == 403
        self.login_as_reviewer()

        # on the first pages
        listed_version_id_anchor = f'#version-{to_dom_id(listed.version)}'
        self.assertRedirects(
            self.client.get(redirect_url(listed)),
            review_url_listed + listed_version_id_anchor,
        )
        deleted_version_id_anchor = f'#version-{to_dom_id(deleted.version)}'
        self.assertRedirects(
            self.client.get(redirect_url(deleted)),
            review_url_listed + deleted_version_id_anchor,
        )
        unlisted_version_id_anchor = f'#version-{to_dom_id(unlisted.version)}'
        self.assertRedirects(
            self.client.get(redirect_url(unlisted)),
            review_url_unlisted + unlisted_version_id_anchor,
        )
        # add another 9 listed versions
        for _i in range(9):
            version_factory(addon=addon)
        # the first listed version will be on the second page now
        self.assertRedirects(
            self.client.get(redirect_url(listed)),
            review_url_listed + '?page=2' + listed_version_id_anchor,
        )
        # the deleted version will still be on the first page though
        self.assertRedirects(
            self.client.get(redirect_url(deleted)),
            review_url_listed + deleted_version_id_anchor,
        )
        # unlisted too, because it's independently paginated
        self.assertRedirects(
            self.client.get(redirect_url(unlisted)),
            review_url_unlisted + unlisted_version_id_anchor,
        )

    def test_version_not_found(self):
        self.login_as_reviewer()

        addon = addon_factory()
        assert (
            self.client.get(
                reverse(
                    'reviewers.review_version_redirect',
                    args=(addon.id, addon.current_version.version + '.1'),
                )
            ).status_code
            == 404
        )

        # Doesn't find a version on a diferrent add-on either.
        other = addon_factory()
        assert (
            self.client.get(
                reverse(
                    'reviewers.review_version_redirect',
                    args=(addon.id, other.current_version.version),
                )
            ).status_code
            == 404
        )


class TestHeldDecisionQueue(ReviewerTest):
    def setUp(self):
        super().setUp()

        self.url = reverse('reviewers.queue_decisions')

        self.addon_decision = ContentDecision.objects.create(
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON, addon=addon_factory()
        )
        self.user_decision = ContentDecision.objects.create(
            action=DECISION_ACTIONS.AMO_BAN_USER, user=user_factory()
        )
        self.collection_decision = ContentDecision.objects.create(
            action=DECISION_ACTIONS.AMO_DELETE_COLLECTION,
            collection=collection_factory(),
        )
        self.rating_decision = ContentDecision.objects.create(
            action=DECISION_ACTIONS.AMO_DELETE_RATING,
            rating=Rating.objects.create(addon=addon_factory(), user=user_factory()),
        )

    def test_results(self):
        user = user_factory()
        self.grant_permission(user, 'Addons:HighImpactApprove')
        self.client.force_login(user)

        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)('#held-decision-queue')

        rows = doc('tr.held-item')
        assert rows.length == 4
        links = [link.attrib['href'] for link in doc('a')]
        assert links == [
            self.addon_decision.get_target_review_url(),
            self.user_decision.get_target_review_url(),
            self.collection_decision.get_target_review_url(),
            self.rating_decision.get_target_review_url(),
        ]
        assert doc('tr.held-item').attr('id') == self.addon_decision.get_reference_id(
            short=True
        )
        assert doc('tr.held-item').attr('class') == 'held-item TASKUS'
        assert (
            doc('tr.held-item td div').attr('class')
            == 'app-icon ed-sprite-action-target-Extension'
        )
        assert doc('tr.held-item td div').attr('title') == 'Extension'
        assert doc('tr.held-item td').eq(1).text() == 'TaskUs'
        assert doc('tr.held-item td').eq(2).text() == str(
            self.addon_decision.addon.name
        )
        assert doc('tr.held-item td').eq(3).text() == 'Add-on disable'

        # But overridden decisions should not be present, even if not actioned
        ContentDecision.objects.create(
            action=DECISION_ACTIONS.AMO_APPROVE,
            addon=self.addon_decision.addon,
            action_date=datetime.now(),
            override_of=self.addon_decision,
        )
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)('#held-decision-queue')
        assert doc('tr.held-item').length == 3

    def test_non_admin_cannot_access(self):
        self.login_as_reviewer()
        response = self.client.get(self.url)
        assert response.status_code == 403

    def test_reviewer_viewer_can_access(self):
        user = user_factory()
        self.grant_permission(user, 'ReviewerTools:View')
        self.client.force_login(user)
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert pq(response.content)('#held-decision-queue')


class TestHeldDecisionReview(ReviewerTest):
    def setUp(self):
        super().setUp()

        policy = CinderPolicy.objects.create(
            uuid='1', name='Bad', text='Things like {FOO}'
        )
        self.decision = ContentDecision.objects.create(
            action=DECISION_ACTIONS.AMO_DISABLE_ADDON,
            addon=addon_factory(),
            cinder_id='1234',
            # private and reasoning wouldn't usually exist together but testing both
            private_notes='Seakret deets',
            reasoning='Pooblik deets',
            metadata={
                ContentDecision.POLICY_DYNAMIC_VALUES: {policy.uuid: {'FOO': 'baa'}}
            },
        )
        self.version = self.decision.addon.current_version
        self.decision.target_versions.set([self.version])
        self.decision.policies.add(policy)
        CinderPolicy.objects.create(
            uuid='2',
            name='Approve',
            enforcement_actions=[DECISION_ACTIONS.AMO_APPROVE.api_value],
        )
        self.url = reverse('reviewers.decision_review', args=(self.decision.id,))
        self.user = user_factory()
        self.grant_permission(self.user, 'Addons:HighImpactApprove')
        self.client.force_login(self.user)

    def _test_review_page_addon(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)('.entity-type-Extension')

        assert f'Extension Decision for {self.decision.addon.name}' in doc.html()
        assert doc('h2').attr('class') == 'held-item TASKUS'
        assert f'Extension: {self.decision.addon_id}' in doc.html()
        assert 'TaskUs' == doc('.decision-source td').text()
        assert (
            doc('tr.decision-created a').attr('href').endswith(self.decision.cinder_id)
        )
        assert 'Add-on disable' in doc('tr.decision-action td').html()
        assert 'Bad: Things like baa' in doc('tr.decision-policies td').html()
        assert 'Proceed with action' == doc('[for="id_choice_0"]').text()
        assert 'Pooblik deets' in doc('.decision-notes div').eq(0).html()
        assert 'Seakret deets' in doc('.decision-notes div').eq(1).html()
        assert (
            'Cancel and enqueue in Reviewer Tools' == doc('[for="id_choice_1"]').text()
        )
        assert 'Affected versions' in doc.text()
        assert self.version.version in doc.text()
        return doc

    def test_review_page_addon_no_job(self):
        self._test_review_page_addon()

    def test_review_page_addon_with_job(self):
        CinderJob.objects.create(
            target_addon=self.decision.addon, decision=self.decision
        )
        self._test_review_page_addon()

    def test_review_page_addon_from_amo_reviewer(self):
        self.decision.update(reviewer_user=self.user)
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)('.entity-type-Extension')

        assert f'Extension Decision for {self.decision.addon.name}' in doc.html()
        assert doc('h2').attr('class') == 'held-item REVIEWER'
        assert f'Extension: {self.decision.addon_id}' in doc.html()
        assert 'Reviewer' in doc('.decision-source td').text()
        assert (
            doc('.decision-source td a').attr('href').endswith(self.user.get_url_path())
        )
        assert 'Add-on disable' in doc('tr.decision-action td').html()

    def test_review_page_user(self):
        self.decision.update(
            addon=None, user=user_factory(), action=DECISION_ACTIONS.AMO_BAN_USER
        )
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)('.entity-type-User')

        assert f'User profile Decision for {self.decision.user.name}' in doc.html()
        assert doc('h2').attr('class') == 'held-item TASKUS'
        assert f'User profile: {self.decision.user_id}' in doc.html()
        assert 'TaskUs' == doc('.decision-source td').text()
        assert (
            doc('tr.decision-created a').attr('href').endswith(self.decision.cinder_id)
        )
        assert 'User ban' in doc('tr.decision-action td').html()
        assert 'Bad: Things like baa' in doc('tr.decision-policies td').html()
        assert 'Proceed with action' == doc('[for="id_choice_0"]').text()
        assert 'Pooblik deets' in doc('.decision-notes div').eq(0).html()
        assert 'Seakret deets' in doc('.decision-notes div').eq(1).html()
        assert 'Approve content instead' == doc('[for="id_choice_1"]').text()
        assert 'Forward to Reviewer Tools' not in doc.text()
        assert 'Affected versions' not in doc.text()

    def test_release_addon_disable_hold(self):
        addon = self.decision.addon
        assert addon.status == amo.STATUS_APPROVED

        response = self.client.post(self.url, {'choice': 'yes'})

        assert response.status_code == 302
        assert addon.reload().status == amo.STATUS_DISABLED
        self.assertCloseToNow(self.decision.reload().action_date)

    def test_approve_addon_is_not_possible(self):
        response = self.client.get(self.url)
        assert response.context_data['form'].fields['choice'].choices == [
            ('yes', 'Proceed with action'),
            ('cancel', 'Cancel and enqueue in Reviewer Tools'),
        ]

    def test_cancel_addon_with_job(self):
        addon = self.decision.addon
        job = CinderJob.objects.create(target_addon=addon, decision=self.decision)
        assert addon.status == amo.STATUS_APPROVED

        response = self.client.post(self.url, {'choice': 'cancel'})

        assert response.status_code == 302
        assert addon.reload().status == amo.STATUS_APPROVED
        assert job.reload().resolvable_in_reviewer_tools
        assert self.decision.reload().action_date is None
        assert self.decision.cinder_job == job
        new_decision = job.final_decision
        assert self.decision.overridden_by == new_decision
        assert new_decision.action == DECISION_ACTIONS.AMO_REQUEUE
        assert NeedsHumanReview.objects.filter(
            reason=NeedsHumanReview.REASONS.SECOND_LEVEL_REQUEUE,
            is_active=True,
            version=addon.current_version,
        ).exists()

    def test_cancel_addon_no_job(self):
        addon = self.decision.addon
        assert addon.status == amo.STATUS_APPROVED

        response = self.client.post(self.url, {'choice': 'cancel'})

        assert response.status_code == 302
        assert addon.reload().status == amo.STATUS_APPROVED
        assert self.decision.reload().cinder_job is None
        assert self.decision.overridden_by.action == DECISION_ACTIONS.AMO_REQUEUE
        assert self.decision.reload().action_date is None
        assert NeedsHumanReview.objects.filter(
            reason=NeedsHumanReview.REASONS.SECOND_LEVEL_REQUEUE,
            is_active=True,
            version=addon.current_version,
        ).exists()

    def test_release_user_ban_hold(self):
        self.decision.update(
            addon=None, user=user_factory(), action=DECISION_ACTIONS.AMO_BAN_USER
        )
        user = self.decision.user
        assert not user.banned

        response = self.client.post(self.url, {'choice': 'yes'})

        assert response.status_code == 302
        user.reload()
        self.assertCloseToNow(user.banned)
        self.assertCloseToNow(self.decision.reload().action_date)

    def test_approve_user_instead(self):
        self.decision.update(
            addon=None, user=user_factory(), action=DECISION_ACTIONS.AMO_BAN_USER
        )
        user = self.decision.user
        assert not user.banned
        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}decisions/{self.decision.cinder_id}/override/',
            json={'uuid': '5678'},
            status=201,
        )

        response = self.client.post(self.url, {'choice': 'no'})

        assert response.status_code == 302
        assert not user.banned
        assert self.decision.reload().action == DECISION_ACTIONS.AMO_BAN_USER
        assert self.decision.action_date is None

        override = ContentDecision.objects.get(cinder_id='5678')
        assert override.action == DECISION_ACTIONS.AMO_APPROVE
        self.assertCloseToNow(override.action_date)
        assert override.override_of == self.decision

    def test_non_second_level_approver_cannot_access(self):
        self.login_as_reviewer()
        response = self.client.get(self.url)
        assert response.status_code == 403

    def test_reviewer_viewer_can_access(self):
        user = user_factory()
        self.grant_permission(user, 'ReviewerTools:View')
        self.client.force_login(user)
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert pq(response.content)('.entity-type-Extension')

    def test_reviewer_viewer_cannot_submit(self):
        user = user_factory()
        self.grant_permission(user, 'ReviewerTools:View')
        self.client.force_login(user)
        response = self.client.post(self.url, {'choice': 'yes'})

        assert response.status_code == 403
        assert self.decision.addon.reload().status == amo.STATUS_APPROVED
        assert self.decision.reload().action_date is None

    def test_cant_submit_a_resolved_decision(self):
        self.decision.update(action_date=datetime.now())
        addon = self.decision.addon

        response = self.client.post(self.url, {'choice': 'yes'})

        assert response.status_code == 200
        assert addon.reload().status == amo.STATUS_APPROVED
        self.assertFormError(
            response,
            form='form',
            field=None,
            errors=['Not currently held for 2nd level approval'],
        )
