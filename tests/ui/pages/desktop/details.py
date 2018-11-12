from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as expected

from pages.desktop.base import Base


class Detail(Base):

    _root_locator = (By.CLASS_NAME, 'Addon-extension')
    _addon_name_locator = (By.CLASS_NAME, 'AddonTitle')
    _compatible_locator = (By.CSS_SELECTOR, '.AddonCompatibilityError')
    _install_button_locator = (By.CLASS_NAME, 'AMInstallButton-button')

    def wait_for_page_to_load(self):
        self.wait.until(
            expected.invisibility_of_element_located(
                (By.CLASS_NAME, 'LoadingText')))
        return self

    @property
    def name(self):
        return self.find_element(*self._addon_name_locator).text

    @property
    def is_compatible(self):
        return not self.is_element_displayed(*self._compatible_locator)

    def install(self):
        self.find_element(*self._install_button_locator).click()
