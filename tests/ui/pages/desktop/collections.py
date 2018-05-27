from pypom import Region
from selenium.webdriver.common.by import By

from .base import Base


class Collections(Base):
    """Collections page."""
    _item_locator = (By.CSS_SELECTOR, '.items > div')

    def wait_for_page_to_load(self):
        self.wait.until(lambda _: len(self.collections) > 0 and
                        self.collections[0].name)
        return self

    @property
    def collections(self):
        collections = self.find_elements(*self._item_locator)
        return [self.Collection(self, el) for el in collections]

    class Collection(Region):
        """Represents an individual collection."""
        _name_locator = (By.CSS_SELECTOR, '.info > h3')

        @property
        def name(self):
            return self.find_element(*self._name_locator).text
