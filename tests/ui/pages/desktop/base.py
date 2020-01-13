from pypom import Page, Region
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys


class Base(Page):

    _url = '{base_url}/{locale}'
    _amo_header = (By.CLASS_NAME, 'Header')

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
    def footer(self):
        return Footer(self)

    @property
    def logged_in(self):
        """Returns True if a user is logged in"""
        return self.is_element_displayed(*self.header._user_locator)

    @property
    def search(self):
        return self.header.SearchBox(self)

    def login(self, email, password):
        login_page = self.header.click_login()
        login_page.login(email, password)
        self.selenium.get(self.base_url)
        self.wait.until(lambda _: self.logged_in)

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
    _login_locator = (By.CLASS_NAME, 'Header-authenticate-button')
    _logout_locator = (
        By.CSS_SELECTOR, '.DropdownMenu-items .Header-logout-button')
    _more_dropdown_locator = (
        By.CSS_SELECTOR,
        '.Header-SectionLinks .SectionLinks-dropdown')
    _more_dropdown_link_locator = (By.CSS_SELECTOR, '.DropdownMenuItem a')
    _themes_locator = (By.CSS_SELECTOR, '.SectionLinks > li:nth-child(3) > \
                       a:nth-child(1)')
    _user_locator = (
        By.CSS_SELECTOR,
        '.Header-user-and-external-links .DropdownMenu-button-text')

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

    def click_title(self):
        self.find_element(*self._header_title_locator).click()

        from pages.desktop.home import Home
        return Home(self.selenium, self.page.base_url).wait_for_page_to_load()

    def click_login(self):
        self.find_element(*self._login_locator).click()
        from pages.desktop.login import Login
        return Login(self.selenium, self.page.base_url)

    def click_logout(self):
        user = self.find_element(*self._user_locator)
        logout = self.find_element(*self._logout_locator)
        action = ActionChains(self.selenium)
        action.move_to_element(user)
        action.click()
        action.pause(2)
        action.move_to_element(logout)
        action.pause(2)
        action.click(logout)
        action.perform()
        self.wait.until(lambda s: self.is_element_displayed(
            *self._login_locator))

    def more_menu(self, item=None):
        menu = self.find_element(*self._more_dropdown_locator)
        links = menu.find_elements(*self._more_dropdown_link_locator)
        # Create an action chain clicking on the elements of the dropdown more
        # menu. It pauses between each action to account for lag.
        action = ActionChains(self.selenium)
        action.move_to_element(menu)
        action.click()
        action.pause(2)
        action.move_to_element(links[item])
        action.click()
        action.pause(2)
        action.perform()

    class SearchBox(Region):

        _root_locator = (By.CLASS_NAME, 'AutoSearchInput')
        _search_suggestions_list_locator = (
            By.CLASS_NAME, 'AutoSearchInput-suggestions-list')
        _search_suggestions_item_locator = (
            By.CLASS_NAME, 'AutoSearchInput-suggestions-item')
        _search_textbox_locator = (By.CLASS_NAME, 'AutoSearchInput-query')

        def search_for(self, term, execute=True):
            textbox = self.find_element(*self._search_textbox_locator)
            textbox.click()
            textbox.send_keys(term)
            # Send 'enter' since the mobile page does not have a submit button
            if execute:
                textbox.send_keys(Keys.ENTER)
                from pages.desktop.search import Search
                return Search(self.selenium, self.page).wait_for_page_to_load()
            return self.search_suggestions

        @property
        def search_suggestions(self):
            self.wait.until(
                lambda _: self.is_element_displayed(
                    *self._search_suggestions_list_locator)
            )
            el_list = self.find_element(*self._search_suggestions_list_locator)
            items = el_list.find_elements(
                *self._search_suggestions_item_locator)
            return [self.SearchSuggestionItem(self.page, el) for el in items]

        class SearchSuggestionItem(Region):

            _item_name = (By.CLASS_NAME, 'SearchSuggestion-name')

            @property
            def name(self):
                return self.find_element(*self._item_name).text

            @property
            def select(self):
                self.root.click()
                from pages.desktop.details import Detail
                return Detail(self.selenium, self.page).wait_for_page_to_load()


class Footer(Region):

    _root_locator = (By.CSS_SELECTOR, '.Footer-wrapper')
    _footer_amo_links = (By.CSS_SELECTOR, '.Footer-amo-links')
    _footer_firefox_links = (By.CSS_SELECTOR, '.Footer-firefox-links')
    _footer_links = (By.CSS_SELECTOR, '.Footer-links li a')

    @property
    def addon_links(self):
        header = self.find_element(*self._footer_amo_links)
        return header.find_elements(*self._footer_links)

    @property
    def firefox_links(self):
        header = self.find_element(*self._footer_firefox_links)
        return header.find_elements(*self._footer_links)
