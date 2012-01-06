from django.conf import settings

from mock import patch
from nose.tools import eq_
from pyquery import PyQuery as pq

import amo.tests
from amo.urlresolvers import reverse
from perf.cron import update_perf
from perf.models import Performance
from addons.models import Addon


class TestPerfIndex(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/addon_3615', 'base/addon_5299_gcal',
                'perf/index']

    def setUp(self):
        super(TestPerfIndex, self).setUp()
        update_perf()
        self.url = reverse('perf.index')
        self._perf_threshold = settings.PERF_THRESHOLD
        settings.PERF_THRESHOLD = 25

    def tearDown(self):
        settings.PERF_THRESHOLD = self._perf_threshold

    def test_get(self):
        # Are you there page?
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        addons = r.context['addons']
        eq_(len(addons), 2)
        qs = Performance.objects.filter(addon__isnull=False)
        eq_([a.id for a in addons],
            [p.addon_id for p in qs.order_by('-average')])

    def test_threshold_filter(self):
        # Threshold is 25, so only 1 add-on will show up
        Addon.objects.get(pk=3615).update(ts_slowness=10)
        Addon.objects.get(pk=5299).update(ts_slowness=50)
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        addons = r.context['addons']
        eq_(len(addons), 1)

    def test_empty_perf_table(self):
        Addon.objects.update(ts_slowness=None)
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        eq_(pq(r.content)('.no-results').length, 1)

    @patch('perf.tasks.update_perf.subtask')
    def test_last_update_none(self, subtask):
        Performance.objects.all().delete()
        update_perf()
        assert not subtask.called


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
