import mock
from nose.tools import eq_

import mkt.constants.regions as regions
from mkt.regions import get_region, get_region_id, set_region


@mock.patch('mkt.regions._local', None)
def test_get_region_empty():
    eq_(get_region(), regions.WORLDWIDE.slug)
    eq_(get_region_id(), regions.WORLDWIDE.id)


@mock.patch('mkt.regions._local')
def test_get_region_not_empty(local):
    local.region = 'us'

    eq_(get_region(), 'us')
    eq_(get_region_id(), regions.US.id)


@mock.patch('mkt.regions._local')
def test_set_region(local):
    local.region = 'us'

    eq_(get_region(), 'us')
    set_region('es')
    eq_(get_region(), 'es')
