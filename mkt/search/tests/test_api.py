import json
from datetime import datetime

from django.contrib.auth.models import User

from mock import patch
from nose.tools import eq_, ok_

import amo
import mkt.regions
from addons.models import (AddonCategory, AddonDeviceType, AddonUpsell,
                           Category)
from amo.tests import app_factory, ESTestCase
from market.models import AddonPremium, Price, PriceCurrency
from mkt.api.base import list_url
from mkt.api.models import Access, generate
from mkt.api.tests.test_oauth import BaseOAuth, OAuthClient
from mkt.search.forms import DEVICE_CHOICES_IDS
from mkt.site.fixtures import fixture
from mkt.webapps.models import Webapp


class TestApi(BaseOAuth, ESTestCase):
    fixtures = fixture('webapp_337141')

    def setUp(self):
        self.create_switch('search-api-es')
        self.client = OAuthClient(None)
        self.url = list_url('search')
        self.webapp = Webapp.objects.get(pk=337141)
        self.category = Category.objects.create(name='test',
                                                type=amo.ADDON_WEBAPP)
        self.webapp.save()
        self.refresh('webapp')

    def test_verbs(self):
        self._allowed_verbs(self.url, ['get'])

    def test_has_cors(self):
        self.assertCORS(self.client.get(self.url), 'get')

    def test_meta(self):
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        eq_(set(data.keys()), set(['objects', 'meta']))
        eq_(data['meta']['total_count'], 1)

    def test_wrong_category(self):
        res = self.client.get(self.url + ({'cat': self.category.pk + 1},))
        eq_(res.status_code, 400)
        eq_(res['Content-Type'], 'application/json')

    def test_wrong_weight(self):
        self.category.update(weight=-1)
        res = self.client.get(self.url + ({'cat': self.category.pk},))
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        eq_(len(data['objects']), 0)

    def test_wrong_sort(self):
        res = self.client.get(self.url + ({'sort': 'awesomeness'},))
        eq_(res.status_code, 400)

    def test_right_category(self):
        res = self.client.get(self.url + ({'cat': self.category.pk},))
        eq_(res.status_code, 200)
        eq_(json.loads(res.content)['objects'], [])

    def create(self):
        AddonCategory.objects.create(addon=self.webapp, category=self.category)
        self.webapp.save()
        self.refresh('webapp')

    def test_right_category_present(self):
        self.create()
        res = self.client.get(self.url + ({'cat': self.category.pk},))
        eq_(res.status_code, 200)
        objs = json.loads(res.content)['objects']
        eq_(len(objs), 1)

    def test_dehydrate(self):
        with self.settings(SITE_URL=''):
            self.create()
            res = self.client.get(self.url + ({'cat': self.category.pk},))
            eq_(res.status_code, 200)
            obj = json.loads(res.content)['objects'][0]
            eq_(obj['absolute_url'], self.webapp.get_absolute_url())
            eq_(obj['app_type'], self.webapp.app_type)
            eq_(obj['content_ratings'], None)
            eq_(obj['current_version']['version'], u'1.0')
            eq_(obj['description'], unicode(self.webapp.description))
            eq_(obj['icons']['128'], self.webapp.get_icon_url(128))
            eq_(obj['id'], str(self.webapp.id))
            eq_(obj['manifest_url'], self.webapp.get_manifest_url())
            eq_(obj['payment_account'], None)
            eq_(obj['public_stats'], self.webapp.public_stats)
            eq_(obj['ratings'], {'average': 0.0, 'count': 0})
            eq_(obj['resource_uri'], '/api/v1/apps/app/337141/')
            eq_(obj['slug'], self.webapp.app_slug)
            eq_(obj['summary'], u'')

            # These only exists if requested by a reviewer.
            ok_('latest_version_status' not in obj)
            ok_('reviewer_flags' not in obj)

    def test_upsell(self):
        upsell = app_factory()
        AddonUpsell.objects.create(free=self.webapp, premium=upsell)
        self.webapp.save()
        self.refresh('webapp')

        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        obj = json.loads(res.content)['objects'][0]
        eq_(obj['upsell']['id'], upsell.id)
        eq_(obj['upsell']['app_slug'], upsell.app_slug)
        eq_(obj['upsell']['name'], upsell.name)
        eq_(obj['upsell']['icon_url'], upsell.get_icon_url(128))
        eq_(obj['upsell']['resource_uri'], '/api/v1/apps/app/%s/' % upsell.id)

    def test_q(self):
        res = self.client.get(self.url + ({'q': 'something'},))
        eq_(res.status_code, 200)
        obj = json.loads(res.content)['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

    def test_name_localized(self):
        res = self.client.get(self.url + ({'q': 'something',
                                           'lang': 'es'},))
        eq_(res.status_code, 200)
        obj = json.loads(res.content)['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)
        eq_(obj['name'], u'Algo Algo Steamcube!')

    def test_name_localized_to_default_locale(self):
        self.webapp.update(default_locale='es')
        self.refresh('webapp')

        # Make a request in another language that we know will fail.
        res = self.client.get(self.url + ({'q': 'something',
                                           'lang': 'de'},))
        eq_(res.status_code, 200)
        obj = json.loads(res.content)['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)
        eq_(obj['name'], u'Algo Algo Steamcube!')

    def test_device(self):
        AddonDeviceType.objects.create(
            addon=self.webapp, device_type=DEVICE_CHOICES_IDS['desktop'])
        self.webapp.save()
        self.refresh('webapp')
        res = self.client.get(self.url + ({'device': 'desktop'},))
        eq_(res.status_code, 200)
        obj = json.loads(res.content)['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

    def test_no_flash_on_gaia(self):
        AddonDeviceType.objects.create(
            addon=self.webapp, device_type=DEVICE_CHOICES_IDS['gaia'])
        f = self.webapp.get_latest_file()
        f.uses_flash = True
        f.save()
        self.webapp.save()
        self.refresh('webapp')
        res = self.client.get(self.url + ({'dev': 'firefoxos'},))
        eq_(res.status_code, 200)
        eq_(len(json.loads(res.content)['objects']), 0)

    def test_premium_types(self):
        res = self.client.get(self.url + (
            {'premium_types': 'free'},))
        eq_(res.status_code, 200)
        obj = json.loads(res.content)['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

    def test_premium_types_empty(self):
        res = self.client.get(self.url + (
            {'premium_types': 'premium'},))
        eq_(res.status_code, 200)
        objs = json.loads(res.content)['objects']
        eq_(len(objs), 0)

    def test_multiple_premium_types(self):
        res = self.client.get(self.url + (
            {'premium_types': 'free'},
            {'premium_types': 'premium'}))
        eq_(res.status_code, 200)
        obj = json.loads(res.content)['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

    def test_app_type_hosted(self):
        res = self.client.get(self.url + ({'app_type': 'hosted'},))
        eq_(res.status_code, 200)
        obj = json.loads(res.content)['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

    def test_app_type_packaged(self):
        self.webapp.update(is_packaged=True)
        self.webapp.save()
        self.refresh('webapp')

        res = self.client.get(self.url + ({'app_type': 'packaged'},))
        eq_(res.status_code, 200)
        obj = json.loads(res.content)['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

    def test_status_anon(self):
        res = self.client.get(self.url + ({'status': 'public'},))
        eq_(res.status_code, 200)
        obj = json.loads(res.content)['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

        res = self.client.get(self.url + ({'status': 'vindaloo'},))
        eq_(res.status_code, 400)
        error = json.loads(res.content)['error_message']
        eq_(error.keys(), ['status'])

        res = self.client.get(self.url + ({'status': 'any'},))
        eq_(res.status_code, 401)
        eq_(json.loads(res.content)['reason'],
            'Unauthorized to filter by status.')

        res = self.client.get(self.url + ({'status': 'rejected'},))
        eq_(res.status_code, 401)
        eq_(json.loads(res.content)['reason'],
            'Unauthorized to filter by status.')

    def test_status_value_packaged(self):
        # When packaged and not a reviewer we exclude latest version status.
        self.webapp.update(is_packaged=True)
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        obj = json.loads(res.content)['objects'][0]
        eq_(obj['status'], amo.STATUS_PUBLIC)
        eq_('latest_version_status' in obj, False)

    def test_addon_type_anon(self):
        res = self.client.get(self.url + ({'type': 'app'},))
        eq_(res.status_code, 200)
        obj = json.loads(res.content)['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

        res = self.client.get(self.url + ({'type': 'vindaloo'},))
        eq_(res.status_code, 400)
        error = json.loads(res.content)['error_message']
        eq_(error.keys(), ['type'])

        res = self.client.get(self.url + ({'type': 'theme'},))
        eq_(res.status_code, 200)
        eq_(len(res.json['objects']), 0)

    @patch.object(mkt.regions.US, 'supports_carrier_billing', False)
    def test_minimum_price_tier(self):
        price = Price.objects.create(name="5", price=0.50)
        PriceCurrency.objects.create(currency='BRL', price=1.00, tier=price)
        AddonPremium.objects.create(addon=self.webapp, price=price)
        self.webapp.save()
        self.refresh('webapp')
        res = self.client.get(self.url + ({'region': 'br'},))
        eq_(res.status_code, 200)
        eq_(len(res.json['objects']), 1)
        res2 = self.client.get(self.url + ({'region': 'us'},))
        eq_(res2.status_code, 200)
        eq_(len(res2.json['objects']), 0)


class TestApiReviewer(BaseOAuth, ESTestCase):
    fixtures = fixture('webapp_337141', 'user_2519')

    def setUp(self, api_name='apps'):
        self.create_switch('search-api-es')
        self.user = User.objects.get(pk=2519)
        self.profile = self.user.get_profile()
        self.profile.update(read_dev_agreement=datetime.now())
        self.grant_permission(self.profile, 'Apps:Review')

        self.access = Access.objects.create(
            key='test_oauth_key', secret=generate(), user=self.user)
        self.client = OAuthClient(self.access, api_name=api_name)
        self.url = list_url('search')

        self.webapp = Webapp.objects.get(pk=337141)
        self.category = Category.objects.create(name='test',
                                                type=amo.ADDON_WEBAPP)
        self.webapp.save()
        self.refresh('webapp')

    def test_status_reviewer(self):
        res = self.client.get(self.url + ({'status': 'public'},))
        eq_(res.status_code, 200)
        obj = json.loads(res.content)['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

        res = self.client.get(self.url + ({'status': 'rejected'},))
        eq_(res.status_code, 200)
        objs = json.loads(res.content)['objects']
        eq_(len(objs), 0)

        res = self.client.get(self.url + ({'status': 'any'},))
        eq_(res.status_code, 200)
        obj = json.loads(res.content)['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

        res = self.client.get(self.url + ({'status': 'vindaloo'},))
        eq_(res.status_code, 400)
        error = json.loads(res.content)['error_message']
        eq_(error.keys(), ['status'])

    def test_status_value_packaged(self):
        # When packaged we also include the latest version status.
        self.webapp.update(is_packaged=True)
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        obj = json.loads(res.content)['objects'][0]
        eq_(obj['status'], amo.STATUS_PUBLIC)
        eq_(obj['latest_version_status'], amo.STATUS_PUBLIC)

    def test_addon_type_reviewer(self):
        res = self.client.get(self.url + ({'type': 'app'},))
        eq_(res.status_code, 200)
        obj = json.loads(res.content)['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

        res = self.client.get(self.url + ({'type': 'theme'},))
        eq_(res.status_code, 200)
        objs = json.loads(res.content)['objects']
        eq_(len(objs), 0)

        res = self.client.get(self.url + ({'type': 'vindaloo'},))
        eq_(res.status_code, 400)
        error = json.loads(res.content)['error_message']
        eq_(error.keys(), ['type'])

    def test_extra_attributes(self):
        version = self.webapp.versions.latest()
        version.has_editor_comment = True
        version.has_info_request = True
        version.save()

        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        obj = json.loads(res.content)['objects'][0]

        # These only exist if requested by a reviewer.
        eq_(obj['latest_version_status'], amo.STATUS_PUBLIC)
        eq_(obj['reviewer_flags']['has_comment'], True)
        eq_(obj['reviewer_flags']['has_info_request'], True)
        eq_(obj['reviewer_flags']['is_escalated'], False)


class TestCategoriesWithFeatured(BaseOAuth, ESTestCase):
    fixtures = fixture('user_2519', 'webapp_337141')
    list_url = list_url('search/featured')

    def setUp(self):
        super(TestCategoriesWithFeatured, self).setUp()
        self.create_switch('search-api-es')
        self.cat = Category.objects.create(type=amo.ADDON_WEBAPP, slug='shiny')
        self.app = Webapp.objects.get(pk=337141)

    def test_featured_plus_category(self):
        app2 = amo.tests.app_factory()
        AddonCategory.objects.get_or_create(addon=app2, category=self.cat)
        AddonCategory.objects.get_or_create(addon_id=self.app.pk,
                                            category=self.cat)
        self.make_featured(app=app2, category=self.cat, region=mkt.regions.US)
        self.reindex(Webapp, 'webapp')

        res = self.client.get(self.list_url + ({'cat': 'shiny'},))
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        eq_(len(data['objects']), 2)
        eq_(len(data['featured']), 1)
        eq_(int(data['featured'][0]['id']), app2.pk)

    def test_no_category(self):
        AddonCategory.objects.get_or_create(addon=self.app, category=self.cat)
        self.make_featured(app=self.app, category=None, region=mkt.regions.US)
        self.reindex(Webapp, 'webapp')

        res = self.client.get(self.list_url)
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        eq_(len(data['objects']), 2)
        eq_(len(data['featured']), 1)
        eq_(int(data['featured'][0]['id']), self.app.pk)
