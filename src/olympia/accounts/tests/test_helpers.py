from django.test import RequestFactory

from olympia.accounts.templatetags import jinja_helpers


def test_login_link():
    request = RequestFactory().get('/en-US/firefox/addons')
    assert jinja_helpers.login_link({'request': request}) == (
        'http://testserver/api/v5/accounts/login/start/'
        '?to=%2Fen-US%2Ffirefox%2Faddons'
    )

    request = RequestFactory().get('/en-US/firefox/addons?blah=1')
    assert jinja_helpers.login_link({'request': request}) == (
        'http://testserver/api/v5/accounts/login/start/'
        '?to=%2Fen-US%2Ffirefox%2Faddons%3Fblah%3D1'
    )

    request = RequestFactory().get('/en-US/firefox/addons?blah=1&bâr=2')
    assert jinja_helpers.login_link({'request': request}) == (
        'http://testserver/api/v5/accounts/login/start/'
        '?to=%2Fen-US%2Ffirefox%2Faddons%3Fblah%3D1%26b%25C3%25A2r%3D2'
    )
