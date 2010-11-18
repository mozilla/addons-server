import test_utils
from nose.tools import eq_

from amo.urlresolvers import reverse
from perf.models import Performance


class TestPerfIndex(test_utils.TestCase):
    fixtures = ['base/apps', 'base/addon_3615', 'base/addon_5299_gcal',
                'perf/index']

    def setUp(self):
        # TODO: appversion
        self.url = reverse('perf.index')

    def test_get(self):
        # Are you there page?
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        addons = r.context['addons']
        eq_([a.id for a in addons],
            [p.addon_id for p in Performance.objects.order_by('-average')])
        for addon in addons:
            assert r.context['perfs'][addon.id]

    def test_empty_perf_table(self):
        Performance.objects.all().delete()
        r = self.client.get(self.url)
        eq_(r.status_code, 404)
