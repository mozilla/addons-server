from selenium.webdriver.common.by import By

from pages.desktop.base import Base


class Themes(Base):

    URL_TEMPLATE = 'themes/'

    _browse_all_locator = (By.CSS_SELECTOR, '.Card-footer-link > a')
    _title_locator = (By.CLASS_NAME, 'LandingPage-addonType-name')

    def wait_for_page_to_load(self):
        self.wait.until(
            lambda _: self.is_element_displayed(*self._title_locator))
        return self.find_element(*self._title_locator)

    @property
    def browse_all(self):
        self.find_element(*self._browse_all_locator).click()
