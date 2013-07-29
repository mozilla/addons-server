from decimal import Decimal

from django.test.utils import override_settings

import mock
import waffle
from elasticutils.contrib.django import S
from nose.tools import eq_, ok_
from test_utils import RequestFactory

import amo
import amo.tests

from addons.models import (AddonCategory, AddonDeviceType, Category,
                           Preview)
from market.models import PriceCurrency
from mkt.constants import regions
from mkt.site.fixtures import fixture
from mkt.webapps.models import Installed, Webapp, WebappIndexer
from mkt.webapps.utils import (app_to_dict, es_app_to_dict,
                               get_supported_locales)
from users.models import UserProfile
from versions.models import Version


class TestAppToDict(amo.tests.TestCase):
    fixtures = fixture('user_2519')

    def setUp(self):
        self.app = amo.tests.app_factory(version_kw={'version': '1.8'})
        self.profile = UserProfile.objects.get(pk=2519)

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
        eq_(res['payment_required'], False)

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

    def test_current_version(self):
        res = app_to_dict(self.app)
        ok_('current_version' in res)
        eq_(res['current_version'], self.app.current_version.version)

    def test_versions_one(self):
        res = app_to_dict(self.app)
        self.assertSetEqual([v.version for v in self.app.versions.all()],
                            res['versions'].keys())

    def test_versions_multiple(self):
        ver = Version.objects.create(addon=self.app, version='1.9')
        self.app.update(_current_version=ver, _latest_version=ver)
        res = app_to_dict(self.app)
        eq_(res['current_version'], ver.version)
        self.assertSetEqual([v.version for v in self.app.versions.all()],
                            res['versions'].keys())

    def test_categories(self):
        cat1 = Category.objects.create(type=amo.ADDON_WEBAPP, slug='cat1')
        cat2 = Category.objects.create(type=amo.ADDON_WEBAPP, slug='cat2')
        AddonCategory.objects.create(addon=self.app, category=cat1)
        AddonCategory.objects.create(addon=self.app, category=cat2)
        res = app_to_dict(self.app)
        self.assertSetEqual(res['categories'], ['cat1', 'cat2'])


@override_settings(PURCHASE_ENABLED_REGIONS=[regions.US.id, regions.PL.id])
class TestAppToDictPrices(amo.tests.TestCase):
    fixtures = fixture('user_2519')

    def setUp(self):
        self.app = amo.tests.app_factory(premium_type=amo.ADDON_PREMIUM)
        self.profile = UserProfile.objects.get(pk=2519)
        self.create_flag('allow-paid-app-search', everyone=True)

    def test_some_price(self):
        self.make_premium(self.app, price='0.99')
        res = app_to_dict(self.app, region=regions.US.id)
        eq_(res['price'], Decimal('0.99'))
        eq_(res['price_locale'], '$0.99')
        eq_(res['payment_required'], True)

    def test_no_charge(self):
        self.make_premium(self.app, price='0.00')
        res = app_to_dict(self.app, region=regions.US.id)
        eq_(res['price'], Decimal('0.00'))
        eq_(res['price_locale'], '$0.00')
        eq_(res['payment_required'], False)

    def test_wrong_region(self):
        self.make_premium(self.app, price='0.99')
        res = app_to_dict(self.app, region=regions.PL.id)
        eq_(res['price'], None)
        eq_(res['price_locale'], None)
        eq_(res['payment_required'], True)

    def test_with_locale(self):
        premium = self.make_premium(self.app, price='0.99')
        PriceCurrency.objects.create(region=regions.PL.id, currency='PLN',
                                     price='5.01', tier=premium.price,
                                     provider=1)

        with self.activate(locale='fr'):
            res = app_to_dict(self.app, region=regions.PL.id)
            eq_(res['price'], Decimal('5.01'))
            eq_(res['price_locale'], u'5,01\xa0PLN')

    def test_missing_price(self):
        premium = self.make_premium(self.app, price='0.99')
        premium.price = None
        premium.save()

        res = app_to_dict(self.app)
        eq_(res['price'], None)
        eq_(res['price_locale'], None)

    def test_cannot_purchase(self):
        self.make_premium(self.app, price='0.99')
        with self.settings(PURCHASE_ENABLED_REGIONS=[]):
            res = app_to_dict(self.app, region=regions.UK.id)
        eq_(res['price'], None)
        eq_(res['price_locale'], None)
        eq_(res['payment_required'], True)

    def test_can_purchase(self):
        self.make_premium(self.app, price='0.99')
        with self.settings(PURCHASE_ENABLED_REGIONS=[regions.UK.id]):
            res = app_to_dict(self.app, region=regions.UK.id)
        res = app_to_dict(self.app, region=regions.UK.id)
        eq_(res['price'], None)
        eq_(res['price_locale'], None)
        eq_(res['payment_required'], True)

    def test_waffle_fallback(self):
        self.make_premium(self.app, price='0.99')
        flag = waffle.models.Flag.objects.get(name='allow-paid-app-search')
        flag.everyone = None
        flag.users.add(self.profile.user)
        flag.save()

        req = RequestFactory().get('/')
        req.user = self.profile.user
        with self.settings(PURCHASE_ENABLED_REGIONS=[]):
            res = app_to_dict(self.app, region=regions.US.id, request=req)
        eq_(res['price'], Decimal('0.99'))
        eq_(res['price_locale'], '$0.99')
        eq_(res['payment_required'], True)


@mock.patch('versions.models.Version.is_privileged', False)
class TestESAppToDict(amo.tests.ESTestCase):
    fixtures = fixture('user_2519', 'webapp_337141')

    def setUp(self):
        self.app = Webapp.objects.get(pk=337141)
        self.version = self.app.current_version
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
            'author': 'Mozilla Tester',
            'created': self.app.created,
            'current_version': '1.0',
            'description': u'Something Something Steamcube description!',
            'homepage': '',
            'id': '337141',
            'is_packaged': False,
            'latest_version': {
                'status': 4,
                'is_privileged': False
            },
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
            'support_email': None,
            'support_url': None,
            'user': {
                'developed': False,
                'installed': False,
                'purchased': False,
            },
            'versions': {
                '1.0': '/api/v1/apps/versions/1268829/'
            },
            'weekly_downloads': None,
        }

        for k, v in res.items():
            if k in expected:
                eq_(expected[k], v,
                    u'Expected value "%s" for field "%s", got "%s"' %
                                                            (expected[k], k, v))

    def test_show_downloads_count(self):
        """Show weekly_downloads in results if app stats are public."""
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
        self.app.addonuser_set.create(user=self.profile)
        self.profile.installed_set.create(addon=self.app)
        self.app.addonpurchase_set.create(user=self.profile)
        self.app.save()
        self.refresh('webapp')

        res = es_app_to_dict(self.get_obj(), profile=self.profile)
        eq_(res['user'],
            {'developed': True, 'installed': True, 'purchased': True})

    def test_user_not_mine(self):
        self.app.addonuser_set.create(user_id=31337)
        Installed.objects.create(addon=self.app, user_id=31337)
        self.app.addonpurchase_set.create(user_id=31337)
        self.app.save()
        self.refresh('webapp')

        res = es_app_to_dict(self.get_obj(), profile=self.profile)
        eq_(res['user'],
            {'developed': False, 'installed': False, 'purchased': False})


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
