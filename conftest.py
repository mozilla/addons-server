"""
pytest hooks and fixtures used for our unittests.

Please note that there should not be any Django/Olympia related imports
on module-level, they should instead be added to hooks or fixtures directly.
"""
import os
import uuid

import pytest
import responses


@pytest.fixture(autouse=True)
def unpin_db(request):
    """Unpin the database from master in the current DB.

    The `multidb` middleware pins the current thread to master for 15 seconds
    after any POST request, which can lead to unexpected results for tests
    of DB slave functionality."""
    from multidb import pinning

    request.addfinalizer(pinning.unpin_this_thread)


@pytest.fixture(autouse=True, scope='class')
def mock_elasticsearch():
    """Mock ElasticSearch in tests by default.

    Tests that do need ES should inherit from ESTestCase, which will stop the
    mock at setup time."""
    from olympia.amo.tests import start_es_mocks, stop_es_mocks

    start_es_mocks()

    yield

    stop_es_mocks()


@pytest.fixture(autouse=True)
def start_responses_mocking(request):
    """Enable ``responses`` this enforcing us to explicitly mark tests
    that require internet usage.
    """
    marker = request.node.get_closest_marker('allow_external_http_requests')

    if not marker:
        responses.start()

    yield

    try:
        if not marker:
            responses.stop()
            responses.reset()
    except RuntimeError:
        # responses patcher was already uninstalled
        pass


@pytest.fixture(autouse=True)
def mock_basket(settings):
    """Mock Basket in tests by default.

    Tests that do need basket to work should disable `responses`
    and add a passthrough.
    """
    USER_TOKEN = u'13f64f64-1de7-42f6-8c7f-a19e2fae5021'
    responses.add(
        responses.GET,
        settings.BASKET_URL + '/news/lookup-user/',
        json={'status': 'ok', 'newsletters': [], 'token': USER_TOKEN})
    responses.add(
        responses.POST,
        settings.BASKET_URL + '/news/subscribe/',
        json={'status': 'ok', 'token': USER_TOKEN})
    responses.add(
        responses.POST,
        settings.BASKET_URL + '/news/unsubscribe/{}/'.format(USER_TOKEN),
        json={'status': 'ok', 'token': USER_TOKEN})
    responses.add(
        responses.GET,
        'https://addons.mozilla.org/api/v4/addons/{}'.format(
            'search/?recommended=true&sort=random&type=extension'),
        json={'status': 'ok'})
    responses.add(
        responses.GET,
        'https://addons.mozilla.org/api/v4/addons/{}'.format(
            'search/?recommended=true&sort=users&type=extension'),
        json={'status': 'ok'})
    responses.add(
        responses.GET,
        'https://addons.mozilla.org/api/v4/addons/{}'.format(
            'recommended=true&sort=users&type=extension'),
        json={'status': 'not found'})
    responses.add(
        responses.GET,
        'https://addons.mozilla.org/api/v4/addons/{}'.format(
            'search/?recommended=false&sort=random&type=extension'),
        json={'status': 'bad request'})
    responses.add(
        responses.GET,
        'https://addons.mozilla.org/api/v4/addons/{}'.format(
            'search/?sort=users&type=theme'),
        json={'status': 'ok'})


@pytest.fixture(autouse=True)
def update_services_db_name_to_follow_test_db_name(db, settings, request):
    settings.SERVICES_DATABASE['NAME'] = settings.DATABASES['default']['NAME']


def pytest_configure(config):
    import django
    # Forcefully call `django.setup`, pytest-django tries to be very lazy
    # and doesn't call it if it has already been setup.
    # That is problematic for us since we overwrite our logging config
    # in settings_test and it can happen that django get's initialized
    # with the wrong configuration. So let's forcefully re-initialize
    # to setup the correct logging config since at this point
    # DJANGO_SETTINGS_MODULE should be `settings_test` every time.
    django.setup()

    from olympia.amo.tests import prefix_indexes
    prefix_indexes(config)


@pytest.fixture(autouse=True, scope='session')
def instrument_jinja():
    """Make sure the "templates" list in a response is properly updated, even
    though we're using Jinja2 and not the default django template engine."""
    import jinja2
    from django import test

    old_render = jinja2.Template.render

    def instrumented_render(self, *args, **kwargs):
        context = dict(*args, **kwargs)
        test.signals.template_rendered.send(
            sender=self, template=self, context=context)
        return old_render(self, *args, **kwargs)

    jinja2.Template.render = instrumented_render


def default_prefixer(settings):
    """Make sure each test starts with a default URL prefixer."""
    from django import http
    from olympia import amo

    request = http.HttpRequest()
    request.META['SCRIPT_NAME'] = ''
    prefixer = amo.urlresolvers.Prefixer(request)
    prefixer.app = settings.DEFAULT_APP
    prefixer.locale = settings.LANGUAGE_CODE
    amo.urlresolvers.set_url_prefix(prefixer)


@pytest.fixture(autouse=True)
def test_pre_setup(request, tmpdir, settings):
    from django.core.cache import caches
    from django.utils import translation
    from olympia import amo, core
    from olympia.translations.hold import clean_translations
    from waffle.utils import get_cache as waffle_get_cache
    from waffle import models as waffle_models

    # Clear all cache-instances. They'll be re-initialized by Django
    # This will make sure that our random `KEY_PREFIX` is applied
    # appropriately.
    # This is done by Django too whenever `settings` is changed
    # directly but because we're using the `settings` fixture
    # here this is not detected correctly.
    caches._caches.caches = {}

    # Randomize the cache key prefix to keep
    # tests isolated from each other.
    prefix = uuid.uuid4().hex
    settings.CACHES['default']['KEY_PREFIX'] = 'amo:{0}:'.format(prefix)

    # Reset global django-waffle cache instance to make sure it's properly
    # using our new key prefix
    waffle_models.cache = waffle_get_cache()

    translation.trans_real.deactivate()
    # Django fails to clear this cache.
    translation.trans_real._translations = {}
    translation.trans_real.activate(settings.LANGUAGE_CODE)

    def _path(*args):
        path = str(os.path.join(*args))
        if not os.path.exists(path):
            os.makedirs(path)
        return path

    settings.STORAGE_ROOT = storage_root = _path(str(tmpdir.mkdir('storage')))
    settings.SHARED_STORAGE = shared_storage = _path(
        storage_root, 'shared_storage')

    settings.ADDONS_PATH = _path(storage_root, 'files')
    settings.GUARDED_ADDONS_PATH = _path(storage_root, 'guarded-addons')
    settings.GIT_FILE_STORAGE_PATH = _path(storage_root, 'git-storage')
    settings.MLBF_STORAGE_PATH = _path(storage_root, 'mlbf')
    settings.MEDIA_ROOT = _path(shared_storage, 'uploads')
    settings.TMP_PATH = _path(shared_storage, 'tmp')

    # Reset the prefixer and urlconf after updating media root
    default_prefixer(settings)

    from django.urls import clear_url_caches, set_urlconf

    def _clear_urlconf():
        clear_url_caches()
        set_urlconf(None)

    _clear_urlconf()

    request.addfinalizer(_clear_urlconf)

    yield

    core.set_user(None)
    clean_translations(None)  # Make sure queued translations are removed.

    # Make sure we revert everything we might have changed to prefixers.
    amo.urlresolvers.clean_url_prefixes()


@pytest.fixture
def admin_group(db):
    """Create the Admins group."""
    from olympia.access.models import Group
    return Group.objects.create(name='Admins', rules='*:*')


@pytest.fixture
def mozilla_user(admin_group, settings):
    """Create a "Mozilla User"."""
    from olympia.access.models import GroupUser
    from olympia.users.models import UserProfile

    user = UserProfile.objects.create(pk=settings.TASK_USER_ID,
                                      email='admin@mozilla.com',
                                      username='admin')
    user.save()
    GroupUser.objects.create(user=user, group=admin_group)
    return user
