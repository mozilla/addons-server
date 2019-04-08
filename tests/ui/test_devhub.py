import time

import pytest
import requests
from selenium.common.exceptions import NoSuchElementException

from pages.desktop.devhub import DevHub
from pages.desktop.details import Detail


@pytest.mark.fxa_login
@pytest.mark.desktop_only
@pytest.mark.nondestructive
@pytest.mark.allow_external_http_requests
def test_devhub_home_loads_addons(base_url, selenium, devhub_login):
    """Test devhub home loads correct number of addons listed."""
    devhub = devhub_login
    r = requests.get('{}/api/v4/accounts/account/uitest/'.format(base_url))
    author_addons = r.json()['num_addons_listed']
    assert len(devhub.addons_list) == author_addons


@pytest.mark.fxa_login
@pytest.mark.desktop_only
@pytest.mark.nondestructive
@pytest.mark.allow_external_http_requests
def test_devhub_addon_edit_link_works(base_url, selenium, devhub_login):
    """Test addon edit link returns edit page."""
    devhub = devhub_login
    addon_name = devhub.addons_list[0].name
    addon_editor = devhub.addons_list[0].edit()
    assert addon_name == addon_editor.name


@pytest.mark.fxa_login
@pytest.mark.desktop_only
@pytest.mark.nondestructive
@pytest.mark.allow_external_http_requests
@pytest.mark.withoutresponses
def test_devhub_logout(base_url, selenium, devhub_login):
    """Logging out from devhub."""
    assert devhub_login.logged_in
    devhub = devhub_login.header.click_sign_out()
    assert not devhub.logged_in


@pytest.mark.desktop_only
@pytest.mark.nondestructive
def test_devhub_register(base_url, selenium):
    """Test register link loads register page."""
    selenium.get('{}/developers'.format(base_url))
    devhub = DevHub(selenium, base_url)
    assert not devhub.logged_in
    devhub.header.register()
    assert 'signup' in selenium.current_url


@pytest.mark.fxa_login
@pytest.mark.desktop_only
@pytest.mark.nondestructive
@pytest.mark.allow_external_http_requests
def test_devhub_addon_upload_approve_install(
        base_url, selenium, devhub_upload, firefox, firefox_notifications):
    """Test uploading an addon via devhub."""
    'ui-test-addon-2' in devhub_upload.addons[-1].name
    # We have to wait for approval
    time.sleep(15)
    page_loaded = False
    while page_loaded is not True:
        try:
            selenium.get('{}/addon/ui-test_devhub_ext/'.format(base_url))
            addon = Detail(selenium, base_url)
            'UI-Test_devhub_ext' in addon.name
        except NoSuchElementException:
            pass
        except Exception:
            raise Exception
        else:
            page_loaded = True
            return page_loaded
    addon.install()
    firefox.browser.wait_for_notification(
        firefox_notifications.AddOnInstallBlocked
    ).allow()
    firefox.browser.wait_for_notification(
        firefox_notifications.AddOnInstallConfirmation
    ).install()
    firefox.browser.wait_for_notification(
        firefox_notifications.AddOnInstallComplete
    ).close()
