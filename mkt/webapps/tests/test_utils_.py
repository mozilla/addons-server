from decimal import Decimal

from nose.tools import eq_

import amo
import amo.tests

from addons.models import Preview
from mkt.site.fixtures import fixture
from mkt.webapps.utils import app_to_dict
from market.models import AddonPremium, Price


class TestAppToDict(amo.tests.TestCase):
    # TODO: expand this and move more stuff out of
    # mkt/api/tests/test_handlers.

    def setUp(self):
        self.app = amo.tests.app_factory()

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


class TestAppToDictPrices(amo.tests.TestCase):
    fixtures = fixture('prices')

    def setUp(self):
        self.app = amo.tests.app_factory()
        price = Price.objects.get(pk=1)
        AddonPremium.objects.create(addon=self.app, price=price)

    def test_some_price(self):
        res = app_to_dict(self.app)
        eq_(res['price'], Decimal('0.99'))
        eq_(res['price_locale'], '$0.99')

    def test_with_locale(self):
        with self.activate(locale='fr'):
            res = app_to_dict(self.app)
            eq_(res['price'], Decimal('5.01'))
            eq_(res['price_locale'], u'5,01\xa0\u20ac')
