import mock
from nose.tools import eq_

import mkt.constants.regions as regions
from mkt.regions import get_region, get_region_id


@mock.patch('mkt.regions.local')
def test_get_region_empty(local):
    local.return_value = None

    eq_(get_region(), regions.WORLDWIDE.slug)
    eq_(get_region_id(), regions.WORLDWIDE.id)


@mock.patch('mkt.regions.local')
def test_get_region_not_empty(local):
    m = mock.Mock()
    m.region = 'us'
    local.return_value = m

    eq_(get_region(), 'us')
    eq_(get_region_id(), regions.US.id)
