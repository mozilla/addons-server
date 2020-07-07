# -*- coding: utf-8 -*-
import datetime
import os

from django.core.files.storage import default_storage as storage
from django.test.utils import override_settings

from unittest import mock

from olympia import amo
from olympia.addons import cron
from olympia.addons.models import Addon, AppSupport
from olympia.amo.tests import addon_factory, file_factory, TestCase
from olympia.files.models import File
from olympia.stats.models import DownloadCount
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
        super().setUp()

        self.create_switch('local-statistics-processing')

    @mock.patch(
        'olympia.addons.cron.get_addons_and_average_daily_users_from_bigquery'
    )
    def test_update_addon_average_daily_users_with_bigquery(self, get_mock):
        addon = Addon.objects.get(pk=3615)
        addon.update(average_daily_users=0)
        count = 56789
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
        addon_without_count = addon_factory(type=amo.ADDON_DICT,
                                            average_daily_users=2)
        assert addon.average_daily_users == 0
        assert langpack.average_daily_users == 0
        assert dictionary.average_daily_users == 0
        assert addon_without_count.average_daily_users == 2

        # Pretend bigquery is returning correct data for the extension, but
        # also incorrect data for langpacks and dicts - we should ignore those.
        get_mock.return_value = [
            (addon.guid, count),
            (dictionary.guid, 42),
            (langpack.guid, 42),
        ]

        cron.update_addon_average_daily_users()
        addon.refresh_from_db()
        langpack.refresh_from_db()
        dictionary.refresh_from_db()
        addon_without_count.refresh_from_db()

        get_mock.assert_called
        assert addon.average_daily_users == count
        assert langpack.average_daily_users == langpack_count
        assert dictionary.average_daily_users == dictionary_count
        # The value is 0 because the add-on does not have download counts.
        assert addon_without_count.average_daily_users == 0

    @mock.patch('olympia.addons.cron.chunked')
    @mock.patch(
        'olympia.addons.cron.get_addons_and_average_daily_users_from_bigquery'
    )
    def test_update_addon_average_daily_users_values_with_bigquery(
        self, get_mock, chunked_mock
    ):
        chunked_mock.return_value = []
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
        DownloadCount.objects.update_or_create(
            addon=langpack,
            date=self.days_ago(3),
            defaults={'count': 0}
        )
        # We use download counts for dictionaries.
        dictionary = addon_factory(type=amo.ADDON_DICT, average_daily_users=0)
        dictionary_count = 6789
        DownloadCount.objects.update_or_create(
            addon=dictionary,
            date=datetime.date.today(),
            defaults={'count': 6780}
        )
        DownloadCount.objects.update_or_create(
            addon=dictionary,
            date=self.days_ago(2),
            defaults={'count': 9}
        )
        # This one should be ignored.
        addon_without_guid = addon_factory(guid=None, type=amo.ADDON_LPAPP)
        DownloadCount.objects.update_or_create(
            addon=addon_without_guid,
            date=datetime.date.today(),
            defaults={'count': 123}
        )
        # This one should be ignored as well.
        addon_factory(guid='', type=amo.ADDON_LPAPP)

        cron.update_addon_average_daily_users()

        chunked_mock.assert_called_with([
            (addon.guid, count),
            (langpack.guid, langpack_count),
            (dictionary.guid, dictionary_count),
        ], 250)

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
    def test_does_nothing(self):
        cron.deliver_hotness()
