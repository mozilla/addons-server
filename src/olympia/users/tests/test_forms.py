import hashlib
from datetime import datetime

from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.utils.http import urlsafe_base64_encode

from django.conf import settings
from mock import Mock, patch
from pyquery import PyQuery as pq

from olympia import amo
from olympia.amo.tests import TestCase
from olympia.amo.urlresolvers import reverse
from olympia.amo.tests.test_helpers import get_uploaded_file
from olympia.users.models import BlacklistedPassword, UserProfile
from olympia.users.forms import AuthenticationForm, UserEditForm


class UserFormBase(TestCase):
    fixtures = ['users/test_backends']

    def setUp(self):
        super(UserFormBase, self).setUp()
        self.user = self.user_profile = UserProfile.objects.get(id='4043307')
        self.uidb64 = urlsafe_base64_encode(str(self.user.id))
        self.token = default_token_generator.make_token(self.user)


class TestSetPasswordForm(UserFormBase):

    def _get_reset_url(self):
        return "/en-US/firefox/users/pwreset/%s/%s" % (self.uidb64, self.token)

    def test_url_fail(self):
        r = self.client.get('/users/pwreset/junk/', follow=True)
        assert r.status_code == 404

        r = self.client.get('/en-US/firefox/users/pwreset/%s/12-345' %
                            self.uidb64)
        self.assertContains(r, "Password reset unsuccessful")

    def test_set_fail(self):
        url = self._get_reset_url()
        r = self.client.post(url, {'new_password1': '', 'new_password2': ''})
        self.assertFormError(r, 'form', 'new_password1',
                             "This field is required.")
        self.assertFormError(r, 'form', 'new_password2',
                             "This field is required.")

        r = self.client.post(url, {'new_password1': 'onelonger',
                                   'new_password2': 'twolonger'})
        self.assertFormError(r, 'form', 'new_password2',
                             "The two password fields didn't match.")

    def test_set_blacklisted(self):
        BlacklistedPassword.objects.create(password='password')
        url = self._get_reset_url()
        r = self.client.post(url, {'new_password1': 'password',
                                   'new_password2': 'password'})
        self.assertFormError(r, 'form', 'new_password1',
                             'That password is not allowed.')

    def test_set_short(self):
        url = self._get_reset_url()
        r = self.client.post(url, {'new_password1': 'short',
                                   'new_password2': 'short'})
        self.assertFormError(r, 'form', 'new_password1',
                             'Must be 8 characters or more.')

    def test_set_success(self):
        url = self._get_reset_url()

        assert self.user_profile.check_password('testlonger') is False

        self.client.post(url, {'new_password1': 'testlonger',
                               'new_password2': 'testlonger'})

        self.user_profile = UserProfile.objects.get(id='4043307')

        assert self.user_profile.check_password('testlonger')
        assert self.user_profile.userlog_set.filter(
            activity_log__action=amo.LOG.CHANGE_PASSWORD.id).count() == 1


class TestPasswordResetForm(UserFormBase):

    def test_request_with_unkown_email(self):
        r = self.client.post(
            reverse('password_reset_form'),
            {'email': 'someemail@somedomain.com'}
        )

        assert len(mail.outbox) == 0
        self.assert3xx(r, reverse('password_reset_done'))

    def test_request_success(self):
        self.client.post(
            reverse('password_reset_form'),
            {'email': self.user.email}
        )

        assert len(mail.outbox) == 1
        assert mail.outbox[0].subject.find('Password reset') == 0
        assert mail.outbox[0].body.find('pwreset/%s' % self.uidb64) > 0

    def test_request_success_migrated(self):
        self.user.update(fxa_id='555')
        response = self.client.post(
            reverse('password_reset_form'),
            {'email': self.user.email})

        assert len(mail.outbox) == 0
        assert response.status_code == 200
        assert ('You must recover your password through Firefox Accounts' in
                response.content)

    def test_request_success_getpersona_password(self):
        """Email is sent even if the user has no password and the profile has
        an "unusable" password according to django's AbstractBaseUser."""
        bytes_ = '\xb1\x98og\x88\x87\x08q'
        md5 = hashlib.md5('password').hexdigest()
        hsh = hashlib.sha512(bytes_ + md5).hexdigest()
        self.user.password = 'sha512+MD5$%s$%s' % (bytes, hsh)
        self.user.save()
        self.client.post(
            reverse('password_reset_form'),
            {'email': self.user.email}
        )

        assert len(mail.outbox) == 1
        assert mail.outbox[0].subject.find('Password reset') == 0
        assert mail.outbox[0].body.find('pwreset/%s' % self.uidb64) > 0

    def test_required_attrs(self):
        res = self.client.get(reverse('password_reset_form'))
        email_input = pq(res.content.decode('utf-8'))('#id_email')
        assert email_input.attr('required') == 'required'
        assert email_input.attr('aria-required') == 'true'


class TestUserDeleteForm(UserFormBase):

    def test_bad_email(self):
        self.client.login(username='jbalogh@mozilla.com', password='password')
        data = {'email': 'wrong@example.com', 'confirm': True}
        r = self.client.post('/en-US/firefox/users/delete', data)
        msg = "Email must be jbalogh@mozilla.com."
        self.assertFormError(r, 'form', 'email', msg)

    def test_not_confirmed(self):
        self.client.login(username='jbalogh@mozilla.com', password='password')
        data = {'email': 'jbalogh@mozilla.com'}
        r = self.client.post('/en-US/firefox/users/delete', data)
        self.assertFormError(r, 'form', 'confirm', 'This field is required.')

    def test_success(self):
        self.client.login(username='jbalogh@mozilla.com', password='password')
        data = {'email': 'jbalogh@mozilla.com', 'confirm': True}
        self.client.post('/en-US/firefox/users/delete', data, follow=True)
        # TODO XXX: Bug 593055
        # self.assertContains(r, "Profile Deleted")
        u = UserProfile.objects.get(id=4043307)
        assert u.deleted
        assert u.email is None

    @patch('olympia.users.models.UserProfile.is_developer')
    def test_developer_attempt(self, f):
        """A developer's attempt to delete one's self must be thwarted."""
        f.return_value = True
        self.client.login(username='jbalogh@mozilla.com', password='password')
        data = {'email': 'jbalogh@mozilla.com', 'confirm': True}
        r = self.client.post('/en-US/firefox/users/delete', data, follow=True)
        self.assertContains(r, 'You cannot delete your account')


class TestUserEditForm(UserFormBase):

    def setUp(self):
        super(TestUserEditForm, self).setUp()
        self.client.login(username='jbalogh@mozilla.com', password='password')
        self.url = reverse('users.edit')

    def test_no_username_or_display_name(self):
        assert not self.user.has_anonymous_username()
        data = {'username': '',
                'email': 'jbalogh@mozilla.com',
                'lang': 'pt-BR'}
        response = self.client.post(self.url, data)
        self.assertNoFormErrors(response)
        assert self.user.reload().has_anonymous_username()

    def test_change_username(self):
        assert self.user.username != 'new-username'
        data = {'username': 'new-username',
                'email': 'jbalogh@mozilla.com',
                'lang': 'fr'}
        response = self.client.post(self.url, data)
        self.assertNoFormErrors(response)
        assert self.user.reload().username == 'new-username'

    def test_no_username_anonymous_does_not_change(self):
        """Test that username isn't required with auto-generated usernames and
        the auto-generated value does not change."""
        username = self.user.anonymize_username()
        self.user.save()
        data = {'username': '',
                'email': 'jbalogh@mozilla.com',
                'lang': 'en-US'}
        response = self.client.post(self.url, data)
        self.assertNoFormErrors(response)
        assert self.user.reload().username == username

    def test_fxa_id_cannot_be_set(self):
        assert self.user.fxa_id is None
        data = {'username': 'blah',
                'email': 'jbalogh@mozilla.com',
                'fxa_id': 'yo',
                'lang': 'en-US'}
        response = self.client.post(self.url, data)
        self.assertNoFormErrors(response)
        assert self.user.reload().fxa_id is None

    def test_no_real_name(self):
        data = {'username': 'blah',
                'email': 'jbalogh@mozilla.com',
                'lang': 'en-US'}
        r = self.client.post(self.url, data, follow=True)
        self.assertContains(r, 'Profile Updated')

    def test_set_wrong_password(self):
        data = {'email': 'jbalogh@mozilla.com',
                'oldpassword': 'wrong',
                'password': 'new',
                'password2': 'new', }
        r = self.client.post(self.url, data)
        self.assertFormError(r, 'form', 'oldpassword',
                             'Wrong password entered!')

    def test_set_unmatched_passwords(self):
        data = {'email': 'jbalogh@mozilla.com',
                'oldpassword': 'password',
                'password': 'longer123',
                'password2': 'longer1234', }
        r = self.client.post(self.url, data)
        self.assertFormError(r, 'form', 'password2',
                             'The passwords did not match.')

    def test_set_new_passwords(self):
        data = {'username': 'jbalogh',
                'email': 'jbalogh@mozilla.com',
                'oldpassword': 'password',
                'password': 'longer123',
                'password2': 'longer123',
                'lang': 'en-US'}
        r = self.client.post(self.url, data, follow=True)
        self.assertContains(r, 'Profile Updated')

    def test_long_data(self):
        data = {'username': 'jbalogh',
                'email': 'jbalogh@mozilla.com',
                'oldpassword': 'password',
                'password': 'new',
                'password2': 'new',
                'lang': 'en-US'}
        for field, length in (('username', 50), ('display_name', 50),
                              ('location', 100), ('occupation', 100)):
            data[field] = 'x' * (length + 1)
            r = self.client.post(self.url, data, follow=True)
            err = u'Ensure this value has at most %s characters (it has %s).'
            self.assertFormError(r, 'form', field, err % (length, length + 1))

    @patch('olympia.amo.models.ModelBase.update')
    def test_photo_modified(self, update_mock):
        dummy = Mock()
        dummy.user = self.user

        data = {'username': self.user_profile.username,
                'email': self.user_profile.email,
                'lang': 'en-US'}
        files = {'photo': get_uploaded_file('transparent.png')}
        form = UserEditForm(data, files=files, instance=self.user_profile,
                            request=dummy)
        assert form.is_valid()
        form.save()
        assert update_mock.called

    def test_lang_initial(self):
        """If no lang is set on the user, initial value is current locale."""
        # Lang is already set: don't change it.
        res = self.client.get(self.url)
        form = res.context['form']
        assert form.initial['lang'] == 'en-US'

        with self.activate('fr'):
            res = self.client.get(reverse('users.edit'))
            form = res.context['form']
            assert form.initial['lang'] == 'en-US'

        # Lang isn't set yet: initial value is set to the current locale.
        user = UserProfile.objects.get(email='jbalogh@mozilla.com')
        user.lang = None
        user.save()

        res = self.client.get(self.url)
        form = res.context['form']
        assert form.initial['lang'] == 'en-US'

        with self.activate('fr'):
            res = self.client.get(reverse('users.edit'))
            form = res.context['form']
            assert form.initial['lang'] == 'fr'

    def test_required_attrs(self):
        res = self.client.get(self.url)
        email_input = pq(res.content.decode('utf-8'))('#id_email')
        assert email_input.attr('required') == 'required'
        assert email_input.attr('aria-required') == 'true'

    def test_existing_email(self):
        data = {'email': 'testo@example.com'}
        r = self.client.post(self.url, data)
        self.assertFormError(r, 'form', 'email',
                             [u'User profile with this Email already exists.'])

    def test_change_email_fxa_migrated(self):
        self.user.update(fxa_id='1a2b3c', email='me@example.com')
        assert self.user.fxa_migrated()
        response = self.client.post(self.url, {'email': 'noway@example.com'})
        self.assertFormError(
            response, 'form', 'email',
            ['Email cannot be changed.'])

    def test_email_matches_fxa_migrated(self):
        self.user.update(fxa_id='1a2b3c', email='me@example.com')
        assert self.user.fxa_migrated()
        response = self.client.post(self.url, {
            'email': 'me@example.com',
            'lang': 'en-US',
        })
        assert self.user.reload().email == 'me@example.com'
        self.assertNoFormErrors(response)

    def test_no_change_email_fxa_migrated(self):
        self.user.update(fxa_id='1a2b3c', email='me@example.com')
        assert self.user.fxa_migrated()
        response = self.client.post(self.url, {
            'username': 'wat',
            'lang': 'en-US',
        })
        assert self.user.reload().email == 'me@example.com'
        self.assertNoFormErrors(response)


class TestAdminUserEditForm(UserFormBase):
    fixtures = ['base/users']

    def setUp(self):
        super(TestAdminUserEditForm, self).setUp()
        self.client.login(username='admin@mozilla.com', password='password')
        self.url = reverse('users.admin_edit', args=[self.user.id])

    def test_delete_link(self):
        r = self.client.get(self.url)
        assert r.status_code == 200
        assert pq(r.content)('a.delete').attr('href') == (
            reverse('admin:users_userprofile_delete', args=[self.user.id]))


class TestUserLoginForm(UserFormBase):

    def _get_login_url(self):
        return "/en-US/firefox/users/login"

    def test_credential_fail(self):
        r = self.client.post(self._get_login_url(),
                             {'username': '', 'password': ''})
        self.assertFormError(r, 'form', 'username', "This field is required.")
        self.assertFormError(r, 'form', 'password', "This field is required.")

    def test_credential_fail_wrong_password(self):
        r = self.client.post(self._get_login_url(),
                             {'username': 'jbalogh@mozilla.com',
                              'password': 'wrongpassword'})
        self.assertFormError(r, 'form', '', ("Please enter a correct username "
                                             "and password. Note that both "
                                             "fields may be case-sensitive."))

    def test_credential_fail_short_password(self):
        r = self.client.post(self._get_login_url(),
                             {'username': 'jbalogh@mozilla.com',
                              'password': 'shortpw'})
        error_msg = (u'As part of our new password policy, your password must '
                     u'be 8 characters or more. Please update your password '
                     u'by <a href="/en-US/firefox/users/pwreset">issuing a '
                     u'password reset</a>.')
        self.assertFormError(r, 'form', 'password', error_msg)

    def test_credential_success(self):
        user = UserProfile.objects.get(email='jbalogh@mozilla.com')
        url = self._get_login_url()
        r = self.client.post(url, {'username': user.email,
                                   'password': 'password'}, follow=True)
        assert pq(r.content.decode('utf-8'))('.account .user').text() == (
            user.display_name)
        assert pq(r.content)('.account .user').attr('title') == user.email

        r = self.client.post(url, {'username': user.email,
                                   'password': 'password',
                                   'rememberme': 1}, follow=True)
        assert pq(r.content.decode('utf-8'))('.account .user').text() == (
            user.display_name)
        assert pq(r.content)('.account .user').attr('title') == user.email
        # Subtract 100 to give some breathing room
        age = settings.SESSION_COOKIE_AGE - 100
        assert self.client.session.get_expiry_age() > age

    def test_unconfirmed_account(self):
        url = self._get_login_url()
        self.user_profile.confirmationcode = 'blah'
        self.user_profile.save()
        r = self.client.post(url, {'username': 'jbalogh@mozilla.com',
                                   'password': 'password'}, follow=True)
        self.assertNotContains(r, "Welcome, Jeff")
        self.assertContains(r, "A link to activate your user account")
        self.assertContains(r, "If you did not receive the confirmation")

    def test_yes_register(self):
        res = self.client.get(self._get_login_url())
        self.assertContains(res, 'Create an Add-ons Account')

    def test_required_attrs(self):
        res = self.client.get(self._get_login_url())
        username_input = pq(res.content.decode('utf-8'))('#id_username')
        assert username_input.attr('required') == 'required'
        assert username_input.attr('aria-required') == 'true'

    def test_disabled_account(self):
        url = self._get_login_url()
        self.user_profile.deleted = True
        self.user_profile.save()
        r = self.client.post(url, {'username': 'jbalogh@mozilla.com',
                                   'password': 'password'}, follow=True)
        self.assertNotContains(r, "Welcome, Jeff")
        self.assertContains(r, 'Wrong email address or password')

    def test_successful_login_logging(self):
        t = datetime.now()
        # microsecond is not saved in the db
        t = datetime(t.year, t.month, t.day, t.hour, t.minute, t.second)
        url = self._get_login_url()
        self.client.post(url, {'username': 'jbalogh@mozilla.com',
                               'password': 'password'}, follow=True)
        u = UserProfile.objects.get(email='jbalogh@mozilla.com')
        assert u.failed_login_attempts == 0
        assert u.last_login_attempt_ip == '127.0.0.1'
        assert u.last_login_ip == '127.0.0.1'
        assert u.last_login_attempt == t or u.last_login_attempt > t

    def test_failed_login_logging(self):
        t = datetime.now()
        # microsecond is not saved in the db
        t = datetime(t.year, t.month, t.day, t.hour, t.minute, t.second)
        url = self._get_login_url()
        self.client.post(url, {'username': 'jbalogh@mozilla.com',
                               'password': 'wrongpassword'})
        u = UserProfile.objects.get(email='jbalogh@mozilla.com')
        assert u.failed_login_attempts == 4
        assert u.last_login_attempt_ip == '127.0.0.1'
        assert u.last_login_ip != '127.0.0.1'
        assert u.last_login_attempt == t or u.last_login_attempt > t

    @patch.object(settings, 'NOBOT_RECAPTCHA_PRIVATE_KEY', 'something')
    def test_recaptcha_errors_only(self):
        """Only recaptcha errors should be returned if validation fails.

        We don't want any information on the username/password returned if the
        captcha is incorrect.

        """
        form = AuthenticationForm(data={'username': 'foo',
                                        'password': 'barpassword',
                                        'recaptcha': ''},
                                  use_recaptcha=True)
        form.is_valid()

        assert len(form.errors) == 1
        assert 'recaptcha' in form.errors


class TestBlacklistedNameAdminAddForm(UserFormBase):

    def test_no_usernames(self):
        self.client.login(username='testo@example.com', password='password')
        url = reverse('admin:users_blacklistedname_add')
        data = {'names': "\n\n", }
        r = self.client.post(url, data)
        msg = 'Please enter at least one name to blacklist.'
        self.assertFormError(r, 'form', 'names', msg)

    def test_add(self):
        self.client.login(username='testo@example.com', password='password')
        url = reverse('admin:users_blacklistedname_add')
        data = {'names': "IE6Fan\nfubar\n\n", }
        r = self.client.post(url, data)
        msg = '1 new values added to the blacklist. '
        msg += '1 duplicates were ignored.'
        self.assertContains(r, msg)
        self.assertNotContains(r, 'fubar')


class TestBlacklistedEmailDomainAdminAddForm(UserFormBase):

    def test_no_domains(self):
        self.client.login(username='testo@example.com', password='password')
        url = reverse('admin:users_blacklistedemaildomain_add')
        data = {'domains': "\n\n", }
        r = self.client.post(url, data)
        msg = 'Please enter at least one e-mail domain to blacklist.'
        self.assertFormError(r, 'form', 'domains', msg)

    def test_add(self):
        self.client.login(username='testo@example.com', password='password')
        url = reverse('admin:users_blacklistedemaildomain_add')
        data = {'domains': "mailinator.com\ntrash-mail.de\n\n", }
        r = self.client.post(url, data)
        msg = '1 new values added to the blacklist. '
        msg += '1 duplicates were ignored.'
        self.assertContains(r, msg)
        self.assertNotContains(r, 'fubar')
