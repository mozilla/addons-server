from django.test import RequestFactory

import mock

from olympia.accounts.templatetags import jinja_helpers


@mock.patch(
    'olympia.accounts.templatetags.jinja_helpers.utils.default_fxa_login_url',
    lambda c: 'http://auth.ca',
)
def test_login_link():
    request = RequestFactory().get('/en-US/firefox/addons')
    assert jinja_helpers.login_link({'request': request}) == ('http://auth.ca')


@mock.patch(
    'olympia.accounts.templatetags.jinja_helpers.utils.'
    'default_fxa_register_url',
    lambda c: 'http://auth.ca',
)
def test_register_link():
    request = RequestFactory().get('/en-US/firefox/addons')
    assert jinja_helpers.register_link({'request': request}) == (
        'http://auth.ca'
    )
