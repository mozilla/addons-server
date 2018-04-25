from pypom import Region
from selenium.webdriver.common.by import By


class Categories(Region):

    _root_locator = (By.CLASS_NAME, 'Categories')
    _categories_locator = (By.CLASS_NAME, 'Categories-item')
    _mobile_categories_locator = (By.CLASS_NAME, 'LandingPage-button')

    @property
    def category_list(self):
        items = self.find_elements(*self._categories_locator)
        return [self.CategoryList(self, el) for el in items]

    class CategoryList(Region):
        _name_locator = (By.CLASS_NAME, 'Categories-link')

        @property
        def name(self):
            return self.find_element(*self._name_locator).text

        def click(self):
            self.root.click()
            from pages.desktop.category import Category
            return Category(self.selenium, self.page)
