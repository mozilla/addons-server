import os
import pytest

from pages.desktop.home import Home


@pytest.mark.skipif(os.environ.get('PYTEST_BASE_URL') is None,
                    reason='Live Server login currently not functioning')
def test_login(base_url, selenium, user):
    """User can login"""
    page = Home(selenium, base_url).open()
    assert not page.logged_in
    page.login(user['email'], user['password'])
    assert page.logged_in


@pytest.mark.skip(
    reason='https://github.com/mozilla/geckodriver/issues/233')
def test_logout(base_url, selenium, user):
    """User can logout"""
    page = Home(selenium, base_url).open()
    page.login(user['email'], user['password'])
    page.logout()
    assert not page.logged_in
