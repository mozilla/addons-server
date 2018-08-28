from selenium.webdriver.common.by import By

from pages.desktop.base import Base


class DevHubAgreement(Base):

    _accept_button_locator = (By.ID, 'accept-agreement')
    _addon_submission_locator = (By.CLASS_NAME, 'addon-submission-process')
    _distribution_agreement_locator = (By.ID, 'id_distribution_agreement')
    _review_policy_locator = (By.ID, 'id_review_policy')


    def wait_for_page_to_load(self):
        self.wait.until(
            lambda _: self.is_element_displayed(
                *self._addon_submission_locator
            )
        )
        return self

    def accept_agreement(self):
        self.selenium.find_element(
            *self._distribution_agreement_locator
        ).click()
        self.selenium.find_element(*self._review_policy_locator).click()
        self.selenium.find_element(*self._accept_button_locator).click()
