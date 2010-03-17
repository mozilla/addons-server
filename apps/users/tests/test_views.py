from django import test
from django.core import mail
from django.contrib.auth.models import User
from django.core.urlresolvers import reverse
from django.test.client import Client

from nose.tools import eq_

from manage import settings

from users.utils import EmailResetCode


class UserViewBase(test.TestCase):

    fixtures = ['users/test_backends']

    def setUp(self):
        self.client = Client()
        self.user = User.objects.get(id='4043307')
        self.user_profile = self.user.get_profile()


class TestEdit(UserViewBase):

    def test_email_change_mail_sent(self):
        self.client.login(username='jbalogh@mozilla.com', password='foo')

        data = {'nickname': 'jbalogh',
                'email': 'jbalogh.changed@mozilla.com',
                'firstname': 'DJ SurfNTurf',
                'lastname': 'Balogh', }

        r = self.client.post('/en-US/firefox/users/edit', data)
        self.assertContains(r, "An email has been sent to %s" % data['email'])

        # The email shouldn't change until they confirm, but the name should
        u = User.objects.get(id='4043307').get_profile()
        self.assertEquals(u.firstname, 'DJ SurfNTurf')
        self.assertEquals(u.email, 'jbalogh@mozilla.com')

        eq_(len(mail.outbox), 1)
        assert mail.outbox[0].subject.find('Please confirm your email') == 0
        assert mail.outbox[0].body.find('%s/emailchange/' % self.user.id) > 0


class TestEmailChange(UserViewBase):

    def setUp(self):
        super(TestEmailChange, self).setUp()
        self.token, self.hash = EmailResetCode.create(self.user.id, 'nobody@mozilla.org')

    def test_fail(self):
        # Completely invalid user, valid code
        url = reverse('users.emailchange', args=[1234, self.token, self.hash])
        r = self.client.get(url, follow=True)
        eq_(r.status_code, 404)

        # User is in the system, but not attached to this code, valid code
        url = reverse('users.emailchange', args=[9945, self.token, self.hash])
        r = self.client.get(url, follow=True)
        eq_(r.status_code, 400)

        # Valid user, invalid code
        url = reverse('users.emailchange', args=[self.user.id, self.token,
                                                 self.hash[:-3]])
        r = self.client.get(url, follow=True)
        eq_(r.status_code, 400)

    def test_success(self):
        self.assertEqual(self.user_profile.email, 'jbalogh@mozilla.com')
        url = reverse('users.emailchange', args=[self.user.id, self.token,
                                                 self.hash])
        r = self.client.get(url, follow=True)
        eq_(r.status_code, 200)
        u = User.objects.get(id=self.user.id).get_profile()
        self.assertEqual(u.email, 'nobody@mozilla.org')


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
