# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.wait import WebDriverWait

from pypom import Page


class HeaderMenu(Page):
    """
    This class access the header area from the top of the AMO pages.desktop.
    To access it just use:
        HeaderMenu(self.base_url, self.selenium, lookup)
    Where lookup is:
        -the web element coresponding to the menu you want to access
    Ex:
        HeaderMenu(self.base_url, self.selenium, personas_element) returns the Personas menu
    """

    _menu_items_locator = (By.CSS_SELECTOR, 'ul > li')
    _name_locator = (By.CSS_SELECTOR, 'a')
    _footer_locator = (By.ID, 'footer')
    _complete_themes_locator = (By.CSS_SELECTOR, 'div > a > b')

    def __init__(self, selenium, base_url, element):
        Page.__init__(self, selenium, base_url)
        self._root_element = element

    @property
    def name(self):
        return self._root_element.find_element(*self._name_locator).text

    def click(self):
        name = self.name
        self._root_element.find_element(*self._name_locator).click()

        if "EXTENSIONS" in name:
            from pages.desktop.extensions import ExtensionsHome
            return ExtensionsHome(self.selenium, self.base_url)
        elif "THEMES" in name:
            from pages.desktop.themes import Themes
            return Themes(self.base_url, self.selenium)
        elif "COLLECTIONS" in name:
            from pages.desktop.collections import Collections
            return Collections(self.base_url, self.selenium)

    def hover(self):
        WebDriverWait(self.selenium, self.timeout).until(
            lambda _: self._root_element.find_element(*self._name_locator)
        )
        element = self._root_element.find_element(*self._name_locator)
        action = ActionChains(self.selenium)
        action.move_to_element(element)
        action.perform()

    @property
    def is_menu_dropdown_visible(self):
        dropdown_menu = self._root_element.find_element(*self._menu_items_locator)
        return dropdown_menu.is_displayed()

    @property
    def items(self):
        return [self.HeaderMenuItem(self.selenium, self.base_url, web_element, self)
                for web_element in self._root_element.find_elements(*self._menu_items_locator)]

    class HeaderMenuItem (Page):

        _name_locator = (By.CSS_SELECTOR, 'a')

        def __init__(self, selenium, base_url, element, menu):
            Page.__init__(self, selenium, base_url)
            self._root_element = element
            self._menu = menu

        @property
        def name(self):
            self._menu.hover()
            return self._root_element.find_element(*self._name_locator).text

        @property
        def is_featured(self):
            return self._root_element.find_element(By.CSS_SELECTOR, '*').tag_name == 'em'

        def click(self):
            menu_name = self._menu.name
            self._menu.hover()
            ActionChains(self.selenium).\
                move_to_element(self._root_element).\
                click().\
                perform()

            if "EXTENSIONS" in menu_name:
                from pages.desktop.extensions import ExtensionsHome
                return ExtensionsHome(self.base_url, self.selenium)
            elif "THEMES" in menu_name:
                from pages.desktop.themes import Themes
                return Themes(self.base_url, self.selenium)
            elif "COLLECTIONS" in menu_name:
                from pages.desktop.collections import Collections
                return Collections(self.base_url, self.selenium)
