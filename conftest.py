from django import http, test
from django.conf import settings
from django.core.cache import cache
from django.utils import translation

import caching
import pytest
from multidb import pinning

from olympia import amo, core
from olympia.amo.tests import start_es_mocks, stop_es_mocks
from olympia.access.models import Group, GroupUser
from olympia.translations.hold import clean_translations
from olympia.users.models import UserProfile


@pytest.fixture(autouse=True)
def unpin_db(request):
    """Unpin the database from master in the current DB.

    The `multidb` middleware pins the current thread to master for 15 seconds
    after any POST request, which can lead to unexpected results for tests
    of DB slave functionality."""

    request.addfinalizer(pinning.unpin_this_thread)


@pytest.fixture(autouse=True)
def mock_elasticsearch():
    """Mock ElasticSearch in tests by default.

    Tests that do need ES should inherit from ESTestCase, which will stop the
    mock at setup time."""
    start_es_mocks()

    yield

    stop_es_mocks()


@pytest.fixture(autouse=True)
def mock_inline_css(monkeypatch):
    """Mock jingo_minify.helpers.is_external: don't break on missing files.

    When testing, we don't want nor need the bundled/minified css files, so
    pretend that all the css files are external.

    Mocking this will prevent amo.templatetags.jinja_helpers.inline_css to
    believe it should bundle the css.

    """
    from olympia.amo.templatetags import jinja_helpers
    monkeypatch.setattr(jinja_helpers, 'is_external', lambda css: True)


def pytest_configure(config):
    from olympia.amo.tests import prefix_indexes
    prefix_indexes(config)


@pytest.fixture(autouse=True, scope='session')
def instrument_jinja():
    """Make sure the "templates" list in a response is properly updated, even
    though we're using Jinja2 and not the default django template engine."""
    import jinja2
    old_render = jinja2.Template.render

    def instrumented_render(self, *args, **kwargs):
        context = dict(*args, **kwargs)
        test.signals.template_rendered.send(
            sender=self, template=self, context=context)
        return old_render(self, *args, **kwargs)

    jinja2.Template.render = instrumented_render


def default_prefixer():
    """Make sure each test starts with a default URL prefixer."""
    request = http.HttpRequest()
    request.META['SCRIPT_NAME'] = ''
    prefixer = amo.urlresolvers.Prefixer(request)
    prefixer.app = settings.DEFAULT_APP
    prefixer.locale = settings.LANGUAGE_CODE
    amo.urlresolvers.set_url_prefix(prefixer)


@pytest.fixture(autouse=True)
def test_pre_setup():
    cache.clear()
    # Override django-cache-machine caching.base.TIMEOUT because it's
    # computed too early, before settings_test.py is imported.
    caching.base.TIMEOUT = settings.CACHE_COUNT_TIMEOUT

    translation.trans_real.deactivate()
    # Django fails to clear this cache.
    translation.trans_real._translations = {}
    translation.trans_real.activate(settings.LANGUAGE_CODE)

    # Reset the prefixer.
    default_prefixer()


@pytest.fixture(autouse=True)
def test_post_teardown():
    core.set_user(None)
    clean_translations(None)  # Make sure queued translations are removed.

    # Make sure we revert everything we might have changed to prefixers.
    amo.urlresolvers.clean_url_prefixes()


@pytest.fixture
def admin_group(db):
    """Create the Admins group."""
    return Group.objects.create(name='Admins', rules='*:*')


@pytest.fixture
def mozilla_user(admin_group):
    """Create a "Mozilla User"."""
    user = UserProfile.objects.create(pk=settings.TASK_USER_ID,
                                      email='admin@mozilla.com',
                                      username='admin')
    user.save()
    GroupUser.objects.create(user=user, group=admin_group)
    return user
