from pypom import Page, Region
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException
from selenium.common.exceptions import ElementNotVisibleException
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.common.action_chains import ActionChains

import time


class Base(Page):

    _url = '{base_url}/{locale}'

    _amo_logo_locator = (By.CSS_SELECTOR, ".site-title")
    _amo_logo_link_locator = (By.CSS_SELECTOR, ".site-title a")
    _amo_logo_image_locator = (By.CSS_SELECTOR, ".site-title img")

    def __init__(self, selenium, base_url, locale='en-US', **kwargs):
        super(Base, self).__init__(selenium, base_url, locale=locale, **kwargs)

    @property
    def header(self):
        return self.Header(self)

    @property
    def logged_in(self):
        """Returns True if a user is logged in"""
        return self.is_element_displayed(*self.header._user_locator)

    def login(self, email, password):
        login_page = self.header.click_login()
        login_page.login(email, password)

    def logout(self):
        self.header.click_logout()

    @property
    def amo_logo_title(self):
        return self.selenium.find_element(*self._amo_logo_link_locator).get_attribute('title')

    def get_url_current_page(self):
        time.sleep(1)
        # This is a hack until selenium actually learns patience
        return self.selenium.current_url

    @property
    def is_the_current_page(self):
        WebDriverWait(self.selenium, self.timeout).until(
            lambda s: s.title == self.selenium.title)
        return True

    class Header(Region):

        # other applications
        _other_applications_locator = (By.ID, "other-apps")
        _other_applications_menu_locator = (By.CLASS_NAME, "other-apps")

        _root_locator = (By.CLASS_NAME, 'amo-header')
        _login_locator = (By.CSS_SELECTOR, '#aux-nav .account a:nth-child(2)')
        _logout_locator = (By.CSS_SELECTOR, '.logout > a')
        _user_locator = (By.CSS_SELECTOR, '#aux-nav .account .user')

        _site_navigation_menus_locator = (By.CSS_SELECTOR, "#site-nav > ul > li")
        _site_navigation_min_number_menus = 4
        _complete_themes_menu_locator = (By.CSS_SELECTOR, '#site-nav div > a.complete-themes > b')

        def is_other_application_visible(self, other_app):
            hover_locator = self.selenium.find_element(*self._other_applications_locator)
            app_locator = (By.CSS_SELECTOR, "#app-%s" % other_app.lower())
            ActionChains(self.selenium).move_to_element(hover_locator).perform()
            return self.is_element_visible(*app_locator)

        def click_other_application(self, other_app):
            hover_locator = self.selenium.find_element(*self._other_applications_locator)
            app_locator = self.selenium.find_element(By.CSS_SELECTOR,
                                                     "#app-%s > a" % other_app.lower())
            ActionChains(self.selenium).move_to_element(hover_locator).\
                move_to_element(app_locator).\
                click().perform()

        def site_navigation_menu(self, value):
            # used to access one specific menu
            for menu in self.site_navigation_menus:
                if menu.name.encode('utf-8').lower() == value.lower():
                    return menu
            raise Exception("Menu not found: '%s'. Menus: %s" % (value, [menu.name for menu in self.site_navigation_menus]))

        def is_element_visible(self, *locator):
            try:
                return self.selenium.find_element(*locator).is_displayed()
            except (NoSuchElementException, ElementNotVisibleException):
                return False

        @property
        def site_navigation_menus(self):
            # returns a list containing all the site navigation menus
            WebDriverWait(self.selenium, self.timeout).until(lambda s: len(s.find_elements(*self._site_navigation_menus_locator)) >= self._site_navigation_min_number_menus)
            from pages.desktop.regions.header_menu import HeaderMenu
            return [HeaderMenu(self.selenium, self.page.base_url, web_element) for web_element in self.selenium.find_elements(*self._site_navigation_menus_locator)]

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
