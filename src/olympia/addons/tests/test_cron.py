# -*- coding: utf-8 -*-
import datetime
import os
import time

from django.core.management.base import CommandError
from django.test.utils import override_settings

import mock

from olympia import amo
from olympia.addons import cron
from olympia.addons.models import Addon, AppSupport
from olympia.amo.tests import addon_factory, TestCase
from olympia.files.models import File
from olympia.lib.es.utils import flag_reindexing_amo, unflag_reindexing_amo
from olympia.stats.models import DownloadCount, UpdateCount
from olympia.versions.models import Version


class TestLastUpdated(TestCase):
    fixtures = ['base/addon_3615', 'addons/listed',
                'addons/persona', 'base/seamonkey', 'base/thunderbird']

    def test_personas(self):
        Addon.objects.update(type=amo.ADDON_PERSONA, status=amo.STATUS_PUBLIC)

        cron.addon_last_updated()
        for addon in Addon.objects.all():
            assert addon.last_updated == addon.created

        # Make sure it's stable.
        cron.addon_last_updated()
        for addon in Addon.objects.all():
            assert addon.last_updated == addon.created

    def test_catchall(self):
        """Make sure the catch-all last_updated is stable and accurate."""
        # Nullify all datestatuschanged so the public add-ons hit the
        # catch-all.
        (File.objects.filter(status=amo.STATUS_PUBLIC)
         .update(datestatuschanged=None))
        Addon.objects.update(last_updated=None)

        cron.addon_last_updated()
        for addon in Addon.objects.filter(status=amo.STATUS_PUBLIC,
                                          type=amo.ADDON_EXTENSION):
            assert addon.last_updated == addon.created

        # Make sure it's stable.
        cron.addon_last_updated()
        for addon in Addon.objects.filter(status=amo.STATUS_PUBLIC):
            assert addon.last_updated == addon.created

    def test_appsupport(self):
        ids = Addon.objects.values_list('id', flat=True)
        cron._update_appsupport(ids)
        assert AppSupport.objects.filter(app=amo.FIREFOX.id).count() == 4

        # Run it again to test deletes.
        cron._update_appsupport(ids)
        assert AppSupport.objects.filter(app=amo.FIREFOX.id).count() == 4

    def test_appsupport_listed(self):
        AppSupport.objects.all().delete()
        assert AppSupport.objects.filter(addon=3723).count() == 0
        cron.update_addon_appsupport()
        assert AppSupport.objects.filter(
            addon=3723, app=amo.FIREFOX.id).count() == 0

    def test_appsupport_seamonkey(self):
        addon = Addon.objects.get(pk=15663)
        addon.update(status=amo.STATUS_PUBLIC)
        AppSupport.objects.all().delete()
        cron.update_addon_appsupport()
        assert AppSupport.objects.filter(
            addon=15663, app=amo.SEAMONKEY.id).count() == 1


class TestHideDisabledFiles(TestCase):
    msg = 'Moving disabled file: %s => %s'

    def setUp(self):
        super(TestHideDisabledFiles, self).setUp()
        p = amo.PLATFORM_ALL.id
        self.addon = Addon.objects.create(type=amo.ADDON_EXTENSION)
        self.version = Version.objects.create(addon=self.addon)
        self.f1 = File.objects.create(version=self.version, platform=p,
                                      filename='f1')
        self.f2 = File.objects.create(version=self.version, filename='f2',
                                      platform=p)

    @mock.patch('olympia.files.models.os')
    def test_leave_nondisabled_files(self, os_mock):
        # All these addon/file status pairs should stay.
        stati = ((amo.STATUS_PUBLIC, amo.STATUS_PUBLIC),
                 (amo.STATUS_PUBLIC, amo.STATUS_AWAITING_REVIEW))
        for addon_status, file_status in stati:
            self.addon.update(status=addon_status)
            File.objects.update(status=file_status)
            cron.hide_disabled_files()
            assert not os_mock.path.exists.called, (addon_status, file_status)

    @mock.patch('olympia.files.models.File.move_file')
    def test_move_user_disabled_addon(self, mv_mock):
        # Use Addon.objects.update so the signal handler isn't called.
        Addon.objects.filter(id=self.addon.id).update(
            status=amo.STATUS_PUBLIC, disabled_by_user=True)
        File.objects.update(status=amo.STATUS_PUBLIC)
        cron.hide_disabled_files()
        # Check that f2 was moved.
        f2 = self.f2
        mv_mock.assert_called_with(f2.file_path, f2.guarded_file_path,
                                   self.msg)
        # Check that f1 was moved as well.
        f1 = self.f1
        mv_mock.call_args = mv_mock.call_args_list[0]
        mv_mock.assert_called_with(f1.file_path, f1.guarded_file_path,
                                   self.msg)
        # There's only 2 files, both should have been moved.
        assert mv_mock.call_count == 2

    @mock.patch('olympia.files.models.File.move_file')
    def test_move_admin_disabled_addon(self, mv_mock):
        Addon.objects.filter(id=self.addon.id).update(
            status=amo.STATUS_DISABLED)
        File.objects.update(status=amo.STATUS_PUBLIC)
        cron.hide_disabled_files()
        # Check that f2 was moved.
        f2 = self.f2
        mv_mock.assert_called_with(f2.file_path, f2.guarded_file_path,
                                   self.msg)
        # Check that f1 was moved as well.
        f1 = self.f1
        mv_mock.call_args = mv_mock.call_args_list[0]
        mv_mock.assert_called_with(f1.file_path, f1.guarded_file_path,
                                   self.msg)
        # There's only 2 files, both should have been moved.
        assert mv_mock.call_count == 2

    @mock.patch('olympia.files.models.File.move_file')
    def test_move_disabled_file(self, mv_mock):
        Addon.objects.filter(id=self.addon.id).update(status=amo.STATUS_PUBLIC)
        File.objects.filter(id=self.f1.id).update(status=amo.STATUS_DISABLED)
        File.objects.filter(id=self.f2.id).update(
            status=amo.STATUS_AWAITING_REVIEW)
        cron.hide_disabled_files()
        # Only f1 should have been moved.
        f1 = self.f1
        mv_mock.assert_called_with(f1.file_path, f1.guarded_file_path,
                                   self.msg)
        assert mv_mock.call_count == 1

    @mock.patch('olympia.files.models.storage.exists')
    @mock.patch('olympia.files.models.move_stored_file')
    def test_move_disabled_addon_ioerror(self, mv_mock, storage_exists):
        # raise an IOError for the first file, we need to make sure
        # that the second one is still being properly processed
        mv_mock.side_effect = [IOError, None]
        storage_exists.return_value = True

        # Use Addon.objects.update so the signal handler isn't called.
        Addon.objects.filter(id=self.addon.id).update(
            status=amo.STATUS_PUBLIC, disabled_by_user=True)
        File.objects.update(status=amo.STATUS_PUBLIC)

        cron.hide_disabled_files()

        # Check that f2 was moved.
        f2 = self.f2
        mv_mock.assert_called_with(f2.file_path, f2.guarded_file_path)

        # Check that f1 was moved as well.
        f1 = self.f1
        mv_mock.call_args = mv_mock.call_args_list[0]
        mv_mock.assert_called_with(f1.file_path, f1.guarded_file_path)

        # Make sure we called `mv` twice despite an `IOError` for the first
        # file
        assert mv_mock.call_count == 2


class TestUnhideDisabledFiles(TestCase):

    def setUp(self):
        super(TestUnhideDisabledFiles, self).setUp()
        p = amo.PLATFORM_ALL.id
        self.addon = Addon.objects.create(type=amo.ADDON_EXTENSION)
        self.version = Version.objects.create(addon=self.addon)
        self.file_ = File.objects.create(version=self.version, platform=p,
                                         filename=u'fé')

    @mock.patch('olympia.files.models.os')
    def test_leave_disabled_files(self, os_mock):
        self.addon.update(status=amo.STATUS_DISABLED)
        cron.unhide_disabled_files()
        assert not os_mock.path.exists.called

        self.addon.update(status=amo.STATUS_PUBLIC)
        self.file_.update(status=amo.STATUS_DISABLED)
        cron.unhide_disabled_files()
        assert not os_mock.path.exists.called

        self.addon.update(disabled_by_user=True)
        self.file_.update(status=amo.STATUS_PUBLIC)
        cron.unhide_disabled_files()
        assert not os_mock.path.exists.called

    @override_settings(GUARDED_ADDONS_PATH='/tmp/guarded-addons')
    @mock.patch('olympia.files.models.File.unhide_disabled_file')
    def test_move_not_disabled_files(self, unhide_mock):
        fpath = 'src/olympia/files/fixtures/files/jetpack.xpi'
        with amo.tests.copy_file(fpath, self.file_.guarded_file_path):
            # Make sure this works correctly with bytestring base paths
            # and doesn't raise a `UnicodeDecodeError`
            # Reverts what got introduced in #11000 but accidently
            # broke various other unicode-path related things
            # (e.g file viewer extraction)
            cron.unhide_disabled_files()
            assert unhide_mock.called


class TestAvgDailyUserCountTestCase(TestCase):
    fixtures = ['base/addon_3615']

    def setUp(self):
        super(TestAvgDailyUserCountTestCase, self).setUp()
        self.create_switch('local-statistics-processing')

    def test_13_day_window(self):
        addon = Addon.objects.get(pk=3615)

        # can't use a fixed date since we are relying on
        # mysql to get us the `CURDATE()`
        today = datetime.date.today()

        # data is coming from `tab groups` add-on from
        # jun 11 till may 29th 2017
        stats = [
            (today - datetime.timedelta(days=days_in_past), update_count)
            for days_in_past, update_count in (
                (1, 82708), (2, 78793), (3, 99586), (4, 104426), (5, 105431),
                (6, 106065), (7, 98093), (8, 81710), (9, 78843), (10, 99383),
                (11, 104431), (12, 105943), (13, 105039), (14, 100183),
                (15, 82265)
            )]

        UpdateCount.objects.bulk_create([
            UpdateCount(addon=addon, date=date, count=count)
            for date, count in stats
        ])

        addon.update(average_daily_users=0)

        cron.update_addon_average_daily_users()

        addon.refresh_from_db()

        assert (
            82708 + 78793 + 99586 + 104426 + 105431 + 106065 + 98093 +
            81710 + 78843 + 99383 + 104431 + 105943) / 12 == 95451

        assert addon.average_daily_users == 95451

    def test_adu_flag(self):
        addon = Addon.objects.get(pk=3615)

        now = datetime.datetime.now()
        counter = UpdateCount.objects.create(addon=addon, date=now,
                                             count=1234)
        counter.save()

        assert \
            addon.average_daily_users > addon.total_downloads + 10000, \
            ('Unexpected ADU count. ADU of %d not greater than %d' % (
                addon.average_daily_users, addon.total_downloads + 10000))

        adu = cron.update_addon_average_daily_users
        flag_reindexing_amo('new', 'old', 'alias')
        try:
            # Should fail.
            self.assertRaises(CommandError, adu)

            # Should work with the environ flag.
            os.environ['FORCE_INDEXING'] = '1'
            adu()
        finally:
            unflag_reindexing_amo()
            os.environ.pop('FORCE_INDEXING', None)

        addon = Addon.objects.get(pk=3615)
        assert addon.average_daily_users == 1234

    def test_total_and_average_downloads(self):
        addon = Addon.objects.get(pk=3615)
        old_total_downloads = addon.total_downloads
        DownloadCount.objects.update_or_create(
            addon=addon, date=datetime.date.today(), defaults={'count': 42})
        DownloadCount.objects.update_or_create(
            addon=addon,
            date=datetime.date.today() - datetime.timedelta(days=1),
            defaults={'count': 59})

        addon_deleted = addon_factory()
        addon_deleted.delete()
        DownloadCount.objects.update_or_create(
            addon=addon_deleted,
            date=datetime.date.today(), defaults={'count': 666})

        addon2 = addon_factory()
        DownloadCount.objects.update_or_create(
            addon=addon2,
            date=datetime.date.today() - datetime.timedelta(days=366),
            defaults={'count': 21})

        addon_factory()  # No downloads for this add-on

        cron.update_addon_download_totals()

        addon.reload()
        assert addon.total_downloads != old_total_downloads
        assert addon.total_downloads == 101

        addon2.reload()
        assert addon2.total_downloads == 21

    @mock.patch('olympia.addons.cron.Addon.objects.get')
    def test_total_and_average_downloads_addon_doesnotexist(self, get_mock):
        """Regression test

        for https://github.com/mozilla/addons-server/issues/8711
        """
        get_mock.side_effect = Addon.DoesNotExist()

        # Make sure that we don't raise an error when logging
        cron.update_addon_download_totals()


class TestCleanupImageFiles(TestCase):

    @mock.patch('olympia.addons.cron.os')
    def test_cleanup_image_files_exists(self, os_mock):
        cron.cleanup_image_files()
        assert os_mock.path.exists.called

    @mock.patch('olympia.addons.cron.os.unlink')
    @mock.patch('olympia.addons.cron.os.stat')
    @mock.patch('olympia.addons.cron.os.listdir')
    @mock.patch('olympia.addons.cron.os.path')
    def test_cleanup_image_files_age(self, os_path_mock, os_listdir_mock,
                                     os_stat_mock, os_unlink_mock):
        os_path_mock.exists.return_value = True
        os_listdir_mock.return_value = ['foo']

        young = datetime.datetime.today() - datetime.timedelta(hours=10)
        old = datetime.datetime.today() - datetime.timedelta(days=2)

        # Don't delete too young files.
        stat_mock = mock.Mock()
        stat_mock.st_atime = time.mktime(young.timetuple())
        os_stat_mock.return_value = stat_mock
        cron.cleanup_image_files()
        assert os_listdir_mock.called
        assert os_stat_mock.called
        assert not os_unlink_mock.called

        # Delete old files.
        stat_mock = mock.Mock()
        stat_mock.st_atime = time.mktime(old.timetuple())
        os_stat_mock.return_value = stat_mock
        cron.cleanup_image_files()
        assert os_listdir_mock.called
        assert os_stat_mock.called
        assert os_unlink_mock.called
