import pytest

from pages.desktop.home import Home


@pytest.mark.django_db
def test_login(our_base_url, selenium, super_user, session_cookie):
    """User can login"""
    page = Home(selenium, our_base_url).open()
    assert not page.logged_in
    selenium.add_cookie(session_cookie)
    selenium.refresh()
    page.login(super_user['email'], super_user['password'])
    assert page.logged_in


@pytest.mark.skip(
    reason='https://github.com/mozilla/geckodriver/issues/233')
def test_logout(base_url, selenium, user):
    """User can logout"""
    page = Home(selenium, base_url).open()
    page.login(user['email'], user['password'])
    page.logout()
    assert not page.logged_in
