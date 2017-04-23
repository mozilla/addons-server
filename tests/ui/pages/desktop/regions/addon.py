# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from selenium.webdriver.common.by import By

from pypom import Region


class AddOn(Region):
    """Add-on hovercard region"""

    _name_locator = (By.CSS_SELECTOR, '.summary h3')

    @property
    def name(self):
        return self.root.find_element(*self._name_locator).text

    def click(self):
        self.root.find_element(*self._name_locator).click()
        from pages.desktop.details import Details
        return Details(self.base_url, self.selenium)
