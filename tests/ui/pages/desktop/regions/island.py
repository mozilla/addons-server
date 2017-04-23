# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from selenium.webdriver.common.by import By
from pypom import Page, Region


class Island(Region, Page):

    _title_locator = (By.CSS_SELECTOR, 'h2')
    _addon_locator = (By.CSS_SELECTOR, 'section:nth-child(1) .addon')

    @property
    def title(self):
        return self.root.find_element(*self._title_locator).text

    @property
    def addons(self):
        return [self.AddOn(self, el) for el in
                self.root.find_elements(*self._addon_locator)]

    class AddOn(Region):
        pass
