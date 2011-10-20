from nose.tools import eq_

from search.utils import convert_version, floor_version


def test_convert_version():

    def c(x, y):
        x = convert_version(x)
        y = convert_version(y)

        if (x > y):
            return 1
        elif (x < y):
            return - 1

        return 0

    v = ['1.9.0a1pre', '1.9.0a1', '1.9.1.b5', '1.9.1.b5', '1.9.1pre',
         '1.9.1', '1.9.0', '1.9.*', '1.9*']

    eq_(c(v[0], v[1]), -1)
    eq_(c(v[1], v[2]), -1)
    eq_(c(v[2], v[3]), 0)
    eq_(c(v[3], v[4]), -1)
    eq_(c(v[4], v[5]), -1)
    eq_(c(v[5], v[6]), 1)
    eq_(c(v[7], v[8]), 0)


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
