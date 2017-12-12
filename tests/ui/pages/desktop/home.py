from pypom import Region
from selenium.webdriver.common.by import By

from base import Base


class Home(Base):
    """Addons Home page"""
    @property
    def most_popular(self):
        return self.MostPopular(self)

    @property
    def featured_extensions(self):
        return self.FeaturedExtensions(self)

    @property
    def featured_collections(self):
        return self.FeaturedCollections(self)

    @property
    def featured_themes(self):
        return self.FeaturedThemes(self)

    class MostPopular(Region):
        """Most popular extensions region"""
        _root_locator = (By.ID, 'popular-extensions')
        _extension_locator = (By.CSS_SELECTOR, '.toplist li')

        @property
        def extensions(self):
            extensions = self.find_elements(*self._extension_locator)
            return [self.Extension(self.page, el) for el in extensions]

        class Extension(Region):

            _name_locator = (By.CLASS_NAME, 'name')
            _users_locator = (By.TAG_NAME, 'small')

            def __repr__(self):
                return '{0.name} ({0.users:,} users)'.format(self)

            def click(self):
                """Clicks on the addon."""
                self.find_element(*self._name_locator).click()
                from pages.desktop.details import Details
                return Details(
                    self.selenium, self.page.base_url).wait_for_page_to_load()

            @property
            def name(self):
                """Extension name"""
                return self.find_element(*self._name_locator).text

            @property
            def users(self):
                """Number of users that have downloaded the extension"""
                users_str = self.find_element(*self._users_locator).text
                return int(users_str.split()[0].replace(',', ''))

    class FeaturedExtensions(Region):
        """Featured Extension region"""
        _root_locator = (By.ID, 'featured-extensions')
        _extension_locator = (By.CSS_SELECTOR, 'section > li > .addon')
        _see_all_locator = (By.CSS_SELECTOR, 'h2 > a')

        @property
        def extensions(self):
            extentions = self.find_elements(*self._extension_locator)
            return [self.Extension(self.page, el) for el in extentions]

        class Extension(Region):

            _name_locator = (By.CSS_SELECTOR, 'h3')
            _link_locator = (By.CSS_SELECTOR, '.addon .summary a')

            def click(self):
                """Clicks the addon link"""
                self.find_element(*self._link_locator).click()
                from pages.desktop.details import Details
                return Details(
                    self.selenium, self.page.base_url).wait_for_page_to_load()

            @property
            def name(self):
                return self.find_element(*self._name_locator).text

    class FeaturedThemes(Region):
        """Featured Themes region"""
        _root_locator = (By.ID, 'featured-themes')
        _themes_locator = (By.CSS_SELECTOR, 'li')
        _see_all_link = (By.CLASS_NAME, 'seeall')

        @property
        def themes(self):
            """Represents all themes found within the Featured Themes region.
            """
            themes = self.find_elements(*self._themes_locator)
            return [self.Theme(self, el) for el in themes]

        def see_all(self):
            """Clicks the 'See All' link."""
            self.find_element(*self._see_all_link).click()
            from pages.desktop.themes import Themes
            return Themes(
                self.selenium, self.page.base_url).wait_for_page_to_load()

        class Theme(Region):

            _name_locator = (By.CSS_SELECTOR, 'h3')

            @property
            def name(self):
                """Theme Name"""
                return self.find_element(*self._name_locator).text

    class FeaturedCollections(Region):
        """Featured Collections region"""
        _root_locator = (By.ID, 'featured-collections')
        _items_locator = (By.CSS_SELECTOR, 'li')
        _see_all_link = (By.CSS_SELECTOR, 'h2 a')

        @property
        def collections(self):
            """Represents all Collections found within the Featured Collections
            """
            collections = self.find_elements(*self._items_locator)
            return[self.Collection(self.page, el) for el in collections]

        def see_all(self):
            """Clicks the 'See All' link."""
            self.find_element(*self._see_all_link).click()
            from pages.desktop.collections import Collections
            return Collections(
                self.selenium, self.page.base_url).wait_for_page_to_load()

        class Collection(Region):
            """Individual Collection region"""
            _name_locator = (By.TAG_NAME, 'h3')

            @property
            def name(self):
                """Collection name"""
                return self.find_element(*self._name_locator).text
