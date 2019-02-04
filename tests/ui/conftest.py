import os

import pytest
from django.conf import settings
from olympia import amo

from olympia.landfill.serializers import GenerateAddonsSerializer
from pages.desktop.devhub import DevHub

# Window resolutions
DESKTOP = (1080, 1920)
MOBILE = (414, 738)


@pytest.fixture
def firefox_options(firefox_options):
    """Firefox options.

    These options configure firefox to allow for addon installation,
    as well as allowing it to run headless.

    'extensions.install.requireBuiltInCerts', False: This allows extensions to
        be installed with a self-signed certificate.
    'xpinstall.signatures.required', False: This allows an extension to be
        installed without a certificate.
    'extensions.webapi.testing', True: This is needed for whitelisting
        mozAddonManager
    '-foreground': Firefox will run in the foreground with priority
    '-headless': Firefox will run headless

    """
    firefox_options.set_preference(
        'extensions.install.requireBuiltInCerts', False
    )
    firefox_options.set_preference('xpinstall.signatures.required', False)
    firefox_options.set_preference('extensions.webapi.testing', True)
    firefox_options.set_preference('ui.popup.disable_autohide', True)
    firefox_options.add_argument('-foreground')
    firefox_options.add_argument('-headless')
    firefox_options.log.level = 'trace'
    return firefox_options


@pytest.fixture
def firefox_notifications(notifications):
    return notifications


@pytest.fixture(
    scope='function',
    params=[DESKTOP, MOBILE],
    ids=['Resolution: 1080x1920', 'Resolution: 414x738'],
)
def selenium(selenium, request):
    """Fixture to set custom selenium parameters.

    This fixture will also parametrize all of the tests to run them on both a
    Desktop resolution and a mobile resolution.

    Desktop size: 1920x1080
    Mobile size: 738x414 (iPhone 7+)

    """
    # Skip mobile test with marker 'desktop_only'
    if request.node.get_marker('desktop_only') and request.param == MOBILE:
        pytest.skip('Skipping mobile test')
    selenium.set_window_size(*request.param)
    return selenium


@pytest.fixture
def fxa_account(request):
    """Fxa account to use during tests that need to login.

    Returns the email and password of the fxa account set in Makefile-docker.

    """
    try:
        fxa_account.email = os.environ['FXA_EMAIL']
        fxa_account.password = os.environ['FXA_PASSWORD']
    except KeyError:
        if request.node.get_marker('fxa_login'):
            pytest.skip(
                'Skipping test because no fxa account was found.'
                ' Are FXA_EMAIL and FXA_PASSWORD environment variables set?')
    return fxa_account


@pytest.fixture
def devhub_login(selenium, base_url, fxa_account):
    """Log into the devhub."""
    url = selenium.get('http://olympia.test/developers')
    devhub = DevHub(selenium, base_url)
    devhub.login(fxa_account.email, fxa_account.password)
    return devhub.wait_for_page_to_load()


@pytest.fixture
def devhub_upload(devhub_login):
    """Upload addon to devhub.

    This uses a webextension fixture within addons-server to
    upload as a new addon.

    """
    devhub = devhub_login
    addon = devhub.upload_addon('ui-test_devhub_ext-1.0.xpi')
    return addon.fill_addon_submission_form()
