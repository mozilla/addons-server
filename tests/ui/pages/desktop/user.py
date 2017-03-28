# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import re

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import NoSuchElementException
from selenium.common.exceptions import NoSuchAttributeException

from pypom import Page, Region
from pages.desktop.base import Base


class Login(Base):

    _page_title = 'User Login :: Add-ons for Firefox'

    _email_locator = (By.ID, 'id_username')
    _continue_button_locator = (By.CSS_SELECTOR, '#normal-login .login-source-button')

    def login(self, email, password):
        from fxapom.pages.sign_in import SignIn
        SignIn(self.selenium).sign_in(email, password)


class ViewProfile(Base):

    _about_locator = (By.CSS_SELECTOR, "div.island > section.primary > h2")
    _email_locator = (By.CSS_SELECTOR, 'a.email')

    def __init__(self, base_url, selenium):
        Base.__init__(self, base_url, selenium)
        WebDriverWait(self.selenium, self.timeout).until(
            lambda s: (s.find_element(*self._about_locator)).is_displayed())

    @property
    def is_the_current_page(self):
        WebDriverWait(self.selenium, self.timeout).until(
            lambda s: re.match('User Info for .+ :: Add-ons for Firefox', s.title) is not None)
        return True

    @property
    def about_me(self):
        return self.selenium.find_element(*self._about_locator).text

    @property
    def is_email_field_present(self):
        return self.is_element_present(*self._email_locator)

    @property
    def email_value(self):
        email = self.selenium.find_element(*self._email_locator).text
        return email[::-1]


class User(Base):

        _username_locator = (By.CSS_SELECTOR, ".fn.n")

        @property
        def username(self):
            self.wait.until(
                lambda _: self.selenium.find_element(
                    *self._username_locator).text)
            return self.selenium.find_element(*self._username_locator).text


class EditProfile(Base):

    _page_title = 'Account Settings :: Add-ons for Firefox'

    _account_locator = (By.CSS_SELECTOR, "#acct-account > legend")
    _username_locator = (By.ID, 'id_username')
    _profile_locator = (By.CSS_SELECTOR, "#profile-personal > legend")
    _details_locator = (By.CSS_SELECTOR, "#profile-detail > legend")
    _notification_locator = (By.CSS_SELECTOR, "#acct-notify > legend")
    _hide_email_checkbox = (By.ID, 'id_emailhidden')
    _update_account_locator = (By.CSS_SELECTOR, 'p.footer-submit > button.prominent')
    _profile_fields_locator = (By.CSS_SELECTOR, '#profile-personal > ol.formfields li')
    _update_message_locator = (By.CSS_SELECTOR, 'div.notification-box > h2')

    def __init__(self, base_url, selenium):
        Base.__init__(self, base_url, selenium)
        WebDriverWait(self.selenium, self.timeout).until(
            lambda s: (s.find_element(*self._account_locator)).is_displayed())

    @property
    def account_header_text(self):
        return self.selenium.find_element(*self._account_locator).text

    def type_username(self, value):
        self.selenium.find_element(*self._username_locator).send_keys(value)

    @property
    def profile_header_text(self):
        return self.selenium.find_element(*self._profile_locator).text

    @property
    def details_header_text(self):
        return self.selenium.find_element(*self._details_locator).text

    @property
    def notification_header_text(self):
        return self.selenium.find_element(*self._notification_locator).text

    def click_update_account(self):
        self.selenium.find_element(*self._update_account_locator).click()
        WebDriverWait(self.selenium, self.timeout).until(lambda s: self.update_message == "Profile Updated")

    def change_hide_email_state(self):
        self.selenium.find_element(*self._hide_email_checkbox).click()

    @property
    def profile_fields(self):
        return [self.ProfileSection(self.base_url, self.selenium, web_element)
                for web_element in self.selenium.find_elements(*self._profile_fields_locator)]

    @property
    def update_message(self):
        return self.selenium.find_element(*self._update_message_locator).text

    class ProfileSection(Page):

        _input_field_locator = (By.CSS_SELECTOR, ' input')
        _field_name = (By.CSS_SELECTOR, ' label')

        def __init__(self, base_url, selenium, element):
            Page.__init__(self, base_url, selenium)
            self._root_element = element

        @property
        def field_value(self):
            try:
                return self._root_element.find_element(*self._input_field_locator).get_attribute('value')
            except NoSuchAttributeException:
                return ' '

        @property
        def input_type(self):
            try:
                return self._root_element.find_element(*self._input_field_locator).get_attribute('type')
            except (NoSuchElementException, NoSuchAttributeException):
                return ' '

        @property
        def is_field_editable(self):
            return self.input_type == 'text' or self.input_type == 'url'

        @property
        def field_name(self):
            return self._root_element.find_element(*self._field_name).text

        def type_value(self, value):
            if self.field_name == 'Homepage' and value != '':
                self._root_element.find_element(*self._input_field_locator).send_keys('http://example.com/' + value)
            else:
                self._root_element.find_element(*self._input_field_locator).send_keys(value)

        def clear_field(self):
            self._root_element.find_element(*self._input_field_locator).clear()


class MyCollections(Base):

    _header_locator = (By.CSS_SELECTOR, '.primary > header > h2')
    _my_favorites_locator = (By.CSS_SELECTOR, '.other-categories ul:nth-child(3) li:nth-child(3)')

    @property
    def my_collections_header_text(self):
        return self.selenium.find_element(*self._header_locator).text

    def click_my_favorites(self):
        self.selenium.find_element(*self._my_favorites_locator).click()
        return MyFavorites(self.base_url, self.selenium)


class MyFavorites(Base):

    _page_title = 'My Favorite Add-ons :: Collections :: Add-ons for Firefox'
    _header_locator = (By.CSS_SELECTOR, "h2.collection > span")

    _edit_collection_locator = (By.CLASS_NAME, 'edit')
    _addon_locator = (By.CSS_SELECTOR, '.separated-listing .item')
    _add_on_name_locator = (By.CSS_SELECTOR, '.item h3 a')

    def edit_collection(self):
        self.selenium.find_element(*self._edit_collection_locator).click()
        return EditCollection(self.base_url, self.selenium)

    @property
    def my_favorites_header_text(self):
        return self.selenium.find_element(*self._header_locator).text

    @property
    def add_ons(self):
        return [self.AddOn(self.base_url, self.selenium, el) for el in
                self.selenium.find_elements(*self._addon_locator)]

    class AddOn(Region):
        _name_locator = (By.CSS_SELECTOR, '.item a')
        _favorite_locator = (By.CSS_SELECTOR, 'a.favorite')

        @property
        def name(self):
            return self.root.find_element(*self._name_locator).text

        @property
        def favorite(self):
            is_favorite = self.selenium.find_element(*self._favorite_locator).get_attribute('title')
            return 'Remove from favorites' in is_favorite


class EditCollection(Base):

    _title_locator = (By.CSS_SELECTOR, 'header > h2')

    _name_field_locator = (By.ID, 'addon-ac')
    _search_list_locator = (By.CSS_SELECTOR, '#ui-id-1')
    _add_to_collection_button_locator = (By.ID, 'addon-select')
    _addons_tab_locator = (By.CSS_SELECTOR, ".tab-nav li:nth-child(2) a")
    _save_addon_changes_locator = (By.CSS_SELECTOR, '#addons-edit input[type=submit]')

    @property
    def _page_title(self):
        return "%s :: Add-ons for Firefox" % self.title

    @property
    def title(self):
        return self.selenium.find_element(*self._title_locator).text

    def click_add_ons_tab(self):
        self.selenium.find_element(*self._addons_tab_locator).click()

    def include_add_on(self, name):
        item_locator = (By.CSS_SELECTOR, " li:nth-child(1) a")
        self.selenium.find_element(*self._name_field_locator).send_keys(name)
        self.selenium.find_element(*self._search_list_locator).find_element(*item_locator).click()
        self.selenium.find_element(*self._add_to_collection_button_locator).click()

    def click_add_ons_save_changes(self):
        self.selenium.find_element(*self._save_addon_changes_locator).click()
