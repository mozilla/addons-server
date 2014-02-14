import json

from mock import patch
from nose.tools import eq_, ok_
from test_utils import RequestFactory

from addons.models import AddonUser
from amo.tests import app_factory, ESTestCase, TestCase
from amo.urlresolvers import reverse
from users.models import UserProfile

import mkt
from mkt.api.tests import BaseAPI
from mkt.api.tests.test_oauth import RestOAuth
from mkt.fireplace.api import FireplaceAppSerializer
from mkt.webapps.models import Webapp
from mkt.site.fixtures import fixture
from mkt.webapps.models import Installed


# https://bugzilla.mozilla.org/show_bug.cgi?id=958608#c1 and #c2.
FIREPLACE_EXCLUDED_FIELDS = (
    'absolute_url', 'app_type', 'created', 'default_locale', 'payment_account',
    'regions', 'resource_uri', 'supported_locales', 'versions',
    'weekly_downloads', 'upsold', 'tags')


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


class TestConsumerInfoView(RestOAuth, TestCase):
    fixtures = fixture('user_2519')

    def setUp(self):
        super(TestConsumerInfoView, self).setUp()
        self.request = RequestFactory().get('/')
        self.url = reverse('fireplace-consumer-info')
        self.user = UserProfile.objects.get(pk=2519)

    @patch('mkt.regions.middleware.RegionMiddleware.region_from_request')
    def test_no_user_just_region(self, region_from_request):
        region_from_request.return_value = mkt.regions.UK
        res = self.anon.get(self.url)
        data = json.loads(res.content)
        eq_(data['region'], 'uk')
        ok_(not 'developed' in data)
        ok_(not 'installed' in data)
        ok_(not 'purchased' in data)

    @patch('mkt.regions.middleware.RegionMiddleware.region_from_request')
    def test_with_user_developed(self, region_from_request):
        region_from_request.return_value = mkt.regions.BR
        developed_app = app_factory()
        AddonUser.objects.create(user=self.user, addon=developed_app)
        self.client.login(username=self.user.email, password='password')
        res = self.client.get(self.url)
        data = json.loads(res.content)
        eq_(data['region'], 'br')
        eq_(data['installed'], [])
        eq_(data['developed'], [developed_app.pk])
        eq_(data['purchased'], [])

    @patch('mkt.regions.middleware.RegionMiddleware.region_from_request')
    def test_with_user_installed(self, region_from_request):
        region_from_request.return_value = mkt.regions.BR
        installed_app = app_factory()
        Installed.objects.create(user=self.user, addon=installed_app)
        self.client.login(username=self.user.email, password='password')
        res = self.client.get(self.url)
        data = json.loads(res.content)
        eq_(data['region'], 'br')
        eq_(data['installed'], [installed_app.pk])
        eq_(data['developed'], [])
        eq_(data['purchased'], [])

    @patch('users.models.UserProfile.purchase_ids')
    @patch('mkt.regions.middleware.RegionMiddleware.region_from_request')
    def test_with_user_purchased(self, region_from_request, purchase_ids):
        region_from_request.return_value = mkt.regions.BR
        purchased_app = app_factory()
        purchase_ids.return_value = [purchased_app.pk]
        self.client.login(username=self.user.email, password='password')
        res = self.client.get(self.url)
        data = json.loads(res.content)
        eq_(data['region'], 'br')
        eq_(data['installed'], [])
        eq_(data['developed'], [])
        eq_(data['purchased'], [purchased_app.pk])
