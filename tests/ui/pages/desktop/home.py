from pypom import Region
from selenium.webdriver.common.by import By

from pages.desktop.base import Base


class Home(Base):
    """Addons Home page"""

    _extensions_category_locator = (By.CLASS_NAME, 'Home-CuratedCollections')
    _featured_extensions_locator = (By.CLASS_NAME, 'Home-FeaturedExtensions')
    _featured_themes_locator = (By.CLASS_NAME, 'Home-FeaturedThemes')
    _popular_extensions_locator = (By.CLASS_NAME, 'Home-PopularExtensions')
    _popular_themes_locator = (By.CLASS_NAME, 'Home-PopularThemes')
    _themes_category_locator = (By.CLASS_NAME, 'Home-CuratedThemes')
    _toprated_themes_locator = (By.CLASS_NAME, 'Home-TopRatedThemes')

    @property
    def popular_extensions(self):
        el = self.find_element(*self._popular_extensions_locator)
        return self.Extensions(self, el)

    @property
    def featured_extensions(self):
        el = self.find_element(*self._featured_extensions_locator)
        return self.Extensions(self, el)

    @property
    def featured_themes(self):
        el = self.find_element(*self._featured_themes_locator)
        return self.Themes(self, el)

    @property
    def popular_themes(self):
        el = self.find_element(*self._popular_themes_locator)
        return self.Themes(self, el)

    @property
    def toprated_themes(self):
        el = self.find_element(*self._toprated_themes_locator)
        return self.Themes(self, el)

    @property
    def extension_category(self):
        el = self.find_element(*self._extensions_category_locator)
        return self.Category(self, el)

    @property
    def theme_category(self):
        el = self.find_element(*self._themes_category_locator)
        return self.Category(self, el)

    class Category(Region):
        _extensions_locator = (By.CLASS_NAME, 'Home-SubjectShelf-list-item')

        @property
        def list(self):
            items = self.find_elements(*self._extensions_locator)
            return [self.CategoryDetail(self.page, el) for el in items]

        class CategoryDetail(Region):
            _extension_link_locator = (By.CLASS_NAME, 'Home-SubjectShelf-link')
            _extension_name_locator = (
                By.CSS_SELECTOR, '.Home-SubjectShelf-link span')

            @property
            def name(self):
                return self.find_element(*self._extension_name_locator).text

            def click(self):
                self.root.click()
                from pages.desktop.extensions import Extensions
                return Extensions(self.selenium, self.page.base_url)

    class Extensions(Region):
        _browse_all_locator = (By.CSS_SELECTOR, '.Card-footer-link > a')
        _extensions_locator = (By.CLASS_NAME, 'SearchResult')
        _extension_card_locator = (By.CSS_SELECTOR, '.Home-category-li')

        @property
        def list(self):
            items = self.find_elements(*self._extensions_locator)
            return [Home.ExtensionsList(self.page, el) for el in items]

        @property
        def browse_all(self):
            self.find_element(*self._browse_all_locator).click()
            from pages.desktop.search import Search
            search = Search(self.selenium, self.page.base_url)
            return search.wait_for_page_to_load()

    class Themes(Region):
        _browse_all_locator = (By.CSS_SELECTOR, '.Card-footer-link > a')
        _themes_locator = (By.CLASS_NAME, 'SearchResult--theme')
        _theme_card_locator = (By.CSS_SELECTOR, '.Home-category-li')

        @property
        def list(self):
            items = self.find_elements(*self._themes_locator)
            return [Home.ExtensionsList(self.page, el) for el in items]

        @property
        def browse_all(self):
            self.find_element(*self._browse_all_locator).click()
            from pages.desktop.search import Search
            search = Search(self.selenium, self.page.base_url)
            return search.wait_for_page_to_load()

    class ExtensionsList(Region):

        _extension_link_locator = (By.CLASS_NAME, 'SearchResult-link')
        _extension_name_locator = (By.CLASS_NAME, 'SearchResult-name')

        @property
        def name(self):
            return self.find_element(*self._extension_name_locator).text

        def click(self):
            self.find_element(*self._extension_link_locator).click()
            from pages.desktop.extensions import Extensions
            return Extensions(self.selenium, self.page.base_url)
