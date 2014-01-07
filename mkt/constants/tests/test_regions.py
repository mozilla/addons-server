from nose.tools import eq_

import amo.tests

import mkt.constants.regions as regions


class TestRegionContentRatings(amo.tests.TestCase):

    def test_region_to_ratings_body(self):
        region_to_body = regions.REGION_TO_RATINGS_BODY()
        eq_(len(region_to_body), 2)
        eq_(region_to_body['br'], 'classind')
        eq_(region_to_body['de'], 'generic')

    def test_region_to_ratings_body_switch(self):
        self.create_switch('iarc')
        region_to_body = regions.REGION_TO_RATINGS_BODY()
        eq_(region_to_body['br'], 'classind')
        eq_(region_to_body['es'], 'pegi')
        eq_(region_to_body['de'], 'usk')
        eq_(region_to_body['us'], 'esrb')
