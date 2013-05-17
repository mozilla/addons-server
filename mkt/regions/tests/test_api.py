from nose.tools import eq_

from tastypie.bundle import Bundle

import amo
import amo.tests

from mkt.constants.regions import REGIONS_DICT as regions
from mkt.regions.api import RegionResource


class TestRegionResource(amo.tests.TestCase):

    def setUp(self):
        self.app = amo.tests.app_factory()
        self.resource = RegionResource()
        self.bundle = Bundle(obj=regions['us'], request=None)

    def test_full_dehydrate(self):
        res = self.resource.full_dehydrate(self.bundle)
        eq_(res.obj, regions['us'])
        for field in self.resource._meta.fields:
            eq_(res.data[field], getattr(res.obj, field))
