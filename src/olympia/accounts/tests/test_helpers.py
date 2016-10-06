from django.test import RequestFactory

import mock

from olympia.accounts import helpers


@mock.patch(
    'olympia.accounts.helpers.utils.default_fxa_login_url',
    lambda c: 'http://auth.ca')
def test_login_link():
    request = RequestFactory().get('/en-US/firefox/addons')
    assert helpers.login_link({'request': request}) == (
        'http://auth.ca')


@mock.patch(
    'olympia.accounts.helpers.utils.default_fxa_register_url',
    lambda c: 'http://auth.ca')
def test_register_link():
    request = RequestFactory().get('/en-US/firefox/addons')
    assert helpers.register_link({'request': request}) == (
        'http://auth.ca')
