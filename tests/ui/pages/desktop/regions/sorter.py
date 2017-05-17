from selenium.webdriver.common.by import By
import selenium.webdriver.support.expected_conditions as EC

from pypom import Region


class Sorter(Region):
    """Helper class for sorting."""
    _root_locator = (By.ID, 'sorter')
    _sort_by_type_locator = (By.CSS_SELECTOR, 'ul > li')
    _updating_locator = (By.CSS_SELECTOR, '.updating')

    def sort_by(self, sort):
        """Clicks the sort button for the requested sort-order."""
        els = self.find_elements(*self._sort_by_type_locator)
        next(el for el in els if el.text == sort).click()
        self.wait.until(
            EC.invisibility_of_element_located(self._updating_locator))
