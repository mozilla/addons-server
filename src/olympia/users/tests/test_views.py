import collections
from dateutil.parser import parse
from datetime import datetime, timedelta
import json
from urlparse import urlparse

from django.conf import settings
from django.core import mail
from django.core.cache import cache
from django.contrib.auth.tokens import default_token_generator
from django.forms.models import model_to_dict
from django.utils.encoding import smart_unicode
from django.utils.http import urlsafe_base64_encode

from lxml.html import fromstring, HTMLParser
from mock import Mock, patch
from pyquery import PyQuery as pq

from olympia import amo
from olympia.amo.tests import TestCase
from olympia.abuse.models import AbuseReport
from olympia.access.models import Group, GroupUser
from olympia.addons.models import Addon, AddonUser, Category
from olympia.amo.helpers import urlparams
from olympia.amo.urlresolvers import reverse
from olympia.bandwagon.models import Collection, CollectionWatcher
from olympia.devhub.models import ActivityLog
from olympia.reviews.models import Review
from olympia.users import notifications as email
from olympia.users.models import (
    BlacklistedPassword, UserProfile, UserNotification)
from olympia.users.utils import EmailResetCode, UnsubscribeCode


def migrate_path(next_path=None):
    return urlparams(reverse('users.migrate'), to=next_path)


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
    assert r.status_code == 200
    links = pq(r.content)('#secondary-nav ul a')
    amo.tests.check_links(expected, links)
    assert links.filter('.selected').attr('href') == self.url


class UserViewBase(TestCase):
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
        assert r.status_code == 404

    def test_ajax_success(self):
        r = self.client.get(reverse('users.ajax'), {'q': 'fligtar@gmail.com'},
                            follow=True)
        data = json.loads(r.content)
        assert data == {
            'status': 1, 'message': '', 'id': 9945,
            'name': u'Justin Scott \u0627\u0644\u062a\u0637\u0628'}

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
        assert data == (
            {'status': 0,
             'message': 'A user with that email address does not exist.'})

    def test_ajax_failure_no_email(self):
        r = self.client.get(reverse('users.ajax'), {'q': ''}, follow=True)
        data = json.loads(r.content)
        assert data == (
            {'status': 0,
             'message': 'An email address is required.'})

    def test_forbidden(self):
        self.client.logout()
        r = self.client.get(reverse('users.ajax'))
        assert r.status_code == 401


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
        assert res.status_code == 302
        assert self.user.userlog_set.filter(
            activity_log__action=amo.LOG.CHANGE_PASSWORD.id).count() == 1

    def test_password_empty(self):
        admingroup = Group(rules='Users:Edit')
        admingroup.save()
        GroupUser.objects.create(group=admingroup, user=self.user)
        homepage = {'username': 'jbalogh', 'email': 'jbalogh@mozilla.com',
                    'homepage': 'http://cbc.ca', 'lang': 'en-US'}
        res = self.client.post(self.url, homepage)
        assert res.status_code == 302

    def test_password_blacklisted(self):
        BlacklistedPassword.objects.create(password='password')
        bad = self.data.copy()
        bad['password'] = 'password'
        res = self.client.post(self.url, bad)
        assert res.status_code == 200
        assert not res.context['form'].is_valid()
        assert res.context['form'].errors['password'] == (
            [u'That password is not allowed.'])

    def test_password_short(self):
        bad = self.data.copy()
        bad['password'] = 'short'
        res = self.client.post(self.url, bad)
        assert res.status_code == 200
        assert not res.context['form'].is_valid()
        assert res.context['form'].errors['password'] == (
            [u'Must be 8 characters or more.'])

    def test_email_change_mail_sent(self):
        data = {'username': 'jbalogh',
                'email': 'jbalogh.changed@mozilla.com',
                'display_name': 'DJ SurfNTurf',
                'lang': 'en-US'}

        r = self.client.post(self.url, data, follow=True)
        self.assert3xx(r, self.url)
        self.assertContains(r, 'An email has been sent to %s' % data['email'])

        # The email shouldn't change until they confirm, but the name should
        u = UserProfile.objects.get(id='4043307')
        assert u.name == 'DJ SurfNTurf'
        assert u.email == 'jbalogh@mozilla.com'

        assert len(mail.outbox) == 1
        assert mail.outbox[0].subject.find('Please confirm your email') == 0
        assert mail.outbox[0].body.find('%s/emailchange/' % self.user.id) > 0

    @patch.object(settings, 'SEND_REAL_EMAIL', False)
    def test_email_change_mail_send_even_with_fake_email(self):
        data = {'username': 'jbalogh',
                'email': 'jbalogh.changed@mozilla.com',
                'display_name': 'DJ SurfNTurf',
                'lang': 'en-US'}

        self.client.post(self.url, data, follow=True)
        assert len(mail.outbox) == 1
        assert mail.outbox[0].subject.find('Please confirm your email') == 0

    def test_edit_bio(self):
        assert self.get_profile().bio is None

        data = {'username': 'jbalogh',
                'email': 'jbalogh.changed@mozilla.com',
                'bio': 'xxx unst unst',
                'lang': 'en-US'}

        r = self.client.post(self.url, data, follow=True)
        self.assert3xx(r, self.url)
        self.assertContains(r, data['bio'])
        assert unicode(self.get_profile().bio) == data['bio']

        data['bio'] = 'yyy unst unst'
        r = self.client.post(self.url, data, follow=True)
        self.assert3xx(r, self.url)
        self.assertContains(r, data['bio'])
        assert unicode(self.get_profile().bio) == data['bio']

    def check_default_choices(self, choices, checked=True):
        doc = pq(self.client.get(self.url).content)
        assert doc('input[name=notifications]:checkbox').length == len(choices)
        for id, label in choices:
            box = doc('input[name=notifications][value="%s"]' % id)
            if checked:
                assert box.filter(':checked').length == 1
            else:
                assert box.length == 1
            parent = box.parent('label')
            if checked:
                # Check for "NEW" message.
                assert parent.find('.msg').length == 1
            assert parent.remove('.msg, .req').text() == label

    def post_notifications(self, choices):
        self.check_default_choices(choices)

        self.data['notifications'] = []
        r = self.client.post(self.url, self.data)
        self.assert3xx(r, self.url, 302)

        assert UserNotification.objects.count() == len(email.NOTIFICATIONS)
        assert UserNotification.objects.filter(enabled=True).count() == (
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
        self.assert3xx(r, self.url, 302)

        mandatory = [n.id for n in email.NOTIFICATIONS if n.mandatory]
        total = len(self.data['notifications'] + mandatory)
        assert UserNotification.objects.count() == len(email.NOTIFICATIONS)
        assert UserNotification.objects.filter(enabled=True).count() == total

        doc = pq(self.client.get(self.url).content)
        assert doc('input[name=notifications]:checked').length == total

        assert doc('.more-none').length == len(email.NOTIFICATION_GROUPS)
        assert doc('.more-all').length == len(email.NOTIFICATION_GROUPS)

    def test_edit_notifications_non_dev(self):
        self.post_notifications(email.NOTIFICATIONS_CHOICES_NOT_DEV)

    def test_edit_notifications_non_dev_error(self):
        self.data['notifications'] = [2, 4, 6]
        r = self.client.post(self.url, self.data)
        assert r.context['form'].errors['notifications']

    def test_collections_toggles(self):
        r = self.client.get(self.url)
        assert r.status_code == 200
        doc = pq(r.content)
        assert doc('#profile-misc').length == 1

    def test_remove_locale_bad_request(self):
        r = self.client.post(self.user.get_user_url('remove-locale'))
        assert r.status_code == 400

    @patch.object(UserProfile, 'remove_locale')
    def test_remove_locale(self, remove_locale_mock):
        r = self.client.post(self.user.get_user_url('remove-locale'),
                             {'locale': 'el'})
        assert r.status_code == 200
        remove_locale_mock.assert_called_with('el')

    def test_remove_locale_default_locale(self):
        r = self.client.post(self.user.get_user_url('remove-locale'),
                             {'locale': settings.LANGUAGE_CODE})
        assert r.status_code == 400


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
        del data['fxa_id']
        return data

    def get_user(self):
        # Using pk so that we can still get the user after anonymize.
        return UserProfile.objects.get(pk=10482)

    def test_edit(self):
        res = self.client.get(self.url)
        assert res.status_code == 200

    def test_edit_without_user_lang(self):
        self.regular.lang = None
        self.regular.save()
        res = self.client.get(self.url)
        assert res.status_code == 200

    def test_edit_forbidden(self):
        self.client.logout()
        self.client.login(username='editor@mozilla.com', password='password')
        res = self.client.get(self.url)
        assert res.status_code == 403

    def test_edit_forbidden_anon(self):
        self.client.logout()
        res = self.client.get(self.url)
        assert res.status_code == 302

    def test_anonymize(self):
        data = self.get_data()
        data['anonymize'] = True
        res = self.client.post(self.url, data)
        assert res.status_code == 302
        assert self.get_user().password == "sha512$Anonymous$Password"

    def test_anonymize_fails(self):
        data = self.get_data()
        data['anonymize'] = True
        data['email'] = 'something@else.com'
        res = self.client.post(self.url, data)
        assert res.status_code == 200
        assert self.get_user().password == self.regular.password

    def test_admin_logs_edit(self):
        data = self.get_data()
        data['email'] = 'something@else.com'
        self.client.post(self.url, data)
        res = ActivityLog.objects.filter(action=amo.LOG.ADMIN_USER_EDITED.id)
        assert res.count() == 1
        assert self.get_data()['admin_log'] in res[0]._arguments

    def test_admin_logs_anonymize(self):
        data = self.get_data()
        data['anonymize'] = True
        self.client.post(self.url, data)
        res = (ActivityLog.objects
                          .filter(action=amo.LOG.ADMIN_USER_ANONYMIZED.id))
        assert res.count() == 1
        assert self.get_data()['admin_log'] in res[0]._arguments

    def test_admin_no_password(self):
        data = self.get_data()
        data.update({'password': 'pass1234',
                     'password2': 'pass1234',
                     'oldpassword': 'password'})
        self.client.post(self.url, data)
        logs = ActivityLog.objects.filter
        assert logs(action=amo.LOG.CHANGE_PASSWORD.id).count() == 0
        res = logs(action=amo.LOG.ADMIN_USER_EDITED.id)
        assert res.count() == 1
        assert res[0].details['password'][0] == u'****'

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
        assert res.status_code == 200
        assert not res.context['form'].is_valid()
        assert res.context['form'].errors['password'] == (
            [u'Letters and numbers required.'])

    def test_password(self):
        UserProfile.objects.get(username='editor').groups.all().delete()
        res = self.client.post(self.url, self.correct, follow=False)
        assert res.status_code == 302


class TestEmailChange(UserViewBase):

    def setUp(self):
        super(TestEmailChange, self).setUp()
        self.token, self.hash = EmailResetCode.create(self.user.id,
                                                      'nobody@mozilla.org')

    def test_fail(self):
        # Completely invalid user, valid code
        url = reverse('users.emailchange', args=[1234, self.token, self.hash])
        r = self.client.get(url, follow=True)
        assert r.status_code == 404

        # User is in the system, but not attached to this code, valid code
        url = reverse('users.emailchange', args=[9945, self.token, self.hash])
        r = self.client.get(url, follow=True)
        assert r.status_code == 400

        # Valid user, invalid code
        url = reverse('users.emailchange', args=[self.user.id, self.token,
                                                 self.hash[:-3]])
        r = self.client.get(url, follow=True)
        assert r.status_code == 400

    def test_success(self):
        assert self.user.email == 'jbalogh@mozilla.com'
        url = reverse('users.emailchange', args=[self.user.id, self.token,
                                                 self.hash])
        r = self.client.get(url, follow=True)
        assert r.status_code == 200
        u = UserProfile.objects.get(id=self.user.id)
        assert u.email == 'nobody@mozilla.org'

    def test_email_change_to_an_existing_user_email(self):
        token, hash_ = EmailResetCode.create(self.user.id, 'testo@example.com')
        url = reverse('users.emailchange', args=[self.user.id, token, hash_])
        r = self.client.get(url, follow=True)
        assert r.status_code == 400


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

    def test_ok_redirects(self):
        r = self.client.post(self.url, self.data, follow=True)
        self.assert3xx(r, reverse('users.migrate'))

        r = self.client.get(self.url + '?to=/de/firefox/', follow=True)
        self.assert3xx(r, '/de/firefox/')

    def test_absolute_redirect_url(self):
        # We should always be using relative paths so don't allow absolute
        # URLs even if they're on the same domain.
        r = self.client.get(reverse('home'))
        assert 'Log out' not in r.content
        r = self.client.post(self.url, self.data, follow=True)
        self.assert3xx(r, reverse('users.migrate'))
        assert 'Log out' in r.content
        r = self.client.get(
            self.url + '?to=http://testserver/en-US/firefox/users/edit')
        self.assert3xx(r, '/')

    def test_bad_redirect_other_domain(self):
        r = self.client.get(reverse('home'))
        assert 'Log out' not in r.content
        r = self.client.post(
            self.url + '?to=https://example.com/this/is/bad',
            self.data, follow=True)
        self.assert3xx(r, reverse('users.migrate'))
        assert 'Log out' in r.content

    def test_bad_redirect_js(self):
        r = self.client.get(reverse('home'))
        assert 'Log out' not in r.content
        r = self.client.post(
            self.url + '?to=javascript:window.alert("xss");',
            self.data, follow=True)
        self.assert3xx(r, reverse('users.migrate'))
        assert 'Log out' in r.content

    def test_double_login(self):
        r = self.client.post(self.url, self.data, follow=True)
        self.assert3xx(r, migrate_path())

        # If you go to the login page when you're already logged in we bounce
        # you.
        r = self.client.get(self.url, follow=True)
        self.assert3xx(r, reverse('home'))

    def test_ok_redirects_fxa_enabled(self):
        r = self.client.post(
            self.url + '?to=/de/firefox/here/', self.data, follow=True)
        self.assert3xx(r, migrate_path('/de/firefox/here/'))

        r = self.client.get(
            self.url + '?to=/de/firefox/extensions/', follow=True)
        self.assert3xx(r, '/de/firefox/extensions/')

    def test_bad_redirect_other_domain_fxa_enabled(self):
        r = self.client.post(
            self.url + '?to=https://example.com/this/is/bad',
            self.data, follow=True)
        self.assert3xx(r, migrate_path())

    def test_bad_redirect_js_fxa_enabled(self):
        r = self.client.post(
            self.url + '?to=javascript:window.alert("xss");',
            self.data, follow=True)
        self.assert3xx(r, migrate_path())

    def test_login_link(self):
        r = self.client.get(self.url)
        assert r.status_code == 200
        assert pq(r.content)('#aux-nav li.login').length == 1

    def test_logout_link(self):
        self.test_client_login()
        r = self.client.get(reverse('home'))
        assert r.status_code == 200
        assert pq(r.content)('#aux-nav li.logout').length == 1

    @amo.tests.mobile_test
    def test_mobile_login(self):
        r = self.client.get(self.url)
        assert r.status_code == 200
        doc = pq(r.content)('header')
        assert doc('nav').length == 1
        assert doc('#home').length == 1
        assert doc('#auth-nav li.login').length == 0

    def test_login_ajax(self):
        url = reverse('users.login_modal')
        r = self.client.get(url)
        assert r.status_code == 200

        res = self.client.post(url, data=self.data)
        assert res.status_code == 302

    def test_login_ajax_error(self):
        url = reverse('users.login_modal')
        data = self.data
        data['username'] = ''

        res = self.client.post(url, data=self.data)
        assert res.context['form'].errors['username'][0] == (
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
        assert res.status_code == 302

    @patch.object(settings, 'NOBOT_RECAPTCHA_PRIVATE_KEY', 'something')
    @patch.object(settings, 'LOGIN_RATELIMIT_USER', 2)
    def test_login_attempts_recaptcha(self):
        res = self.client.post(self.url, data=self.data)
        assert res.status_code == 200
        assert res.context['form'].fields.get('recaptcha')

    @patch.object(settings, 'NOBOT_RECAPTCHA_PRIVATE_KEY', 'something')
    def test_login_shown_recaptcha(self):
        data = self.data.copy()
        data['recaptcha_shown'] = ''
        res = self.client.post(self.url, data=data)
        assert res.status_code == 200
        assert res.context['form'].fields.get('recaptcha')

    @patch.object(settings, 'NOBOT_RECAPTCHA_PRIVATE_KEY', 'something')
    @patch.object(settings, 'LOGIN_RATELIMIT_USER', 2)
    @patch('olympia.amo.fields.ReCaptchaField.clean')
    def test_login_with_recaptcha(self, clean):
        clean.return_value = ''
        data = self.data.copy()
        data.update({'recaptcha': '', 'recaptcha_shown': ''})
        res = self.client.post(self.url, data=data)
        assert res.status_code == 302

    def test_login_fails_increment(self):
        # It increments even when the form is wrong.
        user = UserProfile.objects.filter(email=self.data['username'])
        assert user.get().failed_login_attempts == 3
        self.client.post(self.url, data={'username': self.data['username']})
        assert user.get().failed_login_attempts == 4

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
        assert res.status_code == 200
        assert UserProfile.objects.get(
            email='charlie@example.com').failed_login_attempts == 1
        res2 = self.client.post(self.url,
                                data={'username': 'charlie@example.com',
                                      'password': 'bazpassword'})
        assert res2.status_code == 302
        res3 = self.client.post(self.url, data={'username': 'bob@example.com',
                                                'password': 'foopassword'})
        assert res3.status_code == 302

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
        assert res.status_code == 200
        assert UserProfile.objects.get(
            email='charlie@example.com').failed_login_attempts == 1
        res2 = self.client.post(self.url,
                                data={'username': 'charlie@example.com',
                                      'password': 'bazpassword'})
        assert res2.status_code == 302


@patch.object(settings, 'NOBOT_RECAPTCHA_PRIVATE_KEY', '')
@patch('olympia.users.models.UserProfile.log_login_attempt')
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
        assert self.log_calls(log_login_attempt) == [True]

    def test_login_fails(self, log_login_attempt):
        self.client.post(self.url, data={'username': self.data['username']})
        assert self.log_calls(log_login_attempt) == [False]

    def test_login_deleted(self, log_login_attempt):
        (UserProfile.objects.get(email=self.data['username'])
                            .update(deleted=True))
        self.client.post(self.url, data={'username': self.data['username']})
        assert self.log_calls(log_login_attempt) == [False]

    def test_login_confirmation(self, log_login_attempt):
        (UserProfile.objects.get(email=self.data['username'])
                            .update(confirmationcode='123'))
        self.client.post(self.url, data={'username': self.data['username']})
        assert self.log_calls(log_login_attempt) == [False]

    def test_login_get(self, log_login_attempt):
        self.client.get(self.url, data={'username': self.data['username']})
        assert not log_login_attempt.called

    def test_login_get_no_data(self, log_login_attempt):
        self.client.get(self.url)
        assert not log_login_attempt.called


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
        assert doc('#standalone ul li').length == 1

        # Make sure the user is unsubscribed
        un = UserNotification.objects.filter(notification_id=perm_setting.id,
                                             user=self.user)
        assert un.count() == 1
        assert not un.all()[0].enabled

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
        assert doc('#standalone ul li').length == 1

        # Make sure the user is unsubscribed
        un = UserNotification.objects.filter(notification_id=perm_setting.id,
                                             user=self.user)
        assert un.count() == 1
        assert not un.all()[0].enabled

    def test_wrong_url(self):
        perm_setting = email.NOTIFICATIONS[0]
        token, hash = UnsubscribeCode.create(self.user.email)
        hash = hash[::-1]  # Reverse the hash, so it's wrong

        url = reverse('users.unsubscribe', args=[token, hash,
                                                 perm_setting.short])
        r = self.client.get(url)
        doc = pq(r.content)

        assert doc('#unsubscribe-fail').length == 1


class TestReset(UserViewBase):
    fixtures = ['base/users']

    def setUp(self):
        super(TestReset, self).setUp()
        self.user = UserProfile.objects.get(email='editor@mozilla.com')
        self.token = [urlsafe_base64_encode(str(self.user.id)),
                      default_token_generator.make_token(self.user)]

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
        assert res.context['form'].errors['new_password1'][0] == (
            'Letters and numbers required.')

    def test_reset_succeeds(self):
        assert not self.user.check_password('password1')
        res = self.client.post(reverse('users.pwreset_confirm',
                                       args=self.token),
                               data={'new_password1': 'password1',
                                     'new_password2': 'password1'})
        assert self.user.reload().check_password('password1')
        assert res.status_code == 302

    def test_reset_incorrect_padding(self):
        """Fixes #929. Even if the b64 padding is incorrect, don't 500."""
        token = ["1kql8", "2xg-9f90e30ba5bda600910d"]
        res = self.client.get(reverse('users.pwreset_confirm', args=token))
        assert not res.context['validlink']

    def test_reset_msg_migrated(self):
        self.user.update(fxa_id='123')
        res = self.client.get(reverse('users.pwreset_confirm',
                                      args=self.token))
        assert 'You can no longer change your password' in res.content

    def test_reset_attempt_migrated(self):
        self.user.update(fxa_id='123')
        assert not self.user.check_password('password1')
        res = self.client.post(reverse('users.pwreset_confirm',
                                       args=self.token),
                               data={'new_password1': 'password1',
                                     'new_password2': 'password1'})
        assert not self.user.reload().check_password('password1')
        assert 'You can no longer change your password' in res.content


class TestSessionLength(UserViewBase):

    def test_session_does_not_expire_quickly(self):
        """Make sure no one is overriding our settings and making sessions
        expire at browser session end. See:
        https://github.com/mozilla/addons-server/issues/1789
        """
        self.client.login(username='jbalogh@mozilla.com', password='password')
        r = self.client.get('/', follow=True)
        cookie = r.cookies[settings.SESSION_COOKIE_NAME]

        # The user's session should be valid for at least four weeks (near a
        # month).
        four_weeks_from_now = datetime.now() + timedelta(days=28)
        expiry = parse(cookie['expires']).replace(tzinfo=None)

        assert cookie.value != ''
        assert expiry >= four_weeks_from_now


class TestLogout(UserViewBase):

    def test_success(self):
        user = UserProfile.objects.get(email='jbalogh@mozilla.com')
        self.client.login(username=user.email, password='password')
        r = self.client.get('/', follow=True)
        assert pq(r.content.decode('utf-8'))('.account .user').text() == (
            user.display_name)
        assert pq(r.content)('.account .user').attr('title') == user.email

        r = self.client.get('/users/logout', follow=True)
        assert not pq(r.content)('.account .user')

    def test_redirect(self):
        self.client.login(username='jbalogh@mozilla.com', password='password')
        self.client.get('/', follow=True)
        url = '/en-US/about'
        r = self.client.get(urlparams(reverse('users.logout'), to=url),
                            follow=True)
        self.assert3xx(r, url, status_code=302)

        url = urlparams(reverse('users.logout'), to='/addon/new',
                        domain='builder')
        r = self.client.get(url, follow=True)
        to, code = r.redirect_chain[0]
        assert to == 'https://builder.addons.mozilla.org/addon/new'
        assert code == 302

        # Test an invalid domain
        url = urlparams(reverse('users.logout'), to='/en-US/about',
                        domain='http://evil.com')
        r = self.client.get(url, follow=True)
        self.assert3xx(r, '/en-US/about', status_code=302)

    def test_session_cookie_deleted_on_logout(self):
        self.client.login(username='jbalogh@mozilla.com', password='password')
        r = self.client.get(reverse('users.logout'))
        cookie = r.cookies[settings.SESSION_COOKIE_NAME]
        assert cookie.value == ''
        assert cookie['expires'] == u'Thu, 01-Jan-1970 00:00:00 GMT'


class TestRegistration(UserViewBase):

    def test_redirects_to_login(self):
        """Register should redirect to login."""
        response = self.client.get(reverse('users.register'))
        self.assert3xx(response, reverse('users.login'), status_code=301)


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
        assert links.length == 1
        assert links.eq(0).attr('href') == reverse(
            'users.abuse', args=[self.user.id])

        # Non-admin, someone else's profile.
        self.client.login(username='jbalogh@mozilla.com', password='password')
        links = get_links(9945)
        assert links.length == 1
        assert links.eq(0).attr('href') == reverse('users.abuse', args=[9945])

        # Non-admin, own profile.
        links = get_links(self.user.id)
        assert links.length == 1
        assert links.eq(0).attr('href') == reverse('users.edit')

        # Admin, someone else's profile.
        admingroup = Group(rules='Users:Edit')
        admingroup.save()
        GroupUser.objects.create(group=admingroup, user=self.user)
        cache.clear()

        # Admin, own profile.
        links = get_links(self.user.id)
        assert links.length == 2
        assert links.eq(0).attr('href') == reverse('users.edit')
        # TODO XXX Uncomment when we have real user editing pages
        # assert links.eq(1).attr('href') + "/" == (
        # reverse('admin:users_userprofile_change', args=[self.user.id]))

    def test_user_properties(self):
        self.client.login(username='jbalogh@mozilla.com', password='password')
        response = self.client.get(reverse('home'))
        request = response.context['request']
        assert hasattr(request.user, 'mobile_addons')
        assert hasattr(request.user, 'favorite_addons')


class TestProfileSections(TestCase):
    fixtures = ['base/users', 'base/addon_3615',
                'base/addon_5299_gcal', 'base/collections',
                'reviews/dev-reply']

    def setUp(self):
        super(TestProfileSections, self).setUp()
        self.user = UserProfile.objects.get(id=10482)
        self.url = reverse('users.profile', args=[self.user.id])

    def test_mine_anonymous(self):
        res = self.client.get('/user/me/', follow=True)
        assert res.status_code == 404

    def test_mine_authenticated(self):
        self.login(self.user)
        res = self.client.get('/user/me/', follow=True)
        assert res.status_code == 200
        assert res.context['user'].id == self.user.id

    def test_my_last_login_anonymous(self):
        res = self.client.get(self.url)
        assert res.status_code == 200
        doc = pq(res.content)
        assert doc('.last-login-time').length == 0
        assert doc('.last-login-ip').length == 0

    def test_my_last_login_authenticated(self):
        self.user.update(last_login_ip='255.255.255.255')
        self.login(self.user)
        res = self.client.get(self.url)
        assert res.status_code == 200
        doc = pq(res.content)
        assert doc('.last-login-time td').text()
        assert doc('.last-login-ip td').text() == '255.255.255.255'

    def test_not_my_last_login(self):
        res = self.client.get('/user/999/', follow=True)
        assert res.status_code == 200
        doc = pq(res.content)
        assert doc('.last-login-time').length == 0
        assert doc('.last-login-ip').length == 0

    def test_my_addons(self):
        assert pq(self.client.get(self.url).content)(
            '.num-addons a').length == 0

        AddonUser.objects.create(user=self.user, addon_id=3615)
        AddonUser.objects.create(user=self.user, addon_id=5299)

        r = self.client.get(self.url)
        a = r.context['addons'].object_list
        assert list(a) == sorted(a, key=lambda x: x.weekly_downloads,
                                 reverse=True)

        doc = pq(r.content)
        assert doc('.num-addons a[href="#my-submissions"]').length == 1
        items = doc('#my-addons .item')
        assert items.length == 2
        assert items('.install[data-addon="3615"]').length == 1
        assert items('.install[data-addon="5299"]').length == 1

    def test_my_unlisted_addons(self):
        """I can't see my own unlisted addons on my profile page."""
        assert pq(self.client.get(self.url).content)(
            '.num-addons a').length == 0

        AddonUser.objects.create(user=self.user, addon_id=3615)
        Addon.objects.get(pk=5299).update(is_listed=False)
        AddonUser.objects.create(user=self.user, addon_id=5299)

        r = self.client.get(self.url)
        assert list(r.context['addons'].object_list) == [
            Addon.objects.get(pk=3615)]

        doc = pq(r.content)
        items = doc('#my-addons .item')
        assert items.length == 1
        assert items('.install[data-addon="3615"]').length == 1

    def test_not_my_unlisted_addons(self):
        """I can't see others' unlisted addons on their profile pages."""
        res = self.client.get('/user/999/', follow=True)
        assert pq(res.content)('.num-addons a').length == 0

        user = UserProfile.objects.get(pk=999)
        AddonUser.objects.create(user=user, addon_id=3615)
        Addon.objects.get(pk=5299).update(is_listed=False)
        AddonUser.objects.create(user=user, addon_id=5299)

        r = self.client.get('/user/999/', follow=True)
        assert list(r.context['addons'].object_list) == [
            Addon.objects.get(pk=3615)]

        doc = pq(r.content)
        items = doc('#my-addons .item')
        assert items.length == 1
        assert items('.install[data-addon="3615"]').length == 1

    def test_my_personas(self):
        assert pq(self.client.get(self.url).content)(
            '.num-addons a').length == 0

        a = amo.tests.addon_factory(type=amo.ADDON_PERSONA)

        AddonUser.objects.create(user=self.user, addon=a)

        r = self.client.get(self.url)

        doc = pq(r.content)
        items = doc('#my-themes .persona')
        assert items.length == 1
        assert items('a[href="%s"]' % a.get_url_path()).length == 1

    def test_my_reviews(self):
        r = Review.objects.filter(reply_to=None)[0]
        r.update(user=self.user)
        cache.clear()
        self.assertSetEqual(set(self.user.reviews), {r})

        r = self.client.get(self.url)
        doc = pq(r.content)('#reviews')
        assert not doc.hasClass('full'), (
            'reviews should not have "full" class when there are collections')
        assert doc('.item').length == 1
        assert doc('#review-218207').length == 1

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
        assert r.length == 1
        assert r.attr('href') == delete_url

        # Editors get the Delete Review link.
        r = _get_reviews(username='editor@mozilla.com', password='password')
        assert r.length == 1
        assert r.attr('href') == delete_url

        # Author gets the Delete Review link.
        r = _get_reviews(username='regular@mozilla.com', password='password')
        assert r.length == 1
        assert r.attr('href') == delete_url

        # Other user does not get the Delete Review link.
        r = _get_reviews(username='clouserw@gmail.com', password='password')
        assert r.length == 0

    def test_my_reviews_no_pagination(self):
        r = self.client.get(self.url)
        assert len(self.user.addons_listed) <= 10, (
            'This user should have fewer than 10 add-ons.')
        assert pq(r.content)('#my-addons .paginator').length == 0

    def test_my_reviews_pagination(self):
        for i in xrange(20):
            AddonUser.objects.create(user=self.user, addon_id=3615)
        assert len(self.user.addons_listed) > 10, (
            'This user should have way more than 10 add-ons.')
        r = self.client.get(self.url)
        assert pq(r.content)('#my-addons .paginator').length == 1

    def test_my_collections_followed(self):
        coll = Collection.objects.all()[0]
        CollectionWatcher.objects.create(collection=coll, user=self.user)
        mine = Collection.objects.listed().filter(following__user=self.user)
        assert list(mine) == [coll]

        r = self.client.get(self.url)
        self.assertTemplateUsed(r, 'bandwagon/users/collection_list.html')
        assert list(r.context['fav_coll']) == [coll]

        doc = pq(r.content)
        assert doc('#reviews.full').length == 0
        ul = doc('#my-collections #my-favorite')
        assert ul.length == 1

        li = ul.find('li')
        assert li.length == 1

        a = li.find('a')
        assert a.attr('href') == coll.get_url_path()
        assert a.text() == unicode(coll.name)

    def test_my_collections_created(self):
        coll = Collection.objects.listed().get(author=self.user)

        r = self.client.get(self.url)
        self.assertTemplateUsed(r, 'bandwagon/users/collection_list.html')
        assert len(r.context['own_coll']) == 1
        assert r.context['own_coll'][0] == coll

        doc = pq(r.content)
        assert doc('#reviews.full').length == 0
        ul = doc('#my-collections #my-created')
        assert ul.length == 1

        li = ul.find('li')
        assert li.length == 1

        a = li.find('a')
        assert a.attr('href') == coll.get_url_path()
        assert a.text() == unicode(coll.name)

    def test_no_my_collections(self):
        Collection.objects.filter(author=self.user).delete()
        r = self.client.get(self.url)
        self.assertTemplateNotUsed(r, 'bandwagon/users/collection_list.html')
        doc = pq(r.content)
        assert doc('#my-collections').length == 0
        assert doc('#reviews.full').length == 1

    def test_review_abuse_form(self):
        r = self.client.get(self.url)
        self.assertTemplateUsed(r, 'reviews/report_review.html')

    def test_user_abuse_form(self):
        abuse_url = reverse('users.abuse', args=[self.user.id])
        r = self.client.get(self.url)
        doc = pq(r.content)
        button = doc('#profile-actions #report-user-abuse')
        assert button.length == 1
        assert button.attr('href') == abuse_url
        modal = doc('#popup-staging #report-user-modal.modal')
        assert modal.length == 1
        assert modal('form').attr('action') == abuse_url
        assert modal('textarea[name=text]').length == 1
        self.assertTemplateUsed(r, 'users/report_abuse.html')

    def test_no_self_abuse(self):
        self.client.login(username='clouserw@gmail.com', password='password')
        r = self.client.get(self.url)
        doc = pq(r.content)
        assert doc('#profile-actions #report-user-abuse').length == 0
        assert doc('#popup-staging #report-user-modal.modal').length == 0
        self.assertTemplateNotUsed(r, 'users/report_abuse.html')


class TestThemesProfile(TestCase):
    fixtures = ['base/user_2519']

    def setUp(self):
        super(TestThemesProfile, self).setUp()
        self.user = UserProfile.objects.get(pk=2519)
        self.url = self.user.get_user_url('themes')

    def _test_good(self, res):
        assert res.status_code == 200

        ids = res.context['addons'].object_list.values_list('id', flat=True)
        self.assertSetEqual(set(ids), {self.theme.id})

        # The 2 following lines replace pq(res.content), it's a workaround for
        # https://github.com/gawel/pyquery/issues/31
        UTF8_PARSER = HTMLParser(encoding='utf-8')
        doc = pq(fromstring(res.content, parser=UTF8_PARSER))

        assert doc('.no-results').length == 0

        results = doc('.personas-grid .persona.hovercard')
        assert results.length == 1
        assert smart_unicode(
            results.find('h3').html()) == unicode(self.theme.name)

    def test_bad_user(self):
        res = self.client.get(reverse('users.themes', args=['yolo']))
        assert res.status_code == 404

    def test_no_themes(self):
        res = self.client.get(self.url)
        assert res.status_code == 200

        assert pq(res.content)('.no-results').length == 1

    def test_themes(self):
        self.theme = amo.tests.addon_factory(type=amo.ADDON_PERSONA)
        self.theme.addonuser_set.create(user=self.user, listed=True)

        res = self.client.get(self.url)
        self._test_good(res)

    def test_bad_category(self):
        res = self.client.get(reverse('users.themes', args=['yolo', 'swag']))
        assert res.status_code == 404

    def test_empty_category(self):
        self.theme = amo.tests.addon_factory(type=amo.ADDON_PERSONA)
        self.theme.addonuser_set.create(user=self.user, listed=True)
        cat = Category.objects.create(type=amo.ADDON_PERSONA, slug='swag')

        res = self.client.get(
            self.user.get_user_url('themes', args=[cat.slug]))
        assert res.status_code == 200

    def test_themes_category(self):
        self.theme = amo.tests.addon_factory(type=amo.ADDON_PERSONA)
        self.theme.addonuser_set.create(user=self.user, listed=True)
        cat = Category.objects.create(type=amo.ADDON_PERSONA, slug='swag')
        self.theme.addoncategory_set.create(category=cat)

        res = self.client.get(
            self.user.get_user_url('themes', args=[cat.slug]))
        self._test_good(res)


@patch.object(settings, 'NOBOT_RECAPTCHA_PRIVATE_KEY', 'something')
class TestReportAbuse(TestCase):
    fixtures = ['base/users']

    def setUp(self):
        super(TestReportAbuse, self).setUp()
        self.full_page = reverse('users.abuse', args=[10482])

    @patch('olympia.amo.fields.ReCaptchaField.clean')
    def test_abuse_anonymous(self, clean):
        clean.return_value = ""
        self.client.post(self.full_page, {'text': 'spammy'})
        assert len(mail.outbox) == 1
        assert 'spammy' in mail.outbox[0].body
        report = AbuseReport.objects.get(user=10482)
        assert report.message == 'spammy'
        assert report.reporter is None

    def test_abuse_anonymous_fails(self):
        r = self.client.post(self.full_page, {'text': 'spammy'})
        assert 'recaptcha' in r.context['abuse_form'].errors

    def test_abuse_logged_in(self):
        self.client.login(username='regular@mozilla.com', password='password')
        self.client.post(self.full_page, {'text': 'spammy'})
        assert len(mail.outbox) == 1
        assert 'spammy' in mail.outbox[0].body
        report = AbuseReport.objects.get(user=10482)
        assert report.message == 'spammy'
        assert report.reporter.email == 'regular@mozilla.com'

        r = self.client.get(self.full_page)
        assert pq(r.content)('.notification-box h2').length == 1


class BaseTestMigrateView(TestCase):
    fixtures = ['base/users']

    def setUp(self):
        super(BaseTestMigrateView, self).setUp()

    def login(self):
        username = 'regular@mozilla.com'
        self.client.login(username=username, password='password')
        return UserProfile.objects.get(email=username)

    def login_migrated(self):
        self.login().update(fxa_id='99')


class TestMigrateViewUnauthenticated(BaseTestMigrateView):

    def test_redirects_to_root_without_next_path(self):
        response = self.client.get(migrate_path())
        self.assertRedirects(response, reverse('home'))

    def test_redirects_to_root_with_unsafe_next_path(self):
        response = self.client.get(migrate_path('https://example.com/wat'))
        self.assertRedirects(response, reverse('home'))

    def test_redirects_to_next_with_safe_next_path(self):
        response = self.client.get(migrate_path('/en-US/firefox/a/place'))
        self.assertRedirects(
            response, '/en-US/firefox/a/place', target_status_code=404)


class TestMigrateViewNotMigrated(BaseTestMigrateView):

    def setUp(self):
        super(TestMigrateViewNotMigrated, self).setUp()
        self.login()

    def test_renders_the_prompt(self):
        response = self.client.get(migrate_path())
        assert response.status_code == 200
        assert 'Migrate to Firefox Accounts' in response.content
        doc = pq(response.content)
        assert doc('.skip-migrate-link a')[0].get('href') == reverse('home')

    def test_skip_link_goes_to_next_path_when_next_path_is_safe(self):
        response = self.client.get(migrate_path('/some/path'))
        assert response.status_code == 200
        assert 'Migrate to Firefox Accounts' in response.content
        doc = pq(response.content)
        assert doc('.skip-migrate-link a')[0].get('href') == '/some/path'

    def test_skip_link_goes_to_root_when_next_path_is_unsafe(self):
        response = self.client.get(
            migrate_path('https://example.com/some/path'))
        assert response.status_code == 200
        assert 'Migrate to Firefox Accounts' in response.content
        doc = pq(response.content)
        assert doc('.skip-migrate-link a')[0].get('href') == reverse('home')


class TestMigrateViewMigratedUser(BaseTestMigrateView):

    def setUp(self):
        super(TestMigrateViewMigratedUser, self).setUp()
        self.login_migrated()

    def test_redirects_to_root_when_migrated(self):
        response = self.client.get(migrate_path())
        self.assertRedirects(response, reverse('home'))

    def test_redirects_to_next_when_migrated_safe_next(self):
        response = self.client.get(migrate_path('/en-US/firefox/go/here'))
        self.assertRedirects(
            response, '/en-US/firefox/go/here', target_status_code=404)

    def test_redirects_to_root_when_migrated_unsafe_next(self):
        response = self.client.get(migrate_path('https://example.com/uh/oh'))
        self.assertRedirects(response, reverse('home'))


class TestDeleteProfilePicture(TestCase):
    fixtures = ['base/users']

    def setUp(self):
        super(TestDeleteProfilePicture, self).setUp()
        self.user = UserProfile.objects.get(pk=10482)
        self.url = reverse('users.delete_photo', args=[10482])
        assert self.user.picture_type

    def test_anon(self):
        self.client.logout()
        self.assertLoginRedirects(self.client.get(self.url), self.url)
        self.assertLoginRedirects(self.client.post(self.url), self.url)

    def test_not_admin(self):
        self.login(UserProfile.objects.get(pk=999))
        assert self.client.get(self.url).status_code == 403
        assert self.client.post(self.url).status_code == 403

    def test_mine_get(self):
        self.login(self.user)
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert response.context['user'] == self.user

    def test_mine_post(self):
        self.login(self.user)
        self.assert3xx(
            self.client.post(self.url),
            reverse('users.edit') + '#user-profile')
        assert not self.user.reload().picture_type

    def test_admin_get(self):
        self.login(UserProfile.objects.get(pk=4043307))
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert response.context['user'] == self.user

    def test_admin_post(self):
        self.admin = UserProfile.objects.get(pk=4043307)
        self.admin.update(picture_type='image/png')
        self.login(self.admin)
        self.assert3xx(
            self.client.post(self.url),
            reverse('users.admin_edit', kwargs={'user_id': 10482}) +
            '#user-profile')
        assert not self.user.reload().picture_type
        assert self.admin.reload().picture_type == 'image/png'
