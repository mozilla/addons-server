# -*- coding: utf-8 -*-
from django.utils import translation


from olympia.lib.cache import cached, make_key


def test_make_key():
    with translation.override('en-US'):
        assert make_key(u'é@øel') == 'eb7592119dace3b998755ef61d90b91b'

    assert make_key(
        u'é@øel', with_locale=False) == 'f40676a34ef1787123e49e1317f9ed31'

    with translation.override('fr'):
        assert make_key(u'é@øel') == 'e0c0ff9a07c763506dc6d77daed9c048'

    with translation.override('en-US'):
        assert make_key(u'é@øel') == 'eb7592119dace3b998755ef61d90b91b'


def test_cached():

    def some_function():
        some_function.call_count += 1
        return 'something'  # Needed for cached() to work.
    some_function.call_count = 0

    cached(some_function, 'my-key')
    cached(some_function, 'my-key')

    assert some_function.call_count == 1
