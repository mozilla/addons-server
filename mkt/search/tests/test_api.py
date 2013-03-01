import json
from datetime import datetime

from django.conf import settings
from django.contrib.auth.models import User

from mock import patch
from nose.tools import eq_

import amo
from addons.models import AddonCategory, AddonDeviceType, Category
from amo.tests import ESTestCase
from mkt.api.models import Access, generate
from mkt.api.tests.test_oauth import BaseOAuth, OAuthClient
from mkt.search.forms import DEVICE_CHOICES_IDS
from mkt.site.fixtures import fixture
from mkt.webapps.models import Webapp


class TestApi(BaseOAuth, ESTestCase):
    fixtures = fixture('webapp_337141')

    def setUp(self):
        self.client = OAuthClient(None)
        self.list_url = ('api_dispatch_list', {'resource_name': 'search'})
        self.webapp = Webapp.objects.get(pk=337141)
        self.category = Category.objects.create(name='test',
                                                type=amo.ADDON_WEBAPP)
        self.webapp.save()
        self.refresh()

    def test_verbs(self):
        self._allowed_verbs(self.list_url, ['get'])

    def test_meta(self):
        res = self.client.get(self.list_url)
        eq_(res.status_code, 200)
        eq_(set(json.loads(res.content).keys()), set(['objects', 'meta']))

    def test_wrong_category(self):
        res = self.client.get(self.list_url + ({'cat': self.category.pk + 1},))
        eq_(res.status_code, 400)
        eq_(res['Content-Type'], 'application/json')

    def test_wrong_weight(self):
        self.category.update(weight=-1)
        res = self.client.get(self.list_url + ({'cat': self.category.pk},))
        eq_(res.status_code, 400)

    def test_wrong_sort(self):
        res = self.client.get(self.list_url + ({'sort': 'awesomeness'},))
        eq_(res.status_code, 400)

    def test_right_category(self):
        res = self.client.get(self.list_url + ({'cat': self.category.pk},))
        eq_(res.status_code, 200)
        eq_(json.loads(res.content)['objects'], [])

    def create(self):
        AddonCategory.objects.create(addon=self.webapp, category=self.category)
        self.webapp.save()
        self.refresh()

    def test_right_category_present(self):
        self.create()
        res = self.client.get(self.list_url + ({'cat': self.category.pk},))
        eq_(res.status_code, 200)
        objs = json.loads(res.content)['objects']
        eq_(len(objs), 1)

    def test_dehydrate(self):
        self.create()
        res = self.client.get(self.list_url + ({'cat': self.category.pk},))
        eq_(res.status_code, 200)
        obj = json.loads(res.content)['objects'][0]
        eq_(obj['app_slug'], self.webapp.app_slug)
        eq_(obj['icon_url_128'], self.webapp.get_icon_url(128))
        eq_(obj['absolute_url'], self.webapp.get_absolute_url())
        eq_(obj['resource_uri'], None)

    def test_q(self):
        res = self.client.get(self.list_url + ({'q': 'something'},))
        eq_(res.status_code, 200)
        obj = json.loads(res.content)['objects'][0]
        eq_(obj['app_slug'], self.webapp.app_slug)

    def test_device(self):
        AddonDeviceType.objects.create(
            addon=self.webapp, device_type=DEVICE_CHOICES_IDS['desktop'])
        self.webapp.save()
        self.refresh()
        res = self.client.get(self.list_url + ({'device': 'desktop'},))
        eq_(res.status_code, 200)
        obj = json.loads(res.content)['objects'][0]
        eq_(obj['app_slug'], self.webapp.app_slug)

    def test_premium_types(self):
        res = self.client.get(self.list_url + (
            {'premium_types': 'free'},))
        eq_(res.status_code, 200)
        obj = json.loads(res.content)['objects'][0]
        eq_(obj['app_slug'], self.webapp.app_slug)

    def test_premium_types_empty(self):
        res = self.client.get(self.list_url + (
            {'premium_types': 'premium'},))
        eq_(res.status_code, 200)
        objs = json.loads(res.content)['objects']
        eq_(len(objs), 0)

    def test_multiple_premium_types(self):
        res = self.client.get(self.list_url + (
            {'premium_types': 'free'},
            {'premium_types': 'premium'}))
        eq_(res.status_code, 200)
        obj = json.loads(res.content)['objects'][0]
        eq_(obj['app_slug'], self.webapp.app_slug)

    def test_app_type_hosted(self):
        res = self.client.get(self.list_url + ({'app_type': 'hosted'},))
        eq_(res.status_code, 200)
        obj = json.loads(res.content)['objects'][0]
        eq_(obj['app_slug'], self.webapp.app_slug)

    def test_app_type_packaged(self):
        self.webapp.update(is_packaged=True)
        self.webapp.save()
        self.refresh()

        res = self.client.get(self.list_url + ({'app_type': 'packaged'},))
        eq_(res.status_code, 200)
        obj = json.loads(res.content)['objects'][0]
        eq_(obj['app_slug'], self.webapp.app_slug)

    def test_status_anon(self):
        res = self.client.get(self.list_url + ({'status': 'public'},))
        eq_(res.status_code, 200)
        obj = json.loads(res.content)['objects'][0]
        eq_(obj['app_slug'], self.webapp.app_slug)

        res = self.client.get(self.list_url + ({'status': 'vindaloo'},))
        eq_(res.status_code, 400)
        error = json.loads(res.content)['error_message']
        eq_(error.keys(), ['status'])

        res = self.client.get(self.list_url + ({'status': 'rejected'},))
        eq_(res.status_code, 401)
        eq_(json.loads(res.content)['reason'],
            'Unauthorized to filter by status.')


@patch.object(settings, 'SITE_URL', 'http://api/')
class TestApiReviewer(BaseOAuth, ESTestCase):
    fixtures = fixture('webapp_337141', 'user_2519')

    def setUp(self, api_name='apps'):
        self.user = User.objects.get(pk=2519)
        self.profile = self.user.get_profile()
        self.profile.update(read_dev_agreement=datetime.now())
        self.grant_permission(self.profile, 'Apps:Review')

        self.access = Access.objects.create(key='foo', secret=generate(),
                                            user=self.user)
        self.client = OAuthClient(self.access, api_name=api_name)
        self.list_url = ('api_dispatch_list', {'resource_name': 'search'})

        self.webapp = Webapp.objects.get(pk=337141)
        self.category = Category.objects.create(name='test',
                                                type=amo.ADDON_WEBAPP)
        self.webapp.save()
        self.refresh()

    def test_status_reviewer(self):
        res = self.client.get(self.list_url + ({'status': 'public'},))
        eq_(res.status_code, 200)
        obj = json.loads(res.content)['objects'][0]
        eq_(obj['app_slug'], self.webapp.app_slug)

        res = self.client.get(self.list_url + ({'status': 'rejected'},))
        eq_(res.status_code, 200)
        objs = json.loads(res.content)['objects']
        eq_(len(objs), 0)
