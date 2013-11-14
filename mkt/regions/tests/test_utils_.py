from nose.tools import eq_

from mkt.constants import regions
from mkt.regions.utils import parse_region


def test_parse_region():
    eq_(parse_region('worldwide'), regions.WORLDWIDE)
    eq_(parse_region('br'), regions.BR)
    eq_(parse_region('brazil'), regions.BR)
    eq_(parse_region('bRaZiL'), regions.BR)
    eq_(parse_region('7'), regions.BR)
    eq_(parse_region(7), regions.BR)
    eq_(parse_region(regions.BR), regions.BR)
    eq_(parse_region(''), None)
