from datetime import date, datetime
from decimal import Decimal

from django import test

from nose.tools import eq_

from stats.db import StatsDict, Count, Sum, First, Last, Avg, DayAvg
from stats.db import prev_month_period, prev_week_period, prev_day_period
from stats.models import DownloadCount


class TestStatsDict(test.TestCase):
    dict_a = StatsDict({'a': 3, 'nested': {'b': 5, 'c': 6}})
    dict_b = StatsDict({'a': 3, 'b': 1, 'nested': {'b': 5, 'c': 6}})
    dict_empty = StatsDict({})

    def test_add(self):
        d = self.dict_empty + self.dict_empty
        eq_(d, self.dict_empty)

        d = self.dict_a + self.dict_empty
        eq_(d, self.dict_a)

        d = self.dict_a + self.dict_b
        res = StatsDict({'a': 6, 'b': 1, 'nested': {'b': 10, 'c': 12}})
        eq_(d, res)

    def test_mul(self):
        d = self.dict_empty * Decimal('1234.432')
        eq_(d, self.dict_empty)

        d = self.dict_a * Decimal('1.1')
        res = StatsDict({'a': Decimal('3.3'),
                         'nested': {'b': Decimal('5.5'), 'c': Decimal('6.6')}})
        eq_(d, res)

    def test_sum_reduce(self):
        sum = self.dict_empty.sum_reduce()
        eq_(sum, 0)

        sum = self.dict_a.sum_reduce()
        eq_(sum, 14)


class TestDateUtils(test.TestCase):

    def test_prev_month_period(self):
        from_to = [
            (date(2008, 1, 1), (date(2007, 12, 1), date(2007, 12, 31))),
            (date(2008, 1, 31), (date(2007, 12, 1), date(2007, 12, 31))),
            (date(2008, 2, 1), (date(2008, 1, 1), date(2008, 1, 31))),
            (date(2008, 2, 29), (date(2008, 1, 1), date(2008, 1, 31))),
            (datetime(2008, 2, 29, 23, 59, 59),
                (date(2008, 1, 1), date(2008, 1, 31))),
            (date(2008, 3, 1), (date(2008, 2, 1), date(2008, 2, 29))),
            (date(2008, 3, 31), (date(2008, 2, 1), date(2008, 2, 29))),
            (date(2008, 4, 1), (date(2008, 3, 1), date(2008, 3, 31))),
            (date(2008, 4, 30), (date(2008, 3, 1), date(2008, 3, 31))),
            (date(2008, 12, 1), (date(2008, 11, 1), date(2008, 11, 30))),
            (date(2008, 12, 31), (date(2008, 11, 1), date(2008, 11, 30))),
        ]
        for (d, expected) in from_to:
            eq_(prev_month_period(d), expected,
                'unexpected prev_month_period result')

    def test_prev_week_period(self):
        from_to = [
            (date(2010, 1, 4), (date(2009, 12, 28), date(2010, 1, 3))),
            (date(2010, 1, 6), (date(2009, 12, 28), date(2010, 1, 3))),
            (date(2010, 1, 10), (date(2009, 12, 28), date(2010, 1, 3))),
            (datetime(2010, 1, 10, 23, 59, 59),
                (date(2009, 12, 28), date(2010, 1, 3))),
        ]
        for (d, expected) in from_to:
            eq_(prev_week_period(d), expected,
                'unexpected prev_week_period result')

    def test_prev_day_period(self):
        from_to = [
            (date(2010, 1, 1), (date(2009, 12, 31), date(2009, 12, 31))),
            (date(2008, 3, 1), (date(2008, 2, 29), date(2008, 2, 29))),
            (datetime(2008, 3, 1, 23, 59, 59),
                (date(2008, 2, 29), date(2008, 2, 29))),
        ]
        for (d, expected) in from_to:
            eq_(prev_day_period(d), expected,
                'unexpected prev_day_period result')


class TestDbAggregates(test.TestCase):
    fixtures = ['stats/test_models.json']

    def test_count(self):
        qs = DownloadCount.stats.filter(date__range=(
            date(2009, 6, 1), date(2009, 6, 30)))
        s = qs.summary(my_count=Count('count'))
        eq_(s['my_count'], 5, 'unexpected aggregate count')
        eq_(s['my_count'], s['row_count'], 'count and row_count differ')

    def test_sum(self):
        qs = DownloadCount.stats.filter(date__range=(
            date(2009, 6, 1), date(2009, 6, 30)))
        s = qs.summary(count_sum=Sum('count'), source_sum=Sum('sources'))
        eq_(s['count_sum'], 50, 'unexpected aggregate count sum')
        eq_(s['source_sum']['search'], 15, 'unexpected aggregate sources sum')

    def test_first(self):
        qs = DownloadCount.stats.filter(date__range=(
            date(2009, 6, 1), date(2009, 6, 30)))
        s = qs.summary(first_date=First('date'))
        eq_(s['first_date'], date(2009, 6, 28),
            'unexpected aggregate first date')

    def test_last(self):
        qs = DownloadCount.stats.filter(date__range=(
            date(2009, 6, 1), date(2009, 6, 30)))
        s = qs.summary(last_date=Last('date'))
        eq_(s['last_date'], date(2009, 6, 1), 'unexpected aggregate last date')

    def test_avg(self):
        qs = DownloadCount.stats.filter(date__range=(
            date(2009, 6, 1), date(2009, 6, 30)))
        s = qs.summary(my_avg=Avg('count'))
        eq_(s['my_avg'], Decimal('10.0'), 'unexpected aggregate avg value')

    def test_dayavg(self):
        qs = DownloadCount.stats.filter(date__range=(
            date(2009, 6, 1), date(2009, 6, 30)))
        s = qs.summary(my_avg=DayAvg('count'))
        eq_(s['my_avg'].quantize(Decimal('0.1')), Decimal('1.8'), # 50 / 28days
            'unexpected aggregate dayavg value')


class TestDbSummaries(test.TestCase):
    fixtures = ['stats/test_models.json']

    def test_period_summary(self):
        qs = DownloadCount.stats.filter(addon=4,
                date__range=(date(2009, 6, 1), date(2009, 7, 3)))

        s = list(qs.period_summary('day', fill_holes=True))
        eq_(len(s), 33)

        s = list(qs.period_summary('week'))
        eq_(len(s), 5)

        s = list(qs.period_summary('month'))
        eq_(len(s), 2)
