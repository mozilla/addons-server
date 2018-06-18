import os

from pypom import Region
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as expected
from olympia.files.tests.test_file_viewer import get_file

from pages.desktop.base import Base


class DevHub(Base):

    URL_TEMPLATE = "developers/"

    _root_locator = (By.CLASS_NAME, "DevHub-Navigation")
    _avatar_locator = (By.CLASS_NAME, "avatar")
    _addons_list_locator = (By.CLASS_NAME, "DevHub-MyAddons-list")
    _addons_item_locator = (By.CLASS_NAME, "DevHub-MyAddons-item")
    _continue_sub_btn_locator = (
        By.CSS_SELECTOR,
        ".addon-submission-field > button:nth-child(1)",
    )
    _override_validation_locator = (
        By.CSS_SELECTOR,
        "input#id_admin_override_validation",
    )
    _submit_addon_btn_locator = (
        By.CSS_SELECTOR,
        ".DevHub-MyAddons-item-buttons-submit > .Button:nth-child(1)",
    )
    _whats_new_locator = (By.CLASS_NAME, "DevHub-MyAddons-whatsnew-container")
    _upload_addon_locator = (By.ID, "upload-addon")
    _submit_upload_btn_locator = (By.ID, "submit-upload-file-finish")

    def wait_for_page_to_load(self):
        self.wait.until(lambda _: self.is_element_displayed(*self._whats_new_locator))
        return self

    @property
    def header(self):
        return self.Header(self)

    def login(self, email, password):
        login_page = self.header.click_login()
        login_page.login(email, password)
        self.wait.until(lambda _: self.is_element_displayed(self._avatar_locator))

    @property
    def logged_in(self):
        return self.is_element_displayed(*self.header._sign_in_locator)

    @property
    def addons_list(self):
        els = self.find_elements(*self._addons_item_locator)
        return [self.AddonsListItem(self, el) for el in els]

    def upload_addon(self):
        """Upload an addon via devhub.
        
        This will use the override validation option.
        """
        file_to_upload = "webextension_no_id.xpi"
        file_path = get_file(file_to_upload)
        self.selenium.find_element(*self._submit_addon_btn_locator).click()
        self.selenium.find_element(*self._continue_sub_btn_locator).click()
        upload = self.selenium.find_element(*self._upload_addon_locator)
        upload.send_keys(file_path)
        self.wait.until(
            expected.element_to_be_clickable(self._override_validation_locator)
        )
        self.selenium.find_element(*self._override_validation_locator).click()
        self.selenium.find_element(*self._submit_upload_btn_locator).click()
        from pages.desktop.devhub_submission import DevhubSubmission

        devhub = DevhubSubmission(self.selenium, self.base_url)
        return devhub.wait_for_page_to_load()

    class AddonsListItem(Region):

        _addon_item_name_locator = (By.CLASS_NAME, "DevHub-MyAddons-item-name")
        _addon_edit_link_locator = (By.CLASS_NAME, "DevHub-MyAddons-item-edit")

        @property
        def name(self):
            return self.find_element(*self._addon_item_name_locator).text

        def edit(self):
            self.find_element(*self._addon_edit_link_locator).click()
            from pages.desktop.edit_addon import EditAddon

            edit = EditAddon(self.selenium, self.page.base_url)
            return edit.wait_for_page_to_load()

    class Header(Region):

        _sign_in_locator = (
            By.CSS_SELECTOR,
            ".DevHub-Navigation-Register > a:nth-child(2)",
        )

        def click_login(self):
            self.find_element(*self._sign_in_locator).click()
            from pages.desktop.login import Login

            return Login(self.selenium, self.page.base_url)
