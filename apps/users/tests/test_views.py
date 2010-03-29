from django import test
from django.core import mail
from django.contrib.auth.models import User
from django.core.urlresolvers import reverse
from django.test.client import Client

from nose.tools import eq_

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
        self.token, self.hash = EmailResetCode.create(self.user.id,
                                                      'nobody@mozilla.org')

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

    def test_client_login(self):
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


class TestRegistration(UserViewBase):

    def test_confirm(self):
        # User doesn't have a confirmation code
        url = reverse('users.confirm', args=[self.user.id, 'code'])
        r = self.client.get(url, follow=True)
        self.assertContains(r, '<button type="submit">Log in</button>')

        self.user_profile.confirmationcode = "code"
        self.user_profile.save()

        # URL has the wrong confirmation code
        url = reverse('users.confirm', args=[self.user.id, 'blah'])
        r = self.client.get(url, follow=True)
        eq_(r.status_code, 400)

        # URL has the right confirmation code
        url = reverse('users.confirm', args=[self.user.id, 'code'])
        r = self.client.get(url, follow=True)
        self.assertContains(r, 'Successfully verified!')

    def test_confirm_resend(self):
        # User doesn't have a confirmation code
        url = reverse('users.confirm.resend', args=[self.user.id])
        r = self.client.get(url, follow=True)
        self.assertContains(r, '<button type="submit">Log in</button>')

        self.user_profile.confirmationcode = "code"
        self.user_profile.save()

        # URL has the wrong confirmation code
        url = reverse('users.confirm.resend', args=[self.user.id])
        r = self.client.get(url, follow=True)
        self.assertContains(r, 'An email has been sent to your address')
