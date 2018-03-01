from pypom import Region
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as expected

from pages.desktop.base import Base


class Categories(Base):

    URL_TEMPLATE = 'extensions/categories/'

    _categories_locator = (By.CLASS_NAME, 'Categories-item')
    _mobile_categories_locator = (By.CLASS_NAME, 'LandingPage-button')

    def wait_for_page_to_load(self):
        self.wait.until(
            expected.invisibility_of_element_located(
                (By.CLASS_NAME, 'LoadingText')))

    @property
    def category_list(self):
        categories = self.find_elements(*self._categories_locator)
        return [self.CategoryItem(self, el) for el in categories]

    class CategoryItem(Region):

        _link_locator = (By.CLASS_NAME, 'Categories-link')

        @property
        def name(self):
            return self.find_element(*self._link_locator).text

        def click(self):
            self.find_element(*self._link_locator).click()
            from pages.desktop.category import Category
            return Category(self.selenium, self.page)
