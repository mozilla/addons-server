from pypom import Region
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as expected


class Search(Region):

    _search_results_locator = (By.CLASS_NAME, 'SearchForm-suggestions-item')

    def wait_for_region_to_load(self):
        self.wait.until(
            expected.invisibility_of_element_located(
                (By.CLASS_NAME, 'LoadingText')))
        return self

    @property
    def result_list(self):
        items = self.find_elements(*self._search_results_locator)
        return [self.SearchResultList(self.page, el) for el in items]

    class SearchResultList(Region):

        _search_item_name_locator = (By.CLASS_NAME, 'Suggestion-name')
        _search_item_link_locator = (By.CLASS_NAME, 'Suggestion')

        @property
        def name(self):
            return self.find_element(*self._search_item_name_locator).text

        def link(self):
            self.find_element(*self._search_item_link_locator).click()
            from pages.desktop.detail import Detail
            return Detail(
                self.selenium, self.page.base_url).wait_for_page_to_load()
