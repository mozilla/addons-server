from django import test
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.test.client import Client
from django.utils.http import int_to_base36

from nose.tools import eq_


class UserFormBase(test.TestCase):

    fixtures = ['users/test_backends']

    def setUp(self):
        self.client = Client()
        self.user = User.objects.get(id='4043307')
        self.user_profile = self.user.get_profile()
        self.uidb36 = int_to_base36(self.user.id)
        self.token = default_token_generator.make_token(self.user)


class TestSetPasswordForm(UserFormBase):

    def _get_reset_url(self):
        return "/en-US/firefox/users/pwreset/%s/%s" % (self.uidb36, self.token)

    def test_url_fail(self):
        r = self.client.get('/users/pwreset/junk/', follow=True)
        eq_(r.status_code, 404)

        r = self.client.get('/en-US/firefox/users/pwreset/%s/12-345' %
                                                                self.uidb36)
        self.assertContains(r, "Password reset unsuccessful")

    def test_set_fail(self):
        url = self._get_reset_url()
        r = self.client.post(url, {'new_password1': '', 'new_password2': ''})
        self.assertFormError(r, 'form', 'new_password1',
                                   "This field is required.")
        self.assertFormError(r, 'form', 'new_password2',
                                   "This field is required.")

        r = self.client.post(url, {'new_password1': 'one',
                                   'new_password2': 'two'})
        self.assertFormError(r, 'form', 'new_password2',
                                   "The two password fields didn't match.")

    def test_set_success(self):
        url = self._get_reset_url()

        assert self.user_profile.check_password('testo') is False

        self.client.post(url, {'new_password1': 'testo',
                               'new_password2': 'testo'})

        self.user_profile = User.objects.get(id='4043307').get_profile()

        assert self.user_profile.check_password('testo')


class TestPasswordResetForm(UserFormBase):

    def test_request_fail(self):
        r = self.client.post('/en-US/firefox/users/pwreset',
                            {'email': 'someemail@somedomain.com'})

        eq_(len(mail.outbox), 0)
        self.assertFormError(r, 'form', 'email',
                             ("That e-mail address doesn't have an "
                              "associated user account. Are you sure "
                              "you've registered?"))

    def test_request_success(self):
        self.client.post('/en-US/firefox/users/pwreset',
                        {'email': self.user.email})

        eq_(len(mail.outbox), 1)
        assert mail.outbox[0].subject.find('Password reset') == 0
        assert mail.outbox[0].body.find('pwreset/%s' % self.uidb36) > 0


class TestUserEditForm(UserFormBase):

    def test_set_fail(self):
        # 404 right now because log in page doesn't exist
        #r = self.client.get('/users/edit', follow=True)
        #assert False
        pass
