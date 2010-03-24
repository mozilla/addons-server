from django import test

from nose.tools import eq_


def test_no_vary_cookie():
    c = test.Client()

    # We don't break good usage of Vary.
    response = test.Client().get('/')
    eq_(response['Vary'], 'Accept-Language')

    # But we do prevent Vary: Cookie.
    response = test.Client().get('/', follow=True)
    assert 'Vary' not in response
