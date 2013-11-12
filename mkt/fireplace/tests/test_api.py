import json

from nose.tools import eq_

import amo
from amo.urlresolvers import reverse
from addons.models import AddonUpsell

from mkt.api.tests import BaseAPI
from mkt.webapps.models import Webapp
from mkt.site.fixtures import fixture


class TestAppDetail(BaseAPI):
    fixtures = fixture('webapp_337141')

    def setUp(self):
        super(TestAppDetail, self).setUp()
        self.url = reverse('fireplace-app-detail', kwargs={'pk': 337141})

    def test_get(self):
        res = self.client.get(self.url)
        data = json.loads(res.content)
        eq_(data['id'], 337141)

    def test_get_slug(self):
        Webapp.objects.get(pk=337141).update(app_slug='foo')
        res = self.client.get(reverse('fireplace-app-detail',
                                      kwargs={'pk': 'foo'}))
        data = json.loads(res.content)
        eq_(data['id'], 337141)

    def test_others(self):
        url = reverse('fireplace-app-list')
        self._allowed_verbs(self.url, ['get'])
        self._allowed_verbs(url, [])

    def test_get_no_upsold(self):
        free = Webapp.objects.create(status=amo.STATUS_PUBLIC)
        AddonUpsell.objects.create(premium_id=337141, free=free)
        res = self.client.get(self.url)
        assert 'upsold' not in res.content
