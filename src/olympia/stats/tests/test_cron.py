import datetime

from django.core.management import call_command

from unittest import mock

from olympia import amo
from olympia.amo.tests import TestCase
from olympia.stats import cron
from olympia.stats.models import DownloadCount


@mock.patch('olympia.stats.management.commands.index_stats.group')
class TestIndexStats(TestCase):
    fixtures = ['stats/download_counts']

    def setUp(self):
        super(TestIndexStats, self).setUp()
        self.downloads = (DownloadCount.objects.order_by('-date')
                          .values_list('id', flat=True))

    def test_by_date(self, group_mock):
        call_command('index_stats', addons=None, date='2009-06-01')
        qs = self.downloads.filter(date='2009-06-01')
        calls = group_mock.call_args[0][0]
        assert calls[0].task == 'olympia.stats.tasks.index_download_counts'
        assert calls[0].args == (list(qs), None)

    def test_by_addon_and_date_no_match(self, group_mock):
        call_command('index_stats', addons='5', date='2009-06-01')
        calls = group_mock.call_args[0][0]
        assert len(calls) == 0

    def test_by_date_range(self, group_mock):
        call_command('index_stats', addons=None,
                     date='2009-06-01:2009-06-07')
        qs = self.downloads.filter(date__range=('2009-06-01', '2009-06-07'))
        calls = group_mock.call_args[0][0]
        assert calls[0].task == 'olympia.stats.tasks.index_download_counts'
        assert calls[0].args == (list(qs), None)

    def test_by_addon(self, group_mock):
        call_command('index_stats', addons='5', date=None)
        qs = self.downloads.filter(addon=5)
        calls = group_mock.call_args[0][0]
        assert calls[0].task == 'olympia.stats.tasks.index_download_counts'
        assert calls[0].args == (list(qs), None)

    def test_by_addon_and_date(self, group_mock):
        call_command('index_stats', addons='4', date='2009-06-01')
        qs = self.downloads.filter(addon=4, date='2009-06-01')
        calls = group_mock.call_args[0][0]
        assert calls[0].args == (list(qs), None)

    def test_multiple_addons_and_date(self, group_mock):
        call_command('index_stats', addons='4, 5', date='2009-10-03')
        qs = self.downloads.filter(addon__in=[4, 5], date='2009-10-03')
        calls = group_mock.call_args[0][0]
        assert calls[0].task == 'olympia.stats.tasks.index_download_counts'
        assert calls[0].args == (list(qs), None)

    def test_no_addon_or_date(self, group_mock):
        call_command('index_stats', addons=None, date=None)
        calls = group_mock.call_args[0][0]

        # There should be 10 downloads, but 2 of them have a date close enough
        # together that they'll be indexed in the same chunk, so we should have
        # 9 calls.
        download_counts_calls = [
            call.args for call in calls
            if call.task == 'olympia.stats.tasks.index_download_counts'
        ]
        assert len(download_counts_calls) == 9


class TestIndexLatest(amo.tests.ESTestCase):

    def test_index_latest(self):
        latest = datetime.date.today() - datetime.timedelta(days=5)
        DownloadCount.index({'date': latest})
        self.refresh('stats_download_counts')

        start = latest.strftime('%Y-%m-%d')
        finish = datetime.date.today().strftime('%Y-%m-%d')
        with mock.patch('olympia.stats.cron.call_command') as call:
            cron.index_latest_stats()
            call.assert_called_with('index_stats', addons=None,
                                    date='%s:%s' % (start, finish))
