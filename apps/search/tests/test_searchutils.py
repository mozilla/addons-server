from nose.tools import eq_

from search.utils import floor_version


def test_floor_version():

    def c(x, y):
        eq_(floor_version(x), y)

    c(None, None)
    c('', '')
    c('3', '3.0')
    c('3.6', '3.6')
    c('3.6.22', '3.6')
    c('5.0a2', '5.0')
    c('8.0', '8.0')
    c('8.0.10a', '8.0')
    c('10.0b2pre', '10.0')
    c('8.*', '8.0')
    c('8.0*', '8.0')
    c('8.0.*', '8.0')
    c('8.x', '8.0')
    c('8.0x', '8.0')
    c('8.0.x', '8.0')
