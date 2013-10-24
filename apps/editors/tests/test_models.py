# -*- coding: utf8 -*-
import datetime
import time

from django.core import mail

from nose.tools import eq_

import amo
import amo.tests
from amo.tests import addon_factory
from addons.models import Addon
from versions.models import Version, version_uploaded, ApplicationsVersions
from files.models import Platform, File
from applications.models import Application, AppVersion
from editors.models import (EditorSubscription, RereviewQueue, RereviewQueueTheme,
                            ReviewerScore, send_notifications,
                            ViewFastTrackQueue, ViewFullReviewQueue,
                            ViewPendingQueue, ViewPreliminaryQueue)
from users.models import UserProfile


def create_addon_file(name, version_str, addon_status, file_status,
                      platform=amo.PLATFORM_ALL, application=amo.FIREFOX,
                      admin_review=False, addon_type=amo.ADDON_EXTENSION,
                      created=None):
    app, created_ = Application.objects.get_or_create(id=application.id,
                                                      guid=application.guid)
    app_vr, created_ = AppVersion.objects.get_or_create(application=app,
                                                        version='1.0')
    pl, created_ = Platform.objects.get_or_create(id=platform.id)
    try:
        ad = Addon.objects.get(name__localized_string=name)
    except Addon.DoesNotExist:
        ad = Addon.objects.create(type=addon_type, name=name)
    if admin_review:
        ad.update(admin_review=True)
    vr, created_ = Version.objects.get_or_create(addon=ad, version=version_str)
    va, created_ = ApplicationsVersions.objects.get_or_create(
        version=vr, application=app, min=app_vr, max=app_vr)
    file_ = File.objects.create(version=vr, filename=u"%s.xpi" % name,
                                platform=pl, status=file_status)
    # Update status *after* there are files:
    Addon.objects.get(pk=ad.id).update(status=addon_status)
    if created:
        vr.update(created=created)
        file_.update(created=created)
    return {'addon': ad, 'version': vr, 'file': file_}


def create_search_ext(name, version_str, addon_status, file_status):
    try:
        ad = Addon.objects.get(name__localized_string=name)
    except Addon.DoesNotExist:
        ad = Addon.objects.create(type=amo.ADDON_SEARCH, name=name)
    vr, created = Version.objects.get_or_create(addon=ad, version=version_str)
    pl, created = Platform.objects.get_or_create(id=amo.PLATFORM_ALL.id)
    File.objects.create(version=vr, filename=u"%s.xpi" % name,
                        platform=pl, status=file_status)
    # Update status *after* there are files:
    Addon.objects.get(pk=ad.id).update(status=addon_status)
    return ad


class TestQueue(amo.tests.TestCase):
    """Tests common attributes and coercions that each view must support."""
    __test__ = False  # this is an abstract test case

    def test_latest_version(self):
        self.new_file(version=u'0.1', created=self.days_ago(2))
        self.new_file(version=u'0.2', created=self.days_ago(1))
        self.new_file(version=u'0.3')
        row = self.Queue.objects.get()
        eq_(row.latest_version, '0.3')

    def test_file_platforms(self):
        # Here's a dupe platform in another version:
        self.new_file(version=u'0.1', platform=amo.PLATFORM_MAC,
                      created=self.days_ago(1))
        self.new_file(version=u'0.2', platform=amo.PLATFORM_LINUX)
        self.new_file(version=u'0.2', platform=amo.PLATFORM_MAC)
        row = self.Queue.objects.get()
        eq_(sorted(row.file_platform_ids),
            [amo.PLATFORM_LINUX.id, amo.PLATFORM_MAC.id])

    def test_file_applications(self):
        self.new_file(version=u'0.1', application=amo.FIREFOX)
        self.new_file(version=u'0.1', application=amo.THUNDERBIRD)
        # Duplicate:
        self.new_file(version=u'0.1', application=amo.FIREFOX)
        row = self.Queue.objects.get()
        eq_(sorted(row.application_ids),
            [amo.FIREFOX.id, amo.THUNDERBIRD.id])

    def test_addons_disabled_by_user_are_hidden(self):
        f = self.new_file(version=u'0.1')
        f['addon'].update(disabled_by_user=True)
        eq_(list(self.Queue.objects.all()), [])

    def test_addons_disabled_by_admin_are_hidden(self):
        f = self.new_file(version=u'0.1')
        f['addon'].update(status=amo.STATUS_DISABLED)
        eq_(list(self.Queue.objects.all()), [])

    def test_reviewed_files_are_hidden(self):
        self.new_file(name='Unreviewed', version=u'0.1')
        create_addon_file('Already Reviewed', '0.1',
                          amo.STATUS_PUBLIC, amo.STATUS_NULL)
        eq_(sorted(q.addon_name for q in self.Queue.objects.all()),
            ['Unreviewed'])

    def test_search_extensions(self):
        self.new_search_ext('Search Tool', '0.1')
        row = self.Queue.objects.get()
        eq_(row.addon_name, u'Search Tool')
        eq_(row.application_ids, [])
        eq_(row.file_platform_ids, [amo.PLATFORM_ALL.id])

    def test_count_all(self):
        self.new_file(name='Addon 1', version=u'0.1')
        self.new_file(name='Addon 1', version=u'0.2')
        self.new_file(name='Addon 2', version=u'0.1')
        self.new_file(name='Addon 2', version=u'0.2')
        eq_(self.Queue.objects.all().count(), 2)

    def test_no_apps(self):
        self.new_file(name='Addon 1', version=u'0.1',
                      addon_type=amo.ADDON_WEBAPP)
        eq_(self.Queue.objects.count(), 0)


class TestPendingQueue(TestQueue):
    __test__ = True
    Queue = ViewPendingQueue

    def new_file(self, name=u'Pending', version=u'1.0', **kw):
        return create_addon_file(name, version,
                                 amo.STATUS_PUBLIC, amo.STATUS_UNREVIEWED,
                                 **kw)

    def new_search_ext(self, name, version, **kw):
        return create_search_ext(name, version,
                                 amo.STATUS_PUBLIC, amo.STATUS_UNREVIEWED,
                                 **kw)

    def test_waiting_time(self):
        self.new_file(name='Addon 1', version=u'0.1')
        Version.objects.update(created=datetime.datetime.utcnow())
        row = self.Queue.objects.all()[0]
        eq_(row.waiting_time_days, 0)
        # Time zone will be off, hard to test this.
        assert row.waiting_time_hours is not None

    # These apply to all queues, except that all add-ons in the Fast
    # Track queue are Jetpack
    def test_flags_admin_review(self):
        f = self.new_file(version=u'0.1')
        f['addon'].update(admin_review=True)

        q = self.Queue.objects.get()
        eq_(q.flags, [('admin-review', 'Admin Review')])

    def test_flags_info_request(self):
        f = self.new_file(version=u'0.1')
        f['version'].update(has_info_request=True)
        q = self.Queue.objects.get()
        eq_(q.flags, [('info', 'More Information Requested')])

    def test_flags_editor_comment(self):
        f = self.new_file(version=u'0.1')
        f['version'].update(has_editor_comment=True)

        q = self.Queue.objects.get()
        eq_(q.flags, [('editor', 'Contains Editor Comment')])

    def test_flags_jetpack_and_restartless(self):
        f = self.new_file(version=u'0.1')
        f['file'].update(jetpack_version='1.8', no_restart=True)

        q = self.Queue.objects.get()
        eq_(q.flags, [('jetpack', 'Jetpack Add-on')])

    def test_flags_restartless(self):
        f = self.new_file(version=u'0.1')
        f['file'].update(no_restart=True)

        q = self.Queue.objects.get()
        eq_(q.flags, [('restartless', 'Restartless Add-on')])

    def test_no_flags(self):
        self.new_file(version=u'0.1')

        q = self.Queue.objects.get()
        eq_(q.flags, [])


class TestFullReviewQueue(TestQueue):
    __test__ = True
    Queue = ViewFullReviewQueue

    def new_file(self, name=u'Nominated', version=u'1.0', **kw):
        return create_addon_file(name, version,
                                 amo.STATUS_NOMINATED, amo.STATUS_UNREVIEWED,
                                 **kw)

    def new_search_ext(self, name, version, **kw):
        return create_search_ext(name, version,
                                 amo.STATUS_NOMINATED, amo.STATUS_UNREVIEWED,
                                 **kw)

    def test_lite_review_addons_also_shows_up(self):
        create_addon_file('Full', '0.1',
                          amo.STATUS_NOMINATED, amo.STATUS_UNREVIEWED)
        create_addon_file('Lite', '0.1',
                          amo.STATUS_LITE_AND_NOMINATED,
                          amo.STATUS_UNREVIEWED)
        eq_(sorted(q.addon_name for q in self.Queue.objects.all()),
            ['Full', 'Lite'])

    def test_any_nominated_file_shows_up(self):
        create_addon_file('Null', '0.1',
                          amo.STATUS_NOMINATED, amo.STATUS_NULL)
        eq_(sorted(q.addon_name for q in self.Queue.objects.all()), ['Null'])

    def test_waiting_time(self):
        self.new_file(name='Addon 1', version=u'0.1')
        Version.objects.update(nomination=datetime.datetime.utcnow())
        row = self.Queue.objects.all()[0]
        eq_(row.waiting_time_days, 0)
        # Time zone will be off, hard to test this.
        assert row.waiting_time_hours is not None


class TestPreliminaryQueue(TestQueue):
    __test__ = True
    Queue = ViewPreliminaryQueue

    def new_file(self, name=u'Preliminary', version=u'1.0', **kw):
        return create_addon_file(name, version,
                                 amo.STATUS_LITE, amo.STATUS_UNREVIEWED,
                                 **kw)

    def new_search_ext(self, name, version, **kw):
        return create_search_ext(name, version,
                                 amo.STATUS_LITE, amo.STATUS_UNREVIEWED,
                                 **kw)

    def test_unreviewed_addons_are_in_q(self):
        create_addon_file('Lite', '0.1',
                          amo.STATUS_LITE, amo.STATUS_UNREVIEWED)
        create_addon_file('Unreviewed', '0.1',
                          amo.STATUS_UNREVIEWED, amo.STATUS_UNREVIEWED)
        eq_(sorted(q.addon_name for q in self.Queue.objects.all()),
            ['Lite', 'Unreviewed'])

    def test_waiting_time(self):
        self.new_file(name='Addon 1', version=u'0.1')
        Version.objects.update(created=datetime.datetime.utcnow())
        row = self.Queue.objects.all()[0]
        eq_(row.waiting_time_days, 0)
        # Time zone might be off due to your MySQL install, hard to test this.
        assert row.waiting_time_min is not None
        assert row.waiting_time_hours is not None


class TestFastTrackQueue(TestQueue):
    __test__ = True
    Queue = ViewFastTrackQueue

    def query(self):
        return sorted(list(q.addon_name for q in self.Queue.objects.all()))

    def new_file(self, name=u'FastTrack', version=u'1.0', file_params=None,
                 **kw):
        res = create_addon_file(name, version,
                                amo.STATUS_LITE, amo.STATUS_UNREVIEWED, **kw)
        file_ = res['file']
        params = dict(no_restart=True, requires_chrome=False,
                      jetpack_version='1.1')
        if not file_params:
            file_params = {}
        params.update(file_params)
        for k, v in params.items():
            setattr(file_, k, v)
        file_.save()
        return res

    def new_search_ext(self, name, version, **kw):
        addon = create_search_ext(name, version,
                                  amo.STATUS_LITE, amo.STATUS_UNREVIEWED,
                                  **kw)
        file_ = addon.versions.get().files.get()
        file_.no_restart = True
        file_.jetpack_version = '1.1'
        file_.requires_chrome = False
        file_.save()
        return addon

    def test_include_jetpacks(self):
        self.new_file(name='jetpack')
        eq_(self.query(), ['jetpack'])

    def test_ignore_non_jetpacks(self):
        self.new_file(file_params=dict(no_restart=False))
        eq_(self.query(), [])

    def test_ignore_non_sdk_bootstrapped_addons(self):
        self.new_file(file_params=dict(jetpack_version=None))
        eq_(self.query(), [])

    def test_ignore_sneaky_jetpacks(self):
        self.new_file(file_params=dict(requires_chrome=True))
        eq_(self.query(), [])

    def test_include_full_review(self):
        ad = self.new_file(name='full')['addon']
        ad.status = amo.STATUS_NOMINATED
        ad.save()
        eq_(self.query(), ['full'])


class TestEditorSubscription(amo.tests.TestCase):
    fixtures = ['base/addon_3615', 'base/users']

    def setUp(self):
        self.addon = Addon.objects.get(pk=3615)
        self.version = self.addon.current_version
        self.user_one = UserProfile.objects.get(pk=55021)
        self.user_two = UserProfile.objects.get(pk=999)
        for user in [self.user_one, self.user_two]:
            EditorSubscription.objects.create(addon=self.addon, user=user)

    def test_email(self):
        es = EditorSubscription.objects.get(user=self.user_one)
        es.send_notification(self.version)
        eq_(len(mail.outbox), 1)
        eq_(mail.outbox[0].to, [u'del@icio.us'])
        eq_(mail.outbox[0].subject,
            'Mozilla Add-ons: Delicious Bookmarks Updated')

    def test_notifications(self):
        send_notifications(sender=self.version)
        eq_(len(mail.outbox), 2)
        emails = sorted([o.to for o in mail.outbox])
        eq_(emails, [[u'del@icio.us'], [u'regular@mozilla.com']])

    def test_notifications_clean(self):
        send_notifications(Version, self.version)
        eq_(EditorSubscription.objects.count(), 0)
        mail.outbox = []
        send_notifications(Version, self.version)
        eq_(len(mail.outbox), 0)

    def test_notifications_beta(self):
        self.version.all_files[0].update(status=amo.STATUS_BETA)
        version_uploaded.send(sender=self.version)
        eq_(len(mail.outbox), 0)

    def test_signal_edit(self):
        self.version.save()
        eq_(len(mail.outbox), 0)

    def test_signal_create(self):
        v = Version.objects.create(addon=self.addon)
        version_uploaded.send(sender=v)
        eq_(len(mail.outbox), 2)
        eq_(mail.outbox[0].subject,
            'Mozilla Add-ons: Delicious Bookmarks Updated')

    def test_signal_create_twice(self):
        v = Version.objects.create(addon=self.addon)
        version_uploaded.send(sender=v)
        mail.outbox = []
        v = Version.objects.create(addon=self.addon)
        version_uploaded.send(sender=v)
        eq_(len(mail.outbox), 0)


class TestReviewerScore(amo.tests.TestCase):
    fixtures = ['base/users']

    def setUp(self):
        self.addon = amo.tests.addon_factory(status=amo.STATUS_NOMINATED)
        self.app = amo.tests.app_factory(status=amo.STATUS_NOMINATED)
        self.user = UserProfile.objects.get(email='editor@mozilla.com')

    def _give_points(self, user=None, addon=None, status=None):
        user = user or self.user
        addon = addon or self.addon
        ReviewerScore.award_points(user, addon, status or addon.status)

    def check_event(self, type, status, event, **kwargs):
        self.addon.type = type
        eq_(ReviewerScore.get_event(self.addon, status, **kwargs), event, (
            'Score event for type:%s and status:%s was not %s' % (
                type, status, event)))

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
            # WEBAPP is special cased below.
        }
        statuses = {
            amo.STATUS_NULL: None,
            amo.STATUS_UNREVIEWED: 'PRELIM',
            amo.STATUS_PENDING: None,
            amo.STATUS_NOMINATED: 'FULL',
            amo.STATUS_PUBLIC: 'UPDATE',
            amo.STATUS_DISABLED: None,
            amo.STATUS_BETA: None,
            amo.STATUS_LITE: 'PRELIM',
            amo.STATUS_LITE_AND_NOMINATED: 'FULL',
            amo.STATUS_PURGATORY: None,
            amo.STATUS_DELETED: None,
            amo.STATUS_REJECTED: None,
            amo.STATUS_PUBLIC_WAITING: None,
            amo.STATUS_REVIEW_PENDING: None,
            amo.STATUS_BLOCKED: None,
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

    def test_events_webapps(self):
        self.addon = amo.tests.app_factory()
        self.check_event(self.addon.type, amo.STATUS_PENDING,
                         amo.REVIEWED_WEBAPP_HOSTED)

        RereviewQueue.objects.create(addon=self.addon)
        self.check_event(self.addon.type, amo.STATUS_PUBLIC,
                         amo.REVIEWED_WEBAPP_REREVIEW, in_rereview=True)
        RereviewQueue.objects.all().delete()

        self.addon.is_packaged = True
        self.check_event(self.addon.type, amo.STATUS_PENDING,
                         amo.REVIEWED_WEBAPP_PACKAGED)
        self.check_event(self.addon.type, amo.STATUS_PUBLIC,
                         amo.REVIEWED_WEBAPP_UPDATE)

    def test_award_points(self):
        self._give_points()
        eq_(ReviewerScore.objects.all()[0].score,
            amo.REVIEWED_SCORES[amo.REVIEWED_ADDON_FULL])

    def test_award_moderation_points(self):
        ReviewerScore.award_moderation_points(self.user, self.addon, 1)
        score = ReviewerScore.objects.all()[0]
        eq_(score.score, amo.REVIEWED_SCORES.get(amo.REVIEWED_ADDON_REVIEW))
        eq_(score.note_key, amo.REVIEWED_ADDON_REVIEW)

    def test_get_total(self):
        user2 = UserProfile.objects.get(email='admin@mozilla.com')
        self._give_points()
        self._give_points(status=amo.STATUS_LITE)
        self._give_points(user=user2, status=amo.STATUS_NOMINATED)
        eq_(ReviewerScore.get_total(self.user),
            amo.REVIEWED_SCORES[amo.REVIEWED_ADDON_FULL] +
            amo.REVIEWED_SCORES[amo.REVIEWED_ADDON_PRELIM])
        eq_(ReviewerScore.get_total(user2),
            amo.REVIEWED_SCORES[amo.REVIEWED_ADDON_FULL])

    def test_get_recent(self):
        user2 = UserProfile.objects.get(email='admin@mozilla.com')
        self._give_points()
        time.sleep(1)  # Wait 1 sec so ordering by created is checked.
        self._give_points(status=amo.STATUS_LITE)
        self._give_points(user=user2)
        scores = ReviewerScore.get_recent(self.user)
        eq_(len(scores), 2)
        eq_(scores[0].score, amo.REVIEWED_SCORES[amo.REVIEWED_ADDON_PRELIM])
        eq_(scores[1].score, amo.REVIEWED_SCORES[amo.REVIEWED_ADDON_FULL])

    def test_get_leaderboards(self):
        user2 = UserProfile.objects.get(email='regular@mozilla.com')
        self._give_points()
        self._give_points(status=amo.STATUS_LITE)
        self._give_points(user=user2, status=amo.STATUS_NOMINATED)
        leaders = ReviewerScore.get_leaderboards(self.user)
        eq_(leaders['user_rank'], 1)
        eq_(leaders['leader_near'], [])
        eq_(leaders['leader_top'][0]['rank'], 1)
        eq_(leaders['leader_top'][0]['user_id'], self.user.id)
        eq_(leaders['leader_top'][0]['total'],
            amo.REVIEWED_SCORES[amo.REVIEWED_ADDON_FULL] +
            amo.REVIEWED_SCORES[amo.REVIEWED_ADDON_PRELIM])
        eq_(leaders['leader_top'][1]['rank'], 2)
        eq_(leaders['leader_top'][1]['user_id'], user2.id)
        eq_(leaders['leader_top'][1]['total'],
            amo.REVIEWED_SCORES[amo.REVIEWED_ADDON_FULL])

        self._give_points(
            user=user2, addon=amo.tests.addon_factory(type=amo.ADDON_PERSONA))
        leaders = ReviewerScore.get_leaderboards(
            self.user, addon_type=amo.ADDON_PERSONA)
        eq_(len(leaders['leader_top']), 1)
        eq_(leaders['leader_top'][0]['user_id'], user2.id)

    def test_no_admins_or_staff_in_leaderboards(self):
        user2 = UserProfile.objects.get(email='admin@mozilla.com')
        self._give_points()
        self._give_points(status=amo.STATUS_LITE)
        self._give_points(user=user2, status=amo.STATUS_NOMINATED)
        leaders = ReviewerScore.get_leaderboards(self.user)
        eq_(leaders['user_rank'], 1)
        eq_(leaders['leader_near'], [])
        eq_(leaders['leader_top'][0]['user_id'], self.user.id)
        eq_(len(leaders['leader_top']), 1)  # Only the editor is here.
        assert user2.id not in [l['user_id'] for l in leaders['leader_top']], (
            'Unexpected admin user found in leaderboards.')

    def test_no_marketplace_points_in_amo_leaderboards(self):
        self._give_points()
        self._give_points(status=amo.STATUS_LITE)
        self._give_points(addon=self.app, status=amo.STATUS_NOMINATED)
        leaders = ReviewerScore.get_leaderboards(self.user,
                                                 types=amo.REVIEWED_AMO)
        eq_(leaders['leader_top'][0]['total'],
            amo.REVIEWED_SCORES[amo.REVIEWED_ADDON_FULL] +
            amo.REVIEWED_SCORES[amo.REVIEWED_ADDON_PRELIM])

    def test_no_amo_points_in_marketplace_leaderboards(self):
        self._give_points()
        self._give_points(status=amo.STATUS_LITE)
        self._give_points(addon=self.app, status=amo.STATUS_NOMINATED)
        leaders = ReviewerScore.get_leaderboards(
            self.user, types=amo.REVIEWED_MARKETPLACE)
        eq_(leaders['leader_top'][0]['total'],
            amo.REVIEWED_SCORES[amo.REVIEWED_WEBAPP_HOSTED])

    def test_get_breakdown(self):
        self._give_points()
        self._give_points(addon=amo.tests.app_factory())
        breakdown = ReviewerScore.get_breakdown(self.user)
        eq_(len(breakdown), 2)
        eq_(set([b.atype for b in breakdown]),
            set([amo.ADDON_EXTENSION, amo.ADDON_WEBAPP]))

    def test_get_breakdown_since(self):
        self._give_points()
        self._give_points(addon=amo.tests.app_factory())
        rs = list(ReviewerScore.objects.all())
        rs[0].update(created=self.days_ago(50))
        breakdown = ReviewerScore.get_breakdown_since(self.user,
                                                      self.days_ago(30))
        eq_(len(breakdown), 1)
        eq_([b.atype for b in breakdown], [rs[1].addon.type])

    def test_get_leaderboards_last(self):
        users = []
        for i in range(6):
            users.append(UserProfile.objects.create(username='user-%s' % i))
        last_user = users.pop(len(users) - 1)
        for u in users:
            self._give_points(user=u)
        # Last user gets lower points by reviewing a persona.
        addon = self.addon
        addon.type = amo.ADDON_PERSONA
        self._give_points(user=last_user, addon=addon)
        leaders = ReviewerScore.get_leaderboards(last_user)
        eq_(leaders['user_rank'], 6)
        eq_(len(leaders['leader_top']), 3)
        eq_(len(leaders['leader_near']), 2)

    def test_all_users_by_score(self):
        user2 = UserProfile.objects.get(email='regular@mozilla.com')
        amo.REVIEWED_LEVELS[0]['points'] = 180
        self._give_points()
        self._give_points(status=amo.STATUS_LITE)
        self._give_points(user=user2, status=amo.STATUS_NOMINATED)
        users = ReviewerScore.all_users_by_score()
        eq_(len(users), 2)
        # First user.
        eq_(users[0]['total'], 180)
        eq_(users[0]['user_id'], self.user.id)
        eq_(users[0]['level'], amo.REVIEWED_LEVELS[0]['name'])
        # Second user.
        eq_(users[1]['total'], 120)
        eq_(users[1]['user_id'], user2.id)
        eq_(users[1]['level'], '')

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


class TestRereviewQueueTheme(amo.tests.TestCase):

    def test_manager_soft_delete_addons(self):
        """Test manager excludes soft delete add-ons."""
        # Normal RQT object.
        RereviewQueueTheme.objects.create(
            theme=addon_factory(type=amo.ADDON_PERSONA).persona, header='',
            footer='')

        # Deleted add-on RQT object.
        addon = addon_factory(type=amo.ADDON_PERSONA)
        RereviewQueueTheme.objects.create(theme=addon.persona, header='', footer='')
        addon.delete()

        eq_(RereviewQueueTheme.objects.count(), 1)
        eq_(RereviewQueueTheme.with_deleted.count(), 2)
