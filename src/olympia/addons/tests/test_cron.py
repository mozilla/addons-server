from unittest import mock

from celery import group

from olympia import amo
from olympia.addons import cron
from olympia.addons.models import Addon, FrozenAddon
from olympia.addons.tasks import (
    update_addon_average_daily_users,
    update_addon_weekly_downloads,
)
from olympia.amo.tests import TestCase, addon_factory
from olympia.files.models import File


class TestLastUpdated(TestCase):
    fixtures = ['base/addon_3615', 'addons/listed']

    def test_catchall(self):
        """Make sure the catch-all last_updated is stable and accurate."""
        # Nullify all datestatuschanged so the public add-ons hit the
        # catch-all.
        (File.objects.filter(status=amo.STATUS_APPROVED).update(datestatuschanged=None))
        Addon.objects.update(last_updated=None)

        cron.addon_last_updated()
        for addon in Addon.objects.filter(
            status=amo.STATUS_APPROVED, type=amo.ADDON_EXTENSION
        ):
            assert addon.last_updated == addon.created

        # Make sure it's stable.
        cron.addon_last_updated()
        for addon in Addon.objects.filter(status=amo.STATUS_APPROVED):
            assert addon.last_updated == addon.created


class TestAvgDailyUserCountTestCase(TestCase):
    fixtures = ['base/addon_3615']

    def setUp(self):
        super().setUp()

    @mock.patch('olympia.addons.cron.get_addons_and_average_daily_users_from_bigquery')
    def test_update_addon_average_daily_users_with_bigquery(self, get_mock):
        addon = Addon.objects.get(pk=3615)
        addon.update(average_daily_users=0)
        count = 56789
        langpack = addon_factory(type=amo.ADDON_LPAPP, average_daily_users=0)
        langpack_count = 12345
        dictionary = addon_factory(type=amo.ADDON_DICT, average_daily_users=0)
        dictionary_count = 5567
        addon_without_count = addon_factory(type=amo.ADDON_DICT, average_daily_users=2)
        deleted_addon = addon_factory(average_daily_users=0)
        deleted_addon_count = 23456
        deleted_addon.delete()
        assert addon.average_daily_users == 0
        assert langpack.average_daily_users == 0
        assert dictionary.average_daily_users == 0
        assert addon_without_count.average_daily_users == 2
        assert deleted_addon.average_daily_users == 0

        get_mock.return_value = [
            (addon.guid, count),
            (dictionary.guid, dictionary_count),
            (langpack.guid, langpack_count),
            (deleted_addon.guid, deleted_addon_count),
        ]

        cron.update_addon_average_daily_users()
        addon.refresh_from_db()
        langpack.refresh_from_db()
        dictionary.refresh_from_db()
        addon_without_count.refresh_from_db()
        deleted_addon.refresh_from_db()

        get_mock.assert_called()
        assert addon.average_daily_users == count
        assert langpack.average_daily_users == langpack_count
        assert dictionary.average_daily_users == dictionary_count
        assert deleted_addon.average_daily_users == deleted_addon_count
        # The value is 0 because the add-on does not exist in BigQuery.
        assert addon_without_count.average_daily_users == 0

    @mock.patch(
        'olympia.addons.cron.flag_high_abuse_reports_addons_according_to_review_tier.si'
    )
    @mock.patch('olympia.addons.cron.add_high_adu_extensions_to_notable.si')
    @mock.patch('olympia.addons.cron.create_chunked_tasks_signatures')
    @mock.patch('olympia.addons.cron.get_addons_and_average_daily_users_from_bigquery')
    def test_update_addon_average_daily_users_values_with_bigquery(
        self,
        get_mock,
        create_chunked_mock,
        add_high_adu_extensions_to_notable_mock,
        flag_high_abuse_reports_addons_according_to_review_tier_mock,
    ):
        create_chunked_mock.return_value = group([])
        addon = Addon.objects.get(pk=3615)
        addon.update(average_daily_users=0)
        count = 56789
        langpack = addon_factory(type=amo.ADDON_LPAPP, average_daily_users=0)
        langpack_count = 12345
        dictionary = addon_factory(type=amo.ADDON_DICT, average_daily_users=0)
        dictionary_count = 6789
        addon_without_count = addon_factory(type=amo.ADDON_DICT, average_daily_users=2)
        # This one should be ignored.
        addon_factory(guid=None, type=amo.ADDON_LPAPP)
        # This one should be ignored as well.
        addon_factory(guid='', type=amo.ADDON_LPAPP)
        # Deleted add-ons should still have their usage updated.
        deleted_addon = addon_factory(average_daily_users=0)
        deleted_addon_count = 23456
        deleted_addon.delete()

        get_mock.return_value = [
            (addon.guid, count),
            (langpack.guid, langpack_count),
            (dictionary.guid, dictionary_count),
            (deleted_addon.guid, deleted_addon_count),
        ]

        chunk_size = 123
        cron.update_addon_average_daily_users(chunk_size)

        create_chunked_mock.assert_called_with(
            update_addon_average_daily_users,
            [
                (addon_without_count.guid, 0),
                (addon.guid, count),
                (langpack.guid, langpack_count),
                (dictionary.guid, dictionary_count),
                (deleted_addon.guid, deleted_addon_count),
            ],
            chunk_size,
        )

        assert add_high_adu_extensions_to_notable_mock.call_count == 1
        assert (
            flag_high_abuse_reports_addons_according_to_review_tier_mock.call_count == 1
        )


class TestUpdateAddonHotness(TestCase):
    def setUp(self):
        super().setUp()

        self.extension = addon_factory()
        self.unpopular_extension = addon_factory()
        self.barely_popular_extension = addon_factory()
        self.static_theme = addon_factory(type=amo.ADDON_STATICTHEME)
        self.unpopular_theme = addon_factory(type=amo.ADDON_STATICTHEME)
        self.barely_popular_theme = addon_factory(type=amo.ADDON_STATICTHEME)
        self.awaiting_review = addon_factory(status=amo.STATUS_NOMINATED)
        self.deleted_extension = addon_factory()
        self.deleted_extension.delete()

        self.frozen_extension = addon_factory()
        FrozenAddon.objects.create(addon=self.frozen_extension)
        # This frozen add-on should be ignored.
        FrozenAddon.objects.create(addon=addon_factory(guid=None))

        self.not_in_bigquery = addon_factory(hotness=123)
        self.deleted_not_in_bigquery = addon_factory(hotness=666)
        self.deleted_not_in_bigquery.delete()

    @mock.patch('olympia.addons.cron.flag_high_hotness_according_to_review_tier.si')
    @mock.patch('olympia.addons.cron.get_averages_by_addon_from_bigquery')
    def test_basic(self, get_averages_mock, flag_high_hotness_mock):
        get_averages_mock.return_value = {
            self.extension.guid: {
                'avg_this_week': 827080,
                'avg_previous_week': 787930,
            },
            self.static_theme.guid: {
                'avg_this_week': 827080,
                'avg_previous_week': 787930,
            },
            self.unpopular_extension.guid: {
                'avg_this_week': 99,
                'avg_previous_week': 150,
            },
            self.unpopular_theme.guid: {
                'avg_this_week': 249,
                'avg_previous_week': 300,
            },
            self.barely_popular_extension.guid: {
                'avg_this_week': 100,
                'avg_previous_week': 75,
            },
            self.barely_popular_theme.guid: {
                'avg_this_week': 250,
                'avg_previous_week': 188,
            },
            'unknown@guid': {
                'avg_this_week': 10000,
                'avg_previous_week': 10000,
            },
            self.awaiting_review.guid: {
                'avg_this_week': 827080,
                'avg_previous_week': 787930,
            },
            self.deleted_extension.guid: {
                'avg_this_week': 1040,
                'avg_previous_week': 1000,
            },
        }

        cron.update_addon_hotness()

        assert self.extension.reload().hotness == 0.049687154950312847
        assert self.static_theme.reload().hotness == 0.049687154950312847

        # Unpopular extensions and static themes have a hotness of 0.
        assert self.unpopular_extension.reload().hotness == 0
        assert self.unpopular_theme.reload().hotness == 0

        # Themes have different threshold for popularity, and we only start
        # computing hotness for them above 250. This one barely matches that.
        assert self.barely_popular_theme.reload().hotness == 0.32978723404255317

        # For extensions it's above 100.
        assert self.barely_popular_extension.reload().hotness == 0.3333333333333333

        # Deleted or awaiting review add-ons get a hotness too.
        assert self.awaiting_review.reload().hotness == 0.049687154950312847
        assert self.deleted_extension.reload().hotness == 0.04

        # Exclude frozen add-ons too.
        assert self.frozen_extension.reload().hotness == 0
        get_averages_mock.assert_called_once_with(
            today=mock.ANY, exclude=[self.frozen_extension.guid]
        )

        assert self.not_in_bigquery.reload().hotness == 0
        assert self.deleted_not_in_bigquery.reload().hotness == 0

        assert flag_high_hotness_mock.call_count == 1


class TestUpdateAddonWeeklyDownloads(TestCase):
    @mock.patch('olympia.addons.cron.create_chunked_tasks_signatures')
    @mock.patch('olympia.addons.cron.get_addons_and_weekly_downloads_from_bigquery')
    def test_calls_create_chunked_tasks_signatures(self, get_mock, create_chunked_mock):
        create_chunked_mock.return_value = group([])
        addon = addon_factory(weekly_downloads=0)
        count = 56789
        langpack = addon_factory(type=amo.ADDON_LPAPP, weekly_downloads=0)
        langpack_count = 12345
        dictionary = addon_factory(type=amo.ADDON_DICT, weekly_downloads=0)
        dictionary_count = 6789
        addon_without_count = addon_factory(type=amo.ADDON_DICT, weekly_downloads=2)
        # This one should be ignored.
        addon_factory(guid=None, type=amo.ADDON_LPAPP)
        # This one should be ignored as well.
        addon_factory(guid='', type=amo.ADDON_LPAPP)
        get_mock.return_value = [
            (addon.addonguid.hashed_guid, count),
            (langpack.addonguid.hashed_guid, langpack_count),
            (dictionary.addonguid.hashed_guid, dictionary_count),
        ]

        chunk_size = 123
        cron.update_addon_weekly_downloads(chunk_size)

        create_chunked_mock.assert_called_with(
            update_addon_weekly_downloads,
            [
                (addon_without_count.addonguid.hashed_guid, 0),
                (addon.addonguid.hashed_guid, count),
                (langpack.addonguid.hashed_guid, langpack_count),
                (dictionary.addonguid.hashed_guid, dictionary_count),
            ],
            chunk_size,
        )

    @mock.patch('olympia.addons.cron.get_addons_and_weekly_downloads_from_bigquery')
    def test_update_weekly_downloads(self, get_mock):
        addon = addon_factory(weekly_downloads=0)
        count = 56789
        get_mock.return_value = [(addon.addonguid.hashed_guid, count)]

        cron.update_addon_weekly_downloads()
        addon.refresh_from_db()

        assert addon.weekly_downloads == count
