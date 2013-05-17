from decimal import Decimal

from nose.tools import eq_

import amo
import amo.tests

from addons.models import Preview
from mkt.site.fixtures import fixture
from mkt.webapps.utils import app_to_dict, get_supported_locales
from market.models import AddonPremium, Price
from users.models import UserProfile


class TestAppToDict(amo.tests.TestCase):
    fixtures = fixture('user_2519')

    def setUp(self):
        self.app = amo.tests.app_factory()
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


class TestAppToDictPrices(amo.tests.TestCase):
    fixtures = fixture('prices')

    def setUp(self):
        self.app = amo.tests.app_factory(premium_type=amo.ADDON_PREMIUM)
        price = Price.objects.get(pk=1)
        self.premium = AddonPremium.objects.create(addon=self.app, price=price)

    def test_some_price(self):
        res = app_to_dict(self.app)
        eq_(res['price'], Decimal('0.99'))
        eq_(res['price_locale'], '$0.99')

    def test_with_locale(self):
        with self.activate(locale='fr'):
            res = app_to_dict(self.app)
            eq_(res['price'], Decimal('5.01'))
            eq_(res['price_locale'], u'5,01\xa0\u20ac')

    def test_missing_price(self):
        self.premium.update(price=None)
        res = app_to_dict(self.app)
        eq_(res['price'], None)
        eq_(res['price_locale'], None)


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
