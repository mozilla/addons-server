# -*- coding: utf8 -*-
import os
import datetime
import time

from django.core.management.base import CommandError
from django.test.utils import override_settings

from nose.tools import eq_
import mock

import amo
import amo.tests
from addons import cron
from addons.models import Addon, AppSupport
from files.models import File
from lib.es.utils import flag_reindexing_amo, unflag_reindexing_amo
from stats.models import UpdateCount
from versions.models import Version


class TestLastUpdated(amo.tests.TestCase):
    fixtures = ['base/addon_3615', 'addons/listed',
                'addons/persona', 'base/seamonkey', 'base/thunderbird']

    def test_personas(self):
        Addon.objects.update(type=amo.ADDON_PERSONA, status=amo.STATUS_PUBLIC)

        cron.addon_last_updated()
        for addon in Addon.objects.all():
            eq_(addon.last_updated, addon.created)

        # Make sure it's stable.
        cron.addon_last_updated()
        for addon in Addon.objects.all():
            eq_(addon.last_updated, addon.created)

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
            eq_(addon.last_updated, addon.created)

        # Make sure it's stable.
        cron.addon_last_updated()
        for addon in Addon.objects.filter(status=amo.STATUS_PUBLIC):
            eq_(addon.last_updated, addon.created)

    def test_last_updated_lite(self):
        # Make sure lite addons' last_updated matches their file's
        # datestatuschanged.
        Addon.objects.update(status=amo.STATUS_LITE, last_updated=None)
        File.objects.update(status=amo.STATUS_LITE)
        cron.addon_last_updated()
        addon = Addon.objects.get(id=3615)
        files = File.objects.filter(version__addon=addon)
        eq_(len(files), 1)
        eq_(addon.last_updated, files[0].datestatuschanged)
        assert addon.last_updated

    def test_last_update_lite_no_files(self):
        Addon.objects.update(status=amo.STATUS_LITE, last_updated=None)
        File.objects.update(status=amo.STATUS_UNREVIEWED)
        cron.addon_last_updated()
        addon = Addon.objects.get(id=3615)
        eq_(addon.last_updated, addon.created)
        assert addon.last_updated

    def test_appsupport(self):
        ids = Addon.objects.values_list('id', flat=True)
        cron._update_appsupport(ids)
        eq_(AppSupport.objects.filter(app=amo.FIREFOX.id).count(), 4)

        # Run it again to test deletes.
        cron._update_appsupport(ids)
        eq_(AppSupport.objects.filter(app=amo.FIREFOX.id).count(), 4)

    def test_appsupport_listed(self):
        AppSupport.objects.all().delete()
        eq_(AppSupport.objects.filter(addon=3723).count(), 0)
        cron.update_addon_appsupport()
        eq_(AppSupport.objects.filter(addon=3723,
                                      app=amo.FIREFOX.id).count(), 0)

    def test_appsupport_seamonkey(self):
        addon = Addon.objects.get(pk=15663)
        addon.update(status=amo.STATUS_PUBLIC)
        AppSupport.objects.all().delete()
        cron.update_addon_appsupport()
        eq_(AppSupport.objects.filter(addon=15663,
                                      app=amo.SEAMONKEY.id).count(), 1)


class TestHideDisabledFiles(amo.tests.TestCase):
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

    @mock.patch('files.models.os')
    def test_leave_nondisabled_files(self, os_mock):
        # All these addon/file status pairs should stay.
        stati = [(amo.STATUS_PUBLIC, amo.STATUS_PUBLIC),
                 (amo.STATUS_PUBLIC, amo.STATUS_UNREVIEWED),
                 (amo.STATUS_PUBLIC, amo.STATUS_BETA),
                 (amo.STATUS_LITE, amo.STATUS_UNREVIEWED),
                 (amo.STATUS_LITE, amo.STATUS_LITE),
                 (amo.STATUS_LITE_AND_NOMINATED, amo.STATUS_UNREVIEWED),
                 (amo.STATUS_LITE_AND_NOMINATED, amo.STATUS_LITE)]
        for addon_status, file_status in stati:
            self.addon.update(status=addon_status)
            File.objects.update(status=file_status)
            cron.hide_disabled_files()
            assert not os_mock.path.exists.called, (addon_status, file_status)

    @mock.patch('files.models.File.mv')
    @mock.patch('files.models.storage')
    def test_move_user_disabled_addon(self, m_storage, mv_mock):
        # Use Addon.objects.update so the signal handler isn't called.
        Addon.objects.filter(id=self.addon.id).update(
            status=amo.STATUS_PUBLIC, disabled_by_user=True)
        File.objects.update(status=amo.STATUS_PUBLIC)
        cron.hide_disabled_files()
        # Check that f2 was moved.
        f2 = self.f2
        mv_mock.assert_called_with(f2.file_path, f2.guarded_file_path,
                                   self.msg)
        m_storage.delete.assert_called_with(f2.mirror_file_path)
        # Check that f1 was moved as well.
        f1 = self.f1
        mv_mock.call_args = mv_mock.call_args_list[0]
        m_storage.delete.call_args = m_storage.delete.call_args_list[0]
        mv_mock.assert_called_with(f1.file_path, f1.guarded_file_path,
                                   self.msg)
        m_storage.delete.assert_called_with(f1.mirror_file_path)
        # There's only 2 files, both should have been moved.
        eq_(mv_mock.call_count, 2)
        eq_(m_storage.delete.call_count, 2)

    @mock.patch('files.models.File.mv')
    @mock.patch('files.models.storage')
    def test_move_admin_disabled_addon(self, m_storage, mv_mock):
        Addon.objects.filter(id=self.addon.id).update(
            status=amo.STATUS_DISABLED)
        File.objects.update(status=amo.STATUS_PUBLIC)
        cron.hide_disabled_files()
        # Check that f2 was moved.
        f2 = self.f2
        mv_mock.assert_called_with(f2.file_path, f2.guarded_file_path,
                                   self.msg)
        m_storage.delete.assert_called_with(f2.mirror_file_path)
        # Check that f1 was moved as well.
        f1 = self.f1
        mv_mock.call_args = mv_mock.call_args_list[0]
        m_storage.delete.call_args = m_storage.delete.call_args_list[0]
        mv_mock.assert_called_with(f1.file_path, f1.guarded_file_path,
                                   self.msg)
        m_storage.delete.assert_called_with(f1.mirror_file_path)
        # There's only 2 files, both should have been moved.
        eq_(mv_mock.call_count, 2)
        eq_(m_storage.delete.call_count, 2)

    @mock.patch('files.models.File.mv')
    @mock.patch('files.models.storage')
    def test_move_disabled_file(self, m_storage, mv_mock):
        Addon.objects.filter(id=self.addon.id).update(status=amo.STATUS_LITE)
        File.objects.filter(id=self.f1.id).update(status=amo.STATUS_DISABLED)
        File.objects.filter(id=self.f2.id).update(status=amo.STATUS_UNREVIEWED)
        cron.hide_disabled_files()
        # Only f1 should have been moved.
        f1 = self.f1
        mv_mock.assert_called_with(f1.file_path, f1.guarded_file_path,
                                   self.msg)
        eq_(mv_mock.call_count, 1)
        # It should have been removed from mirror stagins.
        m_storage.delete.assert_called_with(f1.mirror_file_path)
        eq_(m_storage.delete.call_count, 1)


class TestUnhideDisabledFiles(amo.tests.TestCase):

    def setUp(self):
        super(TestUnhideDisabledFiles, self).setUp()
        p = amo.PLATFORM_ALL.id
        self.addon = Addon.objects.create(type=amo.ADDON_EXTENSION)
        self.version = Version.objects.create(addon=self.addon)
        self.file_ = File.objects.create(version=self.version, platform=p,
                                         filename=u'fé')

    @mock.patch('files.models.os')
    def test_leave_disabled_files(self, os_mock):
        self.addon.update(status=amo.STATUS_DISABLED)
        cron.unhide_disabled_files()
        assert not os_mock.path.exists.called

        self.addon.update(status=amo.STATUS_LITE)
        self.file_.update(status=amo.STATUS_DISABLED)
        cron.unhide_disabled_files()
        assert not os_mock.path.exists.called

        self.addon.update(disabled_by_user=True)
        self.file_.update(status=amo.STATUS_LITE)
        cron.unhide_disabled_files()
        assert not os_mock.path.exists.called

    @override_settings(GUARDED_ADDONS_PATH=u'/tmp/guarded-addons')
    @mock.patch('files.models.File.unhide_disabled_file')
    def test_move_not_disabled_files(self, unhide_mock):
        with amo.tests.copy_file('apps/files/fixtures/files/jetpack.xpi',
                                 self.file_.guarded_file_path):
            cron.unhide_disabled_files()
            assert unhide_mock.called

            # Not a unicode string for the path.
            with override_settings(GUARDED_ADDONS_PATH='/tmp/guarded-addons'):
                with self.assertRaises(UnicodeDecodeError):
                    # If the parameter to "os.walk" (called by
                    # amo.utils.walkfiles) isn't a unicode string, it'll return
                    # ascii encoded paths, which will break the File query with
                    # the filename, raising the exception.
                    cron.unhide_disabled_files()


class AvgDailyUserCountTestCase(amo.tests.TestCase):
    fixtures = ['base/addon_3615']

    def setUp(self):
        super(AvgDailyUserCountTestCase, self).setUp()
        self.create_switch('local-statistics-processing')

    def test_adu_is_adjusted_in_cron(self):
        addon = Addon.objects.get(pk=3615)
        eq_(addon.average_daily_users, 6000000)
        self.assertTrue(
            addon.average_daily_users > addon.total_downloads + 10000,
            'Unexpected ADU count. ADU of %d not greater than %d' % (
                addon.average_daily_users, addon.total_downloads + 10000))
        cron._update_addon_average_daily_users([(3615, 6000000)])
        addon = Addon.objects.get(pk=3615)
        eq_(addon.average_daily_users, addon.total_downloads)

    def test_adu_flag(self):
        addon = Addon.objects.get(pk=3615)

        now = datetime.datetime.now()
        counter = UpdateCount.objects.create(addon=addon, date=now,
                                             count=1234)
        counter.save()

        self.assertTrue(
            addon.average_daily_users > addon.total_downloads + 10000,
            'Unexpected ADU count. ADU of %d not greater than %d' % (
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
        eq_(addon.average_daily_users, 1234)


class TestCleanupImageFiles(amo.tests.TestCase):

    @mock.patch('addons.cron.os')
    def test_cleanup_image_files_exists(self, os_mock):
        cron.cleanup_image_files()
        assert os_mock.path.exists.called

    @mock.patch('addons.cron.os.unlink')
    @mock.patch('addons.cron.os.stat')
    @mock.patch('addons.cron.os.listdir')
    @mock.patch('addons.cron.os.path')
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
