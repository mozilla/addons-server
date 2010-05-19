from django import test
from nose.tools import eq_

from stats.cron import _update_global_totals
from stats.models import GlobalStat


class TestGlobalStats(test.TestCase):

    fixtures = ['stats/test_models']

    def test_stats_for_date(self):

        date = '2009-06-01'
        job = 'addon_total_downloads'

        eq_(GlobalStat.objects.no_cache().filter(date=date,
                                                 name=job).count(), 0)
        _update_global_totals(job, date)
        eq_(GlobalStat.objects.no_cache().filter(date=date,
                                                 name=job).count(), 1)
