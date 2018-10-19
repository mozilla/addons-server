import pytest
import requests

from pages.desktop.devhub import DevHub


@pytest.mark.fxa_login
@pytest.mark.desktop_only
@pytest.mark.nondestructive
@pytest.mark.withoutresponses
def test_devhub_home_loads_addons(base_url, selenium, devhub_login):
    """Test devhub home loads correct number of addons listed."""
    devhub = devhub_login
    r = requests.get('http://olympia.test/api/v4/accounts/account/uitest/')
    author_addons = r.json()['num_addons_listed']
    assert len(devhub.addons_list) == author_addons


@pytest.mark.fxa_login
@pytest.mark.desktop_only
@pytest.mark.nondestructive
@pytest.mark.withoutresponses
def test_devhub_addon_edit_link_works(base_url, selenium, devhub_login):
    """Test addon edit link returns edit page."""
    devhub = devhub_login
    addon_name = devhub.addons_list[0].name
    addon_editor = devhub.addons_list[0].edit()
    assert addon_name == addon_editor.name


@pytest.mark.fxa_login
@pytest.mark.desktop_only
@pytest.mark.nondestructive
@pytest.mark.withoutresponses
def test_devhub_addon_upload(base_url, selenium, devhub_upload):
    """Test uploading an addon via devhub."""
    'ui-test-addon-2' in devhub_upload.addons[-1].name


@pytest.mark.fxa_login
@pytest.mark.desktop_only
@pytest.mark.nondestructive
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
    selenium.get('http://olympia.test/en-US/developers/')
    devhub = DevHub(selenium, base_url)
    assert not devhub.logged_in
    devhub.header.register()
    assert 'signup' in selenium.current_url
