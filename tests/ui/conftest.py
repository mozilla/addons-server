import datetime
import os
import urlparse

from fxapom.fxapom import DEV_URL, PROD_URL, FxATestAccount
from pytest_django import live_server_helper
import jwt
import pytest
import requests
import json

from django.core.management import call_command
from olympia.amo.tests import create_switch
from olympia.access.models import Group


@pytest.fixture
def our_base_url(our_live_server):
    return our_live_server.url


@pytest.fixture
def capabilities(capabilities):
    # In order to run these tests in Firefox 48, marionette is required
    capabilities['marionette'] = True
    return capabilities


@pytest.fixture
def fxa_account(our_base_url):
    url = DEV_URL if 'dev' or 'localhost' in our_base_url else PROD_URL
    return FxATestAccount(url)


@pytest.fixture
def jwt_issuer(our_base_url, json_file):
    try:
        hostname = urlparse.urlsplit(our_base_url).hostname
        return json_file['api'][hostname]['jwt_issuer']
    except KeyError:
        return os.getenv('JWT_ISSUER')


@pytest.fixture
def jwt_secret(our_base_url, json_file):
    try:
        hostname = urlparse.urlsplit(our_base_url).hostname
        return json_file['api'][hostname]['jwt_secret']
    except KeyError:
        return os.getenv('JWT_SECRET')


@pytest.fixture()
def initial_data(transactional_db, live_server, our_base_url):
    # call_command('reset_db', interactive=False)
    # call_command('syncdb', interactive=False)

    call_command('loaddata', 'initial.json')
    create_switch('super-create-accounts')
    # call_command('import_prod_versions')
    call_command('generate_addons', 10, app='firefox')


@pytest.fixture
def create_superuser(transactional_db, live_server, our_base_url):
    hostname = urlparse.urlsplit(our_base_url).hostname

    call_command(
        'createsuperuser',
        interactive=False,
        username='uitest',
        email='uitester@mozilla.org',
        add_to_supercreate_group=True,
        save_api_credentials='tests/ui/variables.json',
        hostname=hostname
    )


@pytest.fixture
def session_cookie():
    from django.conf import settings
    from django.contrib.auth import (
        SESSION_KEY, BACKEND_SESSION_KEY, HASH_SESSION_KEY
    )
    from django.contrib.sessions.backends.db import SessionStore
    from olympia.users.models import UserProfile

    # First, create a new test user
    user = UserProfile.objects.get(username='uitest')

    # Then create the authenticated session using the new user credentials
    session = SessionStore()
    session[SESSION_KEY] = user.pk
    session[BACKEND_SESSION_KEY] = settings.AUTHENTICATION_BACKENDS[0]
    session[HASH_SESSION_KEY] = user.get_session_auth_hash()
    session.save()

    # Finally, create the cookie dictionary
    cookie = {
        'name': settings.SESSION_COOKIE_NAME,
        'value': session.session_key,
        'secure': False,
        'path': '/',
    }
    return cookie


@pytest.fixture
def super_user(transactional_db, initial_data, create_superuser, our_live_server, our_base_url,
               fxa_account, jwt_token):
    url = '{base_url}/api/v3/accounts/super-create/'.format(base_url=our_base_url)

    params = {
        'email': fxa_account.email,
        'password': fxa_account.password,
        'username': fxa_account.email.split('@')[0],
        'fxa_id': fxa_account.session.uid}
    print(fxa_account.password)
    headers = {'Authorization': 'JWT {token}'.format(token=jwt_token)}
    response = requests.post(url, data=params, headers=headers)
    user = {
        'email': fxa_account.email,
        'password': fxa_account.password,
        'username': fxa_account.email.split('@')[0],
        'fxa_id': fxa_account.session.uid
    }
    assert requests.codes.created == response.status_code
    user.update(response.json())
    print(user)
    return user


@pytest.fixture(scope='function')
def our_live_server(request):
    import django
    request.getfixturevalue('transactional_db')

    addr = (request.config.getvalue('liveserver') or
            os.getenv('DJANGO_LIVE_TEST_SERVER_ADDRESS'))

    if not addr:
        addr = 'localhost:8081,8100-8200'

    server = live_server_helper.LiveServer(addr)
    request.addfinalizer(server.stop)
    return server


@pytest.fixture
def jwt_token(our_base_url, jwt_issuer, jwt_secret):
    payload = {
        'iss': jwt_issuer,
        'iat': datetime.datetime.utcnow(),
        'exp': datetime.datetime.utcnow() + datetime.timedelta(seconds=30)}
    return jwt.encode(payload, jwt_secret, algorithm='HS256')


@pytest.fixture
def json_file():
    with open('tests/ui/variables.json') as f:
        return json.load(f)
