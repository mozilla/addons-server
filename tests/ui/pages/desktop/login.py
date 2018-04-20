from selenium.webdriver.common.by import By

from pages.desktop.base import Base


class Login(Base):

    _email_locator = (By.ID, 'id_username')
    _continue_locator = (By.CSS_SELECTOR, '#normal-login .login-source-button')

    def login(self, email, password):
        from fxapom.pages.sign_in import SignIn
        SignIn(self.selenium).sign_in(email, password)
