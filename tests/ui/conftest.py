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


@pytest.fixture(scope='function')
def my_base_url(base_url, request):
    return base_url or request.getfixturevalue("live_server").url


@pytest.fixture
def capabilities(capabilities):
    # In order to run these tests in Firefox 48, marionette is required
    capabilities['marionette'] = True
    return capabilities


@pytest.fixture
def fxa_account(my_base_url):
    url = DEV_URL if 'dev' or 'localhost' in my_base_url else PROD_URL
    return FxATestAccount(url)


@pytest.fixture(scope='session')
def jwt_issuer(base_url, variables):
    try:
        hostname = urlparse.urlsplit(base_url).hostname
        return variables['api'][hostname]['jwt_issuer']
    except KeyError:
        return os.getenv('JWT_ISSUER')


@pytest.fixture(scope='session')
def jwt_secret(base_url, variables):
    try:
        hostname = urlparse.urlsplit(base_url).hostname
        return variables['api'][hostname]['jwt_secret']
    except KeyError:
        return os.getenv('JWT_SECRET')


@pytest.fixture
def initial_data(transactional_db):
    from olympia.amo.tests import addon_factory, user_factory
    from olympia.addons.models import AddonUser

    for x in range(10):
        AddonUser.objects.create(user=user_factory(), addon=addon_factory())


@pytest.fixture
def create_superuser(transactional_db, my_base_url, tmpdir, variables):
    create_switch('super-create-accounts')
    call_command('loaddata', 'initial.json')

    call_command(
        'createsuperuser',
        interactive=False,
        username='uitest',
        email='uitester@mozilla.org',
        add_to_supercreate_group=True,
        save_api_credentials=str(tmpdir.join('variables.json')),
        hostname=urlparse.urlsplit(my_base_url).hostname
    )

    with tmpdir.join('variables.json').open() as f:
        variables.update(json.load(f))


@pytest.fixture
def user(create_superuser, my_base_url, fxa_account, jwt_token):
    url = '{base_url}/api/v3/accounts/super-create/'.format(
        base_url=my_base_url)

    params = {
        'email': fxa_account.email,
        'password': fxa_account.password,
        'username': fxa_account.email.split('@')[0]}
    headers = {'Authorization': 'JWT {token}'.format(token=jwt_token)}
    response = requests.post(url, data=params, headers=headers)
    assert requests.codes.created == response.status_code
    params.update(response.json())
    return params


@pytest.fixture(scope='function')
def live_server(request, transactional_db):
    """
        This fixture overrides the live_server fixture provided by
        pytest_django. live_server allows us to create a running version of the
        addons django application within pytest for testing.

        cgrebs:
        From what I found out was that the `live_server` fixture (in our setup,
        couldn't reproduce in a fresh project) apparently starts up the
        LiveServerThread way too early before pytest-django configures the
        settings correctly.

        That resulted in the LiveServerThread querying the 'default' database
        which was different from what the other fixtures and tests were using
        which resulted in the problem that the just created api keys could not
        be found in the api methods in the live-server.

        I worked around that by implementing the live_server fixture ourselfs
        and make it function-scoped so that it now runs in a proper
        database-transaction.

        This is a HACK and I'll work on a more permanent solution but for now
        it should be enough to continue working on porting tests...

        Also investigating if there are any problems in pytest-django directly.
    """

    addr = (request.config.getvalue('liveserver') or
            os.getenv('DJANGO_LIVE_TEST_SERVER_ADDRESS'))

    if not addr:
        addr = 'localhost:8081,8100-8200'

    server = live_server_helper.LiveServer(addr)
    yield server
    server.stop()


@pytest.fixture
def jwt_token(base_url, jwt_issuer, jwt_secret):
    payload = {
        'iss': jwt_issuer,
        'iat': datetime.datetime.utcnow(),
        'exp': datetime.datetime.utcnow() + datetime.timedelta(seconds=30)}
    return jwt.encode(payload, jwt_secret, algorithm='HS256')
