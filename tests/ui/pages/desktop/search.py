from pypom import Page, Region
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as expected


class Search(Page):

    _search_box_locator = (By.CLASS_NAME, 'AutoSearchInput-query')
    _submit_button_locator = (By.CLASS_NAME, 'AutoSearchInput-submit-button')
    _search_filters_sort_locator = (By.ID, 'SearchFilters-Sort')
    _search_filters_type_locator = (By.ID, 'SearchFilters-AddonType')
    _search_filters_os_locator = (By.ID, 'SearchFilters-OperatingSystem')

    def wait_for_page_to_load(self):
        self.wait.until(
            expected.invisibility_of_element_located(
                (By.CLASS_NAME, 'LoadingText')))
        return self

    @property
    def result_list(self):
        return self.SearchResultList(self)

    def filter_by_sort(self, value):
        self.find_element(*self._search_filters_sort_locator).click()
        self.find_element(*self._search_filters_sort_locator).send_keys(value)

    def filter_by_type(self, value):
        self.find_element(*self._search_filters_type_locator).click()
        self.find_element(*self._search_filters_type_locator).send_keys(value)

    def filter_by_os(self, value):
        self.find_element(*self._search_filters_os_locator).click()
        self.find_element(*self._search_filters_os_locator).send_keys(value)

    class SearchResultList(Region):

        _result_locator = (By.CLASS_NAME, 'SearchResult')
        _theme_locator = (By.CLASS_NAME, 'SearchResult--theme')
        _extension_locator = (By.CLASS_NAME, 'SearchResult-name')

        @property
        def extensions(self):
            items = self.find_elements(*self._result_locator)
            return [self.ResultListItems(self, el) for el in items]

        @property
        def themes(self):
            items = self.find_elements(*self._theme_locator)
            return [self.ResultListItems(self, el) for el in items]

        class ResultListItems(Region):

            _rating_locator = (By.CSS_SELECTOR, '.Rating--small')
            _search_item_name_locator = (By.CSS_SELECTOR,
                                         '.SearchResult-contents > h2')
            _users_locator = (By.CLASS_NAME, 'SearchResult-users-text')

            @property
            def name(self):
                return self.find_element(*self._search_item_name_locator).text

            def link(self):
                self.find_element(*self._search_item_name_locator).click()

            @property
            def users(self):
                users = self.find_element(*self._users_locator).text
                return int(
                    users.split()[0].replace(',', '').replace('users', ''))

            @property
            def rating(self):
                """Returns the rating"""
                rating = self.find_element(
                    *self._rating_locator).get_property('title')
                return int(rating.split()[1])
