import datetime
import os
import json
import urlparse
from subprocess import call

import jwt
import pytest
import requests
from django.core.management import call_command
from django.conf import settings
from olympia import amo

from pages.desktop.devhub import DevHub


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


@pytest.fixture(scope='session')
def fxa_urls():
     return {
        "authentication": "https://stable.dev.lcip.org/auth/v1",
        "oauth": "https://oauth-stable.dev.lcip.org/v1",
        "content": "https://stable.dev.lcip.org/",
        "profile": "https://stable.dev.lcip.org/profile/v1",
        "token": None,
    }


@pytest.fixture(scope='function',
                params=[(1080, 1080), (414, 738)],
                ids=['Resolution: 1080x1920', 'Resolution: 414x738'])
def selenium(selenium, request):
    """Fixture to set custom selenium parameters.

    This fixture will also parametrize all of the tests to run them on both a
    Desktop resolution and a mobile resolution.

    Desktop size: 1920x1080
    Mobile size: 738x414 (iPhone 7+)

    """
    if request.node.get_marker('desktoponly') and request.param == (414, 738):
        pytest.skip("Skipping mobile test")
    selenium.set_window_size(*request.param)
    return selenium


@pytest.fixture(scope='session')
def base_url(base_url):
    return base_url


@pytest.fixture
def devhub_login(selenium, fxa_account):
    """Log into the devhub."""
    url = selenium.get('http://olympia.test/developers')
    devhub = DevHub(selenium, url)
    devhub.login(fxa_account.email, fxa_account.password)
    return devhub.wait_for_page_to_load()


@pytest.fixture
def devhub_upload(devhub_login):
    """Upload addon to devhub.

    This uses a webextension fixture within addons-server to
    upload as a new addon.
    """
    devhub = devhub_login
    addon = devhub.upload_addon()
    return addon.fill_addon_submission_form()


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
