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


<<<<<<< 7b20c573c86d2ee1c922d52e9989844b58a2be5d
<<<<<<< 9a8cb1873c7b63de19ba3672a7c14d35d6cd42ba
@pytest.fixture
def initial_data(transactional_db):
    from olympia.amo.tests import addon_factory, user_factory
    from olympia.addons.models import AddonUser

    for x in range(10):
        AddonUser.objects.create(user=user_factory(), addon=addon_factory())
=======
@pytest.fixture(scope='session')
def initial_data(live_server):
=======
@pytest.fixture
def gen_10_addons():
>>>>>>> Setup config for initial test move
    from olympia.amo.tests import addon_factory
    from olympia.constants.applications import APPS
    from olympia.landfill.collection import generate_collection
    call_command('generate_addons', 10, app='firefox')
<<<<<<< 7b20c573c86d2ee1c922d52e9989844b58a2be5d
    addon = addon_factory()
    generate_collection(addon, APPS['firefox'])
>>>>>>> Changed conftest for proper db initialization and use
=======
    # call_command('generate_themes', 6)
    generate_collection(addon_factory(), APPS['firefox'])
>>>>>>> Setup config for initial test move


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

<<<<<<< d435e4cad5feb4ebb23ab3b0f1297cb20556a993
    with tmpdir.join('variables.json').open() as f:
        variables.update(json.load(f))
=======

@pytest.fixture
def ui_addon():
    import random

    from olympia import amo
    from olympia.amo.tests import addon_factory, user_factory, version_factory
    from olympia.addons.forms import icons
    from olympia.addons.models import Addon, AddonCategory, Category, Preview, AddonUser
    from olympia.addons.utils import generate_addon_guid
    from olympia.constants.categories import CATEGORIES
    from olympia.constants.applications import APPS
    from olympia.reviews.models import Review
    from olympia.landfill.collection import generate_collection

    cat1 = Category.from_static_category(
            CATEGORIES[amo.FIREFOX.id][amo.ADDON_EXTENSION]['bookmarks'])
    default_icons = [x[0] for x in icons() if x[0].startswith('icon/')]
    addon = addon_factory(
        status=amo.STATUS_PUBLIC,
        average_daily_users=4242,
        average_rating=4.21,
        category=cat1,
        description=u'My Addon description',
        file_kw={
            'hash': 'fakehash',
            'platform': amo.PLATFORM_ALL.id,
            'size': 42,
        },
        guid=generate_addon_guid(),
        homepage=u'https://www.example.org/',
        icon_type=random.choice(default_icons),
        name=u'Ui-Test',
        public_stats=True,
        slug='ui-test',
        summary=u'My Addon summary',
        support_email=u'support@example.org',
        support_url=u'https://support.example.org/support/ui-test-addon/',
        tags=['some_tag', 'another_tag', 'ui-testing', 'selenium', 'python'],
        total_reviews=777,
        weekly_downloads=2147483647,
        developer_comments='This is a testing addon, used within pytest.',
        is_experimental=True,
    )
    first_preview = Preview.objects.create(addon=addon, position=1)
    Review.objects.create(addon=addon, rating=5, user=user_factory())
    Review.objects.create(addon=addon, rating=3, user=user_factory())
    Review.objects.create(addon=addon, rating=2, user=user_factory())
    Review.objects.create(addon=addon, rating=1, user=user_factory())
    addon.reload()
    AddonUser.objects.create(user=user_factory(username='ui-tester'),
                             addon=addon, listed=True)
    AddonUser.objects.create(user=user_factory(username='ui-tester2'),
                             addon=addon, listed=True)
    version_factory(addon=addon, file_kw={'status': amo.STATUS_BETA},
                    version='1.1beta')
    generate_collection(addon, APPS['firefox'])
    addon.save()

    print('Create custom addon for testing successfully')


@pytest.fixture
def force_user_login():
    """
        Fixture for providing the user object to seleniumlogin for logging into
        the live_server specifically. Does not run on 'dev' or 'stage'
        environments.
    """
    from olympia.users.models import UserProfile
    user = UserProfile.objects.get(username='uitest')
    return user
>>>>>>> Initial attempt at creating an addon for testing


@pytest.fixture
def user(create_superuser, my_base_url, fxa_account, jwt_token):
    url = '{base_url}/api/v3/accounts/super-create/'.format(
        base_url=my_base_url)

    params = {
        'email': fxa_account.email,
        'password': fxa_account.password,
        'username': fxa_account.email.split('@')[0],
        'fxa_id': fxa_account.session.uid}
    headers = {'Authorization': 'JWT {token}'.format(token=jwt_token)}
    response = requests.post(url, data=params, headers=headers)
    assert requests.codes.created == response.status_code
    params.update(response.json())
    return params


<<<<<<< 7b20c573c86d2ee1c922d52e9989844b58a2be5d
<<<<<<< 9a8cb1873c7b63de19ba3672a7c14d35d6cd42ba
@pytest.fixture(scope='function')
def live_server(request, transactional_db):
=======
@pytest.fixture(autouse=True)
=======
@pytest.fixture
>>>>>>> Setup config for initial test move
def live_server(request, initial_data, ui_addon):
>>>>>>> Changed conftest for proper db initialization and use
    """
        This fixture overrides the live_server fixture provided by
        pytest_django. live_server allows us to create a running version of the
        addons django application within pytest for testing.
<<<<<<< d435e4cad5feb4ebb23ab3b0f1297cb20556a993
=======

        Christopher Grebs:
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
>>>>>>> Initial attempt at creating an addon for testing

        Christopher Grebs:
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
    # server.stop()


@pytest.fixture
def jwt_token(base_url, jwt_issuer, jwt_secret):
    payload = {
        'iss': jwt_issuer,
        'iat': datetime.datetime.utcnow(),
        'exp': datetime.datetime.utcnow() + datetime.timedelta(seconds=30)}
    return jwt.encode(payload, jwt_secret, algorithm='HS256')
