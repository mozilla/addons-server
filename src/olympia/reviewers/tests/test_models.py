# -*- coding: utf-8 -*-
import json
import time
from datetime import datetime, timedelta
from unittest import mock

from django.conf import settings
from django.core import mail
from olympia import amo
from olympia.abuse.models import AbuseReport
from olympia.access.models import Group, GroupUser
from olympia.addons.models import (
    Addon, AddonApprovalsCounter, AddonReviewerFlags, AddonUser)
from olympia.amo.tests import (
    TestCase, addon_factory, file_factory, user_factory, version_factory)
from olympia.blocklist.models import Block
from olympia.constants.promoted import (
    LINE, NOT_PROMOTED, RECOMMENDED, STRATEGIC)
from olympia.files.models import File, FileValidation, WebextPermission
from olympia.promoted.models import PromotedAddon
from olympia.ratings.models import Rating
from olympia.reviewers.models import (
    AutoApprovalNotEnoughFilesError, AutoApprovalNoValidationResultError,
    AutoApprovalSummary, CannedResponse, ReviewerScore, ReviewerSubscription,
    ViewExtensionQueue, ViewRecommendedQueue, ViewThemeFullReviewQueue,
    ViewThemePendingQueue, ViewUnlistedAllList, send_notifications,
    set_reviewing_cache)
from olympia.users.models import UserProfile
from olympia.versions.models import Version, version_uploaded


def create_search_ext(name, version_str, addon_status, file_status,
                      channel):
    addon, created_ = Addon.objects.get_or_create(
        name__localized_string=name,
        defaults={'type': amo.ADDON_SEARCH, 'name': name})
    version, created_ = Version.objects.get_or_create(
        addon=addon, version=version_str, defaults={'channel': channel})
    File.objects.create(version=version, filename=u"%s.xpi" % name,
                        platform=amo.PLATFORM_ALL.id, status=file_status)
    if file_status == amo.STATUS_AWAITING_REVIEW:
        AddonReviewerFlags.objects.update_or_create(
            addon=addon, auto_approval_disabled=True)
    # Update status *after* there are files:
    addon = Addon.objects.get(pk=addon.id)
    addon.update(status=addon_status)
    return addon


class TestQueue(TestCase):
    """Tests common attributes and coercions that each view must support."""
    __test__ = False  # this is an abstract test case

    def test_latest_version(self):
        addon = self.new_addon()
        v1 = addon.find_latest_version(self.channel)
        v1.update(created=self.days_ago(2))
        v1.all_files[0].update(status=amo.STATUS_APPROVED)
        version_factory(addon=addon, version='2.0', created=self.days_ago(1),
                        channel=self.channel,
                        file_kw={'status': amo.STATUS_APPROVED})
        version_factory(addon=addon, version='3.0', created=self.days_ago(0),
                        channel=self.channel,
                        file_kw={'status': amo.STATUS_AWAITING_REVIEW})
        row = self.Queue.objects.get()
        assert row.latest_version == '3.0'

    def test_addons_disabled_by_user_are_hidden(self):
        self.new_addon(version=u'0.1').update(disabled_by_user=True)
        assert list(self.Queue.objects.all()) == []

    def test_addons_disabled_by_admin_are_hidden(self):
        self.new_addon(version=u'0.1').update(status=amo.STATUS_DISABLED)
        assert list(self.Queue.objects.all()) == []

    def test_reviewed_files_are_hidden(self):
        self.new_addon(name='Unreviewed')
        addon_factory(name='Already Reviewed')
        assert sorted(q.addon_name for q in self.Queue.objects.all()) == (
            ['Unreviewed'])

    def test_search_extensions(self):
        self.new_search_ext('Search Tool', '0.1')
        row = self.Queue.objects.get()
        assert row.addon_name == u'Search Tool'
        assert row.addon_type_id == amo.ADDON_SEARCH

    def test_count_all(self):
        # Create two new addons and give each another version.
        version_factory(addon=self.new_addon(), version=u'2.0',
                        channel=self.channel)
        version_factory(addon=self.new_addon(), version=u'2.0',
                        channel=self.channel)
        assert self.Queue.objects.all().count() == 2


class TestExtensionQueueWithAwaitingReview(TestQueue):
    __test__ = True
    Queue = ViewExtensionQueue
    channel = amo.RELEASE_CHANNEL_LISTED

    def new_addon(self, name=u'Pending', version=u'1.0'):
        """Creates an approved addon with two listed versions, one approved,
        the second awaiting review."""
        addon = addon_factory(
            name=name,
            version_kw={'version': u'0.0.1', 'channel': self.channel,
                        'created': self.days_ago(1)})
        version_factory(
            addon=addon, version=version, channel=self.channel,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW,
                     'is_restart_required': False})
        return addon

    def new_search_ext(self, name, version, **kw):
        return create_search_ext(
            name, version, amo.STATUS_APPROVED, amo.STATUS_AWAITING_REVIEW,
            channel=self.channel, **kw)

    def test_waiting_time(self):
        self.new_addon()
        Version.objects.update(created=datetime.utcnow())
        row = self.Queue.objects.all()[0]
        assert row.waiting_time_days == 0
        # Time zone will be off, hard to test this.
        assert row.waiting_time_hours is not None

    def test_flags_auto_approval_delayed_indefinitely(self):
        AddonReviewerFlags.objects.create(
            addon=self.new_addon(), auto_approval_delayed_until=datetime.max)

        queue = self.Queue.objects.get()
        assert queue.flags == [
            ('auto-approval-delayed-indefinitely',
             'Auto-approval delayed indefinitely')
        ]

    def test_flags_auto_approval_delayed_temporarily(self):
        reviewer_flags = AddonReviewerFlags.objects.create(
            addon=self.new_addon(),
            auto_approval_delayed_until=datetime.now() + timedelta(hours=1))

        queue = self.Queue.objects.get()
        assert queue.flags == [
            ('auto-approval-delayed-temporarily',
             'Auto-approval delayed temporarily')
        ]

        # Ignored if it's in the past.
        reviewer_flags.update(
            auto_approval_delayed_until=datetime.now() - timedelta(hours=1))

        queue = self.Queue.objects.get()
        assert queue.flags == []

    def test_flags_needs_admin_code_review(self):
        AddonReviewerFlags.objects.create(
            addon=self.new_addon(), needs_admin_code_review=True)

        queue = self.Queue.objects.get()
        assert queue.flags == [
            ('needs-admin-code-review', 'Needs Admin Code Review')]

    def test_flags_is_restart_required(self):
        self.new_addon().find_latest_version(self.channel).all_files[0].update(
            is_restart_required=True)

        queue = self.Queue.objects.get()
        assert queue.flags == [('is_restart_required', 'Requires Restart')]

    def test_flags_sources_provided(self):
        self.new_addon().find_latest_version(self.channel).update(
            source='/some/source/file')

        queue = self.Queue.objects.get()
        assert queue.flags == [('sources-provided', 'Sources provided')]

    def test_flags_webextension(self):
        addon = self.new_addon()
        addon.find_latest_version(self.channel).all_files[0].update(
            is_webextension=True)
        AddonReviewerFlags.objects.update_or_create(
            addon=addon, auto_approval_disabled=True)

        queue = self.Queue.objects.get()
        assert queue.flags == [('webextension', 'WebExtension')]

    def test_no_flags(self):
        self.new_addon()

        queue = self.Queue.objects.get()
        assert queue.flags == []


class TestThemePendingQueue(TestQueue):
    Queue = ViewThemePendingQueue


class TestExtensionQueueWithNominated(TestQueue):
    __test__ = True
    Queue = ViewExtensionQueue
    channel = amo.RELEASE_CHANNEL_LISTED

    def new_addon(self, name=u'Nominated', version=u'1.0',
                  addon_status=amo.STATUS_NOMINATED,
                  file_status=amo.STATUS_AWAITING_REVIEW):
        addon = addon_factory(
            name=name, status=addon_status,
            version_kw={'version': version, 'channel': self.channel},
            file_kw={'status': file_status})
        return addon

    def new_search_ext(self, name, version, **kw):
        return create_search_ext(name, version,
                                 amo.STATUS_NOMINATED,
                                 amo.STATUS_AWAITING_REVIEW,
                                 channel=self.channel, **kw)

    def test_waiting_time(self):
        self.new_addon()
        Version.objects.update(nomination=datetime.utcnow())
        row = self.Queue.objects.all()[0]
        assert row.waiting_time_days == 0
        # Time zone will be off, hard to test this.
        assert row.waiting_time_hours is not None


class TestThemeFullReviewQueue(TestQueue):
    Queue = ViewThemeFullReviewQueue


class TestRecommendedQueue(TestQueue):
    __test__ = True
    Queue = ViewRecommendedQueue
    channel = amo.RELEASE_CHANNEL_LISTED

    def new_addon(self, name=u'Nominated', version=u'1.0',
                  addon_status=amo.STATUS_NOMINATED,
                  file_status=amo.STATUS_AWAITING_REVIEW):
        addon = addon_factory(
            name=name, status=addon_status,
            recommended=True,
            version_kw={
                'version': version,
                'channel': self.channel,
                'recommendation_approved': False},
            file_kw={'status': file_status})
        return addon

    def new_search_ext(self, name, version, **kw):
        addon = create_search_ext(
            name, version, amo.STATUS_NOMINATED, amo.STATUS_AWAITING_REVIEW,
            channel=self.channel, **kw)
        self.make_addon_promoted(addon, RECOMMENDED)
        return addon

    def test_new_submissions_and_updates_present(self):
        self.new_addon()
        version_factory(
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
            addon=self.new_addon(
                addon_status=amo.STATUS_APPROVED,
                file_status=amo.STATUS_APPROVED,
                name='Updated'))
        # Add some extras that shouldn't be there
        self.new_addon(
            addon_status=amo.STATUS_APPROVED, file_status=amo.STATUS_APPROVED,
            name='No updates')
        PromotedAddon.objects.get(
            addon=self.new_addon(name='Not recommended')).update(
            group_id=NOT_PROMOTED.id)
        PromotedAddon.objects.get(
            addon=self.new_addon(name='Promoted but not recommended')).update(
            group_id=LINE.id)
        PromotedAddon.objects.get(
            addon=self.new_addon(name='Not discovery item')).delete()

        assert sorted(q.addon_name for q in self.Queue.objects.all()) == (
            ['Nominated', 'Updated'])


class TestUnlistedAllList(TestCase):
    Queue = ViewUnlistedAllList
    channel = amo.RELEASE_CHANNEL_UNLISTED
    fixtures = ['base/users']

    def new_addon(self, name=u'Unlisted', version=u'1.0',
                  addon_status=amo.STATUS_NULL,
                  file_status=amo.STATUS_APPROVED):
        addon = addon_factory(
            name=name, status=addon_status,
            version_kw={'version': version, 'channel': self.channel},
            file_kw={'status': file_status})
        return addon

    def test_all_addons_are_in_q(self):
        self.new_addon('Public', addon_status=amo.STATUS_APPROVED,
                       file_status=amo.STATUS_APPROVED)
        self.new_addon('Nominated', addon_status=amo.STATUS_NOMINATED,
                       file_status=amo.STATUS_AWAITING_REVIEW)
        self.new_addon('Deleted', addon_status=amo.STATUS_APPROVED,
                       file_status=amo.STATUS_APPROVED).delete()
        assert sorted(q.addon_name for q in self.Queue.objects.all()) == (
            ['Deleted', 'Nominated', 'Public'])

    def test_authors(self):
        addon = self.new_addon()
        bert = user_factory(username='bert')
        ernie = user_factory(username='ernie')
        AddonUser.objects.create(addon=addon, user=bert)
        AddonUser.objects.create(addon=addon, user=ernie)
        row = self.Queue.objects.all()[0]
        self.assertSetEqual(set(row.authors),
                            {(ernie.id, 'ernie'), (bert.id, 'bert')})

    def test_addons_disabled_by_user_are_hidden(self):
        self.new_addon().update(disabled_by_user=True)
        assert list(self.Queue.objects.all()) == []

    def test_addons_disabled_by_admin_are_hidden(self):
        self.new_addon(version=u'0.1').update(status=amo.STATUS_DISABLED)
        assert list(self.Queue.objects.all()) == []

    def test_count_all(self):
        addon1 = self.new_addon()
        version_factory(addon=addon1, version=u'0.2')
        addon2 = self.new_addon()
        version_factory(addon=addon2, version=u'0.2')
        assert self.Queue.objects.all().count() == 2

    def test_mixed_listed(self):
        unlisted_listed = addon_factory(
            status=amo.STATUS_NULL, name=u'UnlistedListed',
            version_kw={'version': u'0.1',
                        'channel': amo.RELEASE_CHANNEL_UNLISTED},
            file_kw={'status': amo.STATUS_APPROVED})
        version_factory(addon=unlisted_listed, version=u'0.2',
                        channel=amo.RELEASE_CHANNEL_LISTED,
                        file_kw={'status': amo.STATUS_APPROVED})

        listed_unlisted = addon_factory(
            status=amo.STATUS_NULL, name=u'ListedUnlisted',
            version_kw={'version': u'0.1',
                        'channel': amo.RELEASE_CHANNEL_LISTED},
            file_kw={'status': amo.STATUS_APPROVED})
        version_factory(addon=listed_unlisted, version=u'0.2',
                        channel=amo.RELEASE_CHANNEL_UNLISTED,
                        file_kw={'status': amo.STATUS_APPROVED})

        just_unlisted = addon_factory(
            status=amo.STATUS_NULL, name=u'JustUnlisted',
            version_kw={'version': u'0.1',
                        'channel': amo.RELEASE_CHANNEL_UNLISTED},
            file_kw={'status': amo.STATUS_APPROVED})
        version_factory(addon=just_unlisted, version=u'0.2',
                        channel=amo.RELEASE_CHANNEL_UNLISTED,
                        file_kw={'status': amo.STATUS_APPROVED})

        just_listed = addon_factory(
            status=amo.STATUS_NULL, name=u'JustListed',
            version_kw={'version': u'0.1',
                        'channel': amo.RELEASE_CHANNEL_LISTED},
            file_kw={'status': amo.STATUS_APPROVED})
        version_factory(addon=just_listed, version=u'0.2',
                        channel=amo.RELEASE_CHANNEL_LISTED,
                        file_kw={'status': amo.STATUS_APPROVED})

        assert self.Queue.objects.all().count() == 3
        assert [addon.addon_name for addon in self.Queue.objects.all()] == [
            'UnlistedListed', 'ListedUnlisted', 'JustUnlisted']


class TestReviewerSubscription(TestCase):
    fixtures = ['base/addon_3615', 'base/users']

    def setUp(self):
        super(TestReviewerSubscription, self).setUp()
        self.addon = Addon.objects.get(pk=3615)
        self.version = self.addon.current_version
        self.user_one = UserProfile.objects.get(pk=55021)
        self.user_two = UserProfile.objects.get(pk=999)
        self.reviewer_group = Group.objects.create(
            name='Reviewers: Legacy', rules='Addons:Review')
        GroupUser.objects.create(
            group=self.reviewer_group, user=self.user_one)
        self.post_reviewer_group = Group.objects.create(
            name='Reviewers: Add-ons', rules='Addons:PostReview')
        GroupUser.objects.create(
            group=self.post_reviewer_group, user=self.user_two)
        ReviewerSubscription.objects.create(
            addon=self.addon, user=self.user_one)
        ReviewerSubscription.objects.create(
            addon=self.addon, user=self.user_two)

    def test_email(self):
        es = ReviewerSubscription.objects.get(user=self.user_one)
        es.send_notification(self.version)
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == [u'del@icio.us']
        assert mail.outbox[0].subject == (
            'Mozilla Add-ons: Delicious Bookmarks Updated')

    def test_notifications(self):
        send_notifications(sender=Version, instance=self.version)
        assert len(mail.outbox) == 2
        emails = sorted([o.to for o in mail.outbox])
        assert emails == [[u'del@icio.us'], [u'regular@mozilla.com']]

    def test_notifications_setting_persists(self):
        send_notifications(Version, self.version)
        assert ReviewerSubscription.objects.count() == 2
        mail.outbox = []
        send_notifications(Version, self.version)
        assert len(mail.outbox) == 2

    def test_dont_send_notifications_unlisted(self):
        self.version.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        version_uploaded.send(sender=Version, instance=self.version)
        assert len(mail.outbox) == 0

    def test_signal_edit(self):
        self.version.save()
        assert len(mail.outbox) == 0

    def test_signal_create(self):
        version = Version.objects.create(addon=self.addon)
        version_uploaded.send(sender=Version, instance=version)
        assert len(mail.outbox) == 2
        assert mail.outbox[0].subject == (
            'Mozilla Add-ons: Delicious Bookmarks Updated')

    def test_signal_create_twice(self):
        version = Version.objects.create(addon=self.addon)
        version_uploaded.send(sender=Version, instance=version)
        mail.outbox = []
        version = Version.objects.create(addon=self.addon)
        version_uploaded.send(sender=Version, instance=version)
        assert len(mail.outbox) == 2

    def test_no_email_for_ex_reviewers(self):
        self.user_one.delete()
        mail.outbox = []  # deleting the user sends an email for the addon
        # Remove user_one from reviewers.
        GroupUser.objects.get(
            group=self.reviewer_group, user=self.user_one).delete()
        send_notifications(sender=Version, instance=self.version)
        assert len(mail.outbox) == 1  # Only notification for user_two remains.

    def test_no_email_address_for_reviewer(self):
        self.user_one.update(email=None)
        send_notifications(sender=Version, instance=self.version)
        assert len(mail.outbox) == 1  # Only notification for user_two remains.


class TestReviewerScore(TestCase):
    fixtures = ['base/users']

    def setUp(self):
        super(TestReviewerScore, self).setUp()
        self.addon = amo.tests.addon_factory(status=amo.STATUS_NOMINATED)
        self.user = UserProfile.objects.get(email='reviewer@mozilla.com')

    def _give_points(self, user=None, addon=None, status=None):
        user = user or self.user
        addon = addon or self.addon
        ReviewerScore.award_points(
            user, addon, status or addon.status, version=addon.current_version)

    def check_event(self, type, status, event, **kwargs):
        self.addon.type = type
        assert ReviewerScore.get_event(self.addon, status, **kwargs) == event

    def test_events_addons(self):
        types = {
            amo.ADDON_ANY: None,
            amo.ADDON_EXTENSION: 'ADDON',
            amo.ADDON_DICT: 'DICT',
            amo.ADDON_SEARCH: 'SEARCH',
            amo.ADDON_LPAPP: 'LP',
            amo.ADDON_LPADDON: 'LP',
            amo.ADDON_PLUGIN: 'ADDON',
            amo.ADDON_API: 'ADDON',
            amo.ADDON_STATICTHEME: 'STATICTHEME',
        }
        statuses = {
            amo.STATUS_NULL: None,
            amo.STATUS_NOMINATED: 'FULL',
            amo.STATUS_APPROVED: 'UPDATE',
            amo.STATUS_DISABLED: None,
            amo.STATUS_DELETED: None,
        }
        for tk, tv in types.items():
            for sk, sv in statuses.items():
                try:
                    event = getattr(amo, 'REVIEWED_%s_%s' % (tv, sv))
                except AttributeError:
                    try:
                        event = getattr(amo, 'REVIEWED_%s' % tv)
                    except AttributeError:
                        event = None
                self.check_event(tk, sk, event)

    def test_events_post_review(self):
        self.addon.update(status=amo.STATUS_APPROVED)
        base_args = (self.addon, self.addon.status)
        # No version.
        assert ReviewerScore.get_event(
            *base_args, version=None,
            post_review=True) == amo.REVIEWED_EXTENSION_LOW_RISK
        # No autoapprovalsummary.
        assert ReviewerScore.get_event(
            *base_args, version=self.addon.current_version,
            post_review=True) == amo.REVIEWED_EXTENSION_LOW_RISK
        # Now with a summary... low risk.
        summary = AutoApprovalSummary.objects.create(
            version=self.addon.current_version, verdict=amo.AUTO_APPROVED,
            weight=-10)
        assert ReviewerScore.get_event(
            *base_args, version=self.addon.current_version,
            post_review=True) is amo.REVIEWED_EXTENSION_LOW_RISK
        # Medium risk.
        summary.update(weight=91)
        assert ReviewerScore.get_event(
            *base_args, version=self.addon.current_version,
            post_review=True) is amo.REVIEWED_EXTENSION_MEDIUM_RISK
        # High risk.
        summary.update(weight=176)
        assert ReviewerScore.get_event(
            *base_args, version=self.addon.current_version,
            post_review=True) is amo.REVIEWED_EXTENSION_HIGH_RISK
        # Highest risk.
        summary.update(weight=276)
        assert ReviewerScore.get_event(
            *base_args, version=self.addon.current_version,
            post_review=True) is amo.REVIEWED_EXTENSION_HIGHEST_RISK
        # Highest risk again.
        summary.update(weight=65535)
        assert ReviewerScore.get_event(
            *base_args, version=self.addon.current_version,
            post_review=True) is amo.REVIEWED_EXTENSION_HIGHEST_RISK
        # Content review is always the same.
        assert ReviewerScore.get_event(
            *base_args, version=self.addon.current_version, post_review=True,
            content_review=True) == amo.REVIEWED_CONTENT_REVIEW

    def test_award_points(self):
        self._give_points()
        assert ReviewerScore.objects.all()[0].score == (
            amo.REVIEWED_SCORES[amo.REVIEWED_ADDON_FULL])

    def test_award_points_with_extra_note(self):
        ReviewerScore.award_points(
            self.user, self.addon, self.addon.status, extra_note=u'ÔMG!')
        reviewer_score = ReviewerScore.objects.all()[0]
        assert reviewer_score.note_key == amo.REVIEWED_ADDON_FULL
        assert reviewer_score.score == (
            amo.REVIEWED_SCORES[amo.REVIEWED_ADDON_FULL])
        assert reviewer_score.note == u'ÔMG!'

    def test_award_points_bonus(self):
        user2 = UserProfile.objects.get(email='admin@mozilla.com')
        bonus_days = 2
        days = amo.REVIEWED_OVERDUE_LIMIT + bonus_days

        bonus_addon = addon_factory(
            status=amo.STATUS_NOMINATED,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW})
        bonus_addon.current_version.update(
            nomination=(datetime.now() - timedelta(days=days, minutes=5))
        )
        self._give_points(user2, bonus_addon, amo.STATUS_NOMINATED)
        score = ReviewerScore.objects.get(user=user2)
        expected = (amo.REVIEWED_SCORES[amo.REVIEWED_ADDON_FULL] +
                    (amo.REVIEWED_OVERDUE_BONUS * bonus_days))

        assert score.score == expected

    def test_award_points_no_bonus_for_content_review(self):
        self.addon.update(status=amo.STATUS_APPROVED)
        self.addon.current_version.update(nomination=self.days_ago(28))
        AutoApprovalSummary.objects.create(
            version=self.addon.current_version, verdict=amo.AUTO_APPROVED,
            weight=100)
        ReviewerScore.award_points(
            self.user, self.addon, self.addon.status,
            version=self.addon.current_version,
            post_review=False, content_review=True)
        score = ReviewerScore.objects.get(user=self.user)
        assert score.score == amo.REVIEWED_SCORES[amo.REVIEWED_CONTENT_REVIEW]

    def test_award_points_no_bonus_for_post_review(self):
        self.addon.update(status=amo.STATUS_APPROVED)
        self.addon.current_version.update(nomination=self.days_ago(29))
        AutoApprovalSummary.objects.create(
            version=self.addon.current_version, verdict=amo.AUTO_APPROVED,
            weight=101)
        ReviewerScore.award_points(
            self.user, self.addon, self.addon.status,
            version=self.addon.current_version,
            post_review=True, content_review=False)
        score = ReviewerScore.objects.get(user=self.user)
        assert score.score == amo.REVIEWED_SCORES[
            amo.REVIEWED_EXTENSION_MEDIUM_RISK]
        assert score.version == self.addon.current_version

    def test_award_points_extension_disabled_autoapproval(self):
        self.version = version_factory(
            addon=self.addon, version='1.1', file_kw={
                'status': amo.STATUS_AWAITING_REVIEW,
                'is_webextension': True})
        AutoApprovalSummary.objects.create(
            version=self.addon.current_version, verdict=amo.NOT_AUTO_APPROVED,
            weight=101)
        ReviewerScore.award_points(
            self.user, self.addon, self.addon.status,
            version=self.addon.current_version,
            post_review=False, content_review=False)
        score = ReviewerScore.objects.get(user=self.user)
        assert score.score == amo.REVIEWED_SCORES[
            amo.REVIEWED_EXTENSION_MEDIUM_RISK]
        assert score.version == self.addon.current_version

    def test_award_points_langpack_post_review(self):
        search_provider = amo.tests.addon_factory(
            status=amo.STATUS_APPROVED, type=amo.ADDON_LPAPP)
        self.version = version_factory(
            addon=search_provider, version='1.1', file_kw={
                'status': amo.STATUS_APPROVED,
                'is_webextension': True})
        AutoApprovalSummary.objects.create(
            version=search_provider.current_version,
            verdict=amo.AUTO_APPROVED,
            weight=101)
        ReviewerScore.award_points(
            self.user, search_provider, search_provider.status,
            version=search_provider.current_version,
            post_review=True, content_review=False)
        score = ReviewerScore.objects.get(user=self.user)
        assert score.score == amo.REVIEWED_SCORES[
            amo.REVIEWED_LP_FULL]
        assert score.version == search_provider.current_version

    def test_award_points_langpack_disabled_auto_approval(self):
        search_provider = amo.tests.addon_factory(
            status=amo.STATUS_NOMINATED, type=amo.ADDON_LPAPP)
        self.version = version_factory(
            addon=search_provider, version='1.1', file_kw={
                'status': amo.STATUS_AWAITING_REVIEW,
                'is_webextension': True})
        AutoApprovalSummary.objects.create(
            version=search_provider.current_version,
            verdict=amo.NOT_AUTO_APPROVED,
            weight=101)
        ReviewerScore.award_points(
            self.user, search_provider, search_provider.status,
            version=search_provider.current_version,
            post_review=False, content_review=False)
        score = ReviewerScore.objects.get(user=self.user)
        assert score.score == amo.REVIEWED_SCORES[
            amo.REVIEWED_LP_FULL]
        assert score.version == search_provider.current_version

    def test_award_points_dict_post_review(self):
        dictionary = amo.tests.addon_factory(
            status=amo.STATUS_APPROVED, type=amo.ADDON_DICT)
        self.version = version_factory(
            addon=dictionary, version='1.1', file_kw={
                'status': amo.STATUS_APPROVED,
                'is_webextension': True})
        AutoApprovalSummary.objects.create(
            version=dictionary.current_version,
            verdict=amo.AUTO_APPROVED,
            weight=101)
        ReviewerScore.award_points(
            self.user, dictionary, dictionary.status,
            version=dictionary.current_version,
            post_review=True, content_review=False)
        score = ReviewerScore.objects.get(user=self.user)
        assert score.score == amo.REVIEWED_SCORES[
            amo.REVIEWED_DICT_FULL]
        assert score.version == dictionary.current_version

    def test_award_points_dict_disabled_auto_approval(self):
        dictionary = amo.tests.addon_factory(
            status=amo.STATUS_NOMINATED, type=amo.ADDON_DICT)
        self.version = version_factory(
            addon=dictionary, version='1.1', file_kw={
                'status': amo.STATUS_AWAITING_REVIEW,
                'is_webextension': True})
        AutoApprovalSummary.objects.create(
            version=dictionary.current_version,
            verdict=amo.NOT_AUTO_APPROVED,
            weight=101)
        ReviewerScore.award_points(
            self.user, dictionary, dictionary.status,
            version=dictionary.current_version,
            post_review=False, content_review=False)
        score = ReviewerScore.objects.get(user=self.user)
        assert score.score == amo.REVIEWED_SCORES[
            amo.REVIEWED_DICT_FULL]
        assert score.version == dictionary.current_version

    def test_award_moderation_points(self):
        ReviewerScore.award_moderation_points(self.user, self.addon, 1)
        score = ReviewerScore.objects.all()[0]
        assert score.score == (
            amo.REVIEWED_SCORES.get(amo.REVIEWED_ADDON_REVIEW))
        assert score.note_key == amo.REVIEWED_ADDON_REVIEW
        assert not score.version

    def test_get_total(self):
        user2 = UserProfile.objects.get(email='admin@mozilla.com')
        self._give_points()
        self._give_points(status=amo.STATUS_APPROVED)
        self._give_points(user=user2, status=amo.STATUS_NOMINATED)
        assert ReviewerScore.get_total(self.user) == (
            amo.REVIEWED_SCORES[amo.REVIEWED_ADDON_FULL] +
            amo.REVIEWED_SCORES[amo.REVIEWED_ADDON_UPDATE])
        assert ReviewerScore.get_total(user2) == (
            amo.REVIEWED_SCORES[amo.REVIEWED_ADDON_FULL])

    def test_get_recent(self):
        user2 = UserProfile.objects.get(email='admin@mozilla.com')
        self._give_points()
        time.sleep(1)  # Wait 1 sec so ordering by created is checked.
        self._give_points(status=amo.STATUS_APPROVED)
        self._give_points(user=user2)
        scores = ReviewerScore.get_recent(self.user)
        assert len(scores) == 2
        assert scores[0].score == (
            amo.REVIEWED_SCORES[amo.REVIEWED_ADDON_UPDATE])
        assert scores[1].score == (
            amo.REVIEWED_SCORES[amo.REVIEWED_ADDON_FULL])

    def test_get_leaderboards(self):
        user2 = UserProfile.objects.get(email='theme_reviewer@mozilla.com')
        self._give_points()
        self._give_points(status=amo.STATUS_APPROVED)
        self._give_points(user=user2, status=amo.STATUS_NOMINATED)
        leaders = ReviewerScore.get_leaderboards(self.user)
        assert leaders['user_rank'] == 1
        assert leaders['leader_near'] == []
        assert leaders['leader_top'][0]['rank'] == 1
        assert leaders['leader_top'][0]['user_id'] == self.user.id
        assert leaders['leader_top'][0]['total'] == (
            amo.REVIEWED_SCORES[amo.REVIEWED_ADDON_FULL] +
            amo.REVIEWED_SCORES[amo.REVIEWED_ADDON_UPDATE])
        assert leaders['leader_top'][1]['rank'] == 2
        assert leaders['leader_top'][1]['user_id'] == user2.id
        assert leaders['leader_top'][1]['total'] == (
            amo.REVIEWED_SCORES[amo.REVIEWED_ADDON_FULL])

        self._give_points(
            user=user2, addon=amo.tests.addon_factory(
                type=amo.ADDON_STATICTHEME))
        leaders = ReviewerScore.get_leaderboards(
            self.user, addon_type=amo.ADDON_STATICTHEME)
        assert len(leaders['leader_top']) == 1
        assert leaders['leader_top'][0]['user_id'] == user2.id

    def test_only_active_reviewers_in_leaderboards(self):
        user2 = UserProfile.objects.create(username='former-reviewer')
        self._give_points()
        self._give_points(status=amo.STATUS_APPROVED)
        self._give_points(user=user2, status=amo.STATUS_NOMINATED)
        leaders = ReviewerScore.get_leaderboards(self.user)
        assert leaders['user_rank'] == 1
        assert leaders['leader_near'] == []
        assert leaders['leader_top'][0]['user_id'] == self.user.id
        assert len(leaders['leader_top']) == 1  # Only the reviewer is here.
        assert user2.id not in [
            leader['user_id'] for leader in leaders['leader_top']], (
                'Unexpected non-reviewer user found in leaderboards.')

    def test_no_admins_or_staff_in_leaderboards(self):
        user2 = UserProfile.objects.get(email='admin@mozilla.com')
        self._give_points()
        self._give_points(status=amo.STATUS_APPROVED)
        self._give_points(user=user2, status=amo.STATUS_NOMINATED)
        leaders = ReviewerScore.get_leaderboards(self.user)
        assert leaders['user_rank'] == 1
        assert leaders['leader_near'] == []
        assert leaders['leader_top'][0]['user_id'] == self.user.id
        assert len(leaders['leader_top']) == 1  # Only the reviewer is here.
        assert user2.id not in [
            leader['user_id'] for leader in leaders['leader_top']], (
                'Unexpected admin user found in leaderboards.')

    def test_get_leaderboards_last(self):
        users = []
        for i in range(6):
            user = UserProfile.objects.create(username='user-%s' % i)
            GroupUser.objects.create(group_id=50002, user=user)
            users.append(user)
        last_user = users.pop(len(users) - 1)
        for u in users:
            self._give_points(user=u)
        # Last user gets lower points by reviewing a theme.
        addon = self.addon
        addon.type = amo.ADDON_STATICTHEME
        self._give_points(user=last_user, addon=addon)
        leaders = ReviewerScore.get_leaderboards(last_user)
        assert leaders['user_rank'] == 6
        assert len(leaders['leader_top']) == 3
        assert len(leaders['leader_near']) == 2

    def test_leaderboard_score_when_in_multiple_reviewer_groups(self):
        group_reviewers = Group.objects.create(
            name='Reviewers: Addons', rules='Addons:Review')
        group_content_reviewers = Group.objects.create(
            name='Reviewers: Content', rules='Addons:ContentReview')
        GroupUser.objects.create(group=group_reviewers, user=self.user)
        GroupUser.objects.create(group=group_content_reviewers, user=self.user)

        AutoApprovalSummary.objects.create(
            version=self.addon.current_version, verdict=amo.AUTO_APPROVED,
            weight=101)
        ReviewerScore.award_points(
            self.user, self.addon, self.addon.status,
            version=self.addon.current_version,
            post_review=True, content_review=False)
        assert ReviewerScore._leaderboard_list() == [(
            self.user.id, self.user.name, amo.REVIEWED_SCORES[
                amo.REVIEWED_EXTENSION_MEDIUM_RISK])]

    def test_all_users_by_score(self):
        user2 = UserProfile.objects.create(
            username='otherreviewer', email='otherreviewer@mozilla.com')
        self.grant_permission(
            user2, 'Addons:ThemeReview', name='Reviewers: Themes')
        amo.REVIEWED_LEVELS[0]['points'] = 180
        self._give_points()
        self._give_points(status=amo.STATUS_APPROVED)
        self._give_points(user=user2, status=amo.STATUS_NOMINATED)
        users = ReviewerScore.all_users_by_score()
        assert len(users) == 2
        # First user.
        assert users[0]['total'] == 200
        assert users[0]['user_id'] == self.user.id
        assert users[0]['level'] == amo.REVIEWED_LEVELS[0]['name']
        # Second user.
        assert users[1]['total'] == 120
        assert users[1]['user_id'] == user2.id
        assert users[1]['level'] == ''

    def test_caching(self):
        self._give_points()

        with self.assertNumQueries(1):
            ReviewerScore.get_total(self.user)
        with self.assertNumQueries(0):
            ReviewerScore.get_total(self.user)

        with self.assertNumQueries(1):
            ReviewerScore.get_recent(self.user)
        with self.assertNumQueries(0):
            ReviewerScore.get_recent(self.user)

        with self.assertNumQueries(2):
            ReviewerScore.get_leaderboards(self.user)
        with self.assertNumQueries(0):
            ReviewerScore.get_leaderboards(self.user)

        with self.assertNumQueries(1):
            ReviewerScore.get_breakdown(self.user)
        with self.assertNumQueries(0):
            ReviewerScore.get_breakdown(self.user)

        # New points invalidates all caches.
        self._give_points()

        with self.assertNumQueries(1):
            ReviewerScore.get_total(self.user)
        with self.assertNumQueries(1):
            ReviewerScore.get_recent(self.user)
        with self.assertNumQueries(2):
            ReviewerScore.get_leaderboards(self.user)
        with self.assertNumQueries(1):
            ReviewerScore.get_breakdown(self.user)


class TestAutoApprovalSummary(TestCase):
    def setUp(self):
        self.addon = addon_factory(
            average_daily_users=666, version_kw={'version': '1.0'})
        AutoApprovalSummary.objects.create(
            version=self.addon.current_version, verdict=amo.AUTO_APPROVED,
            confirmed=True)
        self.current_file_validation = FileValidation.objects.create(
            file=self.addon.current_version.all_files[0], validation=u'{}')
        self.version = version_factory(
            addon=self.addon, version='1.1', file_kw={
                'status': amo.STATUS_AWAITING_REVIEW,
                'is_webextension': True})
        self.file = self.version.all_files[0]
        self.file_validation = FileValidation.objects.create(
            file=self.version.all_files[0], validation=u'{}')
        AddonApprovalsCounter.objects.create(addon=self.addon, counter=1)

    def test_negative_weight(self):
        summary = AutoApprovalSummary.objects.create(
            version=self.version, weight=-300)
        summary = AutoApprovalSummary.objects.get(pk=summary.pk)
        assert summary.weight == -300

    def test_calculate_weight(self):
        summary = AutoApprovalSummary(version=self.version)
        assert summary.weight_info == {}
        weight_info = summary.calculate_weight()
        expected_result = {
            'abuse_reports': 0,
            'admin_code_review': 0,
            'average_daily_users': 0,
            'negative_ratings': 0,
            'reputation': 0,
            'past_rejection_history': 0,
            'uses_custom_csp': 0,
            'uses_eval_or_document_write': 0,
            'uses_implied_eval': 0,
            'uses_innerhtml': 0,
            'uses_native_messaging': 0,
            'size_of_code_changes': 0,
            'uses_remote_scripts': 0,
            'uses_unknown_minified_code': 0,
            'violates_mozilla_conditions': 0,
            'uses_coinminer': 0,
        }
        assert weight_info == expected_result
        assert summary.weight_info == weight_info

    def test_calculate_weight_admin_code_review(self):
        AddonReviewerFlags.objects.create(
            addon=self.addon, needs_admin_code_review=True)
        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 100
        assert weight_info['admin_code_review'] == 100

    def test_calculate_weight_abuse_reports(self):
        # Extra abuse report for a different add-on, does not count.
        AbuseReport.objects.create(addon=addon_factory())

        # Extra abuse report for a different user, does not count.
        AbuseReport.objects.create(user=user_factory())

        # Extra old abuse report, does not count either.
        old_report = AbuseReport.objects.create(addon=self.addon)
        old_report.update(created=self.days_ago(43))

        # Recent abuse reports.
        AbuseReport.objects.create(addon=self.addon)
        recent_report = AbuseReport.objects.create(addon=self.addon)
        recent_report.update(created=self.days_ago(41))

        # Recent abuse report for one of the developers of the add-on.
        author = user_factory()
        AddonUser.objects.create(addon=self.addon, user=author)
        AbuseReport.objects.create(user=author)

        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 45
        assert weight_info['abuse_reports'] == 45

        # Should be capped at 100. We're already at 45, adding 4 more should
        # result in a weight of 100 instead of 105.
        for i in range(0, 4):
            AbuseReport.objects.create(addon=self.addon)
        weight_info = summary.calculate_weight()
        assert summary.weight == 100
        assert weight_info['abuse_reports'] == 100

    def test_calculate_weight_abuse_reports_use_created_from_instance(self):
        # Create an abuse report 60 days in the past. It should be ignored it
        # we were calculating from today, but use an AutoApprovalSummary
        # instance that is 20 days old, making the abuse report count.
        report = AbuseReport.objects.create(addon=self.addon)
        report.update(created=self.days_ago(60))

        summary = AutoApprovalSummary.objects.create(version=self.version)
        summary.update(created=self.days_ago(20))

        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 15
        assert weight_info['abuse_reports'] == 15

    def test_calculate_weight_negative_ratings(self):
        # Positive rating, does not count.
        Rating.objects.create(
            user=user_factory(), addon=self.addon, version=self.version,
            rating=5)

        # Negative rating, but too old, does not count.
        old_rating = Rating.objects.create(
            user=user_factory(), addon=self.addon, version=self.version,
            rating=1)
        old_rating.update(created=self.days_ago(370))

        # Negative review on a different add-on, does not count either.
        extra_addon = addon_factory()
        Rating.objects.create(
            user=user_factory(), addon=extra_addon,
            version=extra_addon.current_version, rating=1)

        # Recent negative ratings.
        ratings = [Rating(
            user=user_factory(), addon=self.addon,
            version=self.version, rating=3) for i in range(0, 49)]
        Rating.objects.bulk_create(ratings)
        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 0  # Not enough negative ratings yet...
        assert weight_info['negative_ratings'] == 0

        # Create one more to get to weight == 1.
        Rating.objects.create(
            user=user_factory(), addon=self.addon, version=self.version,
            rating=2)
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 1
        assert weight_info['negative_ratings'] == 1

        # Create 5000 more (sorry!) to make sure it's capped at 100.
        ratings = [Rating(
            user=user_factory(), addon=self.addon,
            version=self.version, rating=3) for i in range(0, 5000)]
        Rating.objects.bulk_create(ratings)

        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 100
        assert weight_info['negative_ratings'] == 100

    def test_calculate_weight_reputation(self):
        summary = AutoApprovalSummary(version=self.version)
        self.addon.update(reputation=0)
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 0
        assert weight_info['reputation'] == 0

        self.addon.update(reputation=3)
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == -300
        assert weight_info['reputation'] == -300

        self.addon.update(reputation=1000)
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == -300
        assert weight_info['reputation'] == -300

        self.addon.update(reputation=-1000)
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 0
        assert weight_info['reputation'] == 0

    def test_calculate_weight_average_daily_users(self):
        self.addon.update(average_daily_users=142444)
        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 14
        assert weight_info['average_daily_users'] == 14

        self.addon.update(average_daily_users=1756567658)
        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 100
        assert weight_info['average_daily_users'] == 100

    def test_calculate_weight_past_rejection_history(self):
        # Old rejected version, does not count.
        version_factory(
            addon=self.addon,
            file_kw={'reviewed': self.days_ago(370),
                     'status': amo.STATUS_DISABLED})

        # Version disabled by the developer, not Mozilla (original_status
        # is set to something different than STATUS_NULL), does not count.
        version_factory(
            addon=self.addon,
            file_kw={'reviewed': self.days_ago(15),
                     'status': amo.STATUS_DISABLED,
                     'original_status': amo.STATUS_APPROVED})

        # Rejected version.
        version_factory(
            addon=self.addon,
            file_kw={'reviewed': self.days_ago(14),
                     'status': amo.STATUS_DISABLED})

        # Another rejected version, with multiple files. Only counts once.
        version_with_multiple_files = version_factory(
            addon=self.addon,
            file_kw={'reviewed': self.days_ago(13),
                     'status': amo.STATUS_DISABLED,
                     'platform': amo.PLATFORM_WIN.id})
        file_factory(
            reviewed=self.days_ago(13),
            version=version_with_multiple_files,
            status=amo.STATUS_DISABLED,
            platform=amo.PLATFORM_MAC.id)

        # Rejected version on a different add-on, does not count.
        version_factory(
            addon=addon_factory(),
            file_kw={'reviewed': self.days_ago(12),
                     'status': amo.STATUS_DISABLED})

        # Approved version, does not count.
        new_approved_version = version_factory(
            addon=self.addon,
            file_kw={'reviewed': self.days_ago(11)})
        FileValidation.objects.create(
            file=new_approved_version.all_files[0], validation=u'{}')

        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 20
        assert weight_info['past_rejection_history'] == 20

        # Should be capped at 100.
        for i in range(0, 10):
            version_factory(
                addon=self.addon,
                file_kw={'reviewed': self.days_ago(10),
                         'status': amo.STATUS_DISABLED})

        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 100
        assert weight_info['past_rejection_history'] == 100

    def test_calculate_weight_uses_eval_or_document_write(self):
        validation_data = {
            'messages': [{
                'id': ['DANGEROUS_EVAL'],
            }]
        }
        self.file_validation.update(validation=json.dumps(validation_data))
        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 50
        assert weight_info['uses_eval_or_document_write'] == 50

        validation_data = {
            'messages': [{
                'id': ['NO_DOCUMENT_WRITE'],
            }]
        }
        self.file_validation.update(validation=json.dumps(validation_data))
        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 50
        assert weight_info['uses_eval_or_document_write'] == 50

        # Still only 20 if both appear.
        validation_data = {
            'messages': [{
                'id': ['DANGEROUS_EVAL'],
            }, {
                'id': ['NO_DOCUMENT_WRITE'],
            }]
        }
        self.file_validation.update(validation=json.dumps(validation_data))
        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 50
        assert weight_info['uses_eval_or_document_write'] == 50

    def test_calculate_weight_uses_implied_eval(self):
        validation_data = {
            'messages': [{
                'id': ['NO_IMPLIED_EVAL'],
            }]
        }
        self.file_validation.update(validation=json.dumps(validation_data))
        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 5
        assert weight_info['uses_implied_eval'] == 5

    def test_calculate_weight_uses_innerhtml(self):
        validation_data = {
            'messages': [{
                'id': ['UNSAFE_VAR_ASSIGNMENT'],
            }]
        }
        self.file_validation.update(validation=json.dumps(validation_data))
        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 50
        assert weight_info['uses_innerhtml'] == 50

    def test_calculate_weight_uses_innerhtml_multiple_times(self):
        validation_data = {
            'messages': [{
                'id': ['UNSAFE_VAR_ASSIGNMENT'],
            }, {
                'id': ['IGNORE_ME'],
            }, {
                'id': ['UNSAFE_VAR_ASSIGNMENT'],
            }, {
                'id': ['UNSAFE_VAR_ASSIGNMENT'],
            }]
        }
        self.file_validation.update(validation=json.dumps(validation_data))
        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        # 50 base, + 10 per additional instance.
        assert summary.weight == 70
        assert weight_info['uses_innerhtml'] == 70

    def test_calculate_weight_uses_custom_csp(self):
        validation_data = {
            'messages': [{
                'id': ['MANIFEST_CSP'],
            }]
        }
        self.file_validation.update(validation=json.dumps(validation_data))
        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 90
        assert weight_info['uses_custom_csp'] == 90

    def test_calculate_weight_uses_native_messaging(self):
        WebextPermission.objects.create(
            file=self.file, permissions=['nativeMessaging'])

        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 100
        assert weight_info['uses_native_messaging'] == 100

    def test_calculate_weight_uses_remote_scripts(self):
        validation_data = {
            'messages': [{
                'id': ['REMOTE_SCRIPT'],
            }]
        }
        self.file_validation.update(validation=json.dumps(validation_data))
        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 100
        assert weight_info['uses_remote_scripts'] == 100

    def test_calculate_weight_violates_mozilla_conditions_of_use(self):
        validation_data = {
            'messages': [{
                'id': ['MOZILLA_COND_OF_USE'],
            }]
        }
        self.file_validation.update(validation=json.dumps(validation_data))
        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 20
        assert weight_info['violates_mozilla_conditions'] == 20

    def test_calculate_weight_uses_unknown_minified_code_nothing(self):
        validation_data = {
            'metadata': {
                'unknownMinifiedFiles': []  # Empty list: no weight.
            }
        }
        self.file_validation.update(validation=json.dumps(validation_data))
        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 0
        assert weight_info['uses_unknown_minified_code'] == 0

        validation_data = {
            'metadata': {
                # Missing property: no weight.
            }
        }
        self.file_validation.update(validation=json.dumps(validation_data))
        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 0
        assert weight_info['uses_unknown_minified_code'] == 0

        validation_data = {
            # Missing metadata: no weight.
        }
        self.file_validation.update(validation=json.dumps(validation_data))
        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 0
        assert weight_info['uses_unknown_minified_code'] == 0

    def test_calculate_weight_uses_unknown_minified_code(self):
        validation_data = {
            'metadata': {
                'unknownMinifiedFiles': ['something']
            }
        }
        self.file_validation.update(validation=json.dumps(validation_data))
        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 100
        assert weight_info['uses_unknown_minified_code'] == 100

    def test_calculate_weight_uses_unknown_minified_code_multiple_times(self):
        validation_data = {
            'metadata': {
                'unknownMinifiedFiles': ['something', 'foobar', 'another']
            }
        }
        self.file_validation.update(validation=json.dumps(validation_data))
        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        # 100 base, + 20 per additional instance.
        assert summary.weight == 120
        assert weight_info['uses_unknown_minified_code'] == 120

    def test_calculate_size_of_code_changes_no_current_validation(self):
        # Delete the validation for the previously confirmed version and reload
        # the version we're testing (otherwise the file validation has already
        # been loaded and is still attached to the instance...)
        self.current_file_validation.delete()
        self.version = Version.objects.get(pk=self.version.pk)
        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 500
        assert weight_info['no_validation_result'] == 500

    def test_calculate_size_of_code_changes_no_new_validation(self):
        # Delete the validation for the new version and reload that version.
        # (otherwise the file validation has already been loaded and is still
        # attached to the instance...)
        self.file_validation.delete()
        self.version = Version.objects.get(pk=self.version.pk)
        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 500
        assert weight_info['no_validation_result'] == 500

    def test_calculate_size_of_code_changes_no_reported_size(self):
        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.calculate_size_of_code_changes() == 0
        assert summary.weight == 0
        assert weight_info['size_of_code_changes'] == 0

    def test_calculate_size_of_code_changes_no_previous_version_size(self):
        validation_data = {
            'metadata': {
                'totalScannedFileSize': 15000,
            }
        }
        self.file_validation.update(validation=json.dumps(validation_data))
        summary = AutoApprovalSummary(version=self.version)
        assert summary.calculate_size_of_code_changes() == 15000
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 3
        assert weight_info['size_of_code_changes'] == 3

    def test_calculate_size_of_code_changes(self):
        old_validation_data = {
            'metadata': {
                'totalScannedFileSize': 5000,
            }
        }
        self.current_file_validation.update(
            validation=json.dumps(old_validation_data))
        new_validation_data = {
            'metadata': {
                'totalScannedFileSize': 15000,
            }
        }
        self.file_validation.update(
            validation=json.dumps(new_validation_data))
        summary = AutoApprovalSummary(version=self.version)
        assert summary.calculate_size_of_code_changes() == 10000
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 2
        assert weight_info['size_of_code_changes'] == 2

    def test_calculate_size_of_code_change_use_previously_confirmed(self):
        old_validation_data = {
            'metadata': {
                'totalScannedFileSize': 5000,
            }
        }
        self.current_file_validation.update(
            validation=json.dumps(old_validation_data))
        new_validation_data = {
            'metadata': {
                'totalScannedFileSize': 15000,
            }
        }
        self.file_validation.update(
            validation=json.dumps(new_validation_data))

        # Add a new current_version, unconfirmed. This version will be ignored
        # for the comparison as all we care about is the previous confirmed
        # version.
        self.addon.current_version.update(created=self.days_ago(2))
        new_version = version_factory(addon=self.addon)
        self.addon.reload()
        assert self.addon.current_version == new_version
        AutoApprovalSummary.objects.create(
            version=new_version, verdict=amo.AUTO_APPROVED)
        new_validation_data = {
            'metadata': {
                'totalScannedFileSize': 14999,
            }
        }
        FileValidation.objects.create(
            file=new_version.all_files[0],
            validation=json.dumps(new_validation_data))

        summary = AutoApprovalSummary(version=self.version)
        # Size of code changes should be 10000 and not 1, proving that it
        # compared with the old, confirmed version.
        assert summary.calculate_size_of_code_changes() == 10000
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 2
        assert weight_info['size_of_code_changes'] == 2

    def test_calculate_size_of_code_changes_no_negative(self):
        old_validation_data = {
            'metadata': {
                'totalScannedFileSize': 20000,
            }
        }
        self.current_file_validation.update(
            validation=json.dumps(old_validation_data))
        new_validation_data = {
            'metadata': {
                'totalScannedFileSize': 5000,
            }
        }
        self.file_validation.update(
            validation=json.dumps(new_validation_data))
        summary = AutoApprovalSummary(version=self.version)
        assert summary.calculate_size_of_code_changes() == 15000
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 3
        assert weight_info['size_of_code_changes'] == 3

    def test_calculate_size_of_code_changes_max(self):
        old_validation_data = {
            'metadata': {
                'totalScannedFileSize': 50000000,
            }
        }
        self.current_file_validation.update(
            validation=json.dumps(old_validation_data))
        new_validation_data = {
            'metadata': {
                'totalScannedFileSize': 0,
            }
        }
        self.file_validation.update(
            validation=json.dumps(new_validation_data))
        summary = AutoApprovalSummary(version=self.version)
        assert summary.calculate_size_of_code_changes() == 50000000
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 100
        assert weight_info['size_of_code_changes'] == 100

    def test_calculate_weight_sum(self):
        validation_data = {
            'messages': [
                {'id': ['MANIFEST_CSP']},
                {'id': ['UNSAFE_VAR_ASSIGNMENT']},
                {'id': ['NO_IMPLIED_EVAL']},
                {'id': ['DANGEROUS_EVAL']},
                {'id': ['UNSAFE_VAR_ASSIGNMENT']},  # Another one.
                {'id': ['NOTHING_TO_SEE_HERE_MOVE_ON']},
            ]
        }
        self.file_validation.update(validation=json.dumps(validation_data))
        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 205
        expected_result = {
            'abuse_reports': 0,
            'admin_code_review': 0,
            'average_daily_users': 0,
            'negative_ratings': 0,
            'reputation': 0,
            'past_rejection_history': 0,
            'uses_custom_csp': 90,
            'uses_eval_or_document_write': 50,
            'uses_implied_eval': 5,
            'uses_innerhtml': 60,  # There is one extra.
            'uses_native_messaging': 0,
            'size_of_code_changes': 0,
            'uses_remote_scripts': 0,
            'uses_unknown_minified_code': 0,
            'violates_mozilla_conditions': 0,
            'uses_coinminer': 0,
        }
        assert weight_info == expected_result

    def test_count_uses_custom_csp(self):
        assert AutoApprovalSummary.count_uses_custom_csp(self.version) == 0

        validation_data = {
            'messages': [{
                'id': ['MANIFEST_CSP'],
            }]
        }
        self.file_validation.update(validation=json.dumps(validation_data))
        assert AutoApprovalSummary.count_uses_custom_csp(self.version) == 1

    def test_count_uses_custom_csp_file_validation_missing(self):
        self.file_validation.delete()
        del self.version.all_files
        with self.assertRaises(AutoApprovalNoValidationResultError):
            AutoApprovalSummary.count_uses_custom_csp(self.version)

        # Also happens if only one file is missing validation info.
        self.file_validation = FileValidation.objects.create(
            file=self.version.all_files[0], validation=u'{}')
        del self.version.all_files
        file_factory(version=self.version, status=amo.STATUS_AWAITING_REVIEW)
        with self.assertRaises(AutoApprovalNoValidationResultError):
            AutoApprovalSummary.count_uses_custom_csp(self.version)

    def test_check_uses_native_messaging(self):
        assert (
            AutoApprovalSummary.check_uses_native_messaging(self.version) == 0)

        webext_permissions = WebextPermission.objects.create(
            file=self.file, permissions=['foobar'])
        del self.file.permissions
        assert (
            AutoApprovalSummary.check_uses_native_messaging(self.version) == 0)

        webext_permissions.update(permissions=['nativeMessaging', 'foobar'])
        del self.file.permissions
        assert (
            AutoApprovalSummary.check_uses_native_messaging(self.version) == 1)

    def test_calculate_weight_uses_coinminer(self):
        validation_data = {
            'messages': [{
                'id': ['COINMINER_USAGE_DETECTED'],
            }]
        }
        self.file_validation.update(validation=json.dumps(validation_data))
        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
        assert summary.weight_info == weight_info
        assert summary.weight == 2000
        assert weight_info['uses_coinminer'] == 2000

    def test_get_pretty_weight_info(self):
        summary = AutoApprovalSummary(version=self.version)
        assert summary.weight_info == {}
        pretty_weight_info = summary.get_pretty_weight_info()
        assert pretty_weight_info == ['Risk breakdown not available.']

        summary.weight_info = {
            'key1': 666,
            'key2': None,
            'key3': 0,
            'key4': -1,
        }
        pretty_weight_info = summary.get_pretty_weight_info()
        assert pretty_weight_info == ['key1: 666', 'key4: -1']

    def test_check_has_auto_approval_disabled(self):
        assert AutoApprovalSummary.check_has_auto_approval_disabled(
            self.version) is False

        flags = AddonReviewerFlags.objects.create(addon=self.addon)
        assert AutoApprovalSummary.check_has_auto_approval_disabled(
            self.version) is False

        flags.update(auto_approval_disabled=True)
        assert AutoApprovalSummary.check_has_auto_approval_disabled(
            self.version) is True

        # That flag only applies to listed.
        self.version.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        assert AutoApprovalSummary.check_has_auto_approval_disabled(
            self.version) is False

    def test_check_has_auto_approval_disabled_until_next_approval(self):
        assert AutoApprovalSummary.check_has_auto_approval_disabled(
            self.version) is False

        flags = AddonReviewerFlags.objects.create(addon=self.addon)
        assert AutoApprovalSummary.check_has_auto_approval_disabled(
            self.version) is False

        flags.update(auto_approval_disabled_until_next_approval=True)
        assert AutoApprovalSummary.check_has_auto_approval_disabled(
            self.version) is True

        # That flag only applies to listed.
        self.version.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        assert AutoApprovalSummary.check_has_auto_approval_disabled(
            self.version) is False

    def test_check_has_auto_approval_delayed_until(self):
        assert AutoApprovalSummary.check_has_auto_approval_disabled(
            self.version) is False

        flags = AddonReviewerFlags.objects.create(addon=self.addon)
        assert AutoApprovalSummary.check_has_auto_approval_disabled(
            self.version) is False

        past_date = datetime.now() - timedelta(hours=1)
        flags.update(auto_approval_delayed_until=past_date)
        assert AutoApprovalSummary.check_has_auto_approval_disabled(
            self.version) is False

        future_date = datetime.now() + timedelta(hours=1)
        flags.update(auto_approval_delayed_until=future_date)
        assert AutoApprovalSummary.check_has_auto_approval_disabled(
            self.version) is True

        # *That* flag applies to both listed and unlisted.
        self.version.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        assert AutoApprovalSummary.check_has_auto_approval_disabled(
            self.version) is True

    def test_check_is_promoted_prereview(self):
        assert AutoApprovalSummary.check_is_promoted_prereview(
            self.version) is False

        promoted = PromotedAddon.objects.create(addon=self.addon)
        assert AutoApprovalSummary.check_is_promoted_prereview(
            self.version) is False

        promoted.update(group_id=RECOMMENDED.id)
        assert AutoApprovalSummary.check_is_promoted_prereview(
            self.version) is True

        promoted.update(group_id=STRATEGIC.id)  # STRATEGIC isn't prereview
        assert AutoApprovalSummary.check_is_promoted_prereview(
            self.version) is False

        promoted.update(group_id=LINE.id)  # LINE is though
        assert AutoApprovalSummary.check_is_promoted_prereview(
            self.version) is True

    def test_check_should_be_delayed(self):
        assert AutoApprovalSummary.check_should_be_delayed(
            self.version) is False

        # Delete current_version, making self.version the first listed version
        # submitted and add-on creation date recent.
        self.addon.current_version.delete()
        self.addon.update(created=datetime.now())
        self.addon.update_status()

        # First test with somehow no nomination date at all. The add-on
        # creation date is used as a fallback, and it was created recently
        # so it should be delayed.
        assert self.version.nomination is None
        assert AutoApprovalSummary.check_should_be_delayed(
            self.version) is True

        # Still using the add-on creation date as fallback, if it's old enough
        # it should not be delayed.
        self.addon.update(created=self.days_ago(2))
        assert AutoApprovalSummary.check_should_be_delayed(
            self.version) is False

        # Now add a recent nomination date. It should be delayed.
        self.version.update(nomination=datetime.now() - timedelta(hours=22))
        assert AutoApprovalSummary.check_should_be_delayed(
            self.version) is True

        # Update nomination date in the past, it should no longer be delayed.
        self.version.update(nomination=self.days_ago(2))
        assert AutoApprovalSummary.check_should_be_delayed(
            self.version) is False

        # Unlisted shouldn't be affected.
        self.version.update(
            nomination=datetime.now() - timedelta(hours=22),
            channel=amo.RELEASE_CHANNEL_UNLISTED)
        assert AutoApprovalSummary.check_has_auto_approval_disabled(
            self.version) is False

    def test_check_should_be_delayed_only_until_first_content_review(self):
        assert AutoApprovalSummary.check_should_be_delayed(
            self.version) is False

        # Delete current_version, making self.version the first listed version
        # submitted and add-on creation date recent.
        self.addon.current_version.delete()
        self.addon.update(created=datetime.now())
        self.addon.update_status()

        # Also remove AddonApprovalsCounter to start fresh.
        self.addon.addonapprovalscounter.delete()

        # Set a recent nomination date. It should be delayed.
        self.version.update(nomination=datetime.now() - timedelta(hours=12))
        assert AutoApprovalSummary.check_should_be_delayed(
            self.version) is True

        # Add AddonApprovalsCounter with default values, it should still be
        # delayed.
        self.addon.addonapprovalscounter = (
            AddonApprovalsCounter.objects.create(addon=self.addon))
        assert self.addon.addonapprovalscounter.last_content_review is None
        assert AutoApprovalSummary.check_should_be_delayed(
            self.version) is True

        # Once there is a content review, it should no longer be delayed.
        self.addon.addonapprovalscounter.update(
            last_content_review=datetime.now())
        assert AutoApprovalSummary.check_should_be_delayed(
            self.version) is False

    def test_check_should_be_delayed_langpacks_are_exempted(self):
        self.addon.update(type=amo.ADDON_LPAPP)
        assert AutoApprovalSummary.check_should_be_delayed(
            self.version) is False

        # Delete current_version, making self.version the first listed version
        # submitted and add-on creation date recent.
        self.addon.current_version.delete()
        self.addon.update(created=datetime.now())
        self.addon.update_status()

        assert self.version.nomination is None
        assert AutoApprovalSummary.check_should_be_delayed(
            self.version) is False
        self.addon.update(created=self.days_ago(2))
        assert AutoApprovalSummary.check_should_be_delayed(
            self.version) is False
        self.version.update(nomination=datetime.now() - timedelta(hours=22))
        assert AutoApprovalSummary.check_should_be_delayed(
            self.version) is False
        self.version.update(nomination=self.days_ago(2))
        assert AutoApprovalSummary.check_should_be_delayed(
            self.version) is False

    def test_check_is_blocked(self):
        assert AutoApprovalSummary.check_is_blocked(self.version) is False

        block = Block.objects.create(
            addon=self.addon, updated_by=user_factory())
        del self.version.addon.block
        assert AutoApprovalSummary.check_is_blocked(self.version) is True

        block.update(min_version='9999999')
        del self.version.addon.block
        assert AutoApprovalSummary.check_is_blocked(self.version) is False

        block.update(min_version='0')
        del self.version.addon.block
        assert AutoApprovalSummary.check_is_blocked(self.version) is True

    def test_check_is_locked(self):
        assert AutoApprovalSummary.check_is_locked(self.version) is False

        set_reviewing_cache(self.version.addon.pk, settings.TASK_USER_ID)
        assert AutoApprovalSummary.check_is_locked(self.version) is False

        set_reviewing_cache(self.version.addon.pk, settings.TASK_USER_ID + 42)
        assert AutoApprovalSummary.check_is_locked(self.version) is True

        # Langpacks are never considered locked.
        self.addon.update(type=amo.ADDON_LPAPP)
        assert AutoApprovalSummary.check_is_locked(self.version) is False

    @mock.patch.object(AutoApprovalSummary, 'calculate_weight', spec=True)
    @mock.patch.object(AutoApprovalSummary, 'calculate_verdict', spec=True)
    def test_create_summary_for_version(
            self, calculate_verdict_mock, calculate_weight_mock):
        def create_dynamic_patch(name):
            patcher = mock.patch.object(
                AutoApprovalSummary, name,
                spec=getattr(AutoApprovalSummary, name))
            thing = patcher.start()
            thing.return_value = False
            self.addCleanup(patcher.stop)
            return thing

        calculate_verdict_mock.return_value = {'dummy_verdict': True}
        dynamic_mocks = [
            create_dynamic_patch(f'check_{field}')
            for field in AutoApprovalSummary.auto_approval_verdict_fields]

        summary, info = AutoApprovalSummary.create_summary_for_version(
            self.version,)

        for mocked_method in dynamic_mocks:
            assert mocked_method.call_count == 1
            mocked_method.assert_called_with(self.version)
        assert calculate_weight_mock.call_count == 1
        assert calculate_verdict_mock.call_count == 1
        assert calculate_verdict_mock.call_args == ({
            'dry_run': False,
        },)
        assert summary.pk
        assert summary.version == self.version
        assert info == {'dummy_verdict': True}

    @mock.patch.object(AutoApprovalSummary, 'calculate_verdict', spec=True)
    def test_create_summary_no_previously_approved_versions(
            self, calculate_verdict_mock):
        AddonApprovalsCounter.objects.all().delete()
        self.version.reload()
        calculate_verdict_mock.return_value = {'dummy_verdict': True}
        summary, info = AutoApprovalSummary.create_summary_for_version(
            self.version)
        assert summary.pk
        assert info == {'dummy_verdict': True}

    def test_create_summary_already_existing(self):
        # Create a dummy summary manually, then call the method to create a
        # real one. It should have just updated the previous instance.
        summary = AutoApprovalSummary.objects.create(
            version=self.version, is_locked=True)
        assert summary.pk
        assert summary.version == self.version
        assert summary.verdict == amo.NOT_AUTO_APPROVED

        previous_summary_pk = summary.pk

        summary, info = AutoApprovalSummary.create_summary_for_version(
            self.version)

        assert summary.pk == previous_summary_pk
        assert summary.version == self.version
        assert summary.is_locked is False
        assert summary.verdict == amo.AUTO_APPROVED
        assert info == {
            'has_auto_approval_disabled': False,
            'is_locked': False,
            'is_promoted_prereview': False,
            'should_be_delayed': False,
            'is_blocked': False,
        }

    def test_create_summary_no_files(self):
        self.file.delete()
        del self.version.all_files
        with self.assertRaises(AutoApprovalNotEnoughFilesError):
            AutoApprovalSummary.create_summary_for_version(self.version)

    def test_calculate_verdict_failure_dry_run(self):
        summary = AutoApprovalSummary.objects.create(
            version=self.version, is_locked=True)
        info = summary.calculate_verdict(dry_run=True)
        assert info == {
            'has_auto_approval_disabled': False,
            'is_locked': True,
            'is_promoted_prereview': False,
            'should_be_delayed': False,
            'is_blocked': False,
        }
        assert summary.verdict == amo.WOULD_NOT_HAVE_BEEN_AUTO_APPROVED

    def test_calculate_verdict_failure(self):
        summary = AutoApprovalSummary.objects.create(
            version=self.version, is_locked=True)
        info = summary.calculate_verdict()
        assert info == {
            'has_auto_approval_disabled': False,
            'is_locked': True,
            'is_promoted_prereview': False,
            'should_be_delayed': False,
            'is_blocked': False,
        }
        assert summary.verdict == amo.NOT_AUTO_APPROVED

    def test_calculate_verdict_success(self):
        summary = AutoApprovalSummary.objects.create(version=self.version)
        info = summary.calculate_verdict()
        assert info == {
            'has_auto_approval_disabled': False,
            'is_locked': False,
            'is_promoted_prereview': False,
            'should_be_delayed': False,
            'is_blocked': False,
        }
        assert summary.verdict == amo.AUTO_APPROVED

    def test_calculate_verdict_success_dry_run(self):
        summary = AutoApprovalSummary.objects.create(version=self.version)
        info = summary.calculate_verdict(dry_run=True)
        assert info == {
            'has_auto_approval_disabled': False,
            'is_locked': False,
            'is_promoted_prereview': False,
            'should_be_delayed': False,
            'is_blocked': False,
        }
        assert summary.verdict == amo.WOULD_HAVE_BEEN_AUTO_APPROVED

    def test_calculate_verdict_has_auto_approval_disabled(self):
        summary = AutoApprovalSummary.objects.create(
            version=self.version, has_auto_approval_disabled=True)
        info = summary.calculate_verdict()
        assert info == {
            'has_auto_approval_disabled': True,
            'is_locked': False,
            'is_promoted_prereview': False,
            'should_be_delayed': False,
            'is_blocked': False,
        }
        assert summary.verdict == amo.NOT_AUTO_APPROVED

    def test_calculate_verdict_is_promoted_prereview(self):
        summary = AutoApprovalSummary.objects.create(
            version=self.version, is_promoted_prereview=True)
        info = summary.calculate_verdict()
        assert info == {
            'has_auto_approval_disabled': False,
            'is_locked': False,
            'is_promoted_prereview': True,
            'should_be_delayed': False,
            'is_blocked': False,
        }
        assert summary.verdict == amo.NOT_AUTO_APPROVED

    def test_calculate_verdict_is_blocked(self):
        summary = AutoApprovalSummary.objects.create(
            version=self.version, is_blocked=True)
        info = summary.calculate_verdict()
        assert info == {
            'has_auto_approval_disabled': False,
            'is_locked': False,
            'is_promoted_prereview': False,
            'should_be_delayed': False,
            'is_blocked': True,
        }
        assert summary.verdict == amo.NOT_AUTO_APPROVED

    def test_calculate_verdict_should_be_delayed(self):
        summary = AutoApprovalSummary.objects.create(
            version=self.version, should_be_delayed=True)
        info = summary.calculate_verdict()
        assert info == {
            'has_auto_approval_disabled': False,
            'is_locked': False,
            'is_promoted_prereview': False,
            'should_be_delayed': True,
            'is_blocked': False,
        }
        assert summary.verdict == amo.NOT_AUTO_APPROVED

    def test_verdict_info_prettifier(self):
        verdict_info = {
            'has_auto_approval_disabled': True,
            'is_locked': True,
            'is_promoted_prereview': True,
            'should_be_delayed': True,
            'is_blocked': True,
        }
        result = list(
            AutoApprovalSummary.verdict_info_prettifier(verdict_info))
        assert result == [
            'Has auto-approval disabled/delayed flag set',
            'Version string and guid match a blocklist Block',
            'Is locked by a reviewer',
            'Is in a promoted addon group that requires pre-review',
            "Delayed because it's the first listed version",
        ]

        result = list(AutoApprovalSummary.verdict_info_prettifier({}))
        assert result == []


class TestCannedResponse(TestCase):

    def test_basic(self):
        response = CannedResponse.objects.create(
            name=u'Terms of services',
            response=u'test',
            category=amo.CANNED_RESPONSE_CATEGORY_OTHER,
            type=amo.CANNED_RESPONSE_TYPE_ADDON)

        assert response.name == u'Terms of services'
        assert response.response == u'test'
        assert response.category == amo.CANNED_RESPONSE_CATEGORY_OTHER
        assert response.type == amo.CANNED_RESPONSE_TYPE_ADDON

    def test_category_default(self):
        response = CannedResponse.objects.create(
            name=u'Terms of services',
            response=u'test',
            type=amo.CANNED_RESPONSE_TYPE_ADDON)

        assert response.category == amo.CANNED_RESPONSE_CATEGORY_OTHER
