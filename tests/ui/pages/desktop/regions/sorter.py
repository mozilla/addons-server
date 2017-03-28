# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.


from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.action_chains import ActionChains

from pypom import Page


class Sorter(Page):

    _sort_by_featured_locator = (By.XPATH, "//div[@id='sorter']//li/a[normalize-space(text())='Featured']")
    _sort_by_most_users_locator = (By.XPATH, "//div[@id='sorter']//li/a[normalize-space(text())='Most Users']")
    _sort_by_top_rated_locator = (By.XPATH, "//div[@id='sorter']//li/a[normalize-space(text())='Top Rated']")
    _sort_by_newest_locator = (By.XPATH, "//div[@id='sorter']//li/a[normalize-space(text())='Newest']")

    _sort_by_name_locator = (By.XPATH, "//div[@id='sorter']//li/a[normalize-space(text())='Name']")
    _sort_by_weekly_downloads_locator = (By.XPATH, "//div[@id='sorter']//li/a[normalize-space(text())='Weekly Downloads']")
    _sort_by_recently_updated_locator = (By.XPATH, "//div[@id='sorter']//li/a[normalize-space(text())='Recently Updated']")
    _sort_by_up_and_coming_locator = (By.XPATH, "//div[@id='sorter']//li/a[normalize-space(text())='Up & Coming']")

    _selected_sort_by_locator = (By.CSS_SELECTOR, '#sorter > ul > li.selected a')

    _hover_more_locator = (By.CSS_SELECTOR, "li.extras > a")
    _updating_locator = (By.CSS_SELECTOR, '.updating')
    _footer_locator = (By.ID, 'footer')

    def sort_by(self, type):
        """This is done because sometimes the hover menus remains open so we move the focus to footer to close the menu
        We go to footer because all the menus open a window under them so moving the mouse from down to up will not leave any menu
        open over the desired element"""
        footer_element = self.selenium.find_element(*self._footer_locator)
        ActionChains(self.selenium).move_to_element(footer_element).perform()
        click_element = self.selenium.find_element(*getattr(self, '_sort_by_%s_locator' % type.replace(' ', '_').lower()))
        if type.replace(' ', '_').lower() in ["featured", "most_users", "top_rated", "newest"]:
            click_element.click()
        else:
            hover_element = self.selenium.find_element(*self._hover_more_locator)
            ActionChains(self.selenium).move_to_element(hover_element).\
                move_to_element(click_element).\
                click().perform()
        WebDriverWait(self.selenium, self.timeout).until(lambda s: not self.is_element_present(*self._updating_locator))

    @property
    def sorted_by(self):
        self.wait.until(
            lambda _: self.selenium.find_element(
                *self._selected_sort_by_locator).text)
        return self.selenium.find_element(*self._selected_sort_by_locator).text
