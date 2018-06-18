from selenium.webdriver.common.by import By

from pages.desktop.base import Base


class DevhubSubmission(Base):

    _name_locator = (By.ID, "id_name")
    _summary_locator = (By.ID, "id_summary_0")
    _license_btn_locator = (By.ID, "id_license-builtin_0")
    _submit_btn_locator = (By.CSS_SELECTOR, ".submission-buttons > button:nth-child(2)")
    _appearance_categories_locator = (By.ID, "id_form-0-categories_0")
    _bookmarks_categories_locator = (By.ID, "id_form-0-categories_1")
    _edit_submission_btn_locator = (
        By.CSS_SELECTOR,
        ".addon-submission-process > p:nth-child(7) > a:nth-child(1)",
    )

    def wait_for_page_to_load(self):
        self.wait.until(lambda _: self.is_element_displayed(*self._name_locator))
        return self

    def fill_addon_submission_form(self):
        """Fill addon submission form."""
        self.find_element(*self._name_locator).send_keys("-ui-test-addon-2")
        self.find_element(*self._summary_locator).send_keys("Words go here")
        self.find_element(*self._appearance_categories_locator).click()
        self.find_element(*self._bookmarks_categories_locator).click()
        self.find_element(*self._license_btn_locator).click()
        self.find_element(*self._submit_btn_locator).click()
        self.selenium.find_element(*self._edit_submission_btn_locator).click()
        from pages.desktop.manage_submissions import ManageSubmissions

        subs = ManageSubmissions(self.selenium, self.base_url)
        return subs.wait_for_page_to_load()
