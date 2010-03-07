from nose.tools import eq_

from translations.utils import truncate


def test_truncate():
    s = '   <p>one</p><ol><li>two</li><li> three</li> </ol><p> four five</p>'

    eq_(truncate(s, 100), s)
    eq_(truncate(s, 6), '   <p>one</p><ol><li>two...</li></ol>')
    eq_(truncate(s, 11), '   <p>one</p><ol><li>two</li><li>three...</li></ol>')
