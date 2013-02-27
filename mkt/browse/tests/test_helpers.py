import mock
from nose.tools import eq_

import amo
import amo.tests
import mkt.browse.helpers as helpers
import mkt.carriers
import mkt.regions
from addons.models import Category
from mkt.browse.helpers import _categories


class TestCategories(amo.tests.TestCase):
    """Test that the appropriate categories are returned by `_categories`."""

    def setUp(self):
        self.cat1 = Category.objects.create(
            name='1', slug='_one', type=amo.ADDON_WEBAPP, weight=1)
        self.cat2 = Category.objects.create(
            name='2', slug='two', type=amo.ADDON_WEBAPP, weight=1)
        self.cat3 = Category.objects.create(
            name='3', slug='three', type=amo.ADDON_WEBAPP, weight=1)

    def test_limit(self):
        self.assertSetEqual(_categories(limit=1), [self.cat1])

    def test_only_webapps(self):
        self.cat1.update(type=amo.ADDON_PERSONA)
        self.assertSetEqual(_categories(), [self.cat2, self.cat3])

    @mock.patch('mkt.browse.helpers.mkt.regions.get_region_id')
    def test_only_correct_region(self, rid):
        self.cat1.update(region=mkt.regions.US.id)

        rid.return_value = mkt.regions.BR.id
        self.assertSetEqual(_categories(), [self.cat2, self.cat3])

        rid.return_value = mkt.regions.US.id
        self.assertSetEqual(_categories(), [self.cat1, self.cat2, self.cat3])

    @mock.patch('mkt.browse.helpers.mkt.carriers.get_carrier_id')
    def test_only_correct_carrier(self, cid):
        self.cat1.update(carrier=mkt.carriers.TELEFONICA.id)

        cid.return_value = None
        cats = _categories()
        self.assertSetEqual(cats, [self.cat2, self.cat3],
                            [c.carrier for c in cats])

        cid.return_value = mkt.carriers.TELEFONICA.id
        cats = _categories()
        self.assertSetEqual(cats, [self.cat1, self.cat2, self.cat3],
                            [c.carrier for c in cats])
