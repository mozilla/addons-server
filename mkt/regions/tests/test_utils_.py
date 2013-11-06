from mkt.constants import regions
from mkt.regions.utils import parse_region
from nose.tools import eq_, assert_raises


def test_parse_region():
    eq_(parse_region('worldwide'), regions.WORLDWIDE)
    eq_(parse_region('br'), regions.BR)
    eq_(parse_region('7'), regions.BR)
    eq_(parse_region(7), regions.BR)
    eq_(parse_region(regions.BR), regions.BR)
    assert_raises(KeyError, parse_region, '')
