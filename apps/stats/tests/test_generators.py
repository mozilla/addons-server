from datetime import date
from decimal import Decimal

from django import test

from nose.tools import eq_

from stats import utils
from stats.models import UpdateCount
from stats.db import DayAvg


class TestUnknownGen(test.TestCase):
    fixtures = ['stats/test_models.json']

    def test_apps_key_conflict(self):
        """
        App named 'unknown' could cause a key conflict for unknown_gen.

        In this test, app['unknown'] exists and is a dictionary. This
        prevents unknown_gen() from simply adding the calculated count
        to this existing dictionary key (which would result in a
        TypeError).
        """
        qs = UpdateCount.stats.filter(pk=3)
        fields = [('date', 'start'), ('count', DayAvg('count')),
                  ('applications', DayAvg('applications'))]
        stats = qs.daily_summary(**dict(fields))
        stats = utils.unknown_gen(stats, 'count', 'applications')
        stats = utils.flatten_gen(stats, flatten_key='applications')
        rows = list(stats)

        eq_(len(rows), 1)
        row = rows[0]
        eq_(row['date'], date(2007, 1, 1))
        eq_(row['count'], Decimal('10'))
        eq_(row['applications/ff/3.0.9'], Decimal('5'))
        eq_(row['applications/unknown/1.0.1'], Decimal('1'))
        eq_(row['applications/unknown'], Decimal('4'))
