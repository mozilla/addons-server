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
def my_base_url(base_url, request, live_server):
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
def initial_data():
    from olympia.amo.tests import addon_factory, user_factory
    from olympia.addons.models import AddonUser
    from olympia.landfill.collection import generate_collection
    from olympia.constants.applications import APPS

    for x in range(10):
        AddonUser.objects.create(user=user_factory(), addon=addon_factory())
        generate_collection(addon_factory(), APPS['firefox'])


@pytest.fixture
def gen_addons():
    from olympia.amo.tests import addon_factory
    from olympia.constants.applications import APPS
    from olympia.landfill.collection import generate_collection

    for x in range(40):
        generate_collection(addon_factory(), APPS['firefox'])


@pytest.fixture
def generate_themes(transactional_db):
    from olympia import amo
    from olympia.amo.tests import addon_factory
    from olympia.landfill.generators import generate_themes
    from olympia.landfill.user import generate_addon_user_and_category, generate_user
    from olympia.landfill.images import generate_addon_preview, generate_theme_images
    from olympia.landfill.collection import generate_collection
    from olympia.landfill.translations import generate_translations
    from olympia.landfill.ratings import generate_ratings
    from olympia.constants.applications import APPS, FIREFOX
    from olympia.constants.base import (
        ADDON_EXTENSION, ADDON_PERSONA, STATUS_PUBLIC, ADDON_THEME)
    from olympia.bandwagon.models import (
        Collection, CollectionAddon, FeaturedCollection)
    from olympia.users.models import UserProfile
    from olympia.addons.utils import generate_addon_guid

    # call_command('generate_themes', 6)
    owner = UserProfile.objects.get(username='uitest')
    generate_themes(6, owner, app=FIREFOX)
    for x in range(6):
        addon = addon_factory(
            status=STATUS_PUBLIC,
            type=ADDON_PERSONA,)
        generate_collection(addon, app=FIREFOX,
                            author=UserProfile.objects.get(username='uitest'),)


@pytest.fixture
def generate_collections(transactional_db):
    from olympia import amo
    from olympia.amo.tests import addon_factory
    from olympia.constants.applications import APPS, FIREFOX
    from olympia.landfill.collection import generate_collection

    for x in range(4):
        generate_collection(addon_factory(
            type=amo.ADDON_EXTENSION
        ), APPS['firefox'], type=amo.COLLECTION_FEATURED)


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
def ui_theme(transactional_db, create_superuser):
    from olympia import amo
    from olympia.amo.tests import addon_factory
    from olympia.addons.utils import generate_addon_guid
    from olympia.constants.applications import FIREFOX
    from olympia.users.models import UserProfile
    from olympia.landfill.collection import generate_collection
    from olympia.constants.base import ADDON_PERSONA, STATUS_PUBLIC

    addon = addon_factory(
        status=STATUS_PUBLIC,
        type=ADDON_PERSONA,
        average_daily_users=4242,
        users=[UserProfile.objects.get(username='uitest')],
        average_rating=4.21,
        description=u'My UI Theme description',
        file_kw={
            'hash': 'fakehash',
            'platform': amo.PLATFORM_ALL.id,
            'size': 42,
        },
        guid=generate_addon_guid(),
        homepage=u'https://www.example.org/',
        name=u'Ui-Test',
        public_stats=True,
        slug='ui-test',
        summary=u'My UI theme summary',
        support_email=u'support@example.org',
        support_url=u'https://support.example.org/support/ui-theme-addon/',
        tags=['some_tag', 'another_tag', 'ui-testing', 'selenium', 'python'],
        total_reviews=777,
        weekly_downloads=123456,
        developer_comments='This is a testing theme, used within pytest.',
    )
    addon.save()
    generate_collection(addon, app=FIREFOX,
                        author=UserProfile.objects.get(username='uitest'),
                        )

    print('Created custom addon for testing successfully')


@pytest.fixture
def ui_addon(transactional_db, create_superuser):
    import random

    from olympia import amo
    from olympia.amo.tests import addon_factory, user_factory, version_factory, collection_factory
    from olympia.addons.forms import icons
    from olympia.addons.models import Addon, AddonCategory, Category, Preview, AddonUser
    from olympia.addons.utils import generate_addon_guid
    from olympia.constants.categories import CATEGORIES
    from olympia.constants.applications import APPS, FIREFOX
    from olympia.reviews.models import Review
    from olympia.users.models import UserProfile
    from olympia.landfill.collection import generate_collection
    from olympia.landfill.user import generate_addon_user_and_category, generate_user
    from olympia.landfill.categories import generate_categories
    from olympia.constants.base import (
        ADDON_EXTENSION, ADDON_PERSONA, STATUS_PUBLIC)

    default_icons = [x[0] for x in icons() if x[0].startswith('icon/')]
    addon = addon_factory(
        status=STATUS_PUBLIC,
        type=ADDON_EXTENSION,
        average_daily_users=4242,
        users=[UserProfile.objects.get(username='uitest')],
        average_rating=4.21,
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
    AddonUser.objects.create(user=user_factory(username='ui-tester2'),
                             addon=addon, listed=True)
    version_factory(addon=addon, file_kw={'status': amo.STATUS_BETA},
                    version='1.1beta')
    addon.save()
    generate_collection(addon, app=FIREFOX,
                        author=UserProfile.objects.get(username='uitest'),
                        )

    print('Created custom addon for testing successfully')


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


@pytest.fixture(scope='function')
def live_server(request, transactional_db):
    """
        This fixture overrides the live_server fixture provided by
        pytest_django. live_server allows us to create a running version of the
        addons django application within pytest for testing.

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


@pytest.fixture
def jwt_token(base_url, jwt_issuer, jwt_secret):
    payload = {
        'iss': jwt_issuer,
        'iat': datetime.datetime.utcnow(),
        'exp': datetime.datetime.utcnow() + datetime.timedelta(seconds=30)}
    return jwt.encode(payload, jwt_secret, algorithm='HS256')
