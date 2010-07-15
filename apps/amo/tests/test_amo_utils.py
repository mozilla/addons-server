# -*- coding: utf-8 -*-
from nose.tools import eq_

from amo.utils import slugify


def test_slugify():
    check = lambda x, y: eq_(slugify(x), y)
    s = [('xx x  - "#$@ x', 'xx-x-x'),
         (u'Bän...g (bang)', u'bäng-bang')]
    for val, expected in s:
        yield check, val, expected
