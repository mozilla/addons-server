import mock
from nose.tools import eq_

from mkt.api.base import list_url
from mkt.api.tests.test_oauth import BaseOAuth
from mkt.stats.api import STATS


@mock.patch('monolith.client.Client')
class TestGlobalStatsResource(BaseOAuth):

    def setUp(self):
        super(TestGlobalStatsResource, self).setUp('stats')
        self.list_url = list_url('global')
        self.get_url = self.get_detail_url('global', STATS.keys()[0])
        self.create_switch('stats-api')
        self.data = {'start': '2013-04-01',
                     'end': '2013-04-15',
                     'interval': 'day'}

    def get_detail_url(self, name, metric, **kw):
        kw.update({'resource_name': name, 'metric': metric})
        return ('api_dispatch_detail', kw)

    def test_verbs(self, mocked):
        self._allowed_verbs(self.get_url, ['get'])
        self._allowed_verbs(self.list_url, [])

    def test_bad_metric(self, mocked):
        res = self.client.get(self.get_detail_url('global', 'foo'))
        eq_(res.status_code, 404)
