from pypom import Region
from selenium.webdriver.common.by import By

from pages.desktop.base import Base


class Extensions(Base):

    URL_TEMPLATE = 'extensions/'

    _featured_addons_locator = (By.CLASS_NAME, 'FeaturedAddons')
    _top_rated_locator = (By.CLASS_NAME, 'HighlyRatedAddons')
    _title_locator = (By.CLASS_NAME, 'LandingPage-addonType-name')
    _trending_addons_locator = (By.CLASS_NAME, 'TrendingAddons')

    def wait_for_page_to_load(self):
        self.wait.until(
            lambda _: self.is_element_displayed(*self._title_locator))
        element = self.find_element(*self._title_locator)
        return element

    @property
    def extension_header(self):
        return self.ExtensionHeader(self)

    @property
    def featured_extensions(self):
        items = self.find_elements(*self._featured_addons_locator)
        return [self.ExtensionDetail(self, el) for el in items]

    @property
    def categories(self):
        from regions.desktop.categories import Categories
        return Categories(self)

    class ExtensionHeader(Region):
        _root_locator = (By.CLASS_NAME, 'Category')
        _header_locator = (By.CLASS_NAME, 'CategoryHeader')
        _category_name_locator = (By.CLASS_NAME, 'CategoryHeader-name')

        @property
        def name(self):
            return self.find_element(*self._category_name_locator).text

    class ExtensionsList(Region):

        _extensions_locator = (By.CLASS_NAME, 'SearchResult')

        @property
        def list(self):
            items = self.find_elements(*self._extensions_locator)
            return [self.ExtensionDetail(self.page, el) for el in items]

    class ExtensionDetail(Region):

        _extension_name_locator = (By.CLASS_NAME, 'SearchResult-name')

        @property
        def name(self):
            return self.find_element(*self._extension_name_locator).text
