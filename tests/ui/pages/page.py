# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
'''
Created on Jun 21, 2010

'''
from selenium.webdriver.support.wait import WebDriverWait
from selenium.common.exceptions import NoSuchElementException
from selenium.common.exceptions import ElementNotVisibleException


class Page(object):
    """
    Base class for all Pages.
    """

    def __init__(self, base_url, selenium, **kwargs):
        """
        Constructor
        """
        self.base_url = base_url
        self.selenium = selenium
        self.timeout = 10
        self.wait = WebDriverWait(self.selenium, self.timeout)
        self.kwargs = kwargs

    def open(self):
        self.selenium.get(self.url)
        self.wait_for_page_to_load()
        return self

    @property
    def url(self):
        if self._url is not None:
            return self._url.format(base_url=self.base_url, **self.kwargs)
        return self.base_url

    def wait_for_page_to_load(self):
        self.wait.until(lambda s: self.url in s.current_url)
        return self

    def get_url(self, url):
        self.selenium.get(url)

    @property
    def verify_current_page(self):
        WebDriverWait(self.selenium, self.timeout).until(
            lambda s: s.title == self._page_title,
            "Expected page title: %s. Actual page title: %s" % (self._page_title, self.selenium.title))
        return True

    def get_url_current_page(self):
        url = self.selenium.current_url
        self.wait.until(lambda s: self.selenium.current_url != url)
        return self.selenium.current_url

    def is_element_present(self, *locator):
        self.selenium.implicitly_wait(0)
        try:
            self.selenium.find_element(*locator)
            return True
        except NoSuchElementException:
            return False
        finally:
            # set back to where you once belonged
            self.selenium.implicitly_wait(self.timeout)

    def is_element_visible(self, *locator):
        try:
            return self.selenium.find_element(*locator).is_displayed()
        except (NoSuchElementException, ElementNotVisibleException):
            return False


class PageRegion(object):

    _root_locator = None

    def __init__(self, base_url, selenium, root=None):
        self.base_url = base_url
        self.selenium = selenium
        self.timeout = 10
        self.root_element = root

    @property
    def root(self):
        if self.root_element is None and self._root_locator is not None:
            self.root_element = self.selenium.find_element(*self._root_locator)
        return self.root_element
