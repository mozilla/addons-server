# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from selenium.webdriver.common.by import By

from pages.desktop.base import Base
from pypom import Page
from pages.desktop.search import SearchResultList


class Collections(Base):

    _url = '{base_url}/{locale}/firefox/collections/'

    _page_title = "Featured Collections :: Add-ons for Firefox"
    _default_selected_tab_locator = (By.CSS_SELECTOR, "#sorter li.selected")
    _collection_name = (By.CSS_SELECTOR, "h2.collection > span")
    _create_a_collection_locator = (By.CSS_SELECTOR, "#side-nav .button")

    @property
    def collection_name(self):
        return self.selenium.find_element(*self._collection_name).text

    @property
    def default_selected_tab(self):
        return self.selenium.find_element(*self._default_selected_tab_locator).text

    def click_create_collection_button(self):
        self.selenium.find_element(*self._create_a_collection_locator).click()
        return self.CreateNewCollection(self.base_url, self.selenium)

    class UserCollections(Page):

        _collections_locator = (By.CSS_SELECTOR, ".featured-inner div.item")
        _no_results_locator = (By.CSS_SELECTOR, ".featured-inner > p.no-results")

        @property
        def collections(self):
            return self.selenium.find_elements(*self._collections_locator)

        @property
        def has_no_results(self):
            return self.is_element_present(*self._no_results_locator)

    class CreateNewCollection(Page):

        _name_field_locator = (By.ID, "id_name")
        _description_field_locator = (By.ID, "id_description")
        _create_collection_button_locator = (By.CSS_SELECTOR, ".featured-inner>form>p>input")

        def type_name(self, value):
            self.selenium.find_element(*self._name_field_locator).send_keys(value)

        def type_description(self, value):
            self.selenium.find_element(*self._description_field_locator).send_keys('Description is ' + value)

        def click_create_collection(self):
            self.selenium.find_element(*self._create_collection_button_locator).click()
            return Collection(self.base_url, self.selenium)


class Collection(Base):

    _notification_locator = (By.CSS_SELECTOR, ".notification-box.success h2")
    _collection_name_locator = (By.CSS_SELECTOR, ".collection > span")
    _delete_collection_locator = (By.CSS_SELECTOR, ".delete")
    _delete_confirmation_locator = (By.CSS_SELECTOR, ".section > form > button")

    @property
    def notification(self):
        return self.selenium.find_element(*self._notification_locator).text

    @property
    def collection_name(self):
        return self.selenium.find_element(*self._collection_name_locator).text

    def delete(self):
        self.selenium.find_element(*self._delete_collection_locator).click()

    def delete_confirmation(self):
        self.selenium.find_element(*self._delete_confirmation_locator).click()
        return Collections.UserCollections(self.base_url, self.selenium)


class CollectionSearchResultList(SearchResultList):
    _results_locator = (By.CSS_SELECTOR, "div.featured-inner div.item")

    class CollectionsSearchResultItem(SearchResultList.SearchResultItem):
        _name_locator = (By.CSS_SELECTOR, 'h3 > a')
