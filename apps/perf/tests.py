from django.conf import settings

from mock import patch
from nose.tools import eq_
from pyquery import PyQuery as pq

import amo.tests
from amo.urlresolvers import reverse
from perf.models import Performance
from addons.models import Addon


class TestModels(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/addon_3615', 'base/addon_5299_gcal',
                'perf/index']

    def setUp(self):
        self.addon = Addon.objects.get(pk=3615)
        self.results = self.addon.performance.all()
        self.result = self.results[0]

    @patch.object(settings, 'PERF_THRESHOLD', 99)
    @patch('perf.models.Performance.get_baseline')
    def test_perf_over(self, get_baseline):
        get_baseline.return_value = 1.0
        self.result.average = 2.0
        eq_(self.result.startup_is_too_slow(), True)

    @patch.object(settings, 'PERF_THRESHOLD', 101)
    @patch('perf.models.Performance.get_baseline')
    def test_perf_under(self, get_baseline):
        get_baseline.return_value = 1.0
        self.result.average = 2.0
        eq_(self.result.startup_is_too_slow(), False)

    @patch.object(settings, 'PERF_THRESHOLD', 1)
    @patch('perf.models.Performance.get_baseline')
    def test_perf_not_slow(self, get_baseline):
        get_baseline.return_value = 100.0
        self.result.average = 90.0  # Not possible, just to check negatives
        eq_(self.result.startup_is_too_slow(), False)

    @patch.object(settings, 'PERF_THRESHOLD', 25)
    @patch('perf.models.Performance.get_baseline')
    def test_perf_barely_slow(self, get_baseline):
        get_baseline.return_value = 100.0
        self.result.average = 126.0
        eq_(self.result.startup_is_too_slow(), True)

    def test_baseline(self):
        eq_(self.result.get_baseline(), 1.2)

    def test_missing_baseline(self):
        Performance.objects.filter(addon=None).delete()
        eq_(self.result.get_baseline(), self.result.average)
