import pytest

from pages.desktop.discopane import DiscoveryPane, DiscoveryPanePage, AboutAddons

@pytest.fixture
def firefox_profile(firefox_profile, discovery_pane_url):
    '''
    Set preferences necessary to load discovery pane, and
    for installing extensions and toggling switches to
    install and uninstall.
    '''
    firefox_profile.set_preference('extensions.webapi.testing', True)
    firefox_profile.set_preference('extensions.webservice.discoverURL', discovery_pane_url)
    firefox_profile.update_preferences()
    return firefox_profile

@pytest.fixture
def discovery_pane(selenium, discovery_pane_url):
    return DiscoveryPanePage(selenium, discovery_pane_url).open().discovery_pane

@pytest.mark.nondestructive
def test_that_discovery_pane_loads(discovery_pane):
    assert discovery_pane.is_discopane_visible
    assert (len(discovery_pane.uninstalled_addons) == 5)

@pytest.mark.nondestructive
def test_that_welcome_video_plays(discovery_pane):
    discovery_pane.play_video()
    assert discovery_pane.is_video_playing
    discovery_pane.close_video()
    assert discovery_pane.is_video_closed

@pytest.mark.nondestructive
def test_see_more_addons_button(discovery_pane):
    assert discovery_pane.is_see_more_addons_displayed
