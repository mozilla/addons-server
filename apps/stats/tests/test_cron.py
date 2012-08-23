import datetime

from django.core.management import call_command

import mock
from nose.tools import eq_

import amo.tests
from addons.models import Addon
from stats.models import (Contribution, DownloadCount, GlobalStat,
                          UpdateCount)
from stats import cron, tasks


class TestGlobalStats(amo.tests.TestCase):
    fixtures = ['stats/test_models']

    def test_stats_for_date(self):

        date = '2009-06-01'
        job = 'addon_total_downloads'

        eq_(GlobalStat.objects.no_cache().filter(date=date,
                                                 name=job).count(), 0)
        tasks.update_global_totals(job, date)
        eq_(len(GlobalStat.objects.no_cache().filter(date=date,
                                                 name=job)), 1)


class TestTotalContributions(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/appversion', 'base/users',
                'base/addon_3615']

    def test_total_contributions(self):

        c = Contribution()
        c.addon_id = 3615
        c.amount = '9.99'
        c.save()

        tasks.addon_total_contributions(3615)
        a = Addon.objects.no_cache().get(pk=3615)
        eq_(float(a.total_contributions), 9.99)

        c = Contribution()
        c.addon_id = 3615
        c.amount = '10.00'
        c.save()

        tasks.addon_total_contributions(3615)
        a = Addon.objects.no_cache().get(pk=3615)
        eq_(float(a.total_contributions), 19.99)


@mock.patch('stats.management.commands.index_stats.create_tasks')
class TestIndexStats(amo.tests.TestCase):
    fixtures = ['stats/test_models']

    def setUp(self):
        self.downloads = (DownloadCount.objects.order_by('-date')
                          .values_list('id', flat=True))
        self.updates = (UpdateCount.objects.order_by('-date')
                        .values_list('id', flat=True))

    def test_by_date(self, tasks_mock):
        call_command('index_stats', addons=None, date='2009-06-01')
        qs = self.downloads.filter(date='2009-06-01')
        download = tasks_mock.call_args_list[1][0]
        eq_(download[0], tasks.index_download_counts)
        eq_(download[1], list(qs))

    def test_called_three(self, tasks_mock):
        call_command('index_stats', addons=None, date='2009-06-01')
        eq_(tasks_mock.call_count, 3)

    def test_called_two(self, tasks_mock):
        call_command('index_stats', addons='5', date='2009-06-01')
        eq_(tasks_mock.call_count, 2)

    def test_by_date_range(self, tasks_mock):
        call_command('index_stats', addons=None,
                     date='2009-06-01:2009-06-07')
        qs = self.downloads.filter(date__range=('2009-06-01', '2009-06-07'))
        download = tasks_mock.call_args_list[1][0]
        eq_(download[0], tasks.index_download_counts)
        eq_(download[1], list(qs))

    def test_by_addon(self, tasks_mock):
        call_command('index_stats', addons='5', date=None)
        qs = self.downloads.filter(addon=5)
        download = tasks_mock.call_args_list[1][0]
        eq_(download[0], tasks.index_download_counts)
        eq_(download[1], list(qs))

    def test_by_addon_and_date(self, tasks_mock):
        call_command('index_stats', addons='4', date='2009-06-01')
        qs = self.downloads.filter(addon=4, date='2009-06-01')
        download = tasks_mock.call_args_list[1][0]
        eq_(download[0], tasks.index_download_counts)
        eq_(download[1], list(qs))

    def test_multiple_addons_and_date(self, tasks_mock):
        call_command('index_stats', addons='4, 5', date='2009-10-03')
        qs = self.downloads.filter(addon__in=[4, 5], date='2009-10-03')
        download = tasks_mock.call_args_list[1][0]
        eq_(download[0], tasks.index_download_counts)
        eq_(download[1], list(qs))

    def test_no_addon_or_date(self, tasks_mock):
        call_command('index_stats', addons=None, date=None)
        calls = tasks_mock.call_args_list
        updates = list(self.updates.values_list('date', flat=True))
        downloads = list(self.downloads.values_list('date', flat=True))

        # Check that we're calling the task in increments of 5 days.
        # We add 1 because picking up 11 days means we have start/stop pairs at
        # [0, 5], [5, 10], [10, 15]
        eq_(len([c for c in calls if c[0][0] == tasks.index_update_counts]),
            1 + (updates[0] - updates[-1]).days / 5)
        eq_(len([c for c in calls if c[0][0] == tasks.index_download_counts]),
            1 + (downloads[0] - downloads[-1]).days / 5)


class TestIndexLatest(amo.tests.ESTestCase):
    es = True

    def test_index_latest(self):
        latest = datetime.date.today() - datetime.timedelta(days=5)
        UpdateCount.index({'date': latest})
        self.refresh('update_counts')

        start = latest.strftime('%Y-%m-%d')
        finish = datetime.date.today().strftime('%Y-%m-%d')
        with mock.patch('stats.cron.call_command') as call:
            cron.index_latest_stats()
            call.assert_called_with('index_stats', addons=None,
                                    date='%s:%s' % (start, finish))
