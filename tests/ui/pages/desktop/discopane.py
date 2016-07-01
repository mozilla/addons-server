from pypom import Page, Region
from selenium.webdriver.common.by import By
import pytest

from base import Base

class DiscoveryPane(Region):

    _discopane_content_locator = (By.CSS_SELECTOR, '.disco-pane')
    _play_video_locator = (By.CSS_SELECTOR, '.play-video')
    _uninstalled_toggles = (By.CSS_SELECTOR, '.switch.uninstalled')
    _close_video_link = (By.CSS_SELECTOR, '.close-video')
    _see_more_addons_locator = (By.CSS_SELECTOR, '.amo-link')

    def click_play_video(self):
        self.find_element(*self._play_video_locator).click()

    def close_video(self):
        self.find_element(*self._close_video_link).click()

    @property
    def is_video_playing(self):
        return self.is_element_present(*self._close_video_link)

    @property
    def is_video_closed(self):
        return self.is_element_present(*self._play_video_locator)

    @property
    def is_discopane_visible(self):
        return self.is_element_present(*self._discopane_content_locator)

    @property
    def uninstalled_addons(self):
        return self.find_elements(*self._uninstalled_toggles)

    @property
    def is_see_more_addons_present(self):
        return self.is_element_present(*self._see_more_addons_locator)


class DiscoveryPanePage(Page):

    @property
    def discovery_pane(self):
        return DiscoveryPane(self)


class AboutAddons(Page):

    _discovery_pane_locator = (By.ID, 'discovery-browser')

    @property
    def discovery_pane(self):
        discover_pane = self.find_element(*self._discovery_pane_locator)
        return DiscoveryPane(self, discover_pane)
