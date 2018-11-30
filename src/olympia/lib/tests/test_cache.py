# -*- coding: utf-8 -*-
from django.utils import translation
from django.core.cache import cache

from unittest import TestCase
from olympia.lib.cache import (
    Message, Token, memoize, memoize_key, cache_get_or_set,
    make_key)


def test_make_key():
    with translation.override('en-US'):
        assert make_key(u'é@øel') == 'é@øel:en-us'

    with translation.override('de'):
        assert make_key(u'é@øel') == 'é@øel:de'

    with translation.override('de'):
        assert make_key(u'é@øel', with_locale=False) == 'é@øel'

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


def test_cache_get_or_set():
    # Compatibility test, since cache_get_or_set is a 1:1 backport from
    # Django 1.11, their unittests apply.

    def some_function():
        some_function.call_count += 1
        return 'something'  # Needed for cache_get_or_set() to work.
    some_function.call_count = 0

    cache_get_or_set('my-key', some_function)
    cache_get_or_set('my-key', some_function)

    assert some_function.call_count == 1


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


class TestToken(TestCase):

    def test_token_pop(self):
        new = Token()
        new.save()
        assert Token.pop(new.token)
        assert not Token.pop(new.token)

    def test_token_valid(self):
        new = Token()
        new.save()
        assert Token.valid(new.token)

    def test_token_fails(self):
        assert not Token.pop('some-random-token')

    def test_token_ip(self):
        new = Token(data='127.0.0.1')
        new.save()
        assert Token.valid(new.token, '127.0.0.1')

    def test_token_no_ip_invalid(self):
        new = Token()
        assert not Token.valid(new.token, '255.255.255.0')

    def test_token_bad_ip_invalid(self):
        new = Token(data='127.0.0.1')
        new.save()
        assert not Token.pop(new.token, '255.255.255.0')
        assert Token.pop(new.token, '127.0.0.1')

    def test_token_well_formed(self):
        new = Token('some badly formed token')
        assert not new.well_formed()


class TestMessage(TestCase):

    def test_message_save(self):
        new = Message('abc')
        new.save('123')

        new = Message('abc')
        assert new.get() == '123'

    def test_message_expires(self):
        new = Message('abc')
        new.save('123')

        cache.delete('message:abc')

        new = Message('abc')
        assert new.get() is None

    def test_message_get_delete(self):
        new = Message('abc')
        new.save('123')

        new = Message('abc')
        assert new.get(delete=False) == '123'
        assert new.get(delete=True) == '123'
        assert new.get() is None
