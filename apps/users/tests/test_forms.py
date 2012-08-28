from datetime import datetime

from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.core.exceptions import SuspiciousOperation
from django.utils.http import int_to_base36

from django.conf import settings
from mock import Mock, patch
from nose.tools import eq_
from pyquery import PyQuery as pq
import waffle

import amo
import amo.tests
from amo.helpers import urlparams
from amo.urlresolvers import reverse
from amo.tests.test_helpers import get_uploaded_file
from users.models import BlacklistedPassword, UserProfile
from users.forms import UserEditForm


class UserFormBase(amo.tests.TestCase):
    fixtures = ['users/test_backends']

    def setUp(self):
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

        self.user_profile = User.objects.get(id='4043307').get_profile()

        assert self.user_profile.check_password('testlonger')
        eq_(self.user_profile.userlog_set
                .filter(activity_log__action=amo.LOG.CHANGE_PASSWORD.id)
                .count(), 1)


class TestPasswordResetForm(UserFormBase):

    def test_request_fail(self):
        r = self.client.post('/en-US/firefox/users/pwreset',
                            {'email': 'someemail@somedomain.com'})

        eq_(len(mail.outbox), 0)
        self.assertFormError(r, 'form', 'email',
            ("An email has been sent to the requested account with further "
             "information. If you do not receive an email then please confirm "
             "you have entered the same email address used during "
             "account registration."))

    def test_request_success(self):
        self.client.post('/en-US/firefox/users/pwreset',
                        {'email': self.user.email})

        eq_(len(mail.outbox), 1)
        assert mail.outbox[0].subject.find('Password reset') == 0
        assert mail.outbox[0].body.find('pwreset/%s' % self.uidb36) > 0

    def test_amo_user_but_no_django_user(self):
        # Password reset should work without a Django user.
        self.user_profile.update(user=None, _signal=True)
        self.user.delete()
        self.client.post('/en-US/firefox/users/pwreset',
                        {'email': self.user.email})
        eq_(len(mail.outbox), 1)


class TestUserDeleteForm(UserFormBase):

    def test_bad_password(self):
        self.client.login(username='jbalogh@mozilla.com', password='foo')
        data = {'password': 'wrong', 'confirm': True, }
        r = self.client.post('/en-US/firefox/users/delete', data)
        msg = "Wrong password entered!"
        self.assertFormError(r, 'form', 'password', msg)

    def test_not_confirmed(self):
        self.client.login(username='jbalogh@mozilla.com', password='foo')
        data = {'password': 'foo'}
        r = self.client.post('/en-US/firefox/users/delete', data)
        self.assertFormError(r, 'form', 'confirm', 'This field is required.')

    def test_success(self):
        self.client.login(username='jbalogh@mozilla.com', password='foo')
        data = {'password': 'foo', 'confirm': True, }
        self.client.post('/en-US/firefox/users/delete', data, follow=True)
        # TODO XXX: Bug 593055
        #self.assertContains(r, "Profile Deleted")
        u = UserProfile.objects.get(id='4043307')
        eq_(u.email, None)

    @patch('users.models.UserProfile.is_developer')
    def test_developer_attempt(self, f):
        """A developer's attempt to delete one's self must be thwarted."""
        f.return_value = True
        self.client.login(username='jbalogh@mozilla.com', password='foo')
        data = {'password': 'foo', 'confirm': True, }
        r = self.client.post('/en-US/firefox/users/delete', data, follow=True)
        self.assertContains(r, 'You cannot delete your account')


class TestUserAdminForm(UserFormBase):

    def test_long_hash(self):
        self.client.login(username='fligtar@gmail.com', password='foo')
        data = {'password': 'sha512$32e15df727a054aa56cf69accc142d1573372641a176aab9b0f1458e27dc6f3b$5bd3bd7811569776a07fbbb5e50156aa6ebdd0bec9267249b57da065340f0324190f1ad0d5f609dca19179a86c64807e22f789d118e6f7109c95b9c64ae8f619',
                'username': 'alice',
                'last_login': '2010-07-03 23:03:11',
                'date_joined': '2010-07-03 23:03:11'}
        r = self.client.post(reverse('admin:auth_user_change',
                                     args=[self.user.id]),
                             data)
        eq_(pq(r.content)('#user_form div.password .errorlist').text(), None)

    def test_toolong_hash(self):
        self.client.login(username='fligtar@gmail.com', password='foo')
        data = {'password': 'sha512$32e15df727a054aa56cf69accc142d1573372641a176aab9b0f1458e27dc6f3b$5bd3bd7811569776a07fbbb5e50156aa6ebdd0bec9267249b57da065340f0324190f1ad0d5f609dca19179a86c64807e22f789d118e6f7109c95b9c64ae8f6190000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000',
                'username': 'alice'}
        r = self.client.post(reverse('admin:auth_user_change',
                                     args=[self.user.id]),
                             data)
        eq_(pq(r.content)('#id_password strong').text(),
            'Invalid password format or unknown hashing algorithm.')


class TestUserEditForm(UserFormBase):

    def setUp(self):
        super(TestUserEditForm, self).setUp()
        self.client.login(username='jbalogh@mozilla.com', password='foo')
        self.url = reverse('users.edit')

    def test_no_names(self):
        data = {'username': '',
                'email': 'jbalogh@mozilla.com', }
        r = self.client.post(self.url, data)
        self.assertFormError(r, 'form', 'username', 'This field is required.')

    def test_no_real_name(self):
        data = {'username': 'blah',
                'email': 'jbalogh@mozilla.com', }
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
                'oldpassword': 'foo',
                'password': 'longer123',
                'password2': 'longer1234', }
        r = self.client.post(self.url, data)
        self.assertFormError(r, 'form', 'password2',
                             'The passwords did not match.')

    def test_set_new_passwords(self):
        data = {'username': 'jbalogh',
                'email': 'jbalogh@mozilla.com',
                'oldpassword': 'foo',
                'password': 'longer123',
                'password2': 'longer123', }
        r = self.client.post(self.url, data, follow=True)
        self.assertContains(r, 'Profile Updated')

    def test_long_data(self):
        data = {'username': 'jbalogh',
                'email': 'jbalogh@mozilla.com',
                'oldpassword': 'foo',
                'password': 'new',
                'password2': 'new', }
        for field, length in (('username', 50), ('display_name', 50),
                              ('location', 100), ('occupation', 100)):
            data[field] = 'x' * (length + 1)
            r = self.client.post(self.url, data, follow=True)
            err = u'Ensure this value has at most %s characters (it has %s).'
            self.assertFormError(r, 'form', field, err % (length, length + 1))

    @patch('amo.models.ModelBase.update')
    def test_photo_modified(self, update_mock):
        dummy = Mock()
        dummy.user = self.user

        data = {'username': self.user_profile.username,
                'email': self.user_profile.email}
        files = {'photo': get_uploaded_file('transparent.png')}
        form = UserEditForm(data, files=files, instance=self.user_profile,
                            request=dummy)
        assert form.is_valid()
        form.save()
        assert update_mock.called


class TestAdminUserEditForm(UserFormBase):
    fixtures = ['base/users']

    def setUp(self):
        super(TestAdminUserEditForm, self).setUp()
        self.client.login(username='admin@mozilla.com', password='password')
        self.url = reverse('users.admin_edit', args=[self.user.id])

    def test_delete_link(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        eq_(pq(r.content)('a.delete').attr('href'),
            reverse('admin:users_userprofile_delete', args=[self.user.id]))


class TestUserLoginForm(UserFormBase):

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
        user = UserProfile.objects.get(email='jbalogh@mozilla.com')
        url = self._get_login_url()
        r = self.client.post(url, {'username': user.email,
                                   'password': 'foo'}, follow=True)
        eq_(pq(r.content.decode('utf-8'))('.account .user').text(),
            user.display_name)
        eq_(pq(r.content)('.account .user').attr('title'), user.email)

        r = self.client.post(url, {'username': user.email,
                                   'password': 'foo',
                                   'rememberme': 1}, follow=True)
        eq_(pq(r.content.decode('utf-8'))('.account .user').text(),
            user.display_name)
        eq_(pq(r.content)('.account .user').attr('title'), user.email)
        # Subtract 100 to give some breathing room
        age = settings.SESSION_COOKIE_AGE - 100
        assert self.client.session.get_expiry_age() > age

    def test_redirect_after_login(self):
        url = urlparams(self._get_login_url(), to="/en-US/firefox/about")
        r = self.client.post(url, {'username': 'jbalogh@mozilla.com',
                                   'password': 'foo'}, follow=True)
        self.assertRedirects(r, '/en-US/about')

        # Test a valid domain.  Note that assertRedirects doesn't work on
        # external domains
        url = urlparams(self._get_login_url(), to="/addon/new",
                        domain="builder")
        r = self.client.post(url, {'username': 'jbalogh@mozilla.com',
                                   'password': 'foo'}, follow=True)
        to, code = r.redirect_chain[0]
        self.assertEqual(to, 'https://builder.addons.mozilla.org/addon/new')
        self.assertEqual(code, 302)

    def test_redirect_after_login_evil(self):
        url = urlparams(self._get_login_url(), to='http://foo.com')
        with self.assertRaises(SuspiciousOperation):
            self.client.post(url, {'username': 'jbalogh@mozilla.com',
                                   'password': 'foo'}, follow=True)

    def test_redirect_after_login_domain(self):
        url = urlparams(self._get_login_url(), to='/en-US/firefox',
                        domain='http://evil.com')
        r = self.client.post(url, {'username': 'jbalogh@mozilla.com',
                                   'password': 'foo'}, follow=True)
        self.assertRedirects(r, '/en-US/firefox/')

    def test_unconfirmed_account(self):
        url = self._get_login_url()
        self.user_profile.confirmationcode = 'blah'
        self.user_profile.save()
        r = self.client.post(url, {'username': 'jbalogh@mozilla.com',
                                   'password': 'foo'}, follow=True)
        self.assertNotContains(r, "Welcome, Jeff")
        self.assertContains(r, "A link to activate your user account")
        self.assertContains(r, "If you did not receive the confirmation")

    @patch.object(settings, 'APP_PREVIEW', True)
    def test_no_register(self):
        res = self.client.get(self._get_login_url())
        assert not res.content in 'Create an Add-ons Account'

    @patch.object(settings, 'APP_PREVIEW', False)
    def test_yes_register(self):
        res = self.client.get(self._get_login_url())
        self.assertContains(res, 'Create an Add-ons Account')

    def test_disabled_account(self):
        url = self._get_login_url()
        self.user_profile.deleted = True
        self.user_profile.save()
        r = self.client.post(url, {'username': 'jbalogh@mozilla.com',
                                   'password': 'foo'}, follow=True)
        self.assertNotContains(r, "Welcome, Jeff")
        self.assertContains(r, 'Please enter a correct username and password. '
                               'Note that both fields are case-sensitive.')

    def test_successful_login_logging(self):
        t = datetime.now()
        # microsecond is not saved in the db
        t = datetime(t.year, t.month, t.day, t.hour, t.minute, t.second)
        url = self._get_login_url()
        self.client.post(url, {'username': 'jbalogh@mozilla.com',
                               'password': 'foo'}, follow=True)
        u = UserProfile.objects.get(email='jbalogh@mozilla.com')
        eq_(u.failed_login_attempts, 0)
        eq_(u.last_login_attempt_ip, '127.0.0.1')
        eq_(u.last_login_ip, '127.0.0.1')
        assert u.last_login_attempt == t or u.last_login_attempt > t

    def test_failed_login_logging(self):
        t = datetime.now()
        # microsecond is not saved in the db
        t = datetime(t.year, t.month, t.day, t.hour, t.minute, t.second)
        url = self._get_login_url()
        self.client.post(url, {'username': 'jbalogh@mozilla.com',
                               'password': 'wrongpassword'})
        u = UserProfile.objects.get(email='jbalogh@mozilla.com')
        eq_(u.failed_login_attempts, 4)
        eq_(u.last_login_attempt_ip, '127.0.0.1')
        assert u.last_login_ip != '127.0.0.1'
        assert u.last_login_attempt == t or u.last_login_attempt > t


class TestUserRegisterForm(UserFormBase):

    def test_no_info(self):
        data = {'email': '',
                'password': '',
                'password2': '',
                'username': '', }
        r = self.client.post('/en-US/firefox/users/register', data)
        msg = "This field is required."
        self.assertFormError(r, 'form', 'email', msg)
        self.assertFormError(r, 'form', 'username', msg)

    def test_register_existing_account(self):
        data = {'email': 'jbalogh@mozilla.com',
                'password': 'xxxlonger',
                'password2': 'xxxlonger',
                'username': 'xxx', }
        r = self.client.post('/en-US/firefox/users/register', data)
        self.assertFormError(r, 'form', 'email',
                             'User profile with this Email already exists.')
        eq_(len(mail.outbox), 0)

    def test_set_unmatched_passwords(self):
        data = {'email': 'john.connor@sky.net',
                'password': 'new1longer',
                'password2': 'new2longer', }
        r = self.client.post('/en-US/firefox/users/register', data)
        self.assertFormError(r, 'form', 'password2',
                                            'The passwords did not match.')
        eq_(len(mail.outbox), 0)

    def test_invalid_username(self):
        data = {'email': 'testo@example.com',
                'password': 'xxxlonger',
                'password2': 'xxxlonger',
                'username': 'Todd/Rochelle', }
        r = self.client.post('/en-US/firefox/users/register', data)
        self.assertFormError(r, 'form', 'username',
            'Enter a valid username consisting of letters, numbers, '
            'underscores or hyphens.')

    def test_blacklisted_username(self):
        data = {'email': 'testo@example.com',
                'password': 'xxxlonger',
                'password2': 'xxxlonger',
                'username': 'IE6Fan', }
        r = self.client.post('/en-US/firefox/users/register', data)
        self.assertFormError(r, 'form', 'username',
                             'This username cannot be used.')

    def test_blacklisted_password(self):
        BlacklistedPassword.objects.create(password='password')
        data = {'email': 'testo@example.com',
                'password': 'password',
                'password2': 'password',
                'username': 'IE6Fan', }
        r = self.client.post('/en-US/firefox/users/register', data)
        self.assertFormError(r, 'form', 'password',
                             'That password is not allowed.')

    def test_password_length(self):
        BlacklistedPassword.objects.create(password='password')
        data = {'email': 'testo@example.com',
                'password': 'short',
                'password2': 'short',
                'username': 'IE6Fan', }
        r = self.client.post('/en-US/firefox/users/register', data)
        self.assertFormError(r, 'form', 'password',
                             'Must be 8 characters or more.')

    def test_invalid_email_domain(self):
        data = {'email': 'fake@mailinator.com',
                'password': 'xxxlonger',
                'password2': 'xxxlonger',
                'username': 'trulyfake', }
        r = self.client.post('/en-US/firefox/users/register', data)
        self.assertFormError(r, 'form', 'email',
                             'Please use an email address from a different '
                             'provider to complete your registration.')

    def test_invalid_homepage(self):
        data = {'homepage': 'example.com:alert(String.fromCharCode(88,83,83)',
                'email': ''}
        m = 'This URL has an invalid format. '
        m += 'Valid URLs look like http://example.com/my_page.'
        r = self.client.post('/en-US/firefox/users/register', data)
        self.assertFormError(r, 'form', 'homepage', m)

    def test_already_logged_in(self):
        self.client.login(username='jbalogh@mozilla.com', password='foo')
        r = self.client.get('/users/register', follow=True)
        self.assertContains(r, "You are already logged in")
        self.assertNotContains(r, '<button type="submit">Register</button>')

    def test_browserid_registered(self):
        u = UserProfile.objects.create(email='bid_test@mozilla.com',
                                       source=amo.LOGIN_SOURCE_BROWSERID,
                                       password='')
        data = {'email': u.email}
        r = self.client.post('/en-US/firefox/users/register', data)
        self.assertContains(r, 'already have an account')

    def good_data(self):
        return {
            'email': 'john.connor@sky.net',
            'password': 'carebears',
            'password2': 'carebears',
            'username': 'BigJC',
            'homepage': ''
        }

    @patch('captcha.fields.ReCaptchaField.clean')
    def test_success(self, clean):
        clean.return_value = ''

        r = self.client.post('/en-US/firefox/users/register', self.good_data(),
                             follow=True)

        self.assertContains(r, "Congratulations!")

        u = User.objects.get(email='john.connor@sky.net').get_profile()

        assert u.confirmationcode
        eq_(len(mail.outbox), 1)
        assert mail.outbox[0].subject.find('Please confirm your email') == 0
        assert mail.outbox[0].body.find('%s/confirm/%s' %
                                        (u.id, u.confirmationcode)) > 0

    def test_long_data(self):
        data = {'username': 'jbalogh',
                'email': 'jbalogh@mozilla.com',
                'oldpassword': 'foo',
                'password': 'new',
                'password2': 'new', }
        for field, length in (('username', 50), ('display_name', 50)):
            data[field] = 'x' * (length + 1)
            r = self.client.post(reverse('users.register'), data, follow=True)
            err = u'Ensure this value has at most %s characters (it has %s).'
            self.assertFormError(r, 'form', field, err % (length, length + 1))

    @patch.object(settings, 'REGISTER_USER_LIMIT', 1)
    def test_hit_limit_get(self):
        res = self.client.get(reverse('users.register'))
        doc = pq(res.content)
        eq_(len(doc('.error')), 1)

    @patch.object(settings, 'REGISTER_USER_LIMIT', 1)
    @patch('captcha.fields.ReCaptchaField.clean')
    def test_hit_limit_post(self, clean):
        before = UserProfile.objects.count()
        clean.return_value = ''
        res = self.client.get(reverse('users.register'),
                              self.good_data())
        doc = pq(res.content)
        eq_(len(doc('.error')), 1)
        eq_(UserProfile.objects.count(), before)  # No user was created.

    @patch.object(settings, 'REGISTER_USER_LIMIT', 1)
    @patch.object(settings, 'REGISTER_OVERRIDE_TOKEN', 'mozilla')
    @patch('captcha.fields.ReCaptchaField.clean')
    def test_override_user_limit(self, clean):
        clean.return_value = ''
        before = UserProfile.objects.count()
        self.client.post(reverse('users.register') + '?ro=mozilla',
                         self.good_data())
        eq_(UserProfile.objects.count(), before + 1)

    @patch.object(settings, 'REGISTER_USER_LIMIT', 1)
    @patch.object(settings, 'REGISTER_OVERRIDE_TOKEN', 'mozilla')
    def test_override_with_wrong_token(self):
        before = UserProfile.objects.count()
        res = self.client.post(reverse('users.register') + '?ro=netscape',
                               self.good_data())
        doc = pq(res.content)
        eq_(len(doc('.error')), 1)
        eq_(UserProfile.objects.count(), before)  # No user was created.

    @patch.object(settings, 'REGISTER_OVERRIDE_TOKEN', 'mozilla')
    def test_pass_through_reg_override_token(self):
        res = self.client.get(reverse('users.register') + '?ro=mozilla')
        doc = pq(res.content)
        eq_(doc('form.user-input').attr('action'),
            reverse('users.register') + '?ro=mozilla')

    @patch.object(settings, 'APP_PREVIEW', False)
    @patch.object(settings, 'REGISTER_USER_LIMIT', 0)
    @patch('captcha.fields.ReCaptchaField.clean')
    def test_no_limit_post(self, clean):
        before = UserProfile.objects.count()
        clean.return_value = ''
        self.client.post(reverse('users.register'), self.good_data())
        eq_(UserProfile.objects.count(), before + 1)

    @patch.object(settings, 'APP_PREVIEW', True)
    def test_no_register(self):
        waffle.models.Switch.objects.create(name='browserid-login',
                                            active=True)
        res = self.client.post(reverse('users.register'), self.good_data())
        eq_(res.status_code, 200)
        eq_(len(pq(res.content)('div.error')), 1)


class TestBlacklistedUsernameAdminAddForm(UserFormBase):

    def test_no_usernames(self):
        self.client.login(username='testo@example.com', password='foo')
        url = reverse('admin:users_blacklistedusername_add')
        data = {'usernames': "\n\n", }
        r = self.client.post(url, data)
        msg = 'Please enter at least one username to blacklist.'
        self.assertFormError(r, 'form', 'usernames', msg)

    def test_add(self):
        self.client.login(username='testo@example.com', password='foo')
        url = reverse('admin:users_blacklistedusername_add')
        data = {'usernames': "IE6Fan\nfubar\n\n", }
        r = self.client.post(url, data)
        msg = '1 new values added to the blacklist. '
        msg += '1 duplicates were ignored.'
        self.assertContains(r, msg)
        self.assertNotContains(r, 'fubar')


class TestBlacklistedEmailDomainAdminAddForm(UserFormBase):

    def test_no_domains(self):
        self.client.login(username='testo@example.com', password='foo')
        url = reverse('admin:users_blacklistedemaildomain_add')
        data = {'domains': "\n\n", }
        r = self.client.post(url, data)
        msg = 'Please enter at least one e-mail domain to blacklist.'
        self.assertFormError(r, 'form', 'domains', msg)

    def test_add(self):
        self.client.login(username='testo@example.com', password='foo')
        url = reverse('admin:users_blacklistedemaildomain_add')
        data = {'domains': "mailinator.com\ntrash-mail.de\n\n", }
        r = self.client.post(url, data)
        msg = '1 new values added to the blacklist. '
        msg += '1 duplicates were ignored.'
        self.assertContains(r, msg)
        self.assertNotContains(r, 'fubar')
