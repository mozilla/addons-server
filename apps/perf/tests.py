import test_utils
from nose.tools import eq_

import amo.tests
from amo.urlresolvers import reverse
from perf.cron import update_perf
from perf.models import Performance
from addons.models import Addon


class TestPerfIndex(amo.tests.RedisTest, test_utils.TestCase):
    fixtures = ['base/apps', 'base/addon_3615', 'base/addon_5299_gcal',
                'perf/index']

    def setUp(self):
        super(TestPerfIndex, self).setUp()
        update_perf()
        self.url = reverse('perf.index')

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
        eq_(r.status_code, 404)
