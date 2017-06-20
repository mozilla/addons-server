from pypom import Page, Region
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains


class Base(Page):

    _url = '{base_url}/{locale}'
    _amo_header = (By.CLASS_NAME, 'amo-header')

    def __init__(self, selenium, base_url, locale='en-US', **kwargs):
        super(Base, self).__init__(
            selenium, base_url, locale=locale, timeout=30, **kwargs)

    def wait_for_page_to_load(self):
        self.wait.until(
            lambda _: self.find_element(*self._amo_header).is_displayed())
        return self

    @property
    def header(self):
        return self.Header(self)

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

        _root_locator = (By.CLASS_NAME, 'amo-header')
        _login_locator = (By.CSS_SELECTOR, '#aux-nav .account a:nth-child(2)')
        _logout_locator = (By.CSS_SELECTOR, '.logout > a')
        _user_locator = (By.CSS_SELECTOR, '#aux-nav .account .user')
        _search_button_locator = (By.CSS_SELECTOR, '.search-button')
        _search_textbox_locator = (By.ID, 'search-q')

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
            self.find_element(*self._search_textbox_locator).send_keys(term)
            self.find_element(*self._search_button_locator).click()
            from pages.desktop.search import SearchResultList
            return SearchResultList(self.selenium, self.page.base_url)
