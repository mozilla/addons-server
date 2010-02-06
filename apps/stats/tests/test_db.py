from datetime import date, datetime

from django import test

from nose.tools import eq_

from stats.db import StatsDict
from stats.db import prev_month


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


class TestDateUtils(test.TestCase):

    def test_prev_month(self):
        from_to = [
            (date(2008, 1, 1), date(2007, 12, 1)),
            (date(2008, 1, 31), date(2007, 12, 1)),
            (date(2008, 2, 1), date(2008, 1, 1)),
            (date(2008, 2, 29), date(2008, 1, 1)),
            (datetime(2008, 2, 29, 23, 59, 59), date(2008, 1, 1)),
            (date(2008, 3, 1), date(2008, 2, 1)),
            (date(2008, 3, 31), date(2008, 2, 1)),
            (date(2008, 4, 1), date(2008, 3, 1)),
            (date(2008, 4, 30), date(2008, 3, 1)),
            (date(2008, 12, 1), date(2008, 11, 1)),
            (date(2008, 12, 31), date(2008, 11, 1)),
        ]
        for (d, expected) in from_to:
            eq_(prev_month(d), expected, 'unexpected prev_month result')
