from pypom import Region
from selenium.webdriver.common.by import By

from base import Base


class SearchResultList(Base):
    """Search page"""
    _results_locator = (By.CSS_SELECTOR, 'div.items div.item.addon')
    _search_text_locator = (By.CSS_SELECTOR, '.primary > h1')

    def wait_for_page_to_load(self):
        self.wait.until(lambda _: self.find_element(
            self._search_text_locator).is_displayed())
        return self

    @property
    def results(self):
        """List of results"""
        elements = self.selenium.find_elements(*self._results_locator)
        return [self.SearchResultItem(self, el) for el in elements]

    def sort_by(self, category, attribute):
        from pages.desktop.regions.sorter import Sorter
        Sorter(self).sort_by(category)

    class SearchResultItem(Region):
        """Represents individual results on the search page."""
        _name_locator = (By.CSS_SELECTOR, 'h3 > a')
        _rating_locator = (By.CSS_SELECTOR, '.rating .stars')
        _users_sort_locator = (By.CSS_SELECTOR, '.vitals .adu')

        @property
        def name(self):
            """Extension Name"""
            return self.find_element(*self._name_locator).text

        @property
        def users(self):
            """Extensions users"""
            number = self.find_element(*self._users_sort_locator).text
            if 'downloads' in number:
                raise AssertionError('Found weekly downloads instead')
            return int(number.split()[0].replace(',', ''))

        @property
        def rating(self):
            """Returns the rating"""
            rating = self.find_element(*self._rating_locator).text
            return int(rating.split()[1])
