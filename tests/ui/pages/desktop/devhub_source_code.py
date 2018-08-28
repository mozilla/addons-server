from selenium.webdriver.common.by import By

from pages.desktop.base import Base


class DevHubSource(Base):

    _no_souce_code_locator = (By.ID, "id_has_source_1")
    _submit_source_locator = (By.ID, 'submit-source')
    _submission_button_locator = (
        By.CSS_SELECTOR, ".submission-buttons > button:nth-child(2)"
    )

    def wait_for_page_to_load(self):
        self.wait.until(
            lambda _: self.is_element_displayed(
                    *self._submit_source_locator
            )
        )
        return self

    def dont_submit_source_code(self):
        self.selenium.find_element(*self._no_souce_code_locator).click()
        self.selenium.find_element(*self._submission_button_locator).click()
