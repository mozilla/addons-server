# -*- coding: utf8 -*-
from datetime import datetime

from django.core import mail

from nose.tools import eq_

import amo
import amo.tests
from addons.models import Addon
from versions.models import Version, version_uploaded, ApplicationsVersions
from files.models import Platform, File
from applications.models import Application, AppVersion
from editors.models import (EditorSubscription, send_notifications,
                            ViewPendingQueue, ViewFullReviewQueue,
                            ViewPreliminaryQueue, ViewFastTrackQueue)
from users.models import UserProfile


def create_addon_file(name, version_str, addon_status, file_status,
                      platform=amo.PLATFORM_ALL, application=amo.FIREFOX,
                      admin_review=False, addon_type=amo.ADDON_EXTENSION):
    app, created = Application.objects.get_or_create(id=application.id,
                                                     guid=application.guid)
    app_vr, created = AppVersion.objects.get_or_create(application=app,
                                                       version='1.0')
    pl, created = Platform.objects.get_or_create(id=platform.id)
    try:
        ad = Addon.objects.get(name__localized_string=name)
    except Addon.DoesNotExist:
        ad = Addon.objects.create(type=addon_type, name=name)
    if admin_review:
        ad.update(admin_review=True)
    vr, created = Version.objects.get_or_create(addon=ad, version=version_str)
    va, created = ApplicationsVersions.objects.get_or_create(
                        version=vr, application=app, min=app_vr, max=app_vr)
    file_ = File.objects.create(version=vr, filename=u"%s.xpi" % name,
                                platform=pl, status=file_status)
    # Update status *after* there are files:
    Addon.objects.get(pk=ad.id).update(status=addon_status)
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
        self.new_file(version=u'0.1')
        self.new_file(version=u'0.2')
        latest = self.new_file(version=u'0.3')
        row = self.Queue.objects.get()
        eq_(row.latest_version, '0.3')
        eq_(row.latest_version_id, latest['version'].id)

    def test_file_platforms(self):
        # Here's a dupe platform in another version:
        self.new_file(version=u'0.1', platform=amo.PLATFORM_MAC)
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
                          amo.STATUS_PUBLIC, amo.STATUS_LISTED)
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
        Version.objects.update(created=datetime.utcnow())
        row = self.Queue.objects.all()[0]
        eq_(row.waiting_time_days, 0)
        # Time zone will be off, hard to test this.
        assert row.waiting_time_hours is not None


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
        Version.objects.update(nomination=datetime.utcnow())
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
        Version.objects.update(created=datetime.utcnow())
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
