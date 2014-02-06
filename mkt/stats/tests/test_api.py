import json

import mock
import requests
from nose.tools import eq_, ok_
from rest_framework.reverse import reverse

from django.conf import settings

import amo
from stats.models import Contribution

from mkt.api.tests.test_oauth import RestOAuth
from mkt.site.fixtures import fixture
from mkt.stats.api import APP_STATS, STATS, _get_monolith_data


class StatsAPITestMixin(object):

    def setUp(self):
        super(StatsAPITestMixin, self).setUp()
        patches = [
            mock.patch('monolith.client.Client'),
            mock.patch.object(settings, 'MONOLITH_SERVER', 'http://0.0.0.0:0'),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def test_cors(self):
        res = self.client.get(self.url(), data=self.data)
        self.assertCORS(res, 'get')

    def test_verbs(self):
        self._allowed_verbs(self.url(), ['get'])

    @mock.patch('monolith.client.Client')
    def test_monolith_down(self, mocked):
        mocked.side_effect = requests.ConnectionError
        res = self.client.get(self.url(), data=self.data)
        eq_(res.status_code, 503)

    def test_anon(self):
        res = self.anon.get(self.url())
        eq_(res.status_code, 403)


class TestGlobalStatsResource(StatsAPITestMixin, RestOAuth):

    def setUp(self):
        super(TestGlobalStatsResource, self).setUp()
        self.grant_permission(self.profile, 'Stats:View')
        self.data = {'start': '2013-04-01',
                     'end': '2013-04-15',
                     'interval': 'day'}

    def url(self, metric=None):
        metric = metric or STATS.keys()[0]
        return reverse('global_stats', kwargs={'metric': metric})

    def test_bad_metric(self):
        res = self.client.get(self.url('foo'))
        eq_(res.status_code, 404)

    def test_missing_args(self):
        res = self.client.get(self.url())
        eq_(res.status_code, 400)
        data = json.loads(res.content)
        for f in ('start', 'end', 'interval'):
            eq_(data['detail'][f], ['This field is required.'])

    def test_good(self):
        res = self.client.get(self.url(), data=self.data)
        eq_(res.status_code, 200)
        eq_(json.loads(res.content)['objects'], [])

    @mock.patch('monolith.client.Client')
    def test_dimensions(self, mocked):
        client = mock.MagicMock()
        mocked.return_value = client

        data = self.data.copy()
        data.update({'region': 'br', 'package_type': 'hosted'})
        res = self.client.get(self.url('apps_added_by_package'), data=data)
        eq_(res.status_code, 200)
        ok_(client.called)
        eq_(client.call_args[1], {'region': 'br', 'package_type': 'hosted'})

    @mock.patch('monolith.client.Client')
    def test_dimensions_default(self, mocked):
        client = mock.MagicMock()
        mocked.return_value = client

        res = self.client.get(self.url('apps_added_by_package'),
                              data=self.data)
        eq_(res.status_code, 200)
        ok_(client.called)
        eq_(client.call_args[1], {'region': 'us', 'package_type': 'hosted'})

    @mock.patch('monolith.client.Client')
    def test_dimensions_default_is_none(self, mocked):
        client = mock.MagicMock()
        mocked.return_value = client

        res = self.client.get(self.url('apps_installed'), data=self.data)
        eq_(res.status_code, 200)
        ok_(client.called)
        eq_(client.call_args[1], {})

        data = self.data.copy()
        data['region'] = 'us'

        res = self.client.get(self.url('apps_installed'), data=data)
        eq_(res.status_code, 200)
        ok_(client.called)
        eq_(client.call_args[1], {'region': 'us'})

    @mock.patch('monolith.client.Client')
    def test_coersion(self, mocked):
        client = mock.MagicMock()
        client.return_value = [{'count': 1.99, 'date': '2013-10-10'}]
        mocked.return_value = client

        data = _get_monolith_data(
            {'metric': 'foo', 'coerce': {'count': str}}, '2013-10-10',
            '2013-10-10', 'day', {})
        eq_(type(data['objects'][0]['count']), str)


class TestAppStatsResource(StatsAPITestMixin, RestOAuth):
    fixtures = fixture('user_2519')

    def setUp(self):
        super(TestAppStatsResource, self).setUp()
        self.app = amo.tests.app_factory(status=amo.STATUS_PUBLIC)
        self.app.addonuser_set.create(user=self.user.get_profile())
        self.data = {'start': '2013-04-01', 'end': '2013-04-15',
                     'interval': 'day'}

    def url(self, pk=None, metric=None):
        pk = pk or self.app.pk
        metric = metric or APP_STATS.keys()[0]
        return reverse('app_stats', kwargs={'pk': pk, 'metric': metric})

    def test_owner(self):
        res = self.client.get(self.url(), data=self.data)
        eq_(res.status_code, 200)

    def test_perms(self):
        self.app.addonuser_set.all().delete()
        self.grant_permission(self.profile, 'Stats:View')
        res = self.client.get(self.url(), data=self.data)
        eq_(res.status_code, 200)

    def test_bad_app(self):
        res = self.client.get(self.url(pk=99999999))
        eq_(res.status_code, 404)

    def test_bad_metric(self):
        res = self.client.get(self.url(metric='foo'))
        eq_(res.status_code, 404)

    def test_missing_args(self):
        res = self.client.get(self.url())
        eq_(res.status_code, 400)
        data = json.loads(res.content)
        for f in ('start', 'end', 'interval'):
            eq_(data['detail'][f], ['This field is required.'])


class TestGlobalStatsTotalResource(StatsAPITestMixin, RestOAuth):
    fixtures = fixture('user_2519')

    def setUp(self):
        super(TestGlobalStatsTotalResource, self).setUp()
        self.grant_permission(self.profile, 'Stats:View')
        self.data = None  # For the mixin tests.

    def url(self):
        return reverse('global_stats_total')

    def test_perms(self):
        res = self.client.get(self.url())
        eq_(res.status_code, 200)


class TestAppStatsTotalResource(StatsAPITestMixin, RestOAuth):
    fixtures = fixture('user_2519')

    def setUp(self):
        super(TestAppStatsTotalResource, self).setUp()
        self.app = amo.tests.app_factory(status=amo.STATUS_PUBLIC)
        self.app.addonuser_set.create(user=self.user.get_profile())
        self.data = None  # For the mixin tests.

    def url(self, pk=None, metric=None):
        pk = pk or self.app.pk
        return reverse('app_stats_total', kwargs={'pk': pk})

    def test_owner(self):
        res = self.client.get(self.url())
        eq_(res.status_code, 200)

    def test_perms(self):
        self.app.addonuser_set.all().delete()
        self.grant_permission(self.profile, 'Stats:View')
        res = self.client.get(self.url())
        eq_(res.status_code, 200)

    def test_bad_app(self):
        res = self.client.get(self.url(pk=99999999))
        eq_(res.status_code, 404)


class TestTransactionResource(RestOAuth):
    fixtures = fixture('prices', 'user_2519', 'webapp_337141')

    def setUp(self):
        super(TestTransactionResource, self).setUp()
        Contribution.objects.create(
            addon_id=337141,
            amount='1.89',
            currency='EUR',
            price_tier_id=2,
            uuid='abcdef123456',
            transaction_id='abc-def',
            type=1,
            user=self.user.get_profile(),
        )

    def url(self, t_id=None):
        t_id = t_id or 'abc-def'
        return reverse('transaction_api', kwargs={'transaction_id': t_id})

    def test_cors(self):
        res = self.client.get(self.url())
        self.assertCORS(res, 'get')

    def test_verbs(self):
        self.grant_permission(self.profile, 'RevenueStats:View')
        self._allowed_verbs(self.url(), ['get'])

    def test_anon(self):
        res = self.anon.get(self.url())
        eq_(res.status_code, 403)

    def test_bad_txn(self):
        self.grant_permission(self.profile, 'RevenueStats:View')
        res = self.client.get(self.url('foo'))
        eq_(res.status_code, 404)

    def test_good_but_no_permission(self):
        res = self.client.get(self.url())
        eq_(res.status_code, 403)

    def test_good(self):
        self.grant_permission(self.profile, 'RevenueStats:View')
        res = self.client.get(self.url())
        eq_(res.status_code, 200)
        obj = json.loads(res.content)
        eq_(obj['id'], 'abc-def')
        eq_(obj['app_id'], 337141)
        eq_(obj['amount_USD'], '1.99')
        eq_(obj['type'], 'Purchase')
