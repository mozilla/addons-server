# -*- coding: utf-8 -*-
from django.utils import translation
from django.core.cache import cache

from olympia.lib.cache import memoize, memoize_key, make_key


def test_make_key():
    with translation.override('en-US'):
        assert make_key(u'é@øel') == u'é@øel:en-us'

    with translation.override('de'):
        assert make_key(u'é@øel') == u'é@øel:de'

    with translation.override('de'):
        assert make_key(u'é@øel', with_locale=False) == u'é@øel'

    with translation.override('en-US'):
        assert (
            make_key(u'é@øel', normalize=True) ==
            '2798e65bbe384320c9da7930e93e63fb')

    assert (
        make_key(u'é@øel', with_locale=False, normalize=True) ==
        'a83feada27737072d4ec741640368f07')

    with translation.override('fr'):
        assert (
            make_key(u'é@øel', normalize=True) ==
            'bc5208e905c8dfcc521e4196e16cfa1a')


def test_memoize_key():
    assert memoize_key('foo', ['a', 'b'], {'c': 'e'}) == (
        'memoize:foo:9666a2a48c17dc1c308fb327c2a6e3a8')


def test_memoize():
    @memoize('f')
    def add(*args):
        return sum(args)

    cache_key = memoize_key('f', 1, 2)
    assert add(1, 2) == cache.get(cache_key)


def test_memcached_unicode():
    """Regression test for

    https://github.com/linsomniac/python-memcached/issues/79
    """
    cache.set(u'këy', u'Iñtërnâtiônàlizætiøn2')
    assert cache.get(u'këy') == u'Iñtërnâtiônàlizætiøn2'
