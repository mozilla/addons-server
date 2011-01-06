# -*- coding: utf-8 -*-
import os
import tempfile

from django.conf import settings
from django.core.validators import ValidationError

from nose.tools import eq_, assert_raises

from amo.utils import slug_validator, slugify, resize_image, to_language


u = u'Ελληνικά'


def test_slug_validator():
    eq_(slug_validator(u.lower()), None)
    eq_(slug_validator('-'.join([u.lower(), u.lower()])), None)
    assert_raises(ValidationError, slug_validator, '234.add')
    assert_raises(ValidationError, slug_validator, 'a a a')
    assert_raises(ValidationError, slug_validator, 'tags/')


def test_slugify():
    x = '-'.join([u, u])
    y = ' - '.join([u, u])

    def check(x, y):
        eq_(slugify(x), y)
        slug_validator(slugify(x))
    s = [('xx x  - "#$@ x', 'xx-x-x'),
         (u'Bän...g (bang)', u'bäng-bang'),
         (u, u.lower()),
         (x, x.lower()),
         (y, x.lower()),
         ('    a ', 'a'),
         ('tags/', 'tags'),
         ('holy_wars', 'holy_wars'),
         # I don't really care what slugify returns.  Just don't crash.
         (u'x𘍿', u'x'),
         (u'ϧ΃𘒬𘓣',  u'\u03e7'),
         (u'¿x', u'x'),
    ]
    for val, expected in s:
        yield check, val, expected


def test_resize_image():
    # src and dst shouldn't be the same.
    assert_raises(Exception, resize_image, 't', 't', 'z')


def test_resize_transparency():
    src = os.path.join(settings.ROOT, 'apps', 'amo', 'tests',
                       'images', 'transparent.png')
    dest = tempfile.mkstemp()[1]
    expected = src.replace('.png', '-expected.png')
    try:
        resize_image(src, dest, (32, 32), remove_src=False)
        with open(dest) as dfh:
            with open(expected) as efh:
                assert dfh.read() == efh.read()
    finally:
        if os.path.exists(dest):
            os.remove(dest)


def test_to_language():
    tests = (('en-us', 'en-US'),
             ('en_US', 'en-US'),
             ('en_us', 'en-US'),
             ('FR', 'fr'),
             ('el', 'el'))

    def check(a, b):
        eq_(to_language(a), b)
    for a, b in tests:
        yield check, a, b
