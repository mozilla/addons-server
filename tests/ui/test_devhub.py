import pytest
import requests


@pytest.mark.desktoponly
@pytest.mark.nondestructive
@pytest.mark.withoutresponses
def test_devhub_home_loads_addons(base_url, selenium, devhub_login):
    """Test devhub home loads correct number of addons listed."""
    devhub = devhub_login
    r = requests.get('http://olympia.test/api/v4/accounts/account/uitest/')
    author_addons = r.json()['num_addons_listed']
    assert len(devhub.addons_list) == author_addons


@pytest.mark.desktoponly
@pytest.mark.nondestructive
@pytest.mark.withoutresponses
def test_devhub_addon_edit_link_works(base_url, selenium, devhub_login):
    """Test addon edit link returns edit page."""
    devhub = devhub_login
    addon_name = devhub.addons_list[0].name
    addon_editor = devhub.addons_list[0].edit()
    assert addon_name == addon_editor.name


@pytest.mark.desktoponly
@pytest.mark.nondestructive
@pytest.mark.withoutresponses
def test_devhub_addon_upload(base_url, selenium, devhub_upload):
    """Test uploading an addon via devhub."""
    'ui-test-addon-2' in devhub_upload.addons[-1].name
