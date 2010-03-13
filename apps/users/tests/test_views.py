from django import test
from django.test.client import Client
from django.contrib.auth.models import User

from manage import settings


class UserViewBase(test.TestCase):

    fixtures = ['users/test_backends']

    def setUp(self):
        self.client = Client()
        self.user = User.objects.get(id='4043307')
        self.user_profile = self.user.get_profile()


class TestEdit(UserViewBase):
    pass


class TestLogin(UserViewBase):

    def _get_login_url(self):
        return "/en-US/firefox/users/login"

    def test_credential_fail(self):
        url = self._get_login_url()
        r = self.client.post(url, {'username': '', 'password': ''})
        self.assertFormError(r, 'form', 'username', "This field is required.")
        self.assertFormError(r, 'form', 'password', "This field is required.")

        r = self.client.post(url, {'username': 'jbalogh@mozilla.com',
                                   'password': 'wrongpassword'})
        self.assertFormError(r, 'form', '', ("Please enter a correct username "
                                             "and password. Note that both "
                                             "fields are case-sensitive."))

    def test_credential_success(self):
        url = self._get_login_url()
        r = self.client.post(url, {'username': 'jbalogh@mozilla.com',
                                   'password': 'foo'}, follow=True)
        self.assertContains(r, "Welcome, Jeff")
        self.assertTrue(self.client.session.get_expire_at_browser_close())

        r = self.client.post(url, {'username': 'jbalogh@mozilla.com',
                                   'password': 'foo',
                                   'rememberme': 1}, follow=True)
        self.assertContains(r, "Welcome, Jeff")
        # Subtract 100 to give some breathing room
        age = settings.SESSION_COOKIE_AGE - 100
        assert self.client.session.get_expiry_age() > age

    def test_test_client_login(self):
        """This is just here to make sure Test Client's login() works with
            our custom code."""
        assert not self.client.login(username='jbalogh@mozilla.com',
                                     password='wrong')
        assert self.client.login(username='jbalogh@mozilla.com',
                                 password='foo')


class TestLogout(UserViewBase):

    def test_success(self):
        self.client.login(username='jbalogh@mozilla.com', password='foo')
        r = self.client.get('/', follow=True)
        self.assertContains(r, "Welcome, Jeff")
        r = self.client.get('/users/logout', follow=True)
        self.assertNotContains(r, "Welcome, Jeff")
        self.assertContains(r, "Log in")


class TestProfile(UserViewBase):
    pass
