import datetime
import os
import urlparse

import jwt
import pytest
import requests
from django.conf import settings
from fxapom.fxapom import DEV_URL, PROD_URL, FxATestAccount
from olympia import amo


@pytest.fixture
def firefox_options(firefox_options):
    """Firefox options.

    These options configure firefox to allow for addon installation,
    as well as allowing it to run headless.

    """
    firefox_options.set_preference(
        'extensions.install.requireBuiltInCerts', False)
    firefox_options.set_preference('xpinstall.signatures.required', False)
    firefox_options.set_preference('extensions.webapi.testing', True)
    firefox_options.set_preference('ui.popup.disable_autohide', True)
    firefox_options.add_argument('-foreground')
    # firefox_options.add_argument('-headless')
    firefox_options.log.level = 'trace'
    return firefox_options


@pytest.fixture
def firefox_notifications(notifications):
    return notifications


@pytest.fixture(scope='function',
                params=[(1080, 1920), (414, 738)],
                ids=['Resolution: 1080x1920', 'Resolution: 414x738'])
def selenium(selenium, request):
    """Fixture to set custom selenium parameters.

    This fixture will also parametrize all of the tests to run them on both a
    Desktop resolution and a mobile resolution.

    Desktop size: 1920x1080
    Mobile size: 738x414 (iPhone 7+)

    """
    selenium.set_window_size(*request.param)
    return selenium


@pytest.fixture(scope='session')
def fxa_account(base_url):
    """Account used to login to the AMO site."""
    url = DEV_URL if 'olympia' or 'localhost' in base_url else PROD_URL
    return FxATestAccount(url)


@pytest.fixture(scope='session')
def jwt_issuer(base_url, variables):
    """JWT Issuer from variables file or env variable named 'JWT_ISSUER'"""
    try:
        hostname = urlparse.urlsplit(base_url).hostname
        return variables['api'][hostname]['jwt_issuer']
    except KeyError:
        return os.getenv('JWT_ISSUER')


@pytest.fixture(scope='session')
def jwt_secret(base_url, variables):
    """JWT Secret from variables file or env vatiable named "JWT_SECRET"""
    try:
        hostname = urlparse.urlsplit(base_url).hostname
        return variables['api'][hostname]['jwt_secret']
    except KeyError:
        return os.getenv('JWT_SECRET')


@pytest.fixture(scope='session')
def user(base_url, fxa_account, jwt_token):
    """This creates a user for logging into the AMO site."""
    url = 'http://olympia.test/api/v3/accounts/super-create/'

    params = {
        'email': fxa_account.email,
        'password': fxa_account.password,
        'username': fxa_account.email.split('@')[0]}
    headers = {'Authorization': 'JWT {token}'.format(token=jwt_token)}
    response = requests.post(url, data=params, headers=headers)
    assert requests.codes.created == response.status_code
    params.update(response.json())
    return params


@pytest.fixture(scope='session')
def jwt_token(jwt_issuer, jwt_secret):
    """This creates a JWT Token"""
    payload = {
        'iss': jwt_issuer,
        'iat': datetime.datetime.utcnow(),
        'exp': datetime.datetime.utcnow() + datetime.timedelta(seconds=30)}
    return jwt.encode(payload, jwt_secret, algorithm='HS256')


def pytest_configure(config):
    from olympia.amo.tests import prefix_indexes

    prefix_indexes(config)


@pytest.fixture(scope='session')
def es_test(pytestconfig):
    from olympia.amo.tests import (
        start_es_mocks, stop_es_mocks, amo_search, setup_es_test_data)

    stop_es_mocks()

    es = amo_search.get_es(timeout=settings.ES_TIMEOUT)
    _SEARCH_ANALYZER_MAP = amo.SEARCH_ANALYZER_MAP
    amo.SEARCH_ANALYZER_MAP = {
        'english': ['en-us'],
        'spanish': ['es'],
    }

    setup_es_test_data(es)

    yield

    amo.SEARCH_ANALYZER_MAP = _SEARCH_ANALYZER_MAP
    start_es_mocks()
