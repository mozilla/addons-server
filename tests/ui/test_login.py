import pytest

from pages.desktop.home import Home


@pytest.mark.fxa_login
@pytest.mark.skip("Addons frontend login not working")
@pytest.mark.allow_external_http_requests
def test_login(base_url, selenium, fxa_account):
    """User can login"""
    page = Home(selenium, base_url).open()
    assert not page.logged_in
    page.login(fxa_account.email, fxa_account.password)
    assert page.logged_in


@pytest.mark.skip(
    reason='https://bugzilla.mozilla.org/show_bug.cgi?id=1453779')
@pytest.mark.allow_external_http_requests
def test_logout(base_url, selenium, user):
    """User can logout"""
    page = Home(selenium, base_url).open()
    page.login(user['email'], user['password'])
    page.logout()
    assert not page.logged_in
