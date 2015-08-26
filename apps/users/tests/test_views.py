import collections
import json
from urlparse import urlparse

from django.conf import settings
from django.core import mail
from django.core.cache import cache
from django.contrib.auth.tokens import default_token_generator
from django.forms.models import model_to_dict
from django.utils.http import urlsafe_base64_encode

from mock import Mock, patch
from nose.tools import eq_

# Unused, but needed so that we can patch jingo.
from waffle import helpers  # NOQA

import amo
import amo.tests
from abuse.models import AbuseReport
from access.models import Group, GroupUser
from addons.models import Addon, AddonUser, Category
from amo.helpers import urlparams
from amo.pyquery_wrapper import PyQuery as pq
from amo.urlresolvers import reverse
from bandwagon.models import Collection, CollectionWatcher
from devhub.models import ActivityLog
from reviews.models import Review
from users.models import BlacklistedPassword, UserProfile, UserNotification
import users.notifications as email
from users.utils import EmailResetCode, UnsubscribeCode
from users.views import tshirt_eligible


def fake_request():
    request = Mock()
    request.LANG = 'foo'
    request.GET = request.META = {}
    # Fake out host/scheme for Persona login.
    request.get_host.return_value = urlparse(settings.SITE_URL).netloc
    request.is_secure.return_value = False
    return request


def check_sidebar_links(self, expected):
    r = self.client.get(self.url)
    eq_(r.status_code, 200)
    links = pq(r.content)('#secondary-nav ul a')
    amo.tests.check_links(expected, links)
    eq_(links.filter('.selected').attr('href'), self.url)


class TestTShirtOrder(amo.tests.TestCase):
    fixtures = ['base/users', 'base/addon_3615']

    def test_normal_user(self):
        user = UserProfile.objects.get(email='regular@mozilla.com')
        assert not tshirt_eligible(user)

    def test_listed_dev(self):
        addon = Addon.objects.get(pk=3615)
        user = addon.authors.get()

        assert tshirt_eligible(user)

    def test_unlisted_dev(self):
        addon = Addon.objects.get(pk=3615)
        user = addon.authors.get()

        addon.update(is_listed=False)
        assert not tshirt_eligible(user)

        addon.versions.get().files.get().update(is_signed=True)
        assert tshirt_eligible(user)

    def test_persona_dev(self):
        addon = Addon.objects.get(pk=3615)
        user = addon.authors.get()

        addon.update(type=amo.ADDON_PERSONA,
                     average_daily_users=1)
        assert not tshirt_eligible(user)

        addon.update(average_daily_users=10000)
        assert tshirt_eligible(user)


class UserViewBase(amo.tests.TestCase):
    fixtures = ['users/test_backends']

    def setUp(self):
        super(UserViewBase, self).setUp()
        self.client = amo.tests.TestClient()
        self.client.get('/')
        self.user = UserProfile.objects.get(id='4043307')

    def get_profile(self):
        return UserProfile.objects.get(id=self.user.id)


class TestAjax(UserViewBase):

    def setUp(self):
        super(TestAjax, self).setUp()
        self.client.login(username='jbalogh@mozilla.com', password='password')

    def test_ajax_404(self):
        r = self.client.get(reverse('users.ajax'), follow=True)
        eq_(r.status_code, 404)

    def test_ajax_success(self):
        r = self.client.get(reverse('users.ajax'), {'q': 'fligtar@gmail.com'},
                            follow=True)
        data = json.loads(r.content)
        eq_(data, {'status': 1, 'message': '', 'id': 9945,
                   'name': u'Justin Scott \u0627\u0644\u062a\u0637\u0628'})

    def test_ajax_xss(self):
        self.user.display_name = '<script>alert("xss")</script>'
        self.user.save()
        assert '<script>' in self.user.display_name, (
            'Expected <script> to be in display name')
        r = self.client.get(reverse('users.ajax'),
                            {'q': self.user.email, 'dev': 0})
        assert '<script>' not in r.content
        assert '&lt;script&gt;' in r.content

    def test_ajax_failure_incorrect_email(self):
        r = self.client.get(reverse('users.ajax'), {'q': 'incorrect'},
                            follow=True)
        data = json.loads(r.content)
        eq_(data,
            {'status': 0,
             'message': 'A user with that email address does not exist.'})

    def test_ajax_failure_no_email(self):
        r = self.client.get(reverse('users.ajax'), {'q': ''}, follow=True)
        data = json.loads(r.content)
        eq_(data,
            {'status': 0,
             'message': 'An email address is required.'})

    def test_forbidden(self):
        self.client.logout()
        r = self.client.get(reverse('users.ajax'))
        eq_(r.status_code, 401)


class TestEdit(UserViewBase):

    def setUp(self):
        super(TestEdit, self).setUp()
        self.client.login(username='jbalogh@mozilla.com', password='password')
        self.user = UserProfile.objects.get(username='jbalogh')
        self.url = reverse('users.edit')
        self.data = {'username': 'jbalogh', 'email': 'jbalogh@mozilla.com',
                     'oldpassword': 'password', 'password': 'longenough',
                     'password2': 'longenough', 'lang': 'en-US'}

    def test_password_logs(self):
        res = self.client.post(self.url, self.data)
        eq_(res.status_code, 302)
        eq_(self.user.userlog_set
                .filter(activity_log__action=amo.LOG.CHANGE_PASSWORD.id)
                .count(), 1)

    def test_password_empty(self):
        admingroup = Group(rules='Users:Edit')
        admingroup.save()
        GroupUser.objects.create(group=admingroup, user=self.user)
        homepage = {'username': 'jbalogh', 'email': 'jbalogh@mozilla.com',
                    'homepage': 'http://cbc.ca', 'lang': 'en-US'}
        res = self.client.post(self.url, homepage)
        eq_(res.status_code, 302)

    def test_password_blacklisted(self):
        BlacklistedPassword.objects.create(password='password')
        bad = self.data.copy()
        bad['password'] = 'password'
        res = self.client.post(self.url, bad)
        eq_(res.status_code, 200)
        eq_(res.context['form'].is_valid(), False)
        eq_(res.context['form'].errors['password'],
            [u'That password is not allowed.'])

    def test_password_short(self):
        bad = self.data.copy()
        bad['password'] = 'short'
        res = self.client.post(self.url, bad)
        eq_(res.status_code, 200)
        eq_(res.context['form'].is_valid(), False)
        eq_(res.context['form'].errors['password'],
            [u'Must be 8 characters or more.'])

    def test_email_change_mail_sent(self):
        data = {'username': 'jbalogh',
                'email': 'jbalogh.changed@mozilla.com',
                'display_name': 'DJ SurfNTurf',
                'lang': 'en-US'}

        r = self.client.post(self.url, data, follow=True)
        self.assertRedirects(r, self.url)
        self.assertContains(r, 'An email has been sent to %s' % data['email'])

        # The email shouldn't change until they confirm, but the name should
        u = UserProfile.objects.get(id='4043307')
        self.assertEquals(u.name, 'DJ SurfNTurf')
        self.assertEquals(u.email, 'jbalogh@mozilla.com')

        eq_(len(mail.outbox), 1)
        eq_(mail.outbox[0].subject.find('Please confirm your email'), 0)
        assert mail.outbox[0].body.find('%s/emailchange/' % self.user.id) > 0

    @patch.object(settings, 'SEND_REAL_EMAIL', False)
    def test_email_change_mail_send_even_with_fake_email(self):
        data = {'username': 'jbalogh',
                'email': 'jbalogh.changed@mozilla.com',
                'display_name': 'DJ SurfNTurf',
                'lang': 'en-US'}

        self.client.post(self.url, data, follow=True)
        eq_(len(mail.outbox), 1)
        eq_(mail.outbox[0].subject.find('Please confirm your email'), 0)

    def test_edit_bio(self):
        eq_(self.get_profile().bio, None)

        data = {'username': 'jbalogh',
                'email': 'jbalogh.changed@mozilla.com',
                'bio': 'xxx unst unst',
                'lang': 'en-US'}

        r = self.client.post(self.url, data, follow=True)
        self.assertRedirects(r, self.url)
        self.assertContains(r, data['bio'])
        eq_(unicode(self.get_profile().bio), data['bio'])

        data['bio'] = 'yyy unst unst'
        r = self.client.post(self.url, data, follow=True)
        self.assertRedirects(r, self.url)
        self.assertContains(r, data['bio'])
        eq_(unicode(self.get_profile().bio), data['bio'])

    def check_default_choices(self, choices, checked=True):
        doc = pq(self.client.get(self.url).content)
        eq_(doc('input[name=notifications]:checkbox').length, len(choices))
        for id, label in choices:
            box = doc('input[name=notifications][value=%s]' % id)
            if checked:
                eq_(box.filter(':checked').length, 1)
            else:
                eq_(box.length, 1)
            parent = box.parent('label')
            if checked:
                eq_(parent.find('.msg').length, 1)  # Check for "NEW" message.
            eq_(parent.remove('.msg, .req').text(), label)

    def post_notifications(self, choices):
        self.check_default_choices(choices)

        self.data['notifications'] = []
        r = self.client.post(self.url, self.data)
        self.assertRedirects(r, self.url, 302)

        eq_(UserNotification.objects.count(), len(email.NOTIFICATIONS))
        eq_(UserNotification.objects.filter(enabled=True).count(),
            len(filter(lambda x: x.mandatory, email.NOTIFICATIONS)))
        self.check_default_choices(choices, checked=False)

    def test_edit_notifications(self):
        # Make jbalogh a developer.
        AddonUser.objects.create(
            user=self.user,
            addon=Addon.objects.create(type=amo.ADDON_EXTENSION))

        choices = email.NOTIFICATIONS_CHOICES
        self.check_default_choices(choices)

        self.data['notifications'] = [2, 4, 6]
        r = self.client.post(self.url, self.data)
        self.assertRedirects(r, self.url, 302)

        mandatory = [n.id for n in email.NOTIFICATIONS if n.mandatory]
        total = len(self.data['notifications'] + mandatory)
        eq_(UserNotification.objects.count(), len(email.NOTIFICATIONS))
        eq_(UserNotification.objects.filter(enabled=True).count(), total)

        doc = pq(self.client.get(self.url).content)
        eq_(doc('input[name=notifications]:checked').length, total)

        eq_(doc('.more-none').length, len(email.NOTIFICATION_GROUPS))
        eq_(doc('.more-all').length, len(email.NOTIFICATION_GROUPS))

    def test_edit_notifications_non_dev(self):
        self.post_notifications(email.NOTIFICATIONS_CHOICES_NOT_DEV)

    def test_edit_notifications_non_dev_error(self):
        self.data['notifications'] = [2, 4, 6]
        r = self.client.post(self.url, self.data)
        assert r.context['form'].errors['notifications']

    def test_collections_toggles(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        doc = pq(r.content)
        eq_(doc('#profile-misc').length, 1,
            'Collections options should be visible.')

    def test_remove_locale_bad_request(self):
        r = self.client.post(self.user.get_user_url('remove-locale'))
        eq_(r.status_code, 400)

    @patch.object(UserProfile, 'remove_locale')
    def test_remove_locale(self, remove_locale_mock):
        r = self.client.post(self.user.get_user_url('remove-locale'),
                             {'locale': 'el'})
        eq_(r.status_code, 200)
        remove_locale_mock.assert_called_with('el')

    def test_remove_locale_default_locale(self):
        r = self.client.post(self.user.get_user_url('remove-locale'),
                             {'locale': settings.LANGUAGE_CODE})
        eq_(r.status_code, 400)


class TestEditAdmin(UserViewBase):
    fixtures = ['base/users']

    def setUp(self):
        super(TestEditAdmin, self).setUp()
        self.client.login(username='admin@mozilla.com', password='password')
        self.regular = self.get_user()
        self.url = reverse('users.admin_edit', args=[self.regular.pk])

    def get_data(self):
        data = model_to_dict(self.regular)
        data['admin_log'] = 'test'
        del data['password']
        return data

    def get_user(self):
        # Using pk so that we can still get the user after anonymize.
        return UserProfile.objects.get(pk=10482)

    def test_edit(self):
        res = self.client.get(self.url)
        eq_(res.status_code, 200)

    def test_edit_without_user_lang(self):
        self.regular.lang = None
        self.regular.save()
        res = self.client.get(self.url)
        eq_(res.status_code, 200)

    def test_edit_forbidden(self):
        self.client.logout()
        self.client.login(username='editor@mozilla.com', password='password')
        res = self.client.get(self.url)
        eq_(res.status_code, 403)

    def test_edit_forbidden_anon(self):
        self.client.logout()
        res = self.client.get(self.url)
        eq_(res.status_code, 302)

    def test_anonymize(self):
        data = self.get_data()
        data['anonymize'] = True
        res = self.client.post(self.url, data)
        eq_(res.status_code, 302)
        eq_(self.get_user().password, "sha512$Anonymous$Password")

    def test_anonymize_fails(self):
        data = self.get_data()
        data['anonymize'] = True
        data['email'] = 'something@else.com'
        res = self.client.post(self.url, data)
        eq_(res.status_code, 200)
        eq_(self.get_user().password, self.regular.password)  # Hasn't changed.

    def test_admin_logs_edit(self):
        data = self.get_data()
        data['email'] = 'something@else.com'
        self.client.post(self.url, data)
        res = ActivityLog.objects.filter(action=amo.LOG.ADMIN_USER_EDITED.id)
        eq_(res.count(), 1)
        assert self.get_data()['admin_log'] in res[0]._arguments

    def test_admin_logs_anonymize(self):
        data = self.get_data()
        data['anonymize'] = True
        self.client.post(self.url, data)
        res = (ActivityLog.objects
                          .filter(action=amo.LOG.ADMIN_USER_ANONYMIZED.id))
        eq_(res.count(), 1)
        assert self.get_data()['admin_log'] in res[0]._arguments

    def test_admin_no_password(self):
        data = self.get_data()
        data.update({'password': 'pass1234',
                     'password2': 'pass1234',
                     'oldpassword': 'password'})
        self.client.post(self.url, data)
        logs = ActivityLog.objects.filter
        eq_(logs(action=amo.LOG.CHANGE_PASSWORD.id).count(), 0)
        res = logs(action=amo.LOG.ADMIN_USER_EDITED.id)
        eq_(res.count(), 1)
        eq_(res[0].details['password'][0], u'****')

    def test_delete_user_display_name_xss(self):
        # This is to test for bug 835827.
        self.regular.display_name = '"><img src=a onerror=alert(1)><a a="'
        self.regular.save()
        delete_url = reverse('admin:users_userprofile_delete',
                             args=(self.regular.pk,))
        res = self.client.post(delete_url, {'post': 'yes'}, follow=True)
        assert self.regular.display_name not in res.content

FakeResponse = collections.namedtuple("FakeResponse", "status_code content")


class TestPasswordAdmin(UserViewBase):
    fixtures = ['base/users']

    def setUp(self):
        super(TestPasswordAdmin, self).setUp()
        self.client.login(username='editor@mozilla.com', password='password')
        self.url = reverse('users.edit')
        self.correct = {'username': 'editor',
                        'email': 'editor@mozilla.com',
                        'oldpassword': 'password', 'password': 'longenough',
                        'password2': 'longenough', 'lang': 'en-US'}

    def test_password_admin(self):
        res = self.client.post(self.url, self.correct, follow=False)
        eq_(res.status_code, 200)
        eq_(res.context['form'].is_valid(), False)
        eq_(res.context['form'].errors['password'],
            [u'Letters and numbers required.'])

    def test_password(self):
        UserProfile.objects.get(username='editor').groups.all().delete()
        res = self.client.post(self.url, self.correct, follow=False)
        eq_(res.status_code, 302)


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
        self.assertEqual(self.user.email, 'jbalogh@mozilla.com')
        url = reverse('users.emailchange', args=[self.user.id, self.token,
                                                 self.hash])
        r = self.client.get(url, follow=True)
        eq_(r.status_code, 200)
        u = UserProfile.objects.get(id=self.user.id)
        self.assertEqual(u.email, 'nobody@mozilla.org')

    def test_email_change_to_an_existing_user_email(self):
        token, hash_ = EmailResetCode.create(self.user.id, 'testo@example.com')
        url = reverse('users.emailchange', args=[self.user.id, token, hash_])
        r = self.client.get(url, follow=True)
        eq_(r.status_code, 400)


class TestLogin(UserViewBase):
    fixtures = ['users/test_backends', 'base/addon_3615']

    def setUp(self):
        super(TestLogin, self).setUp()
        self.url = reverse('users.login')
        self.data = {'username': 'jbalogh@mozilla.com', 'password': 'password'}

    def test_client_login(self):
        """
        This is just here to make sure Test Client's login() works with
        our custom code.
        """
        assert not self.client.login(username='jbalogh@mozilla.com',
                                     password='wrongpassword')
        assert self.client.login(**self.data)

    def test_double_login(self):
        r = self.client.post(self.url, self.data, follow=True)
        self.assertRedirects(r, '/en-US/firefox/')

        # If you go to the login page when you're already logged in we bounce
        # you.
        r = self.client.get(self.url, follow=True)
        self.assertRedirects(r, '/en-US/firefox/')

    def test_ok_redirects(self):
        r = self.client.post(self.url, self.data, follow=True)
        self.assertRedirects(r, '/en-US/firefox/')

        r = self.client.get(self.url + '?to=/de/firefox/', follow=True)
        self.assertRedirects(r, '/de/firefox/')

    def test_bad_redirects(self):
        r = self.client.post(self.url, self.data, follow=True)
        self.assertRedirects(r, '/en-US/firefox/')

        for redirect in ['http://xx.com',
                         'data:text/html,<script>window.alert("xss")</script>',
                         'mailto:test@example.com',
                         'file:///etc/passwd',
                         'javascript:window.alert("xss");']:
            self.assertRedirects(r, '/en-US/firefox/')

    def test_login_link(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        eq_(pq(r.content)('#aux-nav li.login').length, 1)

    def test_logout_link(self):
        self.test_client_login()
        r = self.client.get(reverse('home'))
        eq_(r.status_code, 200)
        eq_(pq(r.content)('#aux-nav li.logout').length, 1)

    @amo.tests.mobile_test
    def test_mobile_login(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        doc = pq(r.content)('header')
        eq_(doc('nav').length, 1)
        eq_(doc('#home').length, 1)
        eq_(doc('#auth-nav li.login').length, 0)

    def test_login_ajax(self):
        url = reverse('users.login_modal')
        r = self.client.get(url)
        eq_(r.status_code, 200)

        res = self.client.post(url, data=self.data)
        eq_(res.status_code, 302)

    def test_login_ajax_error(self):
        url = reverse('users.login_modal')
        data = self.data
        data['username'] = ''

        res = self.client.post(url, data=self.data)
        eq_(res.context['form'].errors['username'][0],
            'This field is required.')

    def test_login_ajax_wrong(self):
        url = reverse('users.login_modal')
        data = self.data
        data['username'] = 'jeffb@mozilla.com'

        res = self.client.post(url, data=self.data)
        text = 'Please enter a correct username and password.'
        assert res.context['form'].errors['__all__'][0].startswith(text)

    def test_login_no_recaptcha(self):
        res = self.client.post(self.url, data=self.data)
        eq_(res.status_code, 302)

    @patch.object(settings, 'RECAPTCHA_PRIVATE_KEY', 'something')
    @patch.object(settings, 'LOGIN_RATELIMIT_USER', 2)
    def test_login_attempts_recaptcha(self):
        res = self.client.post(self.url, data=self.data)
        eq_(res.status_code, 200)
        assert res.context['form'].fields.get('recaptcha')

    @patch.object(settings, 'RECAPTCHA_PRIVATE_KEY', 'something')
    def test_login_shown_recaptcha(self):
        data = self.data.copy()
        data['recaptcha_shown'] = ''
        res = self.client.post(self.url, data=data)
        eq_(res.status_code, 200)
        assert res.context['form'].fields.get('recaptcha')

    @patch.object(settings, 'RECAPTCHA_PRIVATE_KEY', 'something')
    @patch.object(settings, 'LOGIN_RATELIMIT_USER', 2)
    @patch('captcha.fields.ReCaptchaField.clean')
    def test_login_with_recaptcha(self, clean):
        clean.return_value = ''
        data = self.data.copy()
        data.update({'recaptcha': '', 'recaptcha_shown': ''})
        res = self.client.post(self.url, data=data)
        eq_(res.status_code, 302)

    def test_login_fails_increment(self):
        # It increments even when the form is wrong.
        user = UserProfile.objects.filter(email=self.data['username'])
        eq_(user.get().failed_login_attempts, 3)
        self.client.post(self.url, data={'username': self.data['username']})
        eq_(user.get().failed_login_attempts, 4)

    def test_doubled_account(self):
        """
        Logging in to an account that shares a User object with another
        account works properly.
        """
        profile = UserProfile.objects.create(username='login_test',
                                             email='bob@example.com')
        profile.set_password('bazpassword')
        profile.email = 'charlie@example.com'
        profile.save()
        profile2 = UserProfile.objects.create(username='login_test2',
                                              email='bob@example.com')
        profile2.set_password('foopassword')
        profile2.save()

        res = self.client.post(self.url,
                               data={'username': 'charlie@example.com',
                                     'password': 'wrongpassword'})
        eq_(res.status_code, 200)
        eq_(UserProfile.objects.get(email='charlie@example.com')
            .failed_login_attempts, 1)
        res2 = self.client.post(self.url,
                                data={'username': 'charlie@example.com',
                                      'password': 'bazpassword'})
        eq_(res2.status_code, 302)
        res3 = self.client.post(self.url, data={'username': 'bob@example.com',
                                                'password': 'foopassword'})
        eq_(res3.status_code, 302)

    def test_changed_account(self):
        """
        Logging in to an account that had its email changed succeeds.
        """
        profile = UserProfile.objects.create(username='login_test',
                                             email='bob@example.com')
        profile.set_password('bazpassword')
        profile.email = 'charlie@example.com'
        profile.save()

        res = self.client.post(self.url,
                               data={'username': 'charlie@example.com',
                                     'password': 'wrongpassword'})
        eq_(res.status_code, 200)
        eq_(UserProfile.objects.get(email='charlie@example.com')
            .failed_login_attempts, 1)
        res2 = self.client.post(self.url,
                                data={'username': 'charlie@example.com',
                                      'password': 'bazpassword'})
        eq_(res2.status_code, 302)


@patch.object(settings, 'RECAPTCHA_PRIVATE_KEY', '')
@patch('users.models.UserProfile.log_login_attempt')
class TestFailedCount(UserViewBase):
    fixtures = ['users/test_backends', 'base/addon_3615']

    def setUp(self):
        super(TestFailedCount, self).setUp()
        self.url = reverse('users.login')
        self.data = {'username': 'jbalogh@mozilla.com', 'password': 'password'}

    def log_calls(self, obj):
        return [call[0][0] for call in obj.call_args_list]

    def test_login_passes(self, log_login_attempt):
        self.client.post(self.url, data=self.data)
        eq_(self.log_calls(log_login_attempt), [True])

    def test_login_fails(self, log_login_attempt):
        self.client.post(self.url, data={'username': self.data['username']})
        eq_(self.log_calls(log_login_attempt), [False])

    def test_login_deleted(self, log_login_attempt):
        (UserProfile.objects.get(email=self.data['username'])
                            .update(deleted=True))
        self.client.post(self.url, data={'username': self.data['username']})
        eq_(self.log_calls(log_login_attempt), [False])

    def test_login_confirmation(self, log_login_attempt):
        (UserProfile.objects.get(email=self.data['username'])
                            .update(confirmationcode='123'))
        self.client.post(self.url, data={'username': self.data['username']})
        eq_(self.log_calls(log_login_attempt), [False])

    def test_login_get(self, log_login_attempt):
        self.client.get(self.url, data={'username': self.data['username']})
        eq_(log_login_attempt.called, False)

    def test_login_get_no_data(self, log_login_attempt):
        self.client.get(self.url)
        eq_(log_login_attempt.called, False)


class TestUnsubscribe(UserViewBase):
    fixtures = ['base/users']

    def setUp(self):
        super(TestUnsubscribe, self).setUp()
        self.user = UserProfile.objects.get(email='editor@mozilla.com')

    def test_correct_url_update_notification(self):
        # Make sure the user is subscribed
        perm_setting = email.NOTIFICATIONS[0]
        un = UserNotification.objects.create(notification_id=perm_setting.id,
                                             user=self.user,
                                             enabled=True)

        # Create a URL
        token, hash = UnsubscribeCode.create(self.user.email)
        url = reverse('users.unsubscribe', args=[token, hash,
                                                 perm_setting.short])

        # Load the URL
        r = self.client.get(url)
        doc = pq(r.content)

        # Check that it was successful
        assert doc('#unsubscribe-success').length
        assert doc('#standalone').length
        eq_(doc('#standalone ul li').length, 1)

        # Make sure the user is unsubscribed
        un = UserNotification.objects.filter(notification_id=perm_setting.id,
                                             user=self.user)
        eq_(un.count(), 1)
        eq_(un.all()[0].enabled, False)

    def test_correct_url_new_notification(self):
        # Make sure the user is subscribed
        assert not UserNotification.objects.count()

        # Create a URL
        perm_setting = email.NOTIFICATIONS[0]
        token, hash = UnsubscribeCode.create(self.user.email)
        url = reverse('users.unsubscribe', args=[token, hash,
                                                 perm_setting.short])

        # Load the URL
        r = self.client.get(url)
        doc = pq(r.content)

        # Check that it was successful
        assert doc('#unsubscribe-success').length
        assert doc('#standalone').length
        eq_(doc('#standalone ul li').length, 1)

        # Make sure the user is unsubscribed
        un = UserNotification.objects.filter(notification_id=perm_setting.id,
                                             user=self.user)
        eq_(un.count(), 1)
        eq_(un.all()[0].enabled, False)

    def test_wrong_url(self):
        perm_setting = email.NOTIFICATIONS[0]
        token, hash = UnsubscribeCode.create(self.user.email)
        hash = hash[::-1]  # Reverse the hash, so it's wrong

        url = reverse('users.unsubscribe', args=[token, hash,
                                                 perm_setting.short])
        r = self.client.get(url)
        doc = pq(r.content)

        eq_(doc('#unsubscribe-fail').length, 1)


class TestReset(UserViewBase):
    fixtures = ['base/users']

    def setUp(self):
        super(TestReset, self).setUp()
        user = UserProfile.objects.get(email='editor@mozilla.com')
        self.token = [urlsafe_base64_encode(str(user.id)),
                      default_token_generator.make_token(user)]

    def test_reset_msg(self):
        res = self.client.get(reverse('users.pwreset_confirm',
                                      args=self.token))
        assert 'For your account' in res.content

    def test_csrf_token_presence(self):
        res = self.client.get(reverse('users.pwreset_confirm',
                                      args=self.token))
        assert 'csrfmiddlewaretoken' in res.content

    def test_reset_fails(self):
        res = self.client.post(reverse('users.pwreset_confirm',
                                       args=self.token),
                               data={'new_password1': 'spassword',
                                     'new_password2': 'spassword'})
        eq_(res.context['form'].errors['new_password1'][0],
            'Letters and numbers required.')

    def test_reset_succeeds(self):
        res = self.client.post(reverse('users.pwreset_confirm',
                                       args=self.token),
                               data={'new_password1': 'password1',
                                     'new_password2': 'password1'})
        eq_(res.status_code, 302)


class TestLogout(UserViewBase):

    def test_success(self):
        user = UserProfile.objects.get(email='jbalogh@mozilla.com')
        self.client.login(username=user.email, password='password')
        r = self.client.get('/', follow=True)
        eq_(pq(r.content.decode('utf-8'))('.account .user').text(),
            user.display_name)
        eq_(pq(r.content)('.account .user').attr('title'), user.email)

        r = self.client.get('/users/logout', follow=True)
        assert not pq(r.content)('.account .user')

    def test_redirect(self):
        self.client.login(username='jbalogh@mozilla.com', password='password')
        self.client.get('/', follow=True)
        url = '/en-US/about'
        r = self.client.get(urlparams(reverse('users.logout'), to=url),
                            follow=True)
        self.assertRedirects(r, url, status_code=302)

        # Test a valid domain.  Note that assertRedirects doesn't work on
        # external domains
        url = urlparams(reverse('users.logout'), to='/addon/new',
                        domain='builder')
        r = self.client.get(url, follow=True)
        to, code = r.redirect_chain[0]
        self.assertEqual(to, 'https://builder.addons.mozilla.org/addon/new')
        self.assertEqual(code, 302)

        # Test an invalid domain
        url = urlparams(reverse('users.logout'), to='/en-US/about',
                        domain='http://evil.com')
        r = self.client.get(url, follow=True)
        self.assertRedirects(r, '/en-US/about', status_code=302)

    def test_session_cookie_should_be_http_only(self):
        self.client.login(username='jbalogh@mozilla.com', password='password')
        r = self.client.get(reverse('users.logout'))
        self.assertIn('httponly', str(r.cookies[settings.SESSION_COOKIE_NAME]))


class TestRegistration(UserViewBase):

    def test_new_confirm(self):
        # User doesn't have a confirmation code.
        url = reverse('users.confirm', args=[self.user.id, 'code'])
        r = self.client.get(url, follow=True)
        is_anonymous = pq(r.content)('body').attr('data-anonymous')
        eq_(json.loads(is_anonymous), True)

        self.user.update(confirmationcode='code')

        # URL has the wrong confirmation code.
        url = reverse('users.confirm', args=[self.user.id, 'blah'])
        r = self.client.get(url, follow=True)
        self.assertContains(r, 'Invalid confirmation code!')

        # URL has the right confirmation code.
        url = reverse('users.confirm', args=[self.user.id, 'code'])
        r = self.client.get(url, follow=True)
        self.assertContains(r, 'Successfully verified!')

    def test_new_confirm_resend(self):
        # User doesn't have a confirmation code.
        url = reverse('users.confirm.resend', args=[self.user.id])
        r = self.client.get(url, follow=True)

        self.user.update(confirmationcode='code')

        # URL has the right confirmation code now.
        r = self.client.get(url, follow=True)
        self.assertContains(r, 'An email has been sent to your address')

    def test_default_lang(self):
        """When a user registers, set its lang to the current locale."""
        with self.activate('fr'):
            url = reverse('users.register')
            self.client.post(url, data={'email': 'new@example.com',
                                        'username': 'new',
                                        'password': 'foobarbaz',
                                        'password2': 'foobarbaz'})
            user = UserProfile.objects.get(email='new@example.com')
            eq_(user.lang, 'fr')


class TestProfileView(UserViewBase):

    def setUp(self):
        super(TestProfileView, self).setUp()
        self.user = UserProfile.objects.create(homepage='http://example.com')
        self.url = reverse('users.profile', args=[self.user.id])

    def test_non_developer_homepage_url(self):
        """Don't display homepage url if the user is not a developer."""
        r = self.client.get(self.url)
        self.assertNotContains(r, self.user.homepage)

    @patch.object(UserProfile, 'is_developer', True)
    def test_developer_homepage_url(self):
        """Display homepage url for a developer user."""
        r = self.client.get(self.url)
        self.assertContains(r, self.user.homepage)


class TestProfileLinks(UserViewBase):
    fixtures = ['base/appversion', 'base/featured', 'users/test_backends']

    def test_edit_buttons(self):
        """Ensure admin/user edit buttons are shown."""

        def get_links(id):
            """Grab profile, return edit links."""
            url = reverse('users.profile', args=[id])
            r = self.client.get(url)
            return pq(r.content)('#profile-actions a')

        # Anonymous user.
        links = get_links(self.user.id)
        eq_(links.length, 1)
        eq_(links.eq(0).attr('href'), reverse('users.abuse',
                                              args=[self.user.id]))

        # Non-admin, someone else's profile.
        self.client.login(username='jbalogh@mozilla.com', password='password')
        links = get_links(9945)
        eq_(links.length, 1)
        eq_(links.eq(0).attr('href'), reverse('users.abuse', args=[9945]))

        # Non-admin, own profile.
        links = get_links(self.user.id)
        eq_(links.length, 1)
        eq_(links.eq(0).attr('href'), reverse('users.edit'))

        # Admin, someone else's profile.
        admingroup = Group(rules='Users:Edit')
        admingroup.save()
        GroupUser.objects.create(group=admingroup, user=self.user)
        cache.clear()

        # Admin, own profile.
        links = get_links(self.user.id)
        eq_(links.length, 2)
        eq_(links.eq(0).attr('href'), reverse('users.edit'))
        # TODO XXX Uncomment when we have real user editing pages
        #eq_(links.eq(1).attr('href') + "/",
        #reverse('admin:users_userprofile_change', args=[self.user.id]))

    def test_amouser(self):
        # request.amo_user should be a special guy.
        self.client.login(username='jbalogh@mozilla.com', password='password')
        response = self.client.get(reverse('home'))
        request = response.context['request']
        assert hasattr(request.amo_user, 'mobile_addons')
        assert hasattr(request.user, 'mobile_addons')
        assert hasattr(request.amo_user, 'favorite_addons')
        assert hasattr(request.user, 'favorite_addons')


class TestProfileSections(amo.tests.TestCase):
    fixtures = ['base/users', 'base/addon_3615',
                'base/addon_5299_gcal', 'base/collections',
                'reviews/dev-reply']

    def setUp(self):
        super(TestProfileSections, self).setUp()
        self.user = UserProfile.objects.get(id=10482)
        self.url = reverse('users.profile', args=[self.user.id])

    def test_mine_anonymous(self):
        res = self.client.get('/user/me/', follow=True)
        eq_(res.status_code, 404)

    def test_mine_authenticated(self):
        self.login(self.user)
        res = self.client.get('/user/me/', follow=True)
        eq_(res.status_code, 200)
        eq_(res.context['user'].id, self.user.id)

    def test_my_last_login_anonymous(self):
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        doc = pq(res.content)
        eq_(doc('.last-login-time').length, 0)
        eq_(doc('.last-login-ip').length, 0)

    def test_my_last_login_authenticated(self):
        self.user.update(last_login_ip='255.255.255.255')
        self.login(self.user)
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        doc = pq(res.content)
        assert doc('.last-login-time td').text()
        eq_(doc('.last-login-ip td').text(), '255.255.255.255')

    def test_not_my_last_login(self):
        res = self.client.get('/user/999/', follow=True)
        eq_(res.status_code, 200)
        doc = pq(res.content)
        eq_(doc('.last-login-time').length, 0)
        eq_(doc('.last-login-ip').length, 0)

    def test_my_addons(self):
        eq_(pq(self.client.get(self.url).content)('.num-addons a').length, 0)

        AddonUser.objects.create(user=self.user, addon_id=3615)
        AddonUser.objects.create(user=self.user, addon_id=5299)

        r = self.client.get(self.url)
        a = r.context['addons'].object_list
        eq_(list(a), sorted(a, key=lambda x: x.weekly_downloads, reverse=True))

        doc = pq(r.content)
        eq_(doc('.num-addons a[href="#my-submissions"]').length, 1)
        items = doc('#my-addons .item')
        eq_(items.length, 2)
        eq_(items('.install[data-addon=3615]').length, 1)
        eq_(items('.install[data-addon=5299]').length, 1)

    def test_my_unlisted_addons(self):
        """I can't see my own unlisted addons on my profile page."""
        eq_(pq(self.client.get(self.url).content)('.num-addons a').length, 0)

        AddonUser.objects.create(user=self.user, addon_id=3615)
        Addon.objects.get(pk=5299).update(is_listed=False)
        AddonUser.objects.create(user=self.user, addon_id=5299)

        r = self.client.get(self.url)
        assert list(r.context['addons'].object_list) == [
            Addon.objects.get(pk=3615)]

        doc = pq(r.content)
        items = doc('#my-addons .item')
        eq_(items.length, 1)
        eq_(items('.install[data-addon=3615]').length, 1)

    def test_not_my_unlisted_addons(self):
        """I can't see others' unlisted addons on their profile pages."""
        res = self.client.get('/user/999/', follow=True)
        eq_(pq(res.content)('.num-addons a').length, 0)

        user = UserProfile.objects.get(pk=999)
        AddonUser.objects.create(user=user, addon_id=3615)
        Addon.objects.get(pk=5299).update(is_listed=False)
        AddonUser.objects.create(user=user, addon_id=5299)

        r = self.client.get('/user/999/', follow=True)
        assert list(r.context['addons'].object_list) == [
            Addon.objects.get(pk=3615)]

        doc = pq(r.content)
        items = doc('#my-addons .item')
        eq_(items.length, 1)
        eq_(items('.install[data-addon=3615]').length, 1)

    def test_my_personas(self):
        eq_(pq(self.client.get(self.url).content)('.num-addons a').length, 0)

        a = amo.tests.addon_factory(type=amo.ADDON_PERSONA)

        AddonUser.objects.create(user=self.user, addon=a)

        r = self.client.get(self.url)

        doc = pq(r.content)
        items = doc('#my-themes .persona')
        eq_(items.length, 1)
        eq_(items('a[href="%s"]' % a.get_url_path()).length, 1)

    def test_my_reviews(self):
        r = Review.objects.filter(reply_to=None)[0]
        r.update(user=self.user)
        cache.clear()
        self.assertSetEqual(self.user.reviews, [r])

        r = self.client.get(self.url)
        doc = pq(r.content)('#reviews')
        assert not doc.hasClass('full'), (
            'reviews should not have "full" class when there are collections')
        eq_(doc('.item').length, 1)
        eq_(doc('#review-218207').length, 1)

        # Edit Review form should be present.
        self.assertTemplateUsed(r, 'reviews/edit_review.html')

    def test_my_reviews_delete_link(self):
        review = Review.objects.filter(reply_to=None)[0]
        review.user_id = 999
        review.save()
        cache.clear()
        slug = Addon.objects.get(id=review.addon_id).slug
        delete_url = reverse('addons.reviews.delete', args=[slug, review.pk])

        def _get_reviews(username, password):
            self.client.login(username=username, password=password)
            r = self.client.get(reverse('users.profile', args=[999]))
            doc = pq(r.content)('#reviews')
            return doc('#review-218207 .item-actions a.delete-review')

        # Admins get the Delete Review link.
        r = _get_reviews(username='admin@mozilla.com', password='password')
        eq_(r.length, 1)
        eq_(r.attr('href'), delete_url)

        # Editors get the Delete Review link.
        r = _get_reviews(username='editor@mozilla.com', password='password')
        eq_(r.length, 1)
        eq_(r.attr('href'), delete_url)

        # Author gets the Delete Review link.
        r = _get_reviews(username='regular@mozilla.com', password='password')
        eq_(r.length, 1)
        eq_(r.attr('href'), delete_url)

        # Other user does not get the Delete Review link.
        r = _get_reviews(username='clouserw@gmail.com', password='password')
        eq_(r.length, 0)

    def test_my_reviews_no_pagination(self):
        r = self.client.get(self.url)
        assert len(self.user.addons_listed) <= 10, (
            'This user should have fewer than 10 add-ons.')
        eq_(pq(r.content)('#my-addons .paginator').length, 0)

    def test_my_reviews_pagination(self):
        for i in xrange(20):
            AddonUser.objects.create(user=self.user, addon_id=3615)
        assert len(self.user.addons_listed) > 10, (
            'This user should have way more than 10 add-ons.')
        r = self.client.get(self.url)
        eq_(pq(r.content)('#my-addons .paginator').length, 1)

    def test_my_collections_followed(self):
        coll = Collection.objects.all()[0]
        CollectionWatcher.objects.create(collection=coll, user=self.user)
        mine = Collection.objects.listed().filter(following__user=self.user)
        eq_(list(mine), [coll])

        r = self.client.get(self.url)
        self.assertTemplateUsed(r, 'bandwagon/users/collection_list.html')
        eq_(list(r.context['fav_coll']), [coll])

        doc = pq(r.content)
        eq_(doc('#reviews.full').length, 0)
        ul = doc('#my-collections #my-favorite')
        eq_(ul.length, 1)

        li = ul.find('li')
        eq_(li.length, 1)

        a = li.find('a')
        eq_(a.attr('href'), coll.get_url_path())
        eq_(a.text(), unicode(coll.name))

    def test_my_collections_created(self):
        coll = Collection.objects.listed().filter(author=self.user)
        eq_(len(coll), 1)

        r = self.client.get(self.url)
        self.assertTemplateUsed(r, 'bandwagon/users/collection_list.html')
        self.assertSetEqual(r.context['own_coll'], coll)

        doc = pq(r.content)
        eq_(doc('#reviews.full').length, 0)
        ul = doc('#my-collections #my-created')
        eq_(ul.length, 1)

        li = ul.find('li')
        eq_(li.length, 1)

        a = li.find('a')
        eq_(a.attr('href'), coll[0].get_url_path())
        eq_(a.text(), unicode(coll[0].name))

    def test_no_my_collections(self):
        Collection.objects.filter(author=self.user).delete()
        r = self.client.get(self.url)
        self.assertTemplateNotUsed(r, 'bandwagon/users/collection_list.html')
        doc = pq(r.content)
        eq_(doc('#my-collections').length, 0)
        eq_(doc('#reviews.full').length, 1)

    def test_review_abuse_form(self):
        r = self.client.get(self.url)
        self.assertTemplateUsed(r, 'reviews/report_review.html')

    def test_user_abuse_form(self):
        abuse_url = reverse('users.abuse', args=[self.user.id])
        r = self.client.get(self.url)
        doc = pq(r.content)
        button = doc('#profile-actions #report-user-abuse')
        eq_(button.length, 1)
        eq_(button.attr('href'), abuse_url)
        modal = doc('#popup-staging #report-user-modal.modal')
        eq_(modal.length, 1)
        eq_(modal('form').attr('action'), abuse_url)
        eq_(modal('textarea[name=text]').length, 1)
        self.assertTemplateUsed(r, 'users/report_abuse.html')

    def test_no_self_abuse(self):
        self.client.login(username='clouserw@gmail.com', password='password')
        r = self.client.get(self.url)
        doc = pq(r.content)
        eq_(doc('#profile-actions #report-user-abuse').length, 0)
        eq_(doc('#popup-staging #report-user-modal.modal').length, 0)
        self.assertTemplateNotUsed(r, 'users/report_abuse.html')


class TestThemesProfile(amo.tests.TestCase):
    fixtures = ['base/user_2519']

    def setUp(self):
        super(TestThemesProfile, self).setUp()
        self.user = UserProfile.objects.get(pk=2519)
        self.url = self.user.get_user_url('themes')

    def _test_good(self, res):
        eq_(res.status_code, 200)

        ids = res.context['addons'].object_list.values_list('id', flat=True)
        self.assertSetEqual(ids, [self.theme.id])

        doc = pq(res.content)
        eq_(doc('.no-results').length, 0)

        results = doc('.personas-grid .persona-preview')
        eq_(results.length, 1)
        eq_(results.find('h6').text(), unicode(self.theme.name))

    def test_bad_user(self):
        res = self.client.get(reverse('users.themes', args=['yolo']))
        eq_(res.status_code, 404)

    def test_no_themes(self):
        res = self.client.get(self.url)
        eq_(res.status_code, 200)

        eq_(pq(res.content)('.no-results').length, 1)

    def test_themes(self):
        self.theme = amo.tests.addon_factory(type=amo.ADDON_PERSONA)
        self.theme.addonuser_set.create(user=self.user, listed=True)

        res = self.client.get(self.url)
        self._test_good(res)

    def test_bad_category(self):
        res = self.client.get(reverse('users.themes', args=['yolo', 'swag']))
        eq_(res.status_code, 404)

    def test_empty_category(self):
        self.theme = amo.tests.addon_factory(type=amo.ADDON_PERSONA)
        self.theme.addonuser_set.create(user=self.user, listed=True)
        cat = Category.objects.create(type=amo.ADDON_PERSONA, slug='swag')

        res = self.client.get(
            self.user.get_user_url('themes', args=[cat.slug]))
        eq_(res.status_code, 200)

    def test_themes_category(self):
        self.theme = amo.tests.addon_factory(type=amo.ADDON_PERSONA)
        self.theme.addonuser_set.create(user=self.user, listed=True)
        cat = Category.objects.create(type=amo.ADDON_PERSONA, slug='swag')
        self.theme.addoncategory_set.create(category=cat)

        res = self.client.get(
            self.user.get_user_url('themes', args=[cat.slug]))
        self._test_good(res)


@patch.object(settings, 'RECAPTCHA_PRIVATE_KEY', 'something')
class TestReportAbuse(amo.tests.TestCase):
    fixtures = ['base/users']

    def setUp(self):
        super(TestReportAbuse, self).setUp()
        self.full_page = reverse('users.abuse', args=[10482])

    @patch('captcha.fields.ReCaptchaField.clean')
    def test_abuse_anonymous(self, clean):
        clean.return_value = ""
        self.client.post(self.full_page, {'text': 'spammy'})
        eq_(len(mail.outbox), 1)
        assert 'spammy' in mail.outbox[0].body
        report = AbuseReport.objects.get(user=10482)
        eq_(report.message, 'spammy')
        eq_(report.reporter, None)

    def test_abuse_anonymous_fails(self):
        r = self.client.post(self.full_page, {'text': 'spammy'})
        assert 'recaptcha' in r.context['abuse_form'].errors

    def test_abuse_logged_in(self):
        self.client.login(username='regular@mozilla.com', password='password')
        self.client.post(self.full_page, {'text': 'spammy'})
        eq_(len(mail.outbox), 1)
        assert 'spammy' in mail.outbox[0].body
        report = AbuseReport.objects.get(user=10482)
        eq_(report.message, 'spammy')
        eq_(report.reporter.email, 'regular@mozilla.com')

        r = self.client.get(self.full_page)
        eq_(pq(r.content)('.notification-box h2').length, 1)
