# -*- coding: utf-8 -*-
import json
from urlparse import urlparse

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.http import QueryDict
from django.test.client import RequestFactory

from mock import MagicMock, patch
from nose.tools import eq_, ok_
from rest_framework.exceptions import ParseError, PermissionDenied

import amo
import mkt
from access.middleware import ACLMiddleware
from addons.models import AddonCategory, AddonDeviceType, AddonUpsell, Category
from amo.helpers import absolutify
from amo.tests import app_factory, ESTestCase, TestCase
from amo.urlresolvers import reverse
from stats.models import ClientData
from tags.models import Tag
from translations.helpers import truncate
from users.models import UserProfile

import mkt.regions
from mkt.api.tests.test_oauth import RestOAuth, RestOAuthClient
from mkt.collections.constants import (COLLECTIONS_TYPE_BASIC,
                                       COLLECTIONS_TYPE_FEATURED,
                                       COLLECTIONS_TYPE_OPERATOR)
from mkt.collections.models import Collection
from mkt.constants import regions
from mkt.constants.features import FeatureProfile
from mkt.regions.middleware import RegionMiddleware
from mkt.search.api import SearchView
from mkt.search.forms import DEVICE_CHOICES_IDS
from mkt.search.views import DEFAULT_SORTING
from mkt.site.fixtures import fixture
from mkt.webapps.models import Installed, Webapp
from mkt.webapps.tasks import unindex_webapps


class TestGetRegion(TestCase):
    fixtures = fixture('user_2519', 'webapp_337141')

    def setUp(self):
        self.resource = SearchView()
        self.factory = RequestFactory()
        self.profile = UserProfile.objects.get(pk=2519)
        self.user = self.profile.user

    def region_for(self, region):
        req = self.factory.get('/', ({} if region is None else
                                     {'region': region}))
        req.API = True
        req.LANG = ''
        req.user = self.user
        req.amo_user = self.profile
        RegionMiddleware().process_request(req)
        ACLMiddleware().process_request(req)
        return self.resource.get_region(req)

    def give_permission(self):
        self.grant_permission(self.profile, 'Regions:BypassFilters')

    def make_curator(self):
        collection = Collection.objects.create(
            collection_type=COLLECTIONS_TYPE_BASIC)
        collection.curators.add(self.profile)

    @patch('mkt.regions.middleware.RegionMiddleware.region_from_request')
    def test_get_region_all(self, mock_request_region):
        self.give_permission()
        geoip_fallback = regions.PE  # Different than the default (worldwide).
        mock_request_region.return_value = geoip_fallback.slug

        # Test none-ish values (should return None, i.e. no region).
        eq_(self.region_for('None'), None)

        # Test string values (should return region with that slug).
        eq_(self.region_for('worldwide'), regions.WORLDWIDE)
        eq_(self.region_for('us'), regions.US)

        # Test fallback to request.REGION (should return GeoIP region if region
        # isn't specified or is specified and empty).
        eq_(self.region_for(None), geoip_fallback)
        eq_(self.region_for(''), geoip_fallback)

        # Test fallback to worldwide (e.g. if GeoIP fails).
        with patch('mkt.regions.middleware.RegionMiddleware.'
                   'process_request') as mock_process_request:
            eq_(self.region_for(None), regions.WORLDWIDE)
            ok_(mock_process_request.called)

        # Test invalid value (should raise exception).
        with self.assertRaises(ParseError):
            self.region_for('cvanland')  # Scary place

    def test_get_region_permission(self):
        self.give_permission()
        eq_(self.region_for('None'), None)
        eq_(self.region_for('us'), regions.US)

    def test_collection_curator(self):
        self.make_curator()
        eq_(self.region_for('None'), None)
        eq_(self.region_for('us'), regions.US)

    def test_no_permission_not_curator(self):
        with self.assertRaises(PermissionDenied):
            eq_(self.region_for('None'), None)
        eq_(self.region_for('us'), regions.US)


@patch('versions.models.Version.is_privileged', False)
class TestApi(RestOAuth, ESTestCase):
    fixtures = fixture('webapp_337141')

    def setUp(self):
        self.client = RestOAuthClient(None)
        self.url = reverse('search-api')
        self.webapp = Webapp.objects.get(pk=337141)
        self.category = Category.objects.create(name='test', slug='test',
                                                type=amo.ADDON_WEBAPP)
        self.webapp.save()
        self.refresh('webapp')

    def tearDown(self):
        unindex_webapps(list(Webapp.with_deleted.values_list('id', flat=True)))
        Webapp.objects.all().delete()
        super(TestApi, self).tearDown()

    def test_verbs(self):
        self._allowed_verbs(self.url, ['get'])

    def test_has_cors(self):
        self.assertCORS(self.client.get(self.url), 'get')

    def test_meta(self):
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        eq_(set(res.json.keys()), set(['objects', 'meta']))
        eq_(res.json['meta']['total_count'], 1)

    def test_wrong_category(self):
        res = self.client.get(self.url,
                              data={'cat': self.category.slug + 'xq'})
        eq_(res.status_code, 400)
        eq_(res['Content-Type'], 'application/json')

    def test_wrong_weight(self):
        self.category.update(weight=-1)
        res = self.client.get(self.url, data={'cat': self.category.slug})
        eq_(res.status_code, 200)
        eq_(len(res.json['objects']), 0)

    def test_wrong_sort(self):
        res = self.client.get(self.url, data={'sort': 'awesomeness'})
        eq_(res.status_code, 400)

    def test_sort(self):
        # Mocked version, to make sure we are calling ES with the parameters
        # we want.
        with patch('mkt.webapps.models.Webapp.from_search') as mocked_search:
            mocked_qs = MagicMock()
            mocked_search.return_value = mocked_qs
            for api_sort, es_sort in DEFAULT_SORTING.items():
                res = self.client.get(self.url, [('sort', api_sort)])
                eq_(res.status_code, 200, res.content)
                mocked_qs.order_by.assert_called_with(es_sort)

        # Unmocked version, to make sure elasticsearch is actually accepting
        # the params.
        for api_sort, es_sort in DEFAULT_SORTING.items():
            res = self.client.get(self.url, [('sort', api_sort)])
            eq_(res.status_code, 200)

    def test_right_category(self):
        res = self.client.get(self.url, data={'cat': self.category.pk})
        eq_(res.status_code, 200)
        eq_(res.json['objects'], [])

    def create(self):
        AddonCategory.objects.create(addon=self.webapp, category=self.category)
        self.webapp.save()
        self.refresh('webapp')

    def test_right_category_present(self):
        self.create()
        res = self.client.get(
            self.url, data={'cat': self.category.pk})
        eq_(res.status_code, 200)
        objs = res.json['objects']
        eq_(len(objs), 1)

    def test_user_info_with_shared_secret(self):
        user = UserProfile.objects.all()[0]

        def fakeauth(auth, req, **kw):
            req.user = user.user
            req.amo_user = user
            return True

        with patch('mkt.api.authentication.RestSharedSecretAuthentication'
                   '.is_authenticated', fakeauth):
            with self.settings(SITE_URL=''):
                self.create()
            res = self.client.get(
                self.url, data={'cat': self.category.pk})
            obj = res.json['objects'][0]
            assert 'user' in obj

    def test_dehydrate(self):
        def fakeauth(auth, req, **kw):
            req.user = AnonymousUser()
            return True

        with patch('mkt.api.authentication.RestSharedSecretAuthentication'
                   '.is_authenticated', fakeauth):
            with self.settings(SITE_URL=''):
                self.create()
                res = self.client.get(self.url, data={'cat': self.category.pk})
                eq_(res.status_code, 200)
                obj = res.json['objects'][0]
                eq_(obj['absolute_url'], self.webapp.get_absolute_url())
                eq_(obj['app_type'], self.webapp.app_type)
                eq_(obj['content_ratings'],
                    {'descriptors': {}, 'interactive_elements': [],
                     'ratings': None})
                eq_(obj['current_version'], u'1.0')
                eq_(obj['description'],
                    {'en-US': self.webapp.description.localized_string})
                eq_(obj['icons']['128'], self.webapp.get_icon_url(128))
                eq_(obj['id'], long(self.webapp.id))
                eq_(obj['manifest_url'], self.webapp.get_manifest_url())
                eq_(obj['payment_account'], None)
                self.assertApiUrlEqual(obj['privacy_policy'],
                                       '/apps/app/337141/privacy/')
                eq_(obj['public_stats'], self.webapp.public_stats)
                eq_(obj['ratings'], {'average': 0.0, 'count': 0})
                self.assertApiUrlEqual(obj['resource_uri'],
                                       '/apps/app/337141/')
                eq_(obj['slug'], self.webapp.app_slug)
                eq_(obj['supported_locales'], ['en-US', 'es', 'pt-BR'])
                ok_('1.0' in obj['versions'])
                self.assertApiUrlEqual(obj['versions']['1.0'],
                                       '/apps/versions/1268829/')

        # These only exists if requested by a reviewer.
        ok_('latest_version' not in obj)
        ok_('reviewer_flags' not in obj)

    def test_upsell(self):
        upsell = app_factory(premium_type=amo.ADDON_PREMIUM)
        AddonUpsell.objects.create(free=self.webapp, premium=upsell)
        self.webapp.save()
        self.refresh('webapp')

        res = self.client.get(self.url, {'premium_types': 'free'})
        eq_(res.status_code, 200)
        eq_(len(res.json['objects']), 1)
        obj = res.json['objects'][0]
        eq_(obj['upsell']['id'], upsell.id)
        eq_(obj['upsell']['app_slug'], upsell.app_slug)
        eq_(obj['upsell']['name'], upsell.name)
        eq_(obj['upsell']['icon_url'], upsell.get_icon_url(128))
        self.assertApiUrlEqual(obj['upsell']['resource_uri'],
                               '/apps/app/%s/' % upsell.id)
        eq_(obj['upsell']['region_exclusions'], [])

        unindex_webapps([upsell.id])
        upsell.delete()

    def test_dehydrate_regions(self):
        self.webapp.addonexcludedregion.create(region=mkt.regions.BR.id)
        self.webapp.save()
        self.refresh('webapp')

        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        obj = res.json['objects'][0]
        regions = obj['regions']
        ok_(mkt.regions.BR.slug not in [r['slug'] for r in regions])
        eq_(len(regions), len(mkt.regions.ALL_REGION_IDS) - 1)

    def test_region_filtering(self):
        self.webapp.addonexcludedregion.create(region=mkt.regions.BR.id)
        self.webapp.save()
        self.refresh('webapp')

        res = self.client.get(self.url, data={'region': 'br'})
        eq_(res.status_code, 200)
        objs = res.json['objects']
        eq_(len(objs), 0)

    def test_languages_filtering(self):
        # This webapp's supported_locales: [u'en-US', u'es', u'pt-BR']

        res = self.client.get(self.url, data={'languages': 'fr'})
        eq_(res.status_code, 200)
        objs = res.json['objects']
        eq_(len(objs), 0)

        for lang in ('fr,pt-BR', 'es, pt-BR', 'es', 'pt-BR'):
            res = self.client.get(self.url, data={'languages': lang})
            eq_(res.status_code, 200)
            obj = res.json['objects'][0]
            eq_(obj['slug'], self.webapp.app_slug)

    def test_offline_filtering(self):
        def check(offline, visible):
            res = self.client.get(self.url, data={'offline': offline})
            eq_(res.status_code, 200)
            objs = res.json['objects']
            eq_(len(objs), int(visible))

        # Should NOT show up in offline.
        # Should show up in online.
        # Should show up everywhere if not filtered.
        check(offline='True', visible=False)
        check(offline='False', visible=True)
        check(offline='None', visible=True)

        # Mark that app is capable offline.
        self.webapp.update(is_packaged=True)
        self.refresh('webapp')

        # Should show up in offline.
        # Should NOT show up in online.
        # Should show up everywhere if not filtered.
        check(offline='True', visible=True)
        check(offline='False', visible=False)
        check(offline='None', visible=True)

    def test_q(self):
        res = self.client.get(self.url, data={'q': 'something'})
        eq_(res.status_code, 200)
        obj = res.json['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

    def test_q_exact(self):
        app1 = app_factory(name='test app test11')
        app2 = app_factory(name='test app test21')
        app3 = app_factory(name='test app test31')
        self.refresh('webapp')

        res = self.client.get(self.url, data={'q': 'test app test21'})
        eq_(res.status_code, 200)
        eq_(len(res.json['objects']), 3)
        # app2 should be first since it's an exact match and is boosted higher.
        obj = res.json['objects'][0]
        eq_(obj['slug'], app2.app_slug)

        unindex_webapps([app1.id, app2.id, app3.id])
        app1.delete()
        app2.delete()
        app3.delete()

    def test_q_is_tag(self):
        Tag(tag_text='whatsupp').save_tag(self.webapp)
        self.webapp.save()
        self.refresh('webapp')
        res = self.client.get(self.url, data={'q': 'whatsupp'})
        eq_(res.status_code, 200)
        obj = res.json['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

    def test_icu_folding(self):
        self.webapp.name = {'es': 'Páginas Amarillos'}
        self.webapp.save()
        self.refresh('webapp')
        res = self.client.get(self.url, data={'q': 'paginas'})
        eq_(res.status_code, 200)
        obj = res.json['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

    def test_camel_case_word_splitting(self):
        self.webapp.name = 'AirCombat'
        self.webapp.save()
        self.refresh('webapp')
        res = self.client.get(self.url, data={'q': 'air combat'})
        eq_(res.status_code, 200)
        obj = res.json['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

    def test_name_localized(self):
        # First test no ?lang parameter returns all localizations.
        res = self.client.get(self.url, data={'q': 'something'})
        eq_(res.status_code, 200)
        obj = res.json['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)
        eq_(obj['name'], {u'en-US': u'Something Something Steamcube!',
                          u'es': u'Algo Algo Steamcube!'})

        # Second test that adding ?lang returns only that localization.
        res = self.client.get(self.url,
                              data={'q': 'something', 'lang': 'es'})
        eq_(res.status_code, 200)
        obj = res.json['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)
        eq_(obj['name'], u'Algo Algo Steamcube!')

    def test_other_localized(self):
        # Test fields that should be localized.
        translations = {'en-US': u'Test in English',
                        'es': u'Test in Español'}
        self.webapp.homepage = translations
        self.webapp.support_email = translations
        self.webapp.support_url = translations
        self.webapp.save()
        self.refresh('webapp')

        res = self.client.get(self.url, data={'q': 'something'})
        eq_(res.status_code, 200)
        obj = res.json['objects'][0]
        eq_(obj['homepage'], translations)
        eq_(obj['support_email'], translations)
        eq_(obj['support_url'], translations)

    def test_name_localized_to_default_locale(self):
        self.webapp.update(default_locale='es')
        self.refresh('webapp')

        # Make a request in another language that we know will fail.
        res = self.client.get(self.url,
                              data={'q': 'something', 'lang': 'de'})
        eq_(res.status_code, 200)
        obj = res.json['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)
        eq_(obj['name'], u'Algo Algo Steamcube!')

    def test_device(self):
        AddonDeviceType.objects.create(
            addon=self.webapp, device_type=DEVICE_CHOICES_IDS['desktop'])
        self.webapp.save()
        self.refresh('webapp')
        res = self.client.get(self.url, data={'device': 'desktop'})
        eq_(res.status_code, 200)
        obj = res.json['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

    def test_no_flash_on_firefoxos(self):
        AddonDeviceType.objects.create(
            addon=self.webapp, device_type=DEVICE_CHOICES_IDS['firefoxos'])
        f = self.webapp.get_latest_file()
        f.uses_flash = True
        f.save()
        self.webapp.save()
        self.refresh('webapp')
        res = self.client.get(self.url, data={'dev': 'firefoxos'})
        eq_(res.status_code, 200)
        eq_(len(res.json['objects']), 0)

    def test_premium_types(self):
        res = self.client.get(self.url,
                              data={'premium_types': 'free'})
        eq_(res.status_code, 200)
        obj = res.json['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

    def test_premium_types_empty(self):
        res = self.client.get(self.url,
                              data={'premium_types': 'premium'})
        eq_(res.status_code, 200)
        objs = res.json['objects']
        eq_(len(objs), 0)

    def test_multiple_premium_types(self):
        res = self.client.get(self.url,
                              data={'premium_types': ['free', 'premium']})
        eq_(res.status_code, 200)
        obj = res.json['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

    def test_app_type_hosted(self):
        res = self.client.get(self.url,
                              data={'app_type': 'hosted'})
        eq_(res.status_code, 200)
        obj = res.json['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

    def test_app_type_packaged(self):
        self.webapp.update(is_packaged=True)
        self.refresh('webapp')

        res = self.client.get(self.url,
                              data={'app_type': 'packaged'})
        eq_(res.status_code, 200)
        obj = res.json['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

    def test_app_type_privileged(self):
        # Override the class-decorated patch.
        with patch('versions.models.Version.is_privileged', True):
            self.webapp.update(is_packaged=True)
            self.refresh('webapp')

            res = self.client.get(self.url,
                                  data={'app_type': 'packaged'})
            eq_(res.status_code, 200)
            eq_(len(res.json['objects']), 0)

            res = self.client.get(self.url,
                                  data={'app_type': 'privileged'})
            eq_(res.status_code, 200)
            eq_(len(res.json['objects']), 1)
            obj = res.json['objects'][0]
            eq_(obj['slug'], self.webapp.app_slug)

    def test_status_value_packaged(self):
        # When packaged and not a reviewer we exclude latest version status.
        self.webapp.update(is_packaged=True)
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        obj = res.json['objects'][0]
        eq_(obj['status'], amo.STATUS_PUBLIC)
        eq_('latest_version' in obj, False)

    def test_addon_type_anon(self):
        res = self.client.get(self.url, data={'type': 'app'})
        eq_(res.status_code, 200)
        obj = res.json['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

        res = self.client.get(self.url, data={'type': 'vindaloo'})
        eq_(res.status_code, 400)
        error = res.json['detail']
        eq_(error.keys(), ['type'])

        res = self.client.get(self.url, data={'type': 'theme'})
        eq_(res.status_code, 200)
        eq_(len(res.json['objects']), 0)

    def test_adolescent_popularity(self):
        """
        Adolescent regions use global popularity.

          Webapp:   Global: 0, Regional: 0
          Unknown1: Global: 1, Regional: 1 + 10 * 1 = 11
          Unknown2: Global: 2, Regional: 0

        """
        user = UserProfile.objects.all()[0]
        cd = ClientData.objects.create(region=mkt.regions.BR.id)

        unknown1 = amo.tests.app_factory()
        Installed.objects.create(addon=unknown1, user=user, client_data=cd)

        unknown2 = amo.tests.app_factory()
        Installed.objects.create(addon=unknown2, user=user)
        Installed.objects.create(addon=unknown2, user=user)

        self.reindex(Webapp, 'webapp')

        res = self.client.get(self.url, data={'region': 'br'})
        eq_(res.status_code, 200)

        objects = res.json['objects']
        eq_(len(objects), 3)

        eq_(int(objects[0]['id']), unknown2.id)
        eq_(int(objects[1]['id']), unknown1.id)
        eq_(int(objects[2]['id']), self.webapp.id)

        # Cleanup to remove these from the index.
        unindex_webapps([unknown1.id, unknown2.id])
        unknown1.delete()
        unknown2.delete()

    def test_word_delimiter_preserves_original(self):
        self.webapp.description = {
            'en-US': 'This is testing word delimiting preservation in long '
                     'descriptions and here is what we want to find: WhatsApp'
        }
        self.webapp.save()
        self.reindex(Webapp, 'webapp')

        res = self.client.get(self.url, data={'q': 'whatsapp'})
        eq_(res.status_code, 200)
        obj = res.json['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

    def test_pagination(self):
        Webapp.objects.get(pk=337141).delete()
        app1 = app_factory(name='test app test1')
        app2 = app_factory(name='test app test2')
        app3 = app_factory(name='test app test3')
        # Setting 'created' app_factory is unreliable and we need a reliable
        # order.
        app1.update(created=self.days_ago(1))
        app2.update(created=self.days_ago(2))
        app3.update(created=self.days_ago(3))
        self.refresh('webapp')

        res = self.client.get(self.url, data={'limit': '2', 'sort': 'created'})
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        eq_(len(data['objects']), 2)
        eq_(int(data['objects'][0]['id']), app1.id)
        eq_(int(data['objects'][1]['id']), app2.id)
        eq_(data['meta']['total_count'], 3)
        eq_(data['meta']['limit'], 2)
        eq_(data['meta']['previous'], None)
        eq_(data['meta']['offset'], 0)

        next = urlparse(data['meta']['next'])
        eq_(next.path, self.url)
        eq_(QueryDict(next.query).dict(), {'limit': '2', 'offset': '2',
                                           'sort': 'created'})

        res = self.client.get(self.url, QueryDict(next.query).dict())
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        eq_(len(data['objects']), 1)
        eq_(int(data['objects'][0]['id']), app3.id)
        eq_(data['meta']['total_count'], 3)
        eq_(data['meta']['limit'], 2)
        prev = urlparse(data['meta']['previous'])
        eq_(next.path, self.url)
        eq_(QueryDict(prev.query).dict(), {'limit': '2', 'offset': '0',
                                           'sort': 'created'})
        eq_(data['meta']['offset'], 2)
        eq_(data['meta']['next'], None)


class TestApiFeatures(RestOAuth, ESTestCase):
    fixtures = fixture('webapp_337141')

    def setUp(self):
        self.client = RestOAuthClient(None)
        self.url = reverse('search-api')
        self.webapp = Webapp.objects.get(pk=337141)
        self.category = Category.objects.create(name='test',
                                                type=amo.ADDON_WEBAPP)
        # Pick a few common device features.
        self.profile = FeatureProfile(apps=True, audio=True, fullscreen=True,
                                      geolocation=True, indexeddb=True,
                                      sms=True).to_signature()
        self.qs = {'q': 'something', 'pro': self.profile, 'dev': 'firefoxos'}

    def test_no_features(self):
        # Base test to make sure we find the app.
        self.webapp.save()
        self.refresh('webapp')

        res = self.client.get(self.url, data=self.qs)
        eq_(res.status_code, 200)
        obj = json.loads(res.content)['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

    def test_one_good_feature(self):
        # Enable an app feature that matches one in our profile.
        self.webapp.current_version.features.update(has_geolocation=True)
        self.webapp.save()
        self.refresh('webapp')

        res = self.client.get(self.url, data=self.qs)
        eq_(res.status_code, 200)
        obj = json.loads(res.content)['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

    def test_one_bad_feature(self):
        # Enable an app feature that doesn't match one in our profile.
        self.webapp.current_version.features.update(has_pay=True)
        self.webapp.save()
        self.refresh('webapp')

        res = self.client.get(self.url, data=self.qs)
        eq_(res.status_code, 200)
        objs = json.loads(res.content)['objects']
        eq_(len(objs), 0)

    def test_all_good_features(self):
        # Enable app features so they exactly match our device profile.
        fp = FeatureProfile.from_signature(self.profile)
        self.webapp.current_version.features.update(
            **dict(('has_%s' % k, v) for k, v in fp.items()))
        self.webapp.save()
        self.refresh('webapp')

        res = self.client.get(self.url, data=self.qs)
        eq_(res.status_code, 200)
        obj = json.loads(res.content)['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

    def test_bad_profile_on_desktop(self):
        # Enable an app feature that doesn't match one in our profile.
        qs = self.qs.copy()
        del qs['dev']  # Desktop doesn't send a device.
        self.webapp.current_version.features.update(has_pay=True)
        self.webapp.save()
        self.refresh('webapp')

        res = self.client.get(self.url, data=qs)
        eq_(res.status_code, 200)
        obj = json.loads(res.content)['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)


class BaseFeaturedTests(RestOAuth, ESTestCase):
    fixtures = fixture('user_2519', 'webapp_337141')
    list_url = reverse('featured-search-api')

    def setUp(self):
        super(BaseFeaturedTests, self).setUp()
        self.cat = Category.objects.create(type=amo.ADDON_WEBAPP, slug='shiny')
        self.app = Webapp.objects.get(pk=337141)
        AddonDeviceType.objects.create(
            addon=self.app, device_type=DEVICE_CHOICES_IDS['firefoxos'])
        AddonCategory.objects.get_or_create(addon=self.app, category=self.cat)
        self.profile = FeatureProfile(apps=True, audio=True, fullscreen=True,
                                      geolocation=True, indexeddb=True,
                                      sms=True).to_signature()
        self.qs = {'cat': 'shiny', 'pro': self.profile, 'dev': 'firefoxos'}


class TestFeaturedCollections(BaseFeaturedTests):
    """
    Tests to ensure that CollectionFilterSetWithFallback is being called and
    its results are being added to the response.
    """
    col_type = COLLECTIONS_TYPE_BASIC
    prop_name = 'collections'

    def setUp(self):
        super(TestFeaturedCollections, self).setUp()
        self.col = Collection.objects.create(
            name='Hi', description='Mom', collection_type=self.col_type,
            category=self.cat, is_public=True, region=mkt.regions.US.id)
        self.qs['region'] = mkt.regions.US.slug
        self.create_switch('collections-use-es-for-apps')
        # FIXME: mock the search part, we don't care about it.

    def make_request(self):
        res = self.client.get(self.list_url, self.qs)
        eq_(res.status_code, 200)
        return res, res.json

    def test_added_to_results(self):
        res, json = self.make_request()
        ok_(self.prop_name in res.json)
        eq_(len(json[self.prop_name]), 1)
        eq_(json[self.prop_name][0]['id'], self.col.id)
        return res, json

    def test_apps_included(self):
        self.col.add_app(self.app)
        self.refresh('webapp')

        res, json = self.test_added_to_results()
        eq_(len(json[self.prop_name][0]['apps']), 1)

    def test_features_filtered(self):
        """
        Test that the app list is passed through feature profile filtering.
        """
        self.app.current_version.features.update(has_pay=True)
        self.col.add_app(self.app)
        self.refresh('webapp')

        res, json = self.test_added_to_results()
        eq_(len(json[self.prop_name][0]['apps']), 0)

    def test_only_public(self):
        self.col2 = Collection.objects.create(
            name='Col', description='Hidden', collection_type=self.col_type,
            category=self.cat, is_public=False)
        res, json = self.test_added_to_results()

        header = 'API-Fallback-%s' % self.prop_name
        ok_(not header in res)

    def test_only_this_type(self):
        """
        Add a second collection of a different collection type, then ensure
        that it does not change the results of this collection type's property.
        """
        different_type = (COLLECTIONS_TYPE_FEATURED if self.col_type ==
                          COLLECTIONS_TYPE_BASIC else COLLECTIONS_TYPE_BASIC)
        self.col2 = Collection.objects.create(
            name='Bye', description='Dad', collection_type=different_type,
            category=self.cat, is_public=True)
        res, json = self.test_added_to_results()

        header = 'API-Fallback-%s' % self.prop_name
        ok_(not header in res)

    @patch('mkt.collections.serializers.CollectionMembershipField.to_native_es')
    def test_limit(self, mock_field_to_native):
        """
        Add a second collection, then ensure than the old one is not present
        in the results since we are limiting at 1 collection of each type
        """
        mock_field_to_native.return_value = None
        self.col.add_app(self.app)
        self.col = Collection.objects.create(
            name='Me', description='Hello', collection_type=self.col_type,
            category=self.cat, is_public=True, region=mkt.regions.US.id)

        # Call standard test method that adds the app and refreshes ES.
        self.test_apps_included()

        # We are only dealing with one collection with only one app inside,
        # our mock of the method that serializes app data from the db should
        # only have been called once.
        eq_(mock_field_to_native.call_count, 1)

    @patch('mkt.collections.serializers.CollectionMembershipField.to_native')
    def test_limit_preview(self, mock_field_to_native):
        """
        Like test_limit, except we are in preview mode, so we shouldn't be using
        ES for apps. The mock is adjusted accordingly.
        """
        mock_field_to_native.return_value = None
        self.col.add_app(self.app)
        self.col = Collection.objects.create(
            name='Me', description='Hello', collection_type=self.col_type,
            category=self.cat, is_public=True, region=mkt.regions.US.id)

        # Call standard test method that adds the app and tests the result, but
        # make sure we're in preview mode.
        self.qs['preview'] = True
        self.test_apps_included()

        # We are only dealing with one collection with only one app inside,
        # our mock of the method that serializes app data from ES should only
        # have been called once.
        eq_(mock_field_to_native.call_count, 1)

    @patch('mkt.search.api.SearchView.get_region')
    @patch('mkt.search.api.CollectionFilterSetWithFallback')
    def test_collection_filterset_called(self, mock_fallback, mock_region):
        """
        CollectionFilterSetWithFallback should be called 3 times, one for each
        collection_type.
        """
        # Mock get_region() and ensure we are not passing it as the query
        # string parameter.
        self.qs.pop('region', None)
        mock_region.return_value = mkt.regions.SPAIN

        res, json = self.make_request()
        eq_(mock_fallback.call_count, 3)

        # We expect all calls to contain self.qs and region parameter.
        expected_args = {'region': mkt.regions.SPAIN.slug}
        expected_args.update(self.qs)
        for call in mock_fallback.call_args_list:
            eq_(call[0][0], expected_args)

    def test_fallback_usage(self):
        """
        Test that the fallback mechanism is used for the collection_type we are
        testing.
        """
        # Request the list using region. self.col should get picked up
        # because the fallback mechanism will try with region set to None.
        self.col.update(region=None, carrier=None)
        self.qs['region'] = mkt.regions.SPAIN.slug
        self.qs['carrier'] = mkt.carriers.UNKNOWN_CARRIER.slug
        res, json = self.test_added_to_results()

        header = 'API-Fallback-%s' % self.prop_name
        ok_(header in res)
        eq_(res[header], 'region,carrier')


class TestFeaturedOperator(TestFeaturedCollections):
    col_type = COLLECTIONS_TYPE_OPERATOR
    prop_name = 'operator'


class TestFeaturedApps(TestFeaturedCollections):
    col_type = COLLECTIONS_TYPE_FEATURED
    prop_name = 'featured'


@patch.object(settings, 'SITE_URL', 'http://testserver')
class TestSuggestionsApi(ESTestCase):
    fixtures = fixture('webapp_337141')

    def setUp(self):
        self.url = reverse('suggestions-api')
        self.refresh('webapp')
        self.client = RestOAuthClient(None)
        self.app1 = Webapp.objects.get(pk=337141)
        self.app1.save()
        self.app2 = app_factory(name=u'Second âpp',
                                description=u'Second dèsc' * 25,
                                created=self.days_ago(3))
        self.refresh('webapp')

    def tearDown(self):
        # Cleanup to remove these from the index.
        unindex_webapps([self.app1.id, self.app2.id])
        self.app1.delete()
        self.app2.delete()

    def test_suggestions(self):
        response = self.client.get(self.url, data={'lang': 'en-US'})
        parsed = json.loads(response.content)
        eq_(parsed[0], '')
        self.assertSetEqual(
            parsed[1],
            [unicode(self.app1.name), unicode(self.app2.name)])
        self.assertSetEqual(
            parsed[2],
            [unicode(self.app1.description),
             unicode(truncate(self.app2.description))])
        self.assertSetEqual(
            parsed[3],
            [absolutify(self.app1.get_detail_url()),
             absolutify(self.app2.get_detail_url())])
        self.assertSetEqual(
            parsed[4],
            [self.app1.get_icon_url(64), self.app2.get_icon_url(64)])

    def test_suggestions_filtered(self):
        response = self.client.get(self.url, data={'q': 'Second',
                                                   'lang': 'en-US'})
        parsed = json.loads(response.content)
        eq_(parsed[1], [unicode(self.app2.name)])
