from selenium.webdriver.common.by import By

from pages.desktop.base import Base


class EditAddon(Base):
    """Edit page for a specific addon.

    This page is the edit page for an addon that has already
    been approved.
    """

    _root_locator = (By.CLASS_NAME, "section")
    _edit_addon_navbar_locator = (By.CLASS_NAME, "edit-addon-nav")
    _addon_name_locator = (
        By.CSS_SELECTOR,
        "#main-wrapper > div:nth-child(1) >\
                           header:nth-child(2) > h2:nth-child(2)",
    )

    def wait_for_page_to_load(self):
        self.wait.until(
            lambda _:
                self.is_element_displayed(*self._addon_name_locator)
        )
        return self

    @property
    def name(self):
        return self.find_element(*self._addon_name_locator).text
