# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from selenium.webdriver.common.by import By

from pages.desktop.base import Base


class Category(Base):

    _categories_side_navigation_header_locator = (By.CSS_SELECTOR, "#side-nav > h2:nth-of-type(2)")
    _categories_alert_update_link_locator = (By.CSS_SELECTOR, "#side-categories > li:nth-of-type(1) > a")
    _categories_appearance_link_locator = (By.CSS_SELECTOR, "#side-categories > li:nth-of-type(2) > a")
    _categories_bookmarks_link_locator = (By.CSS_SELECTOR, "#side-categories > li:nth-of-type(3) > a")
    _categories_download_management_link_locator = (By.CSS_SELECTOR, "#side-categories > li:nth-of-type(4) > a")
    _categories_feed_news_blog_link_locator = (By.CSS_SELECTOR, "#side-categories > li:nth-of-type(5) > a")
    _categories_games_entertainment_link_locator = (By.CSS_SELECTOR, "#side-categories > li:nth-of-type(6) > a")
    _categories_language_support_link_locator = (By.CSS_SELECTOR, "#side-categories > li:nth-of-type(7) > a")
    _categories_photo_music_video_link_locator = (By.CSS_SELECTOR, "#side-categories > li:nth-of-type(8) > a")
    _categories_privacy_security_link_locator = (By.CSS_SELECTOR, "#side-categories > li:nth-of-type(9) > a")
    _categories_search_tools_link_locator = (By.CSS_SELECTOR, "#side-categories > li:nth-of-type(10) > a")
    _categories_shopping_link_locator = (By.CSS_SELECTOR, "#side-categories > li:nth-of-type(11) > a")
    _categories_social_communication_link_locator = (By.CSS_SELECTOR, "#side-categories > li:nth-of-type(12) > a")
    _categories_tabs_link_locator = (By.CSS_SELECTOR, "#side-categories > li:nth-of-type(13) > a")
    _categories_web_development_link_locator = (By.CSS_SELECTOR, "#side-categories > li:nth-of-type(14) > a")
    _categories_other_link_locator = (By.CSS_SELECTOR, "#side-categories > li:nth-of-type(15) > a")

    @property
    def categories_side_navigation_header_text(self):
        return self.selenium.find_element(*self._categories_side_navigation_header_locator).text

    @property
    def categories_alert_updates_header_text(self):
        return self.selenium.find_element(*self._categories_alert_update_link_locator).text

    @property
    def categories_appearance_header_text(self):
        return self.selenium.find_element(*self._categories_appearance_link_locator).text

    @property
    def categories_bookmark_header_text(self):
        return self.selenium.find_element(*self._categories_bookmarks_link_locator).text

    @property
    def categories_download_management_header_text(self):
        return self.selenium.find_element(*self._categories_download_management_link_locator).text

    @property
    def categories_feed_news_blog_header_text(self):
        return self.selenium.find_element(*self._categories_feed_news_blog_link_locator).text

    @property
    def categories_games_entertainment_header_text(self):
        return self.selenium.find_element(*self._categories_games_entertainment_link_locator).text

    @property
    def categories_language_support_header_text(self):
        return self.selenium.find_element(*self._categories_language_support_link_locator).text

    @property
    def categories_photo_music_video_header_text(self):
        return self.selenium.find_element(*self._categories_photo_music_video_link_locator).text

    @property
    def categories_privacy_security_header_text(self):
        return self.selenium.find_element(*self._categories_privacy_security_link_locator).text

    @property
    def categories_shopping_header_text(self):
        return self.selenium.find_element(*self._categories_shopping_link_locator).text

    @property
    def categories_social_communication_header_text(self):
        return self.selenium.find_element(*self._categories_social_communication_link_locator).text

    @property
    def categories_tabs_header_text(self):
        return self.selenium.find_element(*self._categories_tabs_link_locator).text

    @property
    def categories_web_development_header_text(self):
        return self.selenium.find_element(*self._categories_web_development_link_locator).text

    @property
    def categories_other_header_text(self):
        return self.selenium.find_element(*self._categories_other_link_locator).text
