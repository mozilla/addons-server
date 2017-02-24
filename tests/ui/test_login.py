import os
import pytest

from pages.desktop.home import Home
from seleniumlogin import force_login


@pytest.mark.django_db
@pytest.mark.skipif('localhost' not in os.getenv('PYTEST_BASE_URL'),
                    reason='No force login for dev, prod testing')
def test_login(base_url, selenium, user, force_user_login):
    """User can login"""
    page = Home(selenium, base_url).open()
    assert not page.logged_in
    force_login(force_user_login, selenium, base_url)
    assert page.logged_in


@pytest.mark.django_db
@pytest.mark.skipif('dev' not in os.getenv('PYTEST_BASE_URL'),
                    reason='No UI login for local testing')
def test_login_ui(base_url, selenium, user, force_user_login):
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
