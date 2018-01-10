import pytest


from pages.desktop.details import Details


@pytest.mark.nondestructive
def test_addon_install(
        base_url, selenium, firefox, notifications):
    selenium.get('{}/firefox/addon/ui-test-install'.format(base_url))
    addon = Details(selenium, base_url)
    assert 'Ui-Addon-Install' in addon.description_header.name
    addon.description_header.install_button.click()
    firefox.browser.wait_for_notification(
        notifications.AddOnInstallBlocked).allow()
    firefox.browser.wait_for_notification(
        notifications.AddOnInstallConfirmation).install()
