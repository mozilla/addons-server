# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import re

from selenium.webdriver.common.by import By

from pypom import Region
from pages.desktop.base import Base
from pages.desktop.search import SearchResultList


class Themes(Base):

    _url = '{base_url}/{locale}/firefox/themes/'
    _page_title = "Themes :: Add-ons for Firefox"

    _featured_themes_locator = (By.CSS_SELECTOR, '.personas-featured .persona')
    _recently_added_themes_locator = (By.CSS_SELECTOR, "#personas-created .persona")
    _most_popular_themes_locator = (By.CSS_SELECTOR, "#personas-popular .persona")
    _top_rated_themes_locator = (By.CSS_SELECTOR, "#personas-rating .persona")

    _theme_header_locator = (By.CSS_SELECTOR, ".featured-inner > h2")

    @property
    def featured_themes(self):
        return [self.Theme(self.base_url, self.selenium, root=el) for
                el in self.selenium.find_elements(*self._featured_themes_locator)]

    @property
    def recently_added_themes(self):
        return [self.Theme(self.base_url, self.selenium, root=el) for
                el in self.selenium.find_elements(*self._recently_added_themes_locator)]

    @property
    def most_popular_themes(self):
        return [self.Theme(self.base_url, self.selenium, root=el) for
                el in self.selenium.find_elements(*self._most_popular_themes_locator)]

    @property
    def top_rated_themes(self):
        return [self.Theme(self.base_url, self.selenium, root=el) for
                el in self.selenium.find_elements(*self._top_rated_themes_locator)]

    class Theme(Region):

        _link_locator = (By.TAG_NAME, 'a')

        def click(self):
            self.root.find_element(*self._link_locator).click()
            return ThemesDetail(self.base_url, self.selenium)


class ThemesDetail(Base):

    _page_title_regex = '.+ :: Add-ons for Firefox'

    _themes_title_locator = (By.CSS_SELECTOR, 'h2.addon > span')

    @property
    def is_the_current_page(self):
        # This overrides the method in the Page super class.
        actual_page_title = self.page_title
        assert re.match(self._page_title_regex, actual_page_title) is not None, 'Expected the current page to be the themes detail page.\n Actual title: %s' % actual_page_title
        return True

    @property
    def is_title_visible(self):
        return self.is_element_visible(*self._themes_title_locator)

    @property
    def title(self):
        return self.selenium.find_element(*self._themes_title_locator).text


class ThemesSearchResultList(SearchResultList):
    _results_locator = (By.CSS_SELECTOR, '.personas-grid .persona')

    class ThemesSearchResultItem(SearchResultList.SearchResultItem):
        _name_locator = (By.CSS_SELECTOR, 'h6 > a')
