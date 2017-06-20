from pypom import Region
from selenium.webdriver.common.by import By

from base import Base


class Themes(Base):
    """Themes page."""
    def wait_for_page_to_load(self):
        self.wait.until(lambda _: self.featured.themes[0].name)
        return self

    @property
    def featured(self):
        return self.Featured(self)

    class Featured(Region):
        """Represents the Featured region on the themes page."""
        _root_locator = (By.CLASS_NAME, 'personas-featured')
        _theme_locator = (By.CSS_SELECTOR, '.persona')

        @property
        def themes(self):
            theme = self.find_elements(*self._theme_locator)
            return [Themes.Theme(self.page, el) for el in theme]

    class Theme(Region):
        """Represents an individual theme."""
        _name_locator = (By.CSS_SELECTOR, 'h3')

        @property
        def name(self):
            return self.find_element(*self._name_locator).text
