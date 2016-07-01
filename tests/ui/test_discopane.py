import pytest

from pages.desktop.discopane import DiscoveryPane, DiscoveryPanePage, AboutAddons

@pytest.fixture
def firefox_profile(base_url, firefox_profile):
    if 'allizom' in base_url:
        # set the appropriate signatures for dev and staging
        firefox_profile.set_preference('xpinstall.signatures.dev-root', True)
    firefox_profile.set_preference('extensions.webapi.testing', True)
    firefox_profile.set_preference('extensions.webservice.discoverURL', 'https://discovery.addons-dev.allizom.org/')
    firefox_profile.update_preferences()
    return firefox_profile

@pytest.fixture
def discovery_pane(selenium):
    return DiscoveryPanePage(selenium, 'https://discovery.addons-dev.allizom.org').open().discovery_pane
    #return AboutAddons(selenium, 'about:Addons').open()

@pytest.mark.nondestructive
def test_that_discovery_pane_loads(base_url, selenium, session_capabilities, discovery_pane):
    assert discovery_pane.is_discopane_visible
    assert (len(discovery_pane.uninstalled_addons) == 5)

@pytest.mark.nondestructive
def test_that_welcome_video_plays(base_url, selenium, session_capabilities, discovery_pane):
    discovery_pane.click_play_video()
    assert discovery_pane.is_video_playing
    discovery_pane.close_video()
    assert discovery_pane.is_video_closed

@pytest.mark.nondestructive
def test_see_more_addons_button(base_url, selenium, session_capabilities, discovery_pane):
    assert discovery_pane.is_see_more_addons_present
