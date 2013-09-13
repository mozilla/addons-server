from nose.tools import eq_, ok_

import amo.tests

from mkt.stats.forms import StatsForm


class TestStatsForm(amo.tests.TestCase):

    def setUp(self):
        self.data = {'start': '2013-04-01',
                     'end': '2013-04-15',
                     'interval': 'day'}

    def _check(self, form, valid, fields):
        eq_(form.is_valid(), valid)
        eq_(len(form.errors), len(fields))
        for f in fields:
            ok_(f in form.errors)

    def test_good(self):
        form = StatsForm(self.data)
        ok_(form.is_valid(), form.errors)

    def test_no_values(self):
        form = StatsForm({})
        self._check(form, False, ['start', 'end', 'interval'])

    def test_other_date_format(self):
        self.data.update({'start': '20130401'})
        form = StatsForm(self.data)
        ok_(form.is_valid(), form.errors)

    def test_bad_date(self):
        self.data.update({'start': 'abc'})
        form = StatsForm(self.data)
        self._check(form, False, ['start'])

    def test_interval(self):
        self.data.update({'interval': 'second'})
        form = StatsForm(self.data)
        self._check(form, False, ['interval'])
