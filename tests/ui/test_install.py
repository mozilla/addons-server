import pytest


from pages.desktop.details import Detail


@pytest.mark.nondestructive
def test_addon_install(
        base_url, selenium, firefox, firefox_notifications):
    """Test that navigates to an addon and installs it."""
    selenium.get('{}/addon/ui-test-install'.format(base_url))
    addon = Detail(selenium, base_url)
    assert 'My WebExtension Addon' in addon.name
    addon.install()
    firefox.browser.wait_for_notification(
        firefox_notifications.AddOnInstallBlocked).allow()
    firefox.browser.wait_for_notification(
        firefox_notifications.AddOnInstallConfirmation).install()
    firefox.browser.wait_for_notification(
        firefox_notifications.AddOnInstallComplete).close()
