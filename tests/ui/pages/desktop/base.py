from pypom import Page, Region
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains


class Base(Page):

    _url = '{base_url}/{locale}'
    _amo_header = (By.CLASS_NAME, 'Header-title')

    def __init__(self, selenium, base_url, locale='en-US', **kwargs):
        super(Base, self).__init__(
            selenium, base_url, locale=locale, timeout=30, **kwargs)

    def wait_for_page_to_load(self):
        self.wait.until(
            lambda _: self.find_element(*self._amo_header).is_displayed())
        return self

    @property
    def header(self):
        return Header(self)

    @property
    def logged_in(self):
        """Returns True if a user is logged in"""
        return self.is_element_displayed(*self.header._user_locator)

    def search_for(self, term):
        return self.header.search_for(term)

    def login(self, email, password):
        login_page = self.header.click_login()
        login_page.login(email, password)

    def logout(self):
        self.header.click_logout()


class Header(Region):

    _root_locator = (By.CLASS_NAME, 'Header')
    _header_title_locator = (By.CLASS_NAME, 'Header-title')
    _explore_locator = (By.CSS_SELECTOR, '.SectionLinks > li:nth-child(1) \
                        > a:nth-child(1)')
    _firefox_logo_locator = (By.CLASS_NAME, 'Header-title')
    _extensions_locator = (By.CSS_SELECTOR, '.SectionLinks \
                           > li:nth-child(2) > a:nth-child(1)')
    _login_locator = (By.CSS_SELECTOR,
                      '.Button--action .Header-authenticate-button')
    _logout_locator = (By.CSS_SELECTOR, '.DropdownMenu-items .Header-logout-button')
    _themes_locator = (By.CSS_SELECTOR, '.SectionLinks > li:nth-child(3) > \
                       a:nth-child(1)')
    _user_locator = (By.CSS_SELECTOR,
                     '.Header-user-and-external-links .DropdownMenu-button')
    _search_textbox_locator = (By.CLASS_NAME, 'AutoSearchInput-query')

    def click_explore(self):
        self.find_element(*self._firefox_logo_locator).click()

    def click_extensions(self):
        self.find_element(*self._extensions_locator).click()
        from pages.desktop.extensions import Extensions
        return Extensions(
            self.selenium, self.page.base_url).wait_for_page_to_load()

    def click_themes(self):
        self.find_element(*self._themes_locator).click()
        from pages.desktop.themes import Themes
        return Themes(
            self.selenium, self.page.base_url).wait_for_page_to_load()

    def click_login(self):
        self.find_element(*self._login_locator).click()
        from pages.desktop.login import Login
        return Login(self.selenium, self.page.base_url, timeout=30)

    def click_logout(self):
        user = self.find_element(*self._user_locator)
        logout = self.find_element(*self._logout_locator)
        action = ActionChains(self.selenium)
        action.move_to_element(user)
        action.move_to_element(logout)
        action.click()
        action.perform()
        self.wait.until(lambda s: self.is_element_displayed(
            *self._login_locator))

    def search_for(self, term):
        textbox = self.find_element(*self._search_textbox_locator)
        textbox.click()
        textbox.send_keys(term)
        # Send 'enter' since the mobile page does not have a submit button
        textbox.send_keys(u'\ue007')
        from pages.desktop.search import Search
        return Search(self.selenium, self.page).wait_for_page_to_load()
