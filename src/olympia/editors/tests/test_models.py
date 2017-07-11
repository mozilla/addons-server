# -*- coding: utf-8 -*-
from datetime import datetime, timedelta
import json
import mock
import time

from django.conf import settings
from django.core import mail

from olympia import amo
from olympia.abuse.models import AbuseReport
from olympia.access.models import Group, GroupUser
from olympia.activity.models import ActivityLog
from olympia.amo.tests import TestCase
from olympia.amo.tests import (
    addon_factory, file_factory, user_factory, version_factory)
from olympia.addons.models import Addon, AddonApprovalsCounter, AddonUser
from olympia.files.models import FileValidation
from olympia.reviews.models import Review
from olympia.versions.models import (
    Version, version_uploaded)
from olympia.files.models import File, WebextPermission
from olympia.editors.models import (
    AutoApprovalNotEnoughFilesError, AutoApprovalNoValidationResultError,
    AutoApprovalSummary, EditorSubscription, RereviewQueueTheme, ReviewerScore,
    send_notifications, set_reviewing_cache, ViewFullReviewQueue,
    ViewPendingQueue, ViewUnlistedAllList)
from olympia.users.models import UserProfile


def create_search_ext(name, version_str, addon_status, file_status,
                      channel):
    addon, created_ = Addon.objects.get_or_create(
        name__localized_string=name,
        defaults={'type': amo.ADDON_SEARCH, 'name': name})
    version, created_ = Version.objects.get_or_create(
        addon=addon, version=version_str, defaults={'channel': channel})
    File.objects.create(version=version, filename=u"%s.xpi" % name,
                        platform=amo.PLATFORM_ALL.id, status=file_status)
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
        v1.all_files[0].update(status=amo.STATUS_PUBLIC)
        version_factory(addon=addon, version='2.0', created=self.days_ago(1),
                        channel=self.channel,
                        file_kw={'status': amo.STATUS_PUBLIC})
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


class TestPendingQueue(TestQueue):
    __test__ = True
    Queue = ViewPendingQueue
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
        return create_search_ext(name, version,
                                 amo.STATUS_PUBLIC, amo.STATUS_AWAITING_REVIEW,
                                 channel=self.channel, **kw)

    def test_waiting_time(self):
        self.new_addon()
        Version.objects.update(created=datetime.utcnow())
        row = self.Queue.objects.all()[0]
        assert row.waiting_time_days == 0
        # Time zone will be off, hard to test this.
        assert row.waiting_time_hours is not None

    def test_flags_admin_review(self):
        self.new_addon().update(admin_review=True)

        q = self.Queue.objects.get()
        assert q.flags == [('admin-review', 'Admin Review')]

    def test_flags_info_request(self):
        self.new_addon().find_latest_version(self.channel).update(
            has_info_request=True)
        q = self.Queue.objects.get()
        assert q.flags == [('info', 'More Information Requested')]

    def test_flags_editor_comment(self):
        self.new_addon().find_latest_version(self.channel).update(
            has_editor_comment=True)

        q = self.Queue.objects.get()
        assert q.flags == [('editor', 'Contains Reviewer Comment')]

    def test_flags_jetpack(self):
        self.new_addon().find_latest_version(self.channel).all_files[0].update(
            jetpack_version='1.8')

        q = self.Queue.objects.get()
        assert q.flags == [('jetpack', 'Jetpack Add-on')]

    def test_flags_is_restart_required(self):
        self.new_addon().find_latest_version(self.channel).all_files[0].update(
            is_restart_required=True)

        q = self.Queue.objects.get()
        assert q.flags == [('is_restart_required', 'Requires Restart')]

    def test_flags_sources_provided(self):
        self.new_addon().find_latest_version(self.channel).update(
            source='/some/source/file')

        q = self.Queue.objects.get()
        assert q.flags == [('sources-provided', 'Sources provided')]

    def test_flags_webextension(self):
        self.new_addon().find_latest_version(self.channel).all_files[0].update(
            is_webextension=True)

        queue = self.Queue.objects.get()
        assert queue.flags == [('webextension', 'WebExtension')]

    def test_no_flags(self):
        self.new_addon()

        q = self.Queue.objects.get()
        assert q.flags == []


class TestFullReviewQueue(TestQueue):
    __test__ = True
    Queue = ViewFullReviewQueue
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


class TestUnlistedAllList(TestCase):
    Queue = ViewUnlistedAllList
    channel = amo.RELEASE_CHANNEL_UNLISTED
    fixtures = ['base/users']

    def new_addon(self, name=u'Unlisted', version=u'1.0',
                  addon_status=amo.STATUS_NULL,
                  file_status=amo.STATUS_PUBLIC):
        addon = addon_factory(
            name=name, status=addon_status,
            version_kw={'version': version, 'channel': self.channel},
            file_kw={'status': file_status})
        return addon

    def test_all_addons_are_in_q(self):
        self.new_addon('Public', addon_status=amo.STATUS_PUBLIC,
                       file_status=amo.STATUS_PUBLIC)
        self.new_addon('Nominated', addon_status=amo.STATUS_NOMINATED,
                       file_status=amo.STATUS_AWAITING_REVIEW)
        self.new_addon('Deleted', addon_status=amo.STATUS_PUBLIC,
                       file_status=amo.STATUS_PUBLIC).delete()
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

    def test_last_reviewed_version(self):
        today = datetime.today().date()
        addon = self.new_addon(version='1.0')
        v2 = version_factory(addon=addon, version='2.0', channel=self.channel)
        log = ActivityLog.create(amo.LOG.APPROVE_VERSION, v2, v2.addon,
                                 user=UserProfile.objects.get(pk=999))
        version_factory(addon=addon, version='3.0', channel=self.channel)
        row = self.Queue.objects.all()[0]
        assert row.review_date == today
        assert row.review_version_num == '2.0'
        assert row.review_log_id == log.id

    def test_no_developer_actions(self):
        addon = self.new_addon(version='1.0')
        ActivityLog.create(amo.LOG.ADD_VERSION, addon.latest_unlisted_version,
                           addon, user=UserProfile.objects.get(pk=999))
        row = self.Queue.objects.all()[0]
        assert row.review_version_num is None

        ver2 = version_factory(version='2.0', addon=addon,
                               channel=self.channel)
        ActivityLog.create(amo.LOG.APPROVE_VERSION, ver2, addon,
                           user=UserProfile.objects.get(pk=999))
        row = self.Queue.objects.all()[0]
        assert row.review_version_num == '2.0'

        ver3 = version_factory(version='3.0', addon=addon,
                               channel=self.channel)
        ActivityLog.create(amo.LOG.EDIT_VERSION, ver3, addon,
                           user=UserProfile.objects.get(pk=999))
        row = self.Queue.objects.all()[0]
        # v2.0 is still the last reviewed version.
        assert row.review_version_num == '2.0'

    def test_no_automatic_reviews(self):
        ver = self.new_addon(
            name='addon789', version='1.0').latest_unlisted_version
        ActivityLog.create(
            amo.LOG.APPROVE_VERSION, ver, ver.addon,
            user=UserProfile.objects.get(pk=settings.TASK_USER_ID))
        row = self.Queue.objects.all()[0]
        assert row.review_version_num is None

    def test_latest_version(self):
        addon = addon_factory(
            version_kw={'version': u'0.1', 'channel': self.channel,
                        'created': self.days_ago(2)},
            file_kw={'created': self.days_ago(2)})
        version_factory(
            addon=addon, version=u'0.2', channel=self.channel,
            created=self.days_ago(1), file_kw={'created': self.days_ago(1)})
        version_factory(
            addon=addon, version=u'0.3', channel=self.channel)
        row = self.Queue.objects.get()
        assert row.latest_version == '0.3'

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
            file_kw={'status': amo.STATUS_PUBLIC})
        version_factory(addon=unlisted_listed, version=u'0.2',
                        channel=amo.RELEASE_CHANNEL_LISTED,
                        file_kw={'status': amo.STATUS_PUBLIC})

        listed_unlisted = addon_factory(
            status=amo.STATUS_NULL, name=u'ListedUnlisted',
            version_kw={'version': u'0.1',
                        'channel': amo.RELEASE_CHANNEL_LISTED},
            file_kw={'status': amo.STATUS_PUBLIC})
        version_factory(addon=listed_unlisted, version=u'0.2',
                        channel=amo.RELEASE_CHANNEL_UNLISTED,
                        file_kw={'status': amo.STATUS_PUBLIC})

        just_unlisted = addon_factory(
            status=amo.STATUS_NULL, name=u'JustUnlisted',
            version_kw={'version': u'0.1',
                        'channel': amo.RELEASE_CHANNEL_UNLISTED},
            file_kw={'status': amo.STATUS_PUBLIC})
        version_factory(addon=just_unlisted, version=u'0.2',
                        channel=amo.RELEASE_CHANNEL_UNLISTED,
                        file_kw={'status': amo.STATUS_PUBLIC})

        just_listed = addon_factory(
            status=amo.STATUS_NULL, name=u'JustListed',
            version_kw={'version': u'0.1',
                        'channel': amo.RELEASE_CHANNEL_LISTED},
            file_kw={'status': amo.STATUS_PUBLIC})
        version_factory(addon=just_listed, version=u'0.2',
                        channel=amo.RELEASE_CHANNEL_LISTED,
                        file_kw={'status': amo.STATUS_PUBLIC})

        assert self.Queue.objects.all().count() == 3
        assert [addon.addon_name for addon in self.Queue.objects.all()] == [
            'UnlistedListed', 'ListedUnlisted', 'JustUnlisted']
        assert ([addon.latest_version for addon in self.Queue.objects.all()] ==
                ['0.1', '0.2', '0.2'])


class TestEditorSubscription(TestCase):
    fixtures = ['base/addon_3615', 'base/users']

    def setUp(self):
        super(TestEditorSubscription, self).setUp()
        self.addon = Addon.objects.get(pk=3615)
        self.version = self.addon.current_version
        self.user_one = UserProfile.objects.get(pk=55021)
        self.user_two = UserProfile.objects.get(pk=999)
        self.editor_group = Group.objects.create(
            name='editors', rules='Addons:Review')
        for user in [self.user_one, self.user_two]:
            EditorSubscription.objects.create(addon=self.addon, user=user)
            GroupUser.objects.create(group=self.editor_group, user=user)

    def test_email(self):
        es = EditorSubscription.objects.get(user=self.user_one)
        es.send_notification(self.version)
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == [u'del@icio.us']
        assert mail.outbox[0].subject == (
            'Mozilla Add-ons: Delicious Bookmarks Updated')

    def test_notifications(self):
        send_notifications(sender=self.version)
        assert len(mail.outbox) == 2
        emails = sorted([o.to for o in mail.outbox])
        assert emails == [[u'del@icio.us'], [u'regular@mozilla.com']]

    def test_notifications_clean(self):
        send_notifications(Version, self.version)
        assert EditorSubscription.objects.count() == 0
        mail.outbox = []
        send_notifications(Version, self.version)
        assert len(mail.outbox) == 0

    def test_notifications_beta(self):
        self.version.all_files[0].update(status=amo.STATUS_BETA)
        version_uploaded.send(sender=self.version)
        assert len(mail.outbox) == 0

    def test_signal_edit(self):
        self.version.save()
        assert len(mail.outbox) == 0

    def test_signal_create(self):
        v = Version.objects.create(addon=self.addon)
        version_uploaded.send(sender=v)
        assert len(mail.outbox) == 2
        assert mail.outbox[0].subject == (
            'Mozilla Add-ons: Delicious Bookmarks Updated')

    def test_signal_create_twice(self):
        v = Version.objects.create(addon=self.addon)
        version_uploaded.send(sender=v)
        mail.outbox = []
        v = Version.objects.create(addon=self.addon)
        version_uploaded.send(sender=v)
        assert len(mail.outbox) == 0

    def test_no_email_for_ex_editors(self):
        self.user_one.delete()
        # Remove user_two from editors.
        GroupUser.objects.get(
            group=self.editor_group, user=self.user_two).delete()
        send_notifications(sender=self.version)
        assert len(mail.outbox) == 0

    def test_no_email_address_for_editor(self):
        self.user_one.update(email=None)
        send_notifications(sender=self.version)
        assert len(mail.outbox) == 1


class TestReviewerScore(TestCase):
    fixtures = ['base/users']

    def setUp(self):
        super(TestReviewerScore, self).setUp()
        self.addon = amo.tests.addon_factory(status=amo.STATUS_NOMINATED)
        self.user = UserProfile.objects.get(email='editor@mozilla.com')

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
            amo.ADDON_THEME: 'THEME',
            amo.ADDON_DICT: 'DICT',
            amo.ADDON_SEARCH: 'SEARCH',
            amo.ADDON_LPAPP: 'LP',
            amo.ADDON_LPADDON: 'LP',
            amo.ADDON_PLUGIN: 'ADDON',
            amo.ADDON_API: 'ADDON',
            amo.ADDON_PERSONA: 'PERSONA',
        }
        statuses = {
            amo.STATUS_NULL: None,
            amo.STATUS_PENDING: None,
            amo.STATUS_NOMINATED: 'FULL',
            amo.STATUS_PUBLIC: 'UPDATE',
            amo.STATUS_DISABLED: None,
            amo.STATUS_BETA: None,
            amo.STATUS_DELETED: None,
            amo.STATUS_REJECTED: None,
            amo.STATUS_REVIEW_PENDING: None,
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

    def test_award_points(self):
        self._give_points()
        assert ReviewerScore.objects.all()[0].score == (
            amo.REVIEWED_SCORES[amo.REVIEWED_ADDON_FULL])

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

    def test_award_moderation_points(self):
        ReviewerScore.award_moderation_points(self.user, self.addon, 1)
        score = ReviewerScore.objects.all()[0]
        assert score.score == (
            amo.REVIEWED_SCORES.get(amo.REVIEWED_ADDON_REVIEW))
        assert score.note_key == amo.REVIEWED_ADDON_REVIEW

    def test_get_total(self):
        user2 = UserProfile.objects.get(email='admin@mozilla.com')
        self._give_points()
        self._give_points(status=amo.STATUS_PUBLIC)
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
        self._give_points(status=amo.STATUS_PUBLIC)
        self._give_points(user=user2)
        scores = ReviewerScore.get_recent(self.user)
        assert len(scores) == 2
        assert scores[0].score == (
            amo.REVIEWED_SCORES[amo.REVIEWED_ADDON_UPDATE])
        assert scores[1].score == (
            amo.REVIEWED_SCORES[amo.REVIEWED_ADDON_FULL])

    def test_get_leaderboards(self):
        user2 = UserProfile.objects.get(email='persona-reviewer@mozilla.com')
        self._give_points()
        self._give_points(status=amo.STATUS_PUBLIC)
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
            user=user2, addon=amo.tests.addon_factory(type=amo.ADDON_PERSONA))
        leaders = ReviewerScore.get_leaderboards(
            self.user, addon_type=amo.ADDON_PERSONA)
        assert len(leaders['leader_top']) == 1
        assert leaders['leader_top'][0]['user_id'] == user2.id

    def test_only_active_reviewers_in_leaderboards(self):
        user2 = UserProfile.objects.create(username='former-reviewer')
        self._give_points()
        self._give_points(status=amo.STATUS_PUBLIC)
        self._give_points(user=user2, status=amo.STATUS_NOMINATED)
        leaders = ReviewerScore.get_leaderboards(self.user)
        assert leaders['user_rank'] == 1
        assert leaders['leader_near'] == []
        assert leaders['leader_top'][0]['user_id'] == self.user.id
        assert len(leaders['leader_top']) == 1  # Only the editor is here.
        assert user2.id not in [l['user_id'] for l in leaders['leader_top']], (
            'Unexpected non-reviewer user found in leaderboards.')

    def test_no_admins_or_staff_in_leaderboards(self):
        user2 = UserProfile.objects.get(email='admin@mozilla.com')
        self._give_points()
        self._give_points(status=amo.STATUS_PUBLIC)
        self._give_points(user=user2, status=amo.STATUS_NOMINATED)
        leaders = ReviewerScore.get_leaderboards(self.user)
        assert leaders['user_rank'] == 1
        assert leaders['leader_near'] == []
        assert leaders['leader_top'][0]['user_id'] == self.user.id
        assert len(leaders['leader_top']) == 1  # Only the editor is here.
        assert user2.id not in [l['user_id'] for l in leaders['leader_top']], (
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
        # Last user gets lower points by reviewing a persona.
        addon = self.addon
        addon.type = amo.ADDON_PERSONA
        self._give_points(user=last_user, addon=addon)
        leaders = ReviewerScore.get_leaderboards(last_user)
        assert leaders['user_rank'] == 6
        assert len(leaders['leader_top']) == 3
        assert len(leaders['leader_near']) == 2

    def test_all_users_by_score(self):
        user2 = UserProfile.objects.get(email='senioreditor@mozilla.com')
        amo.REVIEWED_LEVELS[0]['points'] = 180
        self._give_points()
        self._give_points(status=amo.STATUS_PUBLIC)
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

        with self.assertNumQueries(1):
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
        with self.assertNumQueries(1):
            ReviewerScore.get_leaderboards(self.user)
        with self.assertNumQueries(1):
            ReviewerScore.get_breakdown(self.user)


class TestRereviewQueueTheme(TestCase):

    def test_manager_soft_delete_addons(self):
        """Test manager excludes soft delete add-ons."""
        # Normal RQT object.
        RereviewQueueTheme.objects.create(
            theme=addon_factory(type=amo.ADDON_PERSONA).persona, header='',
            footer='')

        # Deleted add-on RQT object.
        addon = addon_factory(type=amo.ADDON_PERSONA)
        RereviewQueueTheme.objects.create(
            theme=addon.persona, header='', footer='')
        addon.delete()

        assert RereviewQueueTheme.objects.count() == 1
        assert RereviewQueueTheme.unfiltered.count() == 2

    def test_footer_path_without_footer(self):
        rqt = RereviewQueueTheme.objects.create(
            theme=addon_factory(type=amo.ADDON_PERSONA).persona, header='',
            footer='')
        assert rqt.footer_path == ''

    def test_footer_url_without_footer(self):
        rqt = RereviewQueueTheme.objects.create(
            theme=addon_factory(type=amo.ADDON_PERSONA).persona, header='',
            footer='')
        assert rqt.footer_url == ''

    def test_filter_for_many_to_many(self):
        # Check https://bugzilla.mozilla.org/show_bug.cgi?id=1142035.
        addon = addon_factory(type=amo.ADDON_PERSONA)
        rqt = RereviewQueueTheme.objects.create(theme=addon.persona)
        assert addon.persona.rereviewqueuetheme_set.get() == rqt

        # Delete the addon: it shouldn't be listed anymore.
        addon.update(status=amo.STATUS_DELETED)
        assert addon.persona.rereviewqueuetheme_set.all().count() == 0


class TestAutoApprovalSummary(TestCase):
    def setUp(self):
        self.addon = addon_factory(average_daily_users=666)
        self.version = version_factory(
            addon=self.addon, file_kw={
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
        weight_info = summary.calculate_weight()
        expected_result = {
            'abuse_reports': 0,
            'admin_review': 0,
            'average_daily_users': 0,
            'negative_reviews': 0,
            'reputation': 0,
            'past_rejection_history': 0,
            'uses_custom_csp': 0,
            'uses_eval_or_document_write': 0,
            'uses_implied_eval': 0,
            'uses_innerhtml': 0,
            'uses_native_messaging': 0
        }
        assert weight_info == expected_result

    def test_calculate_weight_admin_review(self):
        self.addon.update(admin_review=True)
        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
        assert summary.weight == 100
        assert weight_info['admin_review'] == 100

    def test_calculate_weight_abuse_reports(self):
        # Extra abuse report for a different add-on, does not count.
        AbuseReport.objects.create(addon=addon_factory())

        # Extra abuse report for a different user, does not count.
        AbuseReport.objects.create(user=user_factory())

        # Extra old abuse report, does not count either.
        old_report = AbuseReport.objects.create(addon=self.addon)
        old_report.update(created=self.days_ago(370))

        # Recent abuse reports.
        AbuseReport.objects.create(addon=self.addon)
        AbuseReport.objects.create(addon=self.addon)

        # Recent abuse report for one of the developers of the add-on.
        author = user_factory()
        AddonUser.objects.create(addon=self.addon, user=author)
        AbuseReport.objects.create(user=author)

        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
        assert summary.weight == 30
        assert weight_info['abuse_reports'] == 30

        # Should be capped at 100.
        for i in range(0, 10):
            AbuseReport.objects.create(addon=self.addon)
        weight_info = summary.calculate_weight()
        assert summary.weight == 100
        assert weight_info['abuse_reports'] == 100

    def test_calculate_weight_abuse_reports_use_created_from_instance(self):
        # Create an abuse report 400 days in the past. It should be ignored it
        # we were calculating from today, but use an AutoApprovalSummary
        # instance that is 40 days old, making the abuse report count.
        report = AbuseReport.objects.create(addon=self.addon)
        report.update(created=self.days_ago(400))

        summary = AutoApprovalSummary.objects.create(version=self.version)
        summary.update(created=self.days_ago(40))

        weight_info = summary.calculate_weight()
        assert summary.weight == 10
        assert weight_info['abuse_reports'] == 10

    def test_calculate_weight_negative_reviews(self):
        # Positive review, does not count.
        Review.objects.create(
            user=user_factory(), addon=self.addon, version=self.version,
            rating=5)

        # Negative review, but too old, does not count.
        old_review = Review.objects.create(
            user=user_factory(), addon=self.addon, version=self.version,
            rating=1)
        old_review.update(created=self.days_ago(370))

        # Negative review on a different add-on, does not count either.
        extra_addon = addon_factory()
        Review.objects.create(
            user=user_factory(), addon=extra_addon,
            version=extra_addon.current_version, rating=1)

        # Recent negative reviews.
        reviews = [Review(
            user=user_factory(), addon=self.addon,
            version=self.version, rating=3) for i in range(0, 49)]
        Review.objects.bulk_create(reviews)
        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
        assert summary.weight == 0  # Not enough negative reviews yet...
        assert weight_info['negative_reviews'] == 0

        # Create one more to get to weight == 1.
        Review.objects.create(
            user=user_factory(), addon=self.addon, version=self.version,
            rating=2)
        weight_info = summary.calculate_weight()
        assert summary.weight == 1
        assert weight_info['negative_reviews'] == 1

        # Create 5000 more (sorry!) to make sure it's capped at 100.
        reviews = [Review(
            user=user_factory(), addon=self.addon,
            version=self.version, rating=3) for i in range(0, 5000)]
        Review.objects.bulk_create(reviews)

        weight_info = summary.calculate_weight()
        assert summary.weight == 100
        assert weight_info['negative_reviews'] == 100

    def test_calculate_weight_reputation(self):
        summary = AutoApprovalSummary(version=self.version)
        self.addon.update(reputation=0)
        weight_info = summary.calculate_weight()
        assert summary.weight == 0
        assert weight_info['reputation'] == 0

        self.addon.update(reputation=3)
        weight_info = summary.calculate_weight()
        assert summary.weight == -300
        assert weight_info['reputation'] == -300

        self.addon.update(reputation=1000)
        weight_info = summary.calculate_weight()
        assert summary.weight == -300
        assert weight_info['reputation'] == -300

        self.addon.update(reputation=-1000)
        weight_info = summary.calculate_weight()
        assert summary.weight == 0
        assert weight_info['reputation'] == 0

    def test_calculate_weight_average_daily_users(self):
        self.addon.update(average_daily_users=142444)
        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
        assert summary.weight == 14
        assert weight_info['average_daily_users'] == 14

        self.addon.update(average_daily_users=1756567658)
        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
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
                     'original_status': amo.STATUS_PUBLIC})

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
        version_factory(
            addon=self.addon,
            file_kw={'reviewed': self.days_ago(11)})

        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
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
        assert summary.weight == 20
        assert weight_info['uses_eval_or_document_write'] == 20

        validation_data = {
            'messages': [{
                'id': ['NO_DOCUMENT_WRITE'],
            }]
        }
        self.file_validation.update(validation=json.dumps(validation_data))
        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
        assert summary.weight == 20
        assert weight_info['uses_eval_or_document_write'] == 20

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
        assert summary.weight == 20
        assert weight_info['uses_eval_or_document_write'] == 20

    def test_calculate_weight_uses_implied_eval(self):
        validation_data = {
            'messages': [{
                'id': ['NO_IMPLIED_EVAL'],
            }]
        }
        self.file_validation.update(validation=json.dumps(validation_data))
        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
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
        assert summary.weight == 20
        assert weight_info['uses_innerhtml'] == 20

    def test_calculate_weight_uses_custom_csp(self):
        validation_data = {
            'messages': [{
                'id': ['MANIFEST_CSP'],
            }]
        }
        self.file_validation.update(validation=json.dumps(validation_data))
        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
        assert summary.weight == 30
        assert weight_info['uses_custom_csp'] == 30

    def test_calculate_weight_uses_native_messaging(self):
        WebextPermission.objects.create(
            file=self.file, permissions=['nativeMessaging'])

        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
        assert summary.weight == 20
        assert weight_info['uses_native_messaging'] == 20

    def test_calculate_weight_sum(self):
        validation_data = {
            'messages': [
                {'id': ['MANIFEST_CSP']},
                {'id': ['UNSAFE_VAR_ASSIGNMENT']},
                {'id': ['NO_IMPLIED_EVAL']},
                {'id': ['DANGEROUS_EVAL']},
            ]
        }
        self.file_validation.update(validation=json.dumps(validation_data))
        summary = AutoApprovalSummary(version=self.version)
        weight_info = summary.calculate_weight()
        assert summary.weight == 75
        expected_result = {
            'abuse_reports': 0,
            'admin_review': 0,
            'average_daily_users': 0,
            'negative_reviews': 0,
            'reputation': 0,
            'past_rejection_history': 0,
            'uses_custom_csp': 30,
            'uses_eval_or_document_write': 20,
            'uses_implied_eval': 5,
            'uses_innerhtml': 20,
            'uses_native_messaging': 0
        }
        assert weight_info == expected_result

    def test_check_uses_custom_csp(self):
        assert AutoApprovalSummary.check_uses_custom_csp(self.version) is False

        validation_data = {
            'messages': [{
                'id': ['MANIFEST_CSP'],
            }]
        }
        self.file_validation.update(validation=json.dumps(validation_data))
        assert AutoApprovalSummary.check_uses_custom_csp(self.version) is True

    def test_check_uses_custom_csp_file_validation_missing(self):
        self.file_validation.delete()
        del self.version.all_files
        with self.assertRaises(AutoApprovalNoValidationResultError):
            AutoApprovalSummary.check_uses_custom_csp(self.version)

        # Also happens if only one file is missing validation info.
        self.file_validation = FileValidation.objects.create(
            file=self.version.all_files[0], validation=u'{}')
        del self.version.all_files
        file_factory(version=self.version, status=amo.STATUS_AWAITING_REVIEW)
        with self.assertRaises(AutoApprovalNoValidationResultError):
            AutoApprovalSummary.check_uses_custom_csp(self.version)

    def test_check_uses_native_messaging(self):
        assert (
            AutoApprovalSummary.check_uses_native_messaging(self.version)
            is False)

        webext_permissions = WebextPermission.objects.create(
            file=self.file, permissions=['foobar'])
        del self.file.webext_permissions_list
        assert (
            AutoApprovalSummary.check_uses_native_messaging(self.version)
            is False)

        webext_permissions.update(permissions=['nativeMessaging', 'foobar'])
        del self.file.webext_permissions_list
        assert (
            AutoApprovalSummary.check_uses_native_messaging(self.version)
            is True)

    def test_check_uses_content_script_for_all_urls(self):
        assert AutoApprovalSummary.check_uses_content_script_for_all_urls(
            self.version) is False

        webext_permissions = WebextPermission.objects.create(
            file=self.file, permissions=['https://example.com/*'])
        del self.file.webext_permissions_list
        assert AutoApprovalSummary.check_uses_content_script_for_all_urls(
            self.version) is False

        webext_permissions.update(permissions=['<all_urls>'])
        del self.file.webext_permissions_list
        assert AutoApprovalSummary.check_uses_content_script_for_all_urls(
            self.version) is True

    def test_check_is_under_admin_review(self):
        assert AutoApprovalSummary.check_is_under_admin_review(
            self.version) is False

        self.version.addon.update(admin_review=True)
        assert AutoApprovalSummary.check_is_under_admin_review(
            self.version) is True

    def test_check_is_locked(self):
        assert AutoApprovalSummary.check_is_locked(self.version) is False

        set_reviewing_cache(self.version.addon.pk, settings.TASK_USER_ID)
        assert AutoApprovalSummary.check_is_locked(self.version) is False

        set_reviewing_cache(self.version.addon.pk, settings.TASK_USER_ID + 42)
        assert AutoApprovalSummary.check_is_locked(self.version) is True

    def test_check_has_info_request(self):
        assert AutoApprovalSummary.check_has_info_request(
            self.version) is False

        self.version.update(has_info_request=True)
        assert AutoApprovalSummary.check_has_info_request(self.version) is True

    @mock.patch.object(AutoApprovalSummary, 'calculate_weight', spec=True)
    @mock.patch.object(AutoApprovalSummary, 'calculate_verdict', spec=True)
    def test_create_summary_for_version(
            self, calculate_verdict_mock, calculate_weight_mock):
        calculate_verdict_mock.return_value = {'dummy_verdict': True}
        summary, info = AutoApprovalSummary.create_summary_for_version(
            self.version,
            max_average_daily_users=111, min_approved_updates=222)
        assert calculate_weight_mock.call_count == 1
        assert calculate_verdict_mock.call_count == 1
        assert calculate_verdict_mock.call_args == ({
            'max_average_daily_users': 111,
            'min_approved_updates': 222,
            'dry_run': False,
            'post_review': False,
        },)
        assert summary.pk
        assert summary.version == self.version
        assert summary.uses_custom_csp is False
        assert summary.uses_native_messaging is False
        assert summary.uses_content_script_for_all_urls is False
        assert summary.average_daily_users == self.addon.average_daily_users
        assert (summary.approved_updates ==
                self.addon.addonapprovalscounter.counter)
        assert info == {'dummy_verdict': True}

    @mock.patch.object(AutoApprovalSummary, 'calculate_verdict', spec=True)
    def test_create_summary_no_previously_approved_versions(
            self, calculate_verdict_mock):
        AddonApprovalsCounter.objects.all().delete()
        self.version.reload()
        calculate_verdict_mock.return_value = {'dummy_verdict': True}
        summary, info = AutoApprovalSummary.create_summary_for_version(
            self.version,
            max_average_daily_users=111, min_approved_updates=222)
        assert summary.pk
        assert summary.approved_updates == 0
        assert info == {'dummy_verdict': True}

    def test_create_summary_already_existing(self):
        # Create a dummy summary manually, then call the method to create a
        # real one. It should have just updated the previous instance.
        summary = AutoApprovalSummary.objects.create(
            version=self.version,
            uses_custom_csp=True,
            uses_native_messaging=True,
            uses_content_script_for_all_urls=True)
        assert summary.pk
        assert summary.version == self.version
        assert summary.uses_custom_csp is True
        assert summary.uses_native_messaging is True
        assert summary.uses_content_script_for_all_urls is True
        assert summary.average_daily_users == 0
        assert summary.approved_updates == 0
        assert summary.verdict == amo.NOT_AUTO_APPROVED

        previous_summary_pk = summary.pk

        summary, info = AutoApprovalSummary.create_summary_for_version(
            self.version,
            max_average_daily_users=self.addon.average_daily_users + 1,
            min_approved_updates=1)

        assert summary.pk == previous_summary_pk
        assert summary.version == self.version
        assert summary.uses_custom_csp is False
        assert summary.uses_native_messaging is False
        assert summary.uses_content_script_for_all_urls is False
        assert summary.average_daily_users == self.addon.average_daily_users
        assert summary.approved_updates == 1
        assert summary.verdict == amo.AUTO_APPROVED
        assert info == {
            'too_few_approved_updates': False,
            'too_many_average_daily_users': False,
            'uses_content_script_for_all_urls': False,
            'uses_custom_csp': False,
            'uses_native_messaging': False,
            'has_info_request': False,
            'is_locked': False,
            'is_under_admin_review': False,
        }

    def test_create_summary_no_files(self):
        self.file.delete()
        del self.version.all_files
        with self.assertRaises(AutoApprovalNotEnoughFilesError):
            AutoApprovalSummary.create_summary_for_version(self.version)

    def test_calculate_verdict_failure_dry_run(self):
        summary = AutoApprovalSummary.objects.create(
            version=self.version, average_daily_users=1, approved_updates=2)
        info = summary.calculate_verdict(
            max_average_daily_users=summary.average_daily_users + 1,
            min_approved_updates=summary.approved_updates + 1, dry_run=True)
        assert info == {
            'too_few_approved_updates': True,
            'too_many_average_daily_users': False,
            'uses_content_script_for_all_urls': False,
            'uses_custom_csp': False,
            'uses_native_messaging': False,
            'has_info_request': False,
            'is_locked': False,
            'is_under_admin_review': False,
        }
        assert summary.verdict == amo.WOULD_NOT_HAVE_BEEN_AUTO_APPROVED

    def test_calculate_verdict_failure(self):
        summary = AutoApprovalSummary.objects.create(
            version=self.version,
            uses_custom_csp=True,
            uses_native_messaging=True,
            uses_content_script_for_all_urls=True,
            average_daily_users=self.addon.average_daily_users,
            approved_updates=333)
        info = summary.calculate_verdict(
            max_average_daily_users=summary.average_daily_users - 1,
            min_approved_updates=summary.approved_updates + 1)
        assert info == {
            'too_few_approved_updates': True,
            'too_many_average_daily_users': True,
            'uses_content_script_for_all_urls': True,
            'uses_custom_csp': True,
            'uses_native_messaging': True,
            'has_info_request': False,
            'is_locked': False,
            'is_under_admin_review': False,
        }
        assert summary.verdict == amo.NOT_AUTO_APPROVED

    def test_calculate_verdict_success(self):
        summary = AutoApprovalSummary.objects.create(
            version=self.version,
            uses_custom_csp=False,
            uses_native_messaging=False,
            uses_content_script_for_all_urls=False,
            average_daily_users=self.addon.average_daily_users,
            approved_updates=333)
        info = summary.calculate_verdict(
            max_average_daily_users=summary.average_daily_users + 1,
            min_approved_updates=summary.approved_updates)
        assert info == {
            'too_few_approved_updates': False,
            'too_many_average_daily_users': False,
            'uses_content_script_for_all_urls': False,
            'uses_custom_csp': False,
            'uses_native_messaging': False,
            'has_info_request': False,
            'is_locked': False,
            'is_under_admin_review': False,
        }
        assert summary.verdict == amo.AUTO_APPROVED

    def test_calculate_verdict_success_dry_run(self):
        summary = AutoApprovalSummary.objects.create(
            version=self.version,
            uses_custom_csp=False,
            uses_native_messaging=False,
            uses_content_script_for_all_urls=False,
            average_daily_users=self.addon.average_daily_users,
            approved_updates=333)
        info = summary.calculate_verdict(
            max_average_daily_users=summary.average_daily_users + 1,
            min_approved_updates=summary.approved_updates, dry_run=True)
        assert info == {
            'too_few_approved_updates': False,
            'too_many_average_daily_users': False,
            'uses_content_script_for_all_urls': False,
            'uses_custom_csp': False,
            'uses_native_messaging': False,
            'has_info_request': False,
            'is_locked': False,
            'is_under_admin_review': False,
        }
        assert summary.verdict == amo.WOULD_HAVE_BEEN_AUTO_APPROVED

    def test_calculate_verdict_post_review(self):
        summary = AutoApprovalSummary.objects.create(
            version=self.version, average_daily_users=1, approved_updates=2)
        info = summary.calculate_verdict(
            max_average_daily_users=summary.average_daily_users + 1,
            min_approved_updates=summary.approved_updates + 1,
            post_review=True)
        assert info == {}
        assert summary.verdict == amo.AUTO_APPROVED

    def test_calculate_verdict_post_review_dry_run(self):
        summary = AutoApprovalSummary.objects.create(
            version=self.version, average_daily_users=1, approved_updates=2)
        info = summary.calculate_verdict(
            max_average_daily_users=summary.average_daily_users + 1,
            min_approved_updates=summary.approved_updates + 1,
            post_review=True, dry_run=True)
        assert info == {}
        assert summary.verdict == amo.WOULD_HAVE_BEEN_AUTO_APPROVED

    def test_verdict_info_prettifier(self):
        verdict_info = {
            'too_few_approved_updates': True,
            'too_many_average_daily_users': True,
            'uses_content_script_for_all_urls': True,
            'uses_custom_csp': True,
            'uses_native_messaging': True,
            'has_info_request': True,
            'is_locked': True,
            'is_under_admin_review': True,
        }
        result = list(
            AutoApprovalSummary.verdict_info_prettifier(verdict_info))
        assert result == [
            u'Has a pending info request.',
            u'Is locked by a reviewer.',
            u'Is flagged for admin review.',
            u'Has too few consecutive human-approved updates.',
            u'Has too many daily users.',
            u'Uses a content script for all URLs.',
            u'Uses a custom CSP.',
            u'Uses nativeMessaging permission.'
        ]

        verdict_info = {
            'too_few_approved_updates': True,
            'uses_content_script_for_all_urls': True,
            'uses_native_messaging': True
        }
        result = list(
            AutoApprovalSummary.verdict_info_prettifier(verdict_info))
        assert result == [
            u'Has too few consecutive human-approved updates.',
            u'Uses a content script for all URLs.',
            u'Uses nativeMessaging permission.'
        ]

    def test_verdict_info_pretty(self):
        summary = AutoApprovalSummary.objects.create(
            version=self.version,
            uses_custom_csp=True,
            uses_native_messaging=True,
            uses_content_script_for_all_urls=True,
            average_daily_users=self.addon.average_daily_users,
            approved_updates=333)
        expected_result = list(AutoApprovalSummary.verdict_info_prettifier({
            'too_few_approved_updates': True,
            'too_many_average_daily_users': True,
            'uses_content_script_for_all_urls': True,
            'uses_custom_csp': True,
            'uses_native_messaging': True
        }))
        result = list(summary.calculate_verdict(
            max_average_daily_users=summary.average_daily_users - 1,
            min_approved_updates=summary.approved_updates + 1,
            pretty=True))
        assert result == expected_result
        assert summary.verdict == amo.NOT_AUTO_APPROVED
