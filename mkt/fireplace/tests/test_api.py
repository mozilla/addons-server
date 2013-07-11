import json

from nose.tools import eq_

import amo
from addons.models import AddonUpsell

from mkt.api.base import get_url, list_url
from mkt.api.tests import BaseAPI
from mkt.api.tests.test_oauth import get_absolute_url
from mkt.webapps.models import Webapp
from mkt.site.fixtures import fixture


class TestAppDetail(BaseAPI):
    fixtures = fixture('webapp_337141')

    def setUp(self):
        super(TestAppDetail, self).setUp()
        self.url = get_absolute_url(get_url('app', pk=337141),
                                    api_name='fireplace')

    def test_get(self):
        res = self.client.get(self.url)
        data = json.loads(res.content)
        eq_(data['id'], '337141')

    def test_get_slug(self):
        Webapp.objects.get(pk=337141).update(app_slug='foo')
        res = self.client.get(get_absolute_url(('api_dispatch_detail',
            {'resource_name': 'app', 'app_slug': 'foo'}),
            api_name='fireplace'))
        data = json.loads(res.content)
        eq_(data['id'], '337141')

    def test_others(self):
        url = get_absolute_url(list_url('app'), api_name='fireplace')
        self._allowed_verbs(self.url, ['get'])
        self._allowed_verbs(url, [])

    def test_get_no_upsold(self):
        free = Webapp.objects.create(status=amo.STATUS_PUBLIC)
        AddonUpsell.objects.create(premium_id=337141, free=free)
        res = self.client.get(self.url)
        assert 'upsold' not in res.content
