# -*- coding: utf-8 -*-
from datetime import datetime, timedelta
import time

from django.conf import settings
from django.core import mail

from olympia import amo
from olympia.amo.tests import TestCase
from olympia.amo.tests import addon_factory, user_factory
from olympia.addons.models import Addon, AddonUser
from olympia.versions.models import (
    Version, version_uploaded, ApplicationsVersions)
from olympia.files.models import File
from olympia.applications.models import AppVersion
from olympia.editors.models import (
    EditorSubscription, RereviewQueueTheme, ReviewerScore, send_notifications,
    ViewFastTrackQueue, ViewFullReviewQueue, ViewPendingQueue,
    ViewPreliminaryQueue, ViewUnlistedAllList, ViewUnlistedFullReviewQueue,
    ViewUnlistedPendingQueue, ViewUnlistedPreliminaryQueue)
from olympia.users.models import UserProfile


def create_addon_file(name, version_str, addon_status, file_status,
                      platform=amo.PLATFORM_ALL, application=amo.FIREFOX,
                      admin_review=False, addon_type=amo.ADDON_EXTENSION,
                      created=None, file_kw=None, version_kw=None,
                      listed=True, nomination=None):
    if file_kw is None:
        file_kw = {}
    if version_kw is None:
        version_kw = {}
    app_vr, created_ = AppVersion.objects.get_or_create(
        application=application.id, version='1.0')
    ad, created_ = Addon.with_unlisted.get_or_create(
        name__localized_string=name,
        defaults={'type': addon_type, 'name': name, 'is_listed': listed})
    if admin_review:
        ad.update(admin_review=True)
    vr, created_ = Version.objects.get_or_create(addon=ad, version=version_str,
                                                 defaults=version_kw)
    if nomination is not None:
        vr.nomination = nomination
        vr.save()

    if not created_:
        vr.update(**version_kw)
    va, created_ = ApplicationsVersions.objects.get_or_create(
        version=vr, application=application.id, min=app_vr, max=app_vr)
    file_ = File.objects.create(version=vr, filename=u"%s.xpi" % name,
                                platform=platform.id, status=file_status,
                                **file_kw)
    if created:
        vr.update(created=created)
        file_.update(created=created)
    # Update status *after* we are done creating/modifying version and files:
    Addon.with_unlisted.get(pk=ad.id).update(status=addon_status)
    return {'addon': ad, 'version': vr, 'file': file_}


def create_search_ext(name, version_str, addon_status, file_status,
                      listed=True):
    ad, created_ = Addon.with_unlisted.get_or_create(
        name__localized_string=name,
        defaults={'type': amo.ADDON_SEARCH, 'name': name, 'is_listed': listed})
    vr, created_ = Version.objects.get_or_create(addon=ad, version=version_str)
    File.objects.create(version=vr, filename=u"%s.xpi" % name,
                        platform=amo.PLATFORM_ALL.id, status=file_status)
    # Update status *after* there are files:
    Addon.with_unlisted.get(pk=ad.id).update(status=addon_status)
    return ad


class TestQueue(TestCase):
    """Tests common attributes and coercions that each view must support."""
    __test__ = False  # this is an abstract test case
    listed = True  # Are we testing listed or unlisted queues?

    def test_latest_version(self):
        self.new_file(version=u'0.1', created=self.days_ago(2))
        self.new_file(version=u'0.2', created=self.days_ago(1))
        self.new_file(version=u'0.3')
        row = self.Queue.objects.get()
        assert row.latest_version == '0.3'

    def test_file_platforms(self):
        # Here's a dupe platform in another version:
        self.new_file(version=u'0.1', platform=amo.PLATFORM_MAC,
                      created=self.days_ago(1))
        self.new_file(version=u'0.2', platform=amo.PLATFORM_LINUX)
        self.new_file(version=u'0.2', platform=amo.PLATFORM_MAC)
        row = self.Queue.objects.get()
        assert sorted(row.platforms) == (
            [amo.PLATFORM_LINUX.id, amo.PLATFORM_MAC.id])

    def test_file_applications(self):
        self.new_file(version=u'0.1', application=amo.FIREFOX)
        self.new_file(version=u'0.1', application=amo.THUNDERBIRD)
        # Duplicate:
        self.new_file(version=u'0.1', application=amo.FIREFOX)
        row = self.Queue.objects.get()
        assert sorted(row.application_ids) == (
            [amo.FIREFOX.id, amo.THUNDERBIRD.id])

    def test_addons_disabled_by_user_are_hidden(self):
        f = self.new_file(version=u'0.1')
        f['addon'].update(disabled_by_user=True)
        assert list(self.Queue.objects.all()) == []

    def test_addons_disabled_by_admin_are_hidden(self):
        f = self.new_file(version=u'0.1')
        f['addon'].update(status=amo.STATUS_DISABLED)
        assert list(self.Queue.objects.all()) == []

    def test_reviewed_files_are_hidden(self):
        self.new_file(name='Unreviewed', version=u'0.1')
        self.new_file('Already Reviewed', '0.1',
                      amo.STATUS_PUBLIC, amo.STATUS_NULL)
        assert sorted(q.addon_name for q in self.Queue.objects.all()) == (
            ['Unreviewed'])

    def test_search_extensions(self):
        self.new_search_ext('Search Tool', '0.1')
        row = self.Queue.objects.get()
        assert row.addon_name == u'Search Tool'
        assert row.application_ids == []
        assert row.platforms == [amo.PLATFORM_ALL.id]

    def test_count_all(self):
        self.new_file(name='Addon 1', version=u'0.1')
        self.new_file(name='Addon 1', version=u'0.2')
        self.new_file(name='Addon 2', version=u'0.1')
        self.new_file(name='Addon 2', version=u'0.2')
        assert self.Queue.objects.all().count() == 2


class TestPendingQueue(TestQueue):
    __test__ = True
    Queue = ViewPendingQueue

    def new_file(self, name=u'Pending', version=u'1.0',
                 addon_status=amo.STATUS_PUBLIC,
                 file_status=amo.STATUS_UNREVIEWED, **kw):
        # Create the addon and everything related. Note that we are cheating,
        # the addon status might not correspond to the files attached. This is
        # important not to re-save() attached versions and files afterwards,
        # because that might alter the addon status.
        return create_addon_file(name, version, addon_status, file_status,
                                 listed=self.listed, **kw)

    def new_search_ext(self, name, version, **kw):
        return create_search_ext(name, version,
                                 amo.STATUS_PUBLIC, amo.STATUS_UNREVIEWED,
                                 listed=self.listed, **kw)

    def test_waiting_time(self):
        self.new_file(name='Addon 1', version=u'0.1')
        Version.objects.update(created=datetime.utcnow())
        row = self.Queue.objects.all()[0]
        assert row.waiting_time_days == 0
        # Time zone will be off, hard to test this.
        assert row.waiting_time_hours is not None

    # These apply to all queues, except that all add-ons in the Fast
    # Track queue are Jetpack
    def test_flags_admin_review(self):
        f = self.new_file(version=u'0.1')
        f['addon'].update(admin_review=True)

        q = self.Queue.objects.get()
        assert q.flags == [('admin-review', 'Admin Review')]

    def test_flags_info_request(self):
        self.new_file(version=u'0.1', version_kw={'has_info_request': True})
        q = self.Queue.objects.get()
        assert q.flags == [('info', 'More Information Requested')]

    def test_flags_editor_comment(self):
        self.new_file(version=u'0.1', version_kw={'has_editor_comment': True})

        q = self.Queue.objects.get()
        assert q.flags == [('editor', 'Contains Editor Comment')]

    def test_flags_jetpack_and_restartless(self):
        self.new_file(version=u'0.1', file_kw={'jetpack_version': '1.8',
                                               'no_restart': True})

        q = self.Queue.objects.get()
        assert q.flags == [('jetpack', 'Jetpack Add-on')]

    def test_flags_restartless(self):
        self.new_file(version=u'0.1', file_kw={'no_restart': True})

        q = self.Queue.objects.get()
        assert q.flags == [('restartless', 'Restartless Add-on')]

    def test_flags_sources_provided(self):
        f = self.new_file(version=u'0.1')
        f['addon'].versions.update(source='/some/source/file')

        q = self.Queue.objects.get()
        assert q.flags == [('sources-provided', 'Sources provided')]

    def test_flags_webextension(self):
        self.new_file(version=u'0.1', file_kw={'is_webextension': True})

        queue = self.Queue.objects.get()
        assert queue.flags == [('webextension', 'WebExtension')]

    def test_no_flags(self):
        self.new_file(version=u'0.1')

        q = self.Queue.objects.get()
        assert q.flags == []


class TestFullReviewQueue(TestQueue):
    __test__ = True
    Queue = ViewFullReviewQueue

    def new_file(self, name=u'Nominated', version=u'1.0',
                 addon_status=amo.STATUS_NOMINATED,
                 file_status=amo.STATUS_UNREVIEWED, **kw):
        return create_addon_file(name, version, addon_status, file_status,
                                 listed=self.listed, **kw)

    def new_search_ext(self, name, version, **kw):
        return create_search_ext(name, version,
                                 amo.STATUS_NOMINATED, amo.STATUS_UNREVIEWED,
                                 listed=self.listed, **kw)

    def test_lite_review_addons_also_shows_up(self):
        create_addon_file('Full', '0.1',
                          amo.STATUS_NOMINATED, amo.STATUS_UNREVIEWED,
                          listed=self.listed)
        create_addon_file('Lite', '0.1',
                          amo.STATUS_LITE_AND_NOMINATED,
                          amo.STATUS_LITE, listed=self.listed)
        assert sorted(q.addon_name for q in self.Queue.objects.all()) == (
            ['Full', 'Lite'])

    def test_waiting_time(self):
        self.new_file(name='Addon 1', version=u'0.1')
        Version.objects.update(nomination=datetime.utcnow())
        row = self.Queue.objects.all()[0]
        assert row.waiting_time_days == 0
        # Time zone will be off, hard to test this.
        assert row.waiting_time_hours is not None


class TestPreliminaryQueue(TestQueue):
    __test__ = True
    Queue = ViewPreliminaryQueue

    def new_file(self, name=u'Preliminary', version=u'1.0',
                 addon_status=amo.STATUS_LITE,
                 file_status=amo.STATUS_UNREVIEWED, **kw):
        return create_addon_file(name, version, addon_status, file_status,
                                 listed=self.listed, **kw)

    def new_search_ext(self, name, version, **kw):
        return create_search_ext(name, version,
                                 amo.STATUS_LITE, amo.STATUS_UNREVIEWED,
                                 listed=self.listed, **kw)

    def test_unreviewed_addons_are_in_q(self):
        create_addon_file('Lite', '0.1',
                          amo.STATUS_LITE, amo.STATUS_UNREVIEWED,
                          listed=self.listed)
        create_addon_file('Unreviewed', '0.1',
                          amo.STATUS_UNREVIEWED, amo.STATUS_UNREVIEWED,
                          listed=self.listed)
        assert sorted(q.addon_name for q in self.Queue.objects.all()) == (
            ['Lite', 'Unreviewed'])

    def test_waiting_time(self):
        self.new_file(name='Addon 1', version=u'0.1')
        Version.objects.update(created=datetime.utcnow())
        row = self.Queue.objects.all()[0]
        assert row.waiting_time_days == 0
        # Time zone might be off due to your MySQL install, hard to test this.
        assert row.waiting_time_min is not None
        assert row.waiting_time_hours is not None


class TestFastTrackQueue(TestQueue):
    __test__ = True
    Queue = ViewFastTrackQueue

    def query(self):
        return sorted(list(q.addon_name for q in self.Queue.objects.all()))

    def new_file(self, name=u'FastTrack', version=u'1.0',
                 addon_status=amo.STATUS_LITE,
                 file_status=amo.STATUS_UNREVIEWED, file_params=None,
                 **kw):
        res = create_addon_file(name, version, addon_status, file_status, **kw)
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
        assert self.query() == ['jetpack']

    def test_ignore_non_jetpacks(self):
        self.new_file(file_params=dict(no_restart=False))
        assert self.query() == []

    def test_ignore_non_sdk_bootstrapped_addons(self):
        self.new_file(file_params=dict(jetpack_version=None))
        assert self.query() == []

    def test_ignore_sneaky_jetpacks(self):
        self.new_file(file_params=dict(requires_chrome=True))
        assert self.query() == []

    def test_include_full_review(self):
        ad = self.new_file(name='full')['addon']
        ad.status = amo.STATUS_NOMINATED
        ad.save()
        assert self.query() == ['full']

    def test_include_webextensions(self):
        self.new_file(name='webext', file_params=dict(is_webextension=True))
        assert self.query() == ['webext']

    def test_include_jpm_addons(self):
        self.new_file(name='jpm', file_params=dict(jetpack_version='jpm'))
        assert self.query() == ['jpm']


class TestUnlistedPendingQueue(TestPendingQueue):
    Queue = ViewUnlistedPendingQueue
    listed = False


class TestUnlistedFullReviewQueue(TestFullReviewQueue):
    Queue = ViewUnlistedFullReviewQueue
    listed = False


class TestUnlistedPreliminaryQueue(TestPreliminaryQueue):
    Queue = ViewUnlistedPreliminaryQueue
    listed = False


class TestUnlistedAllList(TestCase):
    Queue = ViewUnlistedAllList
    listed = False
    fixtures = ['base/users']

    def new_file(self, name=u'Preliminary', version=u'1.0',
                 addon_status=amo.STATUS_LITE,
                 file_status=amo.STATUS_UNREVIEWED, **kw):
        return create_addon_file(name, version, addon_status, file_status,
                                 listed=self.listed, **kw)

    def test_all_addons_are_in_q(self):
        self.new_file('Lite', addon_status=amo.STATUS_LITE,
                      file_status=amo.STATUS_UNREVIEWED)
        self.new_file('Unreviewed', addon_status=amo.STATUS_UNREVIEWED,
                      file_status=amo.STATUS_UNREVIEWED)
        self.new_file('Public', addon_status=amo.STATUS_PUBLIC,
                      file_status=amo.STATUS_PUBLIC)
        self.new_file('Nominated', addon_status=amo.STATUS_NOMINATED,
                      file_status=amo.STATUS_UNREVIEWED)
        self.new_file('Deleted', addon_status=amo.STATUS_PUBLIC,
                      file_status=amo.STATUS_PUBLIC)['addon'].delete()
        assert sorted(q.addon_name for q in self.Queue.objects.all()) == (
            ['Deleted', 'Lite', 'Nominated', 'Public', 'Unreviewed'])

    def test_authors(self):
        addon = self.new_file()['addon']
        bert = user_factory(username='bert')
        ernie = user_factory(username='ernie')
        AddonUser.objects.create(addon=addon, user=bert)
        AddonUser.objects.create(addon=addon, user=ernie)
        row = self.Queue.objects.all()[0]
        self.assertSetEqual(set(row.authors),
                            {(ernie.id, 'ernie'), (bert.id, 'bert')})

    def test_last_reviewed_version(self):
        today = datetime.today().date()
        self.new_file(name='addon123', version='1.0')
        v2 = self.new_file(name='addon123', version='2.0')['version']
        log = amo.log(amo.LOG.PRELIMINARY_VERSION, v2, v2.addon,
                      user=UserProfile.objects.get(pk=999))
        self.new_file(name='addon123', version='3.0')
        row = self.Queue.objects.all()[0]
        assert row.review_date == today
        assert row.review_version_num == '2.0'
        assert row.review_log_id == log.id

    def test_no_developer_actions(self):
        ver = self.new_file(name='addon456', version='1.0')['version']
        amo.log(amo.LOG.ADD_VERSION, ver, ver.addon,
                user=UserProfile.objects.get(pk=999))
        row = self.Queue.objects.all()[0]
        assert row.review_version_num is None

        ver = self.new_file(name='addon456', version='2.0')['version']
        amo.log(amo.LOG.PRELIMINARY_VERSION, ver, ver.addon,
                user=UserProfile.objects.get(pk=999))
        row = self.Queue.objects.all()[0]
        assert row.review_version_num == '2.0'

        ver = self.new_file(name='addon456', version='3.0')['version']
        amo.log(amo.LOG.EDIT_VERSION, ver, ver.addon,
                user=UserProfile.objects.get(pk=999))
        row = self.Queue.objects.all()[0]
        # v2.0 is still the last reviewed version.
        assert row.review_version_num == '2.0'

    def test_no_automatic_reviews(self):
        ver = self.new_file(name='addon789', version='1.0')['version']
        amo.log(amo.LOG.PRELIMINARY_VERSION, ver, ver.addon,
                user=UserProfile.objects.get(pk=settings.TASK_USER_ID))
        row = self.Queue.objects.all()[0]
        assert row.review_version_num is None

    def test_latest_version(self):
        self.new_file(version=u'0.1', created=self.days_ago(2))
        self.new_file(version=u'0.2', created=self.days_ago(1))
        self.new_file(version=u'0.3')
        row = self.Queue.objects.get()
        assert row.latest_version == '0.3'

    def test_addons_disabled_by_user_are_hidden(self):
        f = self.new_file(version=u'0.1')
        f['addon'].update(disabled_by_user=True)
        assert list(self.Queue.objects.all()) == []

    def test_addons_disabled_by_admin_are_hidden(self):
        f = self.new_file(version=u'0.1')
        f['addon'].update(status=amo.STATUS_DISABLED)
        assert list(self.Queue.objects.all()) == []

    def test_count_all(self):
        self.new_file(name='Addon 1', version=u'0.1')
        self.new_file(name='Addon 1', version=u'0.2')
        self.new_file(name='Addon 2', version=u'0.1')
        self.new_file(name='Addon 2', version=u'0.2')
        assert self.Queue.objects.all().count() == 2


class TestEditorSubscription(TestCase):
    fixtures = ['base/addon_3615', 'base/users']

    def setUp(self):
        super(TestEditorSubscription, self).setUp()
        self.addon = Addon.objects.get(pk=3615)
        self.version = self.addon.current_version
        self.user_one = UserProfile.objects.get(pk=55021)
        self.user_two = UserProfile.objects.get(pk=999)
        for user in [self.user_one, self.user_two]:
            EditorSubscription.objects.create(addon=self.addon, user=user)

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


class TestReviewerScore(TestCase):
    fixtures = ['base/users']

    def setUp(self):
        super(TestReviewerScore, self).setUp()
        self.addon = amo.tests.addon_factory(status=amo.STATUS_NOMINATED)
        self.user = UserProfile.objects.get(email='editor@mozilla.com')

    def _give_points(self, user=None, addon=None, status=None):
        user = user or self.user
        addon = addon or self.addon
        ReviewerScore.award_points(user, addon, status or addon.status)

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
            amo.STATUS_UNREVIEWED: 'PRELIM',
            amo.STATUS_PENDING: None,
            amo.STATUS_NOMINATED: 'FULL',
            amo.STATUS_PUBLIC: 'UPDATE',
            amo.STATUS_DISABLED: None,
            amo.STATUS_BETA: None,
            amo.STATUS_LITE: 'PRELIM',
            amo.STATUS_LITE_AND_NOMINATED: 'FULL',
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
        addon_objects = create_addon_file(
            u'AwardBonus',
            u'1.0',
            amo.STATUS_NOMINATED,
            amo.STATUS_UNREVIEWED,
            nomination=(datetime.now() - timedelta(days=days))
        )
        self._give_points(user2, addon_objects['addon'], 1)
        score = ReviewerScore.objects.get(user=user2)
        expected = (amo.REVIEWED_SCORES[amo.REVIEWED_ADDON_PRELIM] +
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
        self._give_points(status=amo.STATUS_LITE)
        self._give_points(user=user2, status=amo.STATUS_NOMINATED)
        assert ReviewerScore.get_total(self.user) == (
            amo.REVIEWED_SCORES[amo.REVIEWED_ADDON_FULL] +
            amo.REVIEWED_SCORES[amo.REVIEWED_ADDON_PRELIM])
        assert ReviewerScore.get_total(user2) == (
            amo.REVIEWED_SCORES[amo.REVIEWED_ADDON_FULL])

    def test_get_recent(self):
        user2 = UserProfile.objects.get(email='admin@mozilla.com')
        self._give_points()
        time.sleep(1)  # Wait 1 sec so ordering by created is checked.
        self._give_points(status=amo.STATUS_LITE)
        self._give_points(user=user2)
        scores = ReviewerScore.get_recent(self.user)
        assert len(scores) == 2
        assert scores[0].score == (
            amo.REVIEWED_SCORES[amo.REVIEWED_ADDON_PRELIM])
        assert scores[1].score == (
            amo.REVIEWED_SCORES[amo.REVIEWED_ADDON_FULL])

    def test_get_leaderboards(self):
        user2 = UserProfile.objects.get(email='regular@mozilla.com')
        self._give_points()
        self._give_points(status=amo.STATUS_LITE)
        self._give_points(user=user2, status=amo.STATUS_NOMINATED)
        leaders = ReviewerScore.get_leaderboards(self.user)
        assert leaders['user_rank'] == 1
        assert leaders['leader_near'] == []
        assert leaders['leader_top'][0]['rank'] == 1
        assert leaders['leader_top'][0]['user_id'] == self.user.id
        assert leaders['leader_top'][0]['total'] == (
            amo.REVIEWED_SCORES[amo.REVIEWED_ADDON_FULL] +
            amo.REVIEWED_SCORES[amo.REVIEWED_ADDON_PRELIM])
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

    def test_no_admins_or_staff_in_leaderboards(self):
        user2 = UserProfile.objects.get(email='admin@mozilla.com')
        self._give_points()
        self._give_points(status=amo.STATUS_LITE)
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
            users.append(UserProfile.objects.create(username='user-%s' % i))
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
        user2 = UserProfile.objects.get(email='regular@mozilla.com')
        amo.REVIEWED_LEVELS[0]['points'] = 180
        self._give_points()
        self._give_points(status=amo.STATUS_LITE)
        self._give_points(user=user2, status=amo.STATUS_NOMINATED)
        users = ReviewerScore.all_users_by_score()
        assert len(users) == 2
        # First user.
        assert users[0]['total'] == 180
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
