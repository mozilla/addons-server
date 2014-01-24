import json

from nose.tools import eq_, ok_

from amo.tests import ESTestCase
from amo.urlresolvers import reverse

from mkt.api.tests import BaseAPI
from mkt.fireplace.api import FireplaceAppSerializer
from mkt.webapps.models import Webapp
from mkt.site.fixtures import fixture

# https://bugzilla.mozilla.org/show_bug.cgi?id=958608#c1 and #c2.
FIREPLACE_EXCLUDED_FIELDS = (
    'absolute_url', 'app_type', 'created', 'default_locale', 'payment_account',
    'privacy_policy', 'regions', 'resource_uri', 'summary',
    'supported_locales', 'versions', 'weekly_downloads', 'upsold', 'tags')


class TestAppDetail(BaseAPI):
    fixtures = fixture('webapp_337141')

    def setUp(self):
        super(TestAppDetail, self).setUp()
        self.url = reverse('fireplace-app-detail', kwargs={'pk': 337141})

    def test_get(self):
        res = self.client.get(self.url)
        data = json.loads(res.content)
        eq_(data['id'], 337141)
        for field in FIREPLACE_EXCLUDED_FIELDS:
            ok_(not field in data, field)
        for field in FireplaceAppSerializer.Meta.fields:
            ok_(field in data, field)

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


class TestFeaturedSearchView(ESTestCase):
    fixtures = fixture('webapp_337141')

    def setUp(self):
        super(TestFeaturedSearchView, self).setUp()
        self.webapp = Webapp.objects.get(pk=337141)
        self.reindex(Webapp, 'webapp')
        self.url = reverse('fireplace-featured-search-api')

    def test_get(self):
        res = self.client.get(self.url)
        objects = json.loads(res.content)['objects']
        eq_(len(objects), 1)
        data = objects[0]
        eq_(data['id'], 337141)
        for field in FIREPLACE_EXCLUDED_FIELDS:
            ok_(not field in data, field)
        for field in FireplaceAppSerializer.Meta.fields:
            ok_(field in data, field)
