from pypom import Region
from selenium.webdriver.common.by import By

from base import Base


class Details(Base):
    """Details page."""
    def wait_for_page_to_load(self):
        self.wait.until(lambda _: self.description_header.name)
        return self

    @property
    def description_header(self):
        return self.DescriptionHeader(self)

    class DescriptionHeader(Region):
        """Represents the header of the detail page."""
        _root_locator = (By.CLASS_NAME, 'addon-description-header')
        _install_button_locator = (By.CLASS_NAME, 'add')
        _name_locator = (By.TAG_NAME, 'h1')

        @property
        def name(self):
            return self.find_element(*self._name_locator).text

        @property
        def install_button(self):
            return self.find_element(*self._install_button_locator)
