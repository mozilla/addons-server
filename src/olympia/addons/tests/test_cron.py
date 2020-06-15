# -*- coding: utf-8 -*-
import datetime
import os

from django.core.files.storage import default_storage as storage
from django.core.management.base import CommandError
from django.test.utils import override_settings
from waffle.testutils import override_switch

from unittest import mock

from olympia import amo
from olympia.addons import cron
from olympia.addons.models import Addon, AppSupport
from olympia.amo.tests import addon_factory, file_factory, TestCase
from olympia.files.models import File
from olympia.lib.es.utils import flag_reindexing_amo, unflag_reindexing_amo
from olympia.stats.models import DownloadCount, UpdateCount
from olympia.versions.models import Version


class TestLastUpdated(TestCase):
    fixtures = ['base/addon_3615', 'addons/listed']

    def test_catchall(self):
        """Make sure the catch-all last_updated is stable and accurate."""
        # Nullify all datestatuschanged so the public add-ons hit the
        # catch-all.
        (File.objects.filter(status=amo.STATUS_APPROVED)
         .update(datestatuschanged=None))
        Addon.objects.update(last_updated=None)

        cron.addon_last_updated()
        for addon in Addon.objects.filter(status=amo.STATUS_APPROVED,
                                          type=amo.ADDON_EXTENSION):
            assert addon.last_updated == addon.created

        # Make sure it's stable.
        cron.addon_last_updated()
        for addon in Addon.objects.filter(status=amo.STATUS_APPROVED):
            assert addon.last_updated == addon.created

    def test_appsupport(self):
        ids = Addon.objects.values_list('id', flat=True)
        cron.update_appsupport(ids)
        assert AppSupport.objects.filter(app=amo.FIREFOX.id).count() == 2

        # Run it again to test deletes.
        cron.update_appsupport(ids)
        assert AppSupport.objects.filter(app=amo.FIREFOX.id).count() == 2

    def test_appsupport_listed(self):
        AppSupport.objects.all().delete()
        assert AppSupport.objects.filter(addon=3723).count() == 0
        cron.update_addon_appsupport()
        assert AppSupport.objects.filter(
            addon=3723, app=amo.FIREFOX.id).count() == 0


class TestHideDisabledFiles(TestCase):
    msg = 'Moving disabled file: {source} => {destination}'

    def setUp(self):
        super(TestHideDisabledFiles, self).setUp()
        self.addon = Addon.objects.create(type=amo.ADDON_EXTENSION)
        self.version = Version.objects.create(addon=self.addon)
        self.f1 = File.objects.create(version=self.version, filename='f1',
                                      platform=amo.PLATFORM_ALL.id)
        self.f2 = File.objects.create(version=self.version, filename='f2',
                                      platform=amo.PLATFORM_ALL.id)

    @mock.patch('olympia.files.models.os')
    def test_leave_nondisabled_files(self, os_mock):
        # All these addon/file status pairs should stay.
        stati = ((amo.STATUS_APPROVED, amo.STATUS_APPROVED),
                 (amo.STATUS_APPROVED, amo.STATUS_AWAITING_REVIEW))
        for addon_status, file_status in stati:
            self.addon.update(status=addon_status)
            File.objects.update(status=file_status)
            cron.hide_disabled_files()
            assert not os_mock.path.exists.called, (addon_status, file_status)
            assert not os_mock.path.remove.called, (addon_status, file_status)
            assert not os_mock.path.rmdir.called, (addon_status, file_status)

    @mock.patch('olympia.files.models.File.move_file')
    def test_move_user_disabled_addon(self, mv_mock):
        # Use Addon.objects.update so the signal handler isn't called.
        Addon.objects.filter(id=self.addon.id).update(
            status=amo.STATUS_APPROVED, disabled_by_user=True)
        File.objects.update(status=amo.STATUS_APPROVED)
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
        File.objects.update(status=amo.STATUS_APPROVED)
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
        Addon.objects.filter(id=self.addon.id).update(
            status=amo.STATUS_APPROVED)
        File.objects.filter(id=self.f1.id).update(
            status=amo.STATUS_DISABLED)
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
            status=amo.STATUS_APPROVED, disabled_by_user=True)
        File.objects.update(status=amo.STATUS_APPROVED)

        cron.hide_disabled_files()

        # Check that we called `move_stored_file` for f2 properly
        f2 = self.f2
        mv_mock.assert_called_with(f2.file_path, f2.guarded_file_path)

        # Check that we called `move_stored_file` for f1 properly
        f1 = self.f1
        mv_mock.call_args = mv_mock.call_args_list[0]
        mv_mock.assert_called_with(f1.file_path, f1.guarded_file_path)

        # Make sure we called `mv` twice despite an `IOError` for the first
        # file
        assert mv_mock.call_count == 2


class TestUnhideDisabledFiles(TestCase):
    msg = 'Moving undisabled file: {source} => {destination}'

    def setUp(self):
        super(TestUnhideDisabledFiles, self).setUp()
        self.addon = Addon.objects.create(type=amo.ADDON_EXTENSION)
        self.version = Version.objects.create(addon=self.addon)
        self.file_ = File.objects.create(
            version=self.version, platform=amo.PLATFORM_ALL.id, filename=u'fé')

    @mock.patch('olympia.files.models.os')
    def test_leave_disabled_files(self, os_mock):
        self.addon.update(status=amo.STATUS_DISABLED)
        cron.unhide_disabled_files()
        assert not os_mock.path.exists.called
        assert not os_mock.path.remove.called
        assert not os_mock.path.rmdir.called

        self.addon.update(status=amo.STATUS_APPROVED)
        self.file_.update(status=amo.STATUS_DISABLED)
        cron.unhide_disabled_files()
        assert not os_mock.path.exists.called
        assert not os_mock.path.remove.called
        assert not os_mock.path.rmdir.called

        self.addon.update(disabled_by_user=True)
        self.file_.update(status=amo.STATUS_APPROVED)
        cron.unhide_disabled_files()
        assert not os_mock.path.exists.called
        assert not os_mock.path.remove.called
        assert not os_mock.path.rmdir.called

    @mock.patch('olympia.files.models.File.move_file')
    def test_move_public_files(self, mv_mock):
        self.addon.update(status=amo.STATUS_APPROVED)
        self.file_.update(status=amo.STATUS_APPROVED)
        cron.unhide_disabled_files()
        mv_mock.assert_called_with(
            self.file_.guarded_file_path, self.file_.file_path, self.msg)
        assert mv_mock.call_count == 1

    def test_cleans_up_empty_directories_after_moving(self):
        self.addon.update(status=amo.STATUS_APPROVED)
        self.file_.update(status=amo.STATUS_APPROVED)
        with storage.open(self.file_.guarded_file_path, 'wb') as fp:
            fp.write(b'content')
        assert not storage.exists(self.file_.file_path)
        assert storage.exists(self.file_.guarded_file_path)

        cron.unhide_disabled_files()

        assert storage.exists(self.file_.file_path)
        assert not storage.exists(self.file_.guarded_file_path)
        # Empty dir also removed:
        assert not storage.exists(
            os.path.dirname(self.file_.guarded_file_path))

    def test_doesnt_remove_non_empty_directories(self):
        # Add an extra disabled file. The approved one should move, but not the
        # other, so the directory should be left intact.
        self.disabled_file = file_factory(
            version=self.version, status=amo.STATUS_DISABLED)
        self.addon.update(status=amo.STATUS_APPROVED)
        self.file_.update(status=amo.STATUS_APPROVED)
        with storage.open(self.file_.guarded_file_path, 'wb') as fp:
            fp.write(b'content')
        assert not storage.exists(self.file_.file_path)
        assert storage.exists(self.file_.guarded_file_path)
        with storage.open(self.disabled_file.guarded_file_path, 'wb') as fp:
            fp.write(b'disabled content')
        assert not storage.exists(self.disabled_file.file_path)
        assert storage.exists(self.disabled_file.guarded_file_path)

        cron.unhide_disabled_files()

        assert storage.exists(self.file_.file_path)
        assert not storage.exists(self.file_.guarded_file_path)

        # The disabled file shouldn't have moved.
        assert not storage.exists(self.disabled_file.file_path)
        assert storage.exists(self.disabled_file.guarded_file_path)
        # The directory in guarded file path should still exist.
        assert storage.exists(os.path.dirname(self.file_.guarded_file_path))

    @override_settings(GUARDED_ADDONS_PATH='/tmp/guarded-addons')
    @mock.patch('olympia.files.models.File.unhide_disabled_file')
    def test_move_not_disabled_files(self, unhide_mock):
        fpath = 'src/olympia/files/fixtures/files/webextension.xpi'
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

    @override_switch('use-bigquery-for-addon-adu', active=True)
    @mock.patch(
        'olympia.addons.cron.get_addons_and_average_daily_users_from_bigquery'
    )
    def test_update_addon_average_daily_users_with_bigquery(self, get_mock):
        addon = Addon.objects.get(pk=3615)
        addon.update(average_daily_users=0)
        count = 56789
        get_mock.return_value = [(addon.guid, count)]
        # We use download counts for langpacks.
        langpack = addon_factory(type=amo.ADDON_LPAPP, average_daily_users=0)
        langpack_count = 12345
        DownloadCount.objects.update_or_create(
            addon=langpack,
            date=datetime.date.today(),
            defaults={'count': langpack_count}
        )
        # We use download counts for dictionaries.
        dictionary = addon_factory(type=amo.ADDON_DICT, average_daily_users=0)
        dictionary_count = 5567
        DownloadCount.objects.update_or_create(
            addon=dictionary,
            date=datetime.date.today(),
            defaults={'count': dictionary_count}
        )
        assert addon.average_daily_users == 0
        assert langpack.average_daily_users == 0
        assert dictionary.average_daily_users == 0

        cron.update_addon_average_daily_users()
        addon.refresh_from_db()
        langpack.refresh_from_db()
        dictionary.refresh_from_db()

        get_mock.assert_called
        assert addon.average_daily_users == count
        assert langpack.average_daily_users == langpack_count
        assert dictionary.average_daily_users == dictionary_count

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


class TestDeliverHotness(TestCase):
    def setUp(self):
        self.extension = addon_factory()
        self.static_theme = addon_factory(type=amo.ADDON_STATICTHEME)
        self.unpopular_extension = addon_factory()
        self.unpopular_theme = addon_factory(type=amo.ADDON_STATICTHEME)
        self.barely_popular_theme = addon_factory(
            type=amo.ADDON_STATICTHEME)
        self.same_stats_as_barely_popular_theme = addon_factory()
        self.awaiting_review = addon_factory(status=amo.STATUS_NOMINATED)

        today = datetime.date.today()

        stats = [
            (today - datetime.timedelta(days=days_in_past), update_count)
            for days_in_past, update_count in (
                (1, 827080), (2, 787930), (3, 995860), (4, 1044260),
                (5, 105431), (6, 106065), (7, 980930), (8, 817100), (9, 78843),
                (10, 993830), (11, 104431), (12, 105943), (13, 105039),
                (14, 100183), (15, 82265), (16, 100183), (17, 82265),
                (18, 100183), (19, 82265), (20, 100183), (21, 82265),

            )]

        unpopular_stats = [
            (today - datetime.timedelta(days=days_in_past), update_count)
            for days_in_past, update_count in (
                (1, 99), (2, 76), (3, 25), (4, 32),
                (5, 289), (6, 34), (7, 45), (8, 25), (9, 78),
                (10, 36), (11, 25), (12, 100), (13, 156),
                (14, 24), (15, 9), (16, 267), (17, 176),
                (18, 16), (19, 156), (20, 187), (21, 149),

            )]

        barely_popular_stats = [
            (today - datetime.timedelta(days=days_in_past), update_count)
            for days_in_past, update_count in (
                (1, 399), (2, 276), (3, 215), (4, 312),
                (5, 289), (6, 234), (7, 345), (8, 205), (9, 178),
                (10, 336), (11, 325), (12, 400), (13, 456),
                (14, 324), (15, 290), (16, 267), (17, 276),
                (18, 216), (19, 256), (20, 287), (21, 249),

            )]

        for obj in (self.extension, self.static_theme,
                    self.awaiting_review):
            UpdateCount.objects.bulk_create([
                UpdateCount(addon=obj, date=date, count=count)
                for date, count in stats
            ])

        for obj in (self.unpopular_extension, self.unpopular_theme):
            UpdateCount.objects.bulk_create([
                UpdateCount(addon=obj, date=date, count=count)
                for date, count in unpopular_stats
            ])

        for obj in (self.barely_popular_theme,
                    self.same_stats_as_barely_popular_theme):
            UpdateCount.objects.bulk_create([
                UpdateCount(addon=obj, date=date, count=count)
                for date, count in barely_popular_stats
            ])

    @mock.patch('olympia.addons.cron.time.sleep', lambda *a, **kw: None)
    def test_basic(self):
        cron.deliver_hotness()

        assert self.extension.reload().hotness == 1.652672126445855
        assert self.static_theme.reload().hotness == 1.652672126445855

        # Unpopular extensions and static themes have a hotness of 0
        assert self.unpopular_extension.reload().hotness == 0
        assert self.unpopular_theme.reload().hotness == 0

        # A barely popular static theme should have a hotness value > 0
        # but when the same stats are applied to an extension,
        # it should have a hotness of 0
        assert (
            self.barely_popular_theme.reload().hotness ==
            0.0058309523809523135)
        assert (
            self.same_stats_as_barely_popular_theme.reload().hotness ==
            0)

        # Only public add-ons get hotness calculated
        assert self.awaiting_review.reload().hotness == 0

    @mock.patch('olympia.addons.cron.time.sleep', lambda *a, **kw: None)
    def test_avoid_overwriting_values(self):
        cron.deliver_hotness()

        assert self.extension.reload().hotness == 1.652672126445855

        # Make sure we don't update add-ons if nothing changed
        with mock.patch('olympia.addons.cron.Addon.update') as mocked_update:
            cron.deliver_hotness()

        assert not mocked_update.called
