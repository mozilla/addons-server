import datetime
import os
import urlparse

from waffle.testutils import override_switch
from fxapom.fxapom import DEV_URL, PROD_URL, FxATestAccount
import jwt
import pytest
import requests
import json

import django
from django.core.management import call_command
from olympia.access.models import Group


@pytest.fixture
def capabilities(capabilities):
    # In order to run these tests in Firefox 48, marionette is required
    capabilities['marionette'] = True
    return capabilities


@pytest.fixture
def admin_group(db):
    """Create the Admins group."""
    return Group.objects.create(name='Admins', rules='*:*')


@pytest.fixture
def django_setup(base_url, live_server, admin_group):
    django.setup()
    hostname = urlparse.urlsplit(base_url).hostname
    with override_switch('super-create-accounts', active=True):
        print('waffle active')
        call_command(
            'createsuperuser',
            interactive=False,
            username='uitest',
            email='uitester@mozilla.org',
            add_to_supercreate_group=True,
            save_api_credentials='tests/ui/variables.json',
            hostname=hostname
        )
    # call('./manage waffle_switch super-create-accounts on --create')
    return live_server


@pytest.fixture
def fxa_account(base_url):
    url = DEV_URL if 'dev' in base_url else PROD_URL
    return FxATestAccount(url)


@pytest.fixture
def jwt_issuer(base_url, json_file):
    try:
        hostname = urlparse.urlsplit(base_url).hostname
        return json_file['api'][hostname]['jwt_issuer']
    except KeyError:
        return os.getenv('JWT_ISSUER')


@pytest.fixture
def jwt_secret(base_url, json_file):
    try:
        hostname = urlparse.urlsplit(base_url).hostname
        return json_file['api'][hostname]['jwt_secret']
    except KeyError:
        return os.getenv('JWT_SECRET')


@pytest.fixture
def jwt_token(base_url, jwt_issuer, jwt_secret):
    payload = {
        'iss': jwt_issuer,
        'iat': datetime.datetime.utcnow(),
        'exp': datetime.datetime.utcnow() + datetime.timedelta(seconds=30)}
    print(jwt_secret)
    return jwt.encode(payload, jwt_secret, algorithm='HS256')


@pytest.fixture
def user(base_url, django_setup, fxa_account, jwt_token):
    user = {
        'email': fxa_account.email,
        'password': fxa_account.password,
        'username': fxa_account.email.split('@')[0]}
    url = '{base_url}/api/v3/accounts/super-create/'.format(base_url=base_url)
    params = {
        'email': user['email'],
        'username': user['username'],
        'password': user['password'],
        'fxa_id': fxa_account.session.uid}
    headers = {'Authorization': 'JWT {token}'.format(token=jwt_token)}
    r = requests.post(url, data=params, headers=headers)
    assert requests.codes.created == r.status_code
    user.update(r.json())
    return user


@pytest.fixture
def json_file():
    with open('tests/ui/variables.json') as f:
        return json.load(f)
