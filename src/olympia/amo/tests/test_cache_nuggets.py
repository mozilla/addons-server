from unittest import TestCase

from django.core.cache import cache
from django.test.utils import override_settings

from olympia.amo.cache_nuggets import (
    Message, Token, memoize, memoize_get, memoize_key)


@override_settings(CACHE_PREFIX='testing')
def test_memoize_key():
    assert memoize_key('foo', ['a', 'b'], {'c': 'e'}) == (
        'testing:memoize:foo:9666a2a48c17dc1c308fb327c2a6e3a8')


def test_memoize():
    @memoize('f')
    def add(*args):
        return sum(args)

    assert add(1, 2) == memoize_get('f', 1, 2)


class TestToken(TestCase):

    def setUp(self):
        cache.clear()

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

    def setUp(self):
        cache.clear()

    def test_message_save(self):
        new = Message('abc')
        new.save('123')

        new = Message('abc')
        assert new.get() == '123'

    def test_message_expires(self):
        new = Message('abc')
        new.save('123')
        cache.clear()

        new = Message('abc')
        assert new.get() is None

    def test_message_get_delete(self):
        new = Message('abc')
        new.save('123')

        new = Message('abc')
        assert new.get(delete=False) == '123'
        assert new.get(delete=True) == '123'
        assert new.get() is None
