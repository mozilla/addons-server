# -*- coding: utf-8 -*-
from django.core.validators import ValidationError

from nose.tools import eq_, assert_raises

from amo.utils import slug_validator, slugify


u = u'Ελληνικά'


def test_slug_validator():
    eq_(slug_validator(u), None)
    eq_(slug_validator('-'.join([u, u])), None)
    assert_raises(ValidationError, slug_validator, '234.add')
    assert_raises(ValidationError, slug_validator, 'a a a')
    assert_raises(ValidationError, slug_validator, 'tags/')


def test_slugify():
    x = '-'.join([u, u])
    y = ' - '.join([u, u])
    check = lambda x, y: eq_(slugify(x), y)
    s = [('xx x  - "#$@ x', 'xx-x-x'),
         (u'Bän...g (bang)', u'bäng-bang'),
         (u, u.lower()),
         (x, x.lower()),
         (y, x.lower()),
         ('    a ', 'a'),
         ('tags/', 'tags'),
         # I don't really care what slugify returns.  Just don't crash.
         (u'𘍿', u''),
         (u'ϧ΃𘒬𘓣',  u'\u03e7'),
         (u'¿', u''),
    ]
    for val, expected in s:
        yield check, val, expected
