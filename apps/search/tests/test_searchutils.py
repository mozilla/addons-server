from nose.tools import eq_

from search.utils import convert_version


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
         '1.9.1', '1.9.0']

    eq_(c(v[0], v[1]), -1)
    eq_(c(v[1], v[2]), -1)
    eq_(c(v[2], v[3]), 0)
    eq_(c(v[3], v[4]), -1)
    eq_(c(v[4], v[5]), -1)
    eq_(c(v[5], v[6]), 1)
