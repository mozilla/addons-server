from selenium.webdriver.common.by import By

from pages.desktop.base import Base


class EditTheme(Base):
    """Edit page for a specific addon.

    This page is the edit page for a theme that has already
    been approved.
    """

    _root_locator = (By.CLASS_NAME, 'section')
    _edit_addon_navbar_locator = (By.CLASS_NAME, 'edit-addon-nav')

    def wait_for_page_to_load(self):
        self.wait.until(
            lambda _: self.is_element_displayed(
                *self._edit_addon_navbar_locator))
        return self

    @property
    def name(self):
        pass
