from pypom import Region
from selenium.webdriver.common.by import By
from olympia.files.tests.test_file_viewer import get_file

from pages.desktop.base import Base


class ManageSubmissions(Base):

    _root_locator = (By.CSS_SELECTOR, '.listing .island')
    _page_title_locator = (By.CSS_SELECTOR, '.primary .hero > h2')
    _addon_submissions_locator = (By.CLASS_NAME, 'addon')

    def wait_for_page_to_load(self):
        self.wait.until(
            lambda _: self.is_element_displayed(*self._page_title_locator))    
        return self

    @property
    def addons(self):
        els = self.find_elements(*self._addon_submissions_locator)
        return [self.AddonDetail(self, el) for el in els]

    class AddonDetail(Region):
    
        _addon_name_locator = (By.CSS_SELECTOR, '.info > h3')

        @property
        def name(self):
            return self.find_element(*self._addon_name_locator).text

