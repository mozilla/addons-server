from decimal import Decimal

from elasticutils.contrib.django import S
from nose.tools import eq_, ok_

import amo
import amo.tests

from addons.models import AddonDeviceType, AddonUser, Preview
from market.models import AddonPremium, AddonPurchase, Price
from mkt.constants import FEATURES_DICT, regions
from mkt.site.fixtures import fixture
from mkt.webapps.models import Installed, Webapp, WebappIndexer
from mkt.webapps.utils import (app_to_dict, es_app_to_dict,
                               get_supported_locales)
from users.models import UserProfile


class TestAppToDict(amo.tests.TestCase):
    fixtures = fixture('user_2519')

    def setUp(self):
        self.app = amo.tests.app_factory()
        self.profile = UserProfile.objects.get(pk=2519)
        self.features = self.app.current_version.features

    def test_no_previews(self):
        eq_(app_to_dict(self.app)['previews'], [])

    def test_with_preview(self):
        obj = Preview.objects.create(**{'caption': 'foo',
            'filetype': 'image/png', 'thumbtype': 'image/png',
            'addon': self.app})
        preview = app_to_dict(self.app)['previews'][0]
        self.assertSetEqual(preview,
            ['caption', 'filetype', 'id', 'image_url', 'thumbnail_url',
             'resource_uri'])
        eq_(preview['caption'], 'foo')
        eq_(int(preview['id']), obj.pk)

    def test_no_rating(self):
        eq_(app_to_dict(self.app)['content_ratings'], None)

    def test_no_price(self):
        res = app_to_dict(self.app)
        eq_(res['price'], None)
        eq_(res['price_locale'], None)

    def check_profile(self, profile, **kw):
        expected = {'developed': False, 'installed': False, 'purchased': False}
        expected.update(**kw)
        eq_(profile, expected)

    def test_installed(self):
        self.app.installed.create(user=self.profile)
        res = app_to_dict(self.app, profile=self.profile)
        self.check_profile(res['user'], installed=True)

    def test_purchased(self):
        self.app.addonpurchase_set.create(user=self.profile)
        res = app_to_dict(self.app, profile=self.profile)
        self.check_profile(res['user'], purchased=True)

    def test_owned(self):
        self.app.addonuser_set.create(user=self.profile)
        res = app_to_dict(self.app, profile=self.profile)
        self.check_profile(res['user'], developed=True)

    def test_locales(self):
        res = app_to_dict(self.app)
        eq_(res['default_locale'], 'en-US')
        eq_(res['supported_locales'], [])

    def test_multiple_locales(self):
        self.app.current_version.update(supported_locales='en-US,it')
        res = app_to_dict(self.app)
        self.assertSetEqual(res['supported_locales'], ['en-US', 'it'])

    def test_regions(self):
        res = app_to_dict(self.app)
        self.assertSetEqual([region['slug'] for region in res['regions']],
                            [region.slug for region in self.app.get_regions()])

    def test_no_features(self):
        res = app_to_dict(self.app)
        self.assertSetEqual(res['current_version']['required_features'], [])

    def test_one_feature(self):
        self.features.update(has_pay=True)
        res = app_to_dict(self.app)
        self.assertSetEqual(res['current_version']['required_features'],
                            ['pay'])

    def test_all_features(self):
        data = dict(('has_' + f.lower(), True) for f in FEATURES_DICT.keys())
        self.features.update(**data)
        res = app_to_dict(self.app)
        self.assertSetEqual(res['current_version']['required_features'],
                            [f.lower() for f in FEATURES_DICT.keys()])


class TestAppToDictPrices(amo.tests.TestCase):
    fixtures = fixture('prices')

    def setUp(self):
        self.app = amo.tests.app_factory(premium_type=amo.ADDON_PREMIUM)
        price = Price.objects.get(pk=1)
        self.premium = AddonPremium.objects.create(addon=self.app, price=price)

    def test_some_price(self):
        res = app_to_dict(self.app, region=regions.US.id)
        eq_(res['price'], Decimal('0.99'))
        eq_(res['price_locale'], '$0.99')

    def test_with_locale(self):
        with self.activate(locale='fr'):
            res = app_to_dict(self.app, region=regions.PL.id)
            eq_(res['price'], Decimal('5.01'))
            eq_(res['price_locale'], u'5,01\xa0PLN')

    def test_missing_price(self):
        self.premium.update(price=None)
        res = app_to_dict(self.app)
        eq_(res['price'], None)
        eq_(res['price_locale'], None)


class TestESAppToDict(amo.tests.ESTestCase):
    fixtures = fixture('user_2519', 'webapp_337141')

    def setUp(self):
        self.create_switch('search-api-es')
        self.app = Webapp.objects.get(pk=337141)
        self.profile = UserProfile.objects.get(pk=2519)
        self.app.save()
        self.refresh('webapp')

    def get_obj(self):
        return S(WebappIndexer).filter(id=self.app.pk).execute().objects[0]

    def test_basic(self):
        res = es_app_to_dict(self.get_obj())
        expected = {
            'absolute_url': 'http://testserver/app/something-something/',
            'app_type': 'hosted',
            'created': '2011-10-18T16:28:24',
            'current_version': {
                'release_notes': None,
                'version': '1.0',
                'developer_name': u'31337 \u0627\u0644\u062a\u0637\u0628'
            },
            'description': u'Something Something Steamcube description!',
            'homepage': '',
            'id': '337141',
            'is_packaged': False,
            'listed_authors': [
                {'name': u'31337 \u0627\u0644\u062a\u0637\u0628'},
            ],
            'manifest_url': 'http://micropipes.com/temp/steamcube.webapp',
            'name': 'Something Something Steamcube!',
            'premium_type': 'free',
            'public_stats': False,
            'ratings': {
                'average': 0.0,
                'count': 0,
            },
            'slug': 'something-something',
            'status': 4,
            'summary': u'',
            'support_email': None,
            'support_url': None,
            'user': {
                'developed': False,
                'installed': False,
                'purchased': False,
            },
            'weekly_downloads': None,
        }

        for k, v in res.items():
            if k in expected:
                eq_(expected[k], v, u'Unexpected value for field: %s' % k)

    def test_show_downloads_count(self):
        """Show weekly_downloads in results if app stats are public"""
        self.app.update(public_stats=True)
        self.refresh('webapp')
        res = es_app_to_dict(self.get_obj())
        eq_(res['weekly_downloads'], 9999)

    def test_icons(self):
        """
        Tested separately b/c they have timestamps.
        """
        res = es_app_to_dict(self.get_obj())
        self.assertSetEqual(set([16, 48, 64, 128]), set(res['icons'].keys()))
        ok_(res['icons'][128].startswith(
            'http://testserver/img/uploads/addon_icons/337/337141-128.png'))

    def test_devices(self):
        AddonDeviceType.objects.create(addon=self.app,
                                       device_type=amo.DEVICE_GAIA.id)
        self.app.save()
        self.refresh('webapp')

        res = es_app_to_dict(self.get_obj())
        eq_(res['device_types'], ['firefoxos'])

    def test_user(self):
        AddonPurchase.objects.create(addon=self.app, user=self.profile)
        Installed.objects.create(addon=self.app, user=self.profile)
        AddonUser.objects.create(addon=self.app, user=self.profile)
        self.app.save()
        self.refresh('webapp')

        res = es_app_to_dict(self.get_obj(), profile=self.profile)
        eq_(res['user'], {
            'developed': True,
            'installed': True,
            'purchased': True,
        })


class TestSupportedLocales(amo.tests.TestCase):

    def setUp(self):
        self.manifest = {'default_locale': 'en'}

    def check(self, expected):
        eq_(get_supported_locales(self.manifest), expected)

    def test_empty_locale(self):
        self.check([])

    def test_single_locale(self):
        self.manifest.update({'locales': {'es': {'name': 'eso'}}})
        self.check(['es'])

    def test_multiple_locales(self):
        self.manifest.update({'locales': {'es': {'name': 'si'},
                                          'fr': {'name': 'oui'}}})
        self.check(['es', 'fr'])

    def test_short_locale(self):
        self.manifest.update({'locales': {'pt': {'name': 'sim'}}})
        self.check(['pt-PT'])

    def test_unsupported_locale(self):
        self.manifest.update({'locales': {'xx': {'name': 'xx'}}})
        self.check([])
