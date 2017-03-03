import datetime
import json
import os
import urlparse

import jwt
import pytest
import requests
from django.core.management import call_command
from fxapom.fxapom import DEV_URL, PROD_URL, FxATestAccount
from olympia.amo.tests import create_switch
from pytest_django import live_server_helper


@pytest.fixture
def capabilities(capabilities):
    # In order to run these tests in Firefox 48, marionette is required
    capabilities['marionette'] = True
    return capabilities


@pytest.fixture
def fxa_account(base_url):
    url = DEV_URL if 'dev' or 'localhost' in base_url else PROD_URL
    return FxATestAccount(url)


@pytest.fixture
def jwt_issuer(base_url, variables):
    try:
        hostname = urlparse.urlsplit(base_url).hostname
        return variables['api'][hostname]['jwt_issuer']
    except KeyError:
        return os.getenv('JWT_ISSUER')


@pytest.fixture
def jwt_secret(base_url, variables):
    try:
        hostname = urlparse.urlsplit(base_url).hostname
        return variables['api'][hostname]['jwt_secret']
    except KeyError:
        return os.getenv('JWT_SECRET')


@pytest.fixture
def initial_data(transactional_db, live_server):
    call_command('generate_addons', 10, app='firefox')


@pytest.fixture
def create_superuser(transactional_db, live_server, base_url, tmpdir):
    create_switch('super-create-accounts')
    call_command('loaddata', 'initial.json')

    call_command(
        'createsuperuser',
        interactive=False,
        username='uitest',
        email='uitester@mozilla.org',
        add_to_supercreate_group=True,
        save_api_credentials=str(tmpdir.join('variables.json')),
        hostname=urlparse.urlsplit(base_url).hostname
    )


@pytest.fixture
def force_user_login():
    from olympia.users.models import UserProfile
    user = UserProfile.objects.get(username='uitest')
    return user


@pytest.fixture
def user(transactional_db, create_superuser, live_server, base_url,
         fxa_account, jwt_token):
    url = '{base_url}/api/v3/accounts/super-create/'.format(base_url=base_url)

    params = {
        'email': fxa_account.email,
        'password': fxa_account.password,
        'username': fxa_account.email.split('@')[0],
        'fxa_id': fxa_account.session.uid}
    headers = {'Authorization': 'JWT {token}'.format(token=jwt_token)}
    response = requests.post(url, data=params, headers=headers)
    user = params
    assert requests.codes.created == response.status_code
    user.update(response.json())
    return user


@pytest.fixture(scope='function')
def live_server(request):
    """
        This fixture overrides the live_server fixture provided by
        pytest_django. live_server allows us to create a running version of the
        addons django application within pytest for testing.
    """

    request.getfixturevalue('transactional_db')

    addr = (request.config.getvalue('liveserver') or
            os.getenv('DJANGO_LIVE_TEST_SERVER_ADDRESS'))

    if not addr:
        addr = 'localhost:8081,8100-8200'

    server = live_server_helper.LiveServer(addr)
    request.addfinalizer(server.stop)
    yield server
    server.stop()


@pytest.fixture
def jwt_token(base_url, jwt_issuer, jwt_secret):
    payload = {
        'iss': jwt_issuer,
        'iat': datetime.datetime.utcnow(),
        'exp': datetime.datetime.utcnow() + datetime.timedelta(seconds=30)}
    return jwt.encode(payload, jwt_secret, algorithm='HS256')


@pytest.fixture
def variables(tmpdir, variables):
    with tmpdir.join('variables.json').open() as f:
        variables.update(json.load(f))
        return variables
