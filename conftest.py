# The following line is needed for all the hackery done to the python path.
import manage  # noqa

from django.conf import settings
from django.db.models import loading

import pytest


@pytest.fixture(autouse=True, scope='session')
def _load_testapp():
    extra_apps = getattr(settings, 'TEST_INSTALLED_APPS')
    if extra_apps:
        installed_apps = getattr(settings, 'INSTALLED_APPS')
        setattr(settings, 'INSTALLED_APPS', installed_apps + extra_apps)
        loading.cache.loaded = False


@pytest.fixture(autouse=True)
def mock_inline_css(monkeypatch):
    """Mock jingo_minify.helpers.is_external: don't break on missing files.

    When testing, we don't want nor need the bundled/minified css files, so
    pretend that all the css files are external.

    Mocking this will prevent amo.helpers.inline_css to believe it should
    bundle the css.

    """
    import amo.helpers
    monkeypatch.setattr(amo.helpers, 'is_external', lambda css: True)
