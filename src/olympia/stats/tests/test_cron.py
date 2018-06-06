import datetime

from django.core.management import call_command

import mock
from freezegun import freeze_time

from olympia import amo
from olympia.amo.tests import TestCase, addon_factory, version_factory
from olympia.bandwagon.models import Collection, CollectionAddon
from olympia.stats import cron, tasks
from olympia.stats.models import (
    AddonCollectionCount, DownloadCount, GlobalStat, ThemeUserCount,
    UpdateCount)


class TestGlobalStats(TestCase):
    fixtures = ['stats/test_models']

    def test_stats_for_date(self):
        date = datetime.date(2009, 6, 1)
        job = 'addon_total_downloads'

        assert GlobalStat.objects.no_cache().filter(
            date=date, name=job).count() == 0
        tasks.update_global_totals(job, date)
        assert len(GlobalStat.objects.no_cache().filter(
            date=date, name=job)) == 1

    def test_count_stats_for_date(self):
        # Add a listed add-on, it should show up in "addon_count_new".
        listed_addon = addon_factory()

        # Add an unlisted version to that add-on, it should *not* increase the
        # "version_count_new" count.
        version_factory(
            addon=listed_addon, channel=amo.RELEASE_CHANNEL_UNLISTED)

        # Add an unlisted add-on, it should not show up in either
        # "addon_count_new" or "version_count_new".
        addon_factory(version_kw={
            'channel': amo.RELEASE_CHANNEL_UNLISTED
        })

        date = datetime.date.today()
        job = 'addon_count_new'
        tasks.update_global_totals(job, date)
        global_stat = GlobalStat.objects.no_cache().get(date=date, name=job)
        assert global_stat.count == 1

        # Should still work if the date is passed as a datetime string (what
        # celery serialization does).
        job = 'version_count_new'
        tasks.update_global_totals(job, datetime.datetime.now().isoformat())
        global_stat = GlobalStat.objects.no_cache().get(date=date, name=job)
        assert global_stat.count == 1

    def test_through_cron(self):
        # Yesterday, create some stuff.
        with freeze_time(datetime.datetime.now() - datetime.timedelta(days=1)):
            yesterday = datetime.date.today()

            # Add a listed add-on, it should show up in "addon_count_new".
            listed_addon = addon_factory()

            # Add an unlisted version to that add-on, it should *not* increase
            # the "version_count_new" count.
            version_factory(
                addon=listed_addon, channel=amo.RELEASE_CHANNEL_UNLISTED)

            # Add an unlisted add-on, it should not show up in either
            # "addon_count_new" or "version_count_new".
            addon_factory(version_kw={
                'channel': amo.RELEASE_CHANNEL_UNLISTED
            })

        # Launch the cron.
        cron.update_global_totals()

        job = 'addon_count_new'
        global_stat = GlobalStat.objects.no_cache().get(
            date=yesterday, name=job)
        assert global_stat.count == 1

        job = 'version_count_new'
        global_stat = GlobalStat.objects.no_cache().get(
            date=yesterday, name=job)
        assert global_stat.count == 1

    def test_input(self):
        for x in ['2009-1-1',
                  datetime.datetime(2009, 1, 1),
                  datetime.datetime(2009, 1, 1, 11, 0)]:
            with self.assertRaises((TypeError, ValueError)):
                tasks._get_daily_jobs(x)


@mock.patch('olympia.stats.management.commands.index_stats.create_subtasks')
class TestIndexStats(TestCase):
    fixtures = ['stats/test_models']

    def setUp(self):
        super(TestIndexStats, self).setUp()
        self.downloads = (DownloadCount.objects.order_by('-date')
                          .values_list('id', flat=True))
        self.updates = (UpdateCount.objects.order_by('-date')
                        .values_list('id', flat=True))
        self.theme_users = (ThemeUserCount.objects.order_by('-date')
                            .values_list('id', flat=True))

    def test_by_date(self, tasks_mock):
        call_command('index_stats', addons=None, date='2009-06-01')
        qs = self.downloads.filter(date='2009-06-01')
        download = tasks_mock.call_args_list[1][0]
        assert download[0] == tasks.index_download_counts
        assert download[1] == list(qs)

    def test_called_three(self, tasks_mock):
        call_command('index_stats', addons=None, date='2009-06-01')
        assert tasks_mock.call_count == 4

    def test_called_two(self, tasks_mock):
        call_command('index_stats', addons='5', date='2009-06-01')
        assert tasks_mock.call_count == 3

    def test_by_date_range(self, tasks_mock):
        call_command('index_stats', addons=None,
                     date='2009-06-01:2009-06-07')
        qs = self.downloads.filter(date__range=('2009-06-01', '2009-06-07'))
        download = tasks_mock.call_args_list[1][0]
        assert download[0] == tasks.index_download_counts
        assert download[1] == list(qs)

    def test_by_addon(self, tasks_mock):
        call_command('index_stats', addons='5', date=None)
        qs = self.downloads.filter(addon=5)
        download = tasks_mock.call_args_list[1][0]
        assert download[0] == tasks.index_download_counts
        assert download[1] == list(qs)

    def test_by_addon_and_date(self, tasks_mock):
        call_command('index_stats', addons='4', date='2009-06-01')
        qs = self.downloads.filter(addon=4, date='2009-06-01')
        download = tasks_mock.call_args_list[1][0]
        assert download[0] == tasks.index_download_counts
        assert download[1] == list(qs)

    def test_multiple_addons_and_date(self, tasks_mock):
        call_command('index_stats', addons='4, 5', date='2009-10-03')
        qs = self.downloads.filter(addon__in=[4, 5], date='2009-10-03')
        download = tasks_mock.call_args_list[1][0]
        assert download[0] == tasks.index_download_counts
        assert download[1] == list(qs)

    def test_no_addon_or_date(self, tasks_mock):
        call_command('index_stats', addons=None, date=None)
        calls = tasks_mock.call_args_list
        updates = list(self.updates.values_list('date', flat=True))
        downloads = list(self.downloads.values_list('date', flat=True))

        # Check that we're calling the task in increments of 5 days.
        # We add 1 because picking up 11 days means we have start/stop pairs at
        # [0, 5], [5, 10], [10, 15]
        len_ = len([c for c in calls if c[0][0] == tasks.index_update_counts])
        assert len_ == (1 + (updates[0] - updates[-1]).days / 5)
        len_ = len(
            [c for c in calls if c[0][0] == tasks.index_theme_user_counts])
        assert len_ == (1 + (updates[0] - updates[-1]).days / 5)
        len_ = len(
            [c for c in calls if c[0][0] == tasks.index_download_counts])
        assert len_ == (1 + (downloads[0] - downloads[-1]).days / 5)


class TestIndexLatest(amo.tests.ESTestCase):

    def test_index_latest(self):
        self.create_switch('local-statistics-processing')
        latest = datetime.date.today() - datetime.timedelta(days=5)
        UpdateCount.index({'date': latest})
        self.refresh('stats')

        start = latest.strftime('%Y-%m-%d')
        finish = datetime.date.today().strftime('%Y-%m-%d')
        with mock.patch('olympia.stats.cron.call_command') as call:
            cron.index_latest_stats()
            call.assert_called_with('index_stats', addons=None,
                                    date='%s:%s' % (start, finish))


class TestUpdateDownloads(TestCase):
    fixtures = ['base/users', 'base/collections', 'base/addon_3615']

    def test_addons_collections(self):
        collection2 = Collection.objects.create(name="collection2")
        CollectionAddon.objects.create(addon_id=3615, collection=collection2)
        vals = [(3, datetime.date(2013, 1, 1)),
                (5, datetime.date(2013, 1, 2)),
                (7, datetime.date(2013, 1, 3))]
        for col_id in (80, collection2.pk):
            for dls, dt in vals:
                AddonCollectionCount.objects.create(
                    addon_id=3615, collection_id=col_id,
                    count=dls, date=dt)

        with self.assertNumQueries(3):
            cron.update_addons_collections_downloads()
        assert CollectionAddon.objects.get(
            addon_id=3615, collection_id=80).downloads == 15
