from pypom import Region
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as expected

from pages.desktop.base import Base


class Category(Base):

    _root_locator = (By.CLASS_NAME, 'Category')
    _category_header_locator = (By.CLASS_NAME, 'CategoryHeader')

    def wait_for_page_to_load(self):
        self.wait.until(
            expected.invisibility_of_element_located(
                (By.CLASS_NAME, 'LoadingText')))
        return self

    @property
    def header(self):
        return self.Header(self)

    class Header(Region):

        _category_name_locator = (By.CLASS_NAME, 'CategoryHeader-name')

        @property
        def name(self):
            return self.find_element(*self._category_name_locator).text
