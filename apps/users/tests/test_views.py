from datetime import datetime, timedelta
import json

from django.conf import settings
from django.core import mail
from django.core.cache import cache
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.forms.models import model_to_dict
from django.utils.http import int_to_base36

from mock import patch
from nose.tools import eq_
from nose import SkipTest
import waffle

import amo
import amo.tests
from abuse.models import AbuseReport
from access.models import Group, GroupUser
from addons.models import Addon, AddonUser, AddonPremium
from amo.helpers import urlparams
from amo.pyquery_wrapper import PyQuery as pq
from amo.urlresolvers import reverse
from bandwagon.models import Collection, CollectionWatcher
from devhub.models import ActivityLog
from market.models import Price
from reviews.models import Review
from stats.models import Contribution
from users.models import BlacklistedPassword, UserProfile, UserNotification
import users.notifications as email
from users.utils import EmailResetCode, UnsubscribeCode
from webapps.models import Installed


class UserViewBase(amo.tests.TestCase):
    fixtures = ['users/test_backends']

    def setUp(self):
        self.client = amo.tests.TestClient()
        self.client.get('/')
        self.user = User.objects.get(id='4043307')
        self.user_profile = self.get_profile()

    def get_profile(self):
        return UserProfile.objects.get(id=self.user.id)


class TestAjax(UserViewBase):

    def test_ajax(self):
        url = reverse('users.ajax') + '?q=fligtar@gmail.com'
        self.client.login(username='jbalogh@mozilla.com', password='foo')
        r = self.client.get(url, follow=True)
        data = json.loads(r.content)
        eq_(data['id'], 9945)
        eq_(data['name'], u'Justin Scott \u0627\u0644\u062a\u0637\u0628')

    def test_forbidden(self):
        url = reverse('users.ajax')
        r = self.client.get(url)
        eq_(r.status_code, 401)


class TestEdit(UserViewBase):

    def setUp(self):
        super(TestEdit, self).setUp()
        self.client.login(username='jbalogh@mozilla.com', password='foo')
        self.user = UserProfile.objects.get(username='jbalogh')
        self.url = reverse('users.edit')
        self.correct = {'username': 'jbalogh', 'email': 'jbalogh@mozilla.com',
                        'oldpassword': 'foo', 'password': 'longenough',
                        'password2': 'longenough'}

    def test_password_logs(self):
        res = self.client.post(self.url, self.correct)
        eq_(res.status_code, 302)
        eq_(self.user.userlog_set
                .filter(activity_log__action=amo.LOG.CHANGE_PASSWORD.id)
                .count(), 1)

    def test_password_empty(self):
        admingroup = Group(rules='Admin:EditAnyUser')
        admingroup.save()
        GroupUser.objects.create(group=admingroup, user=self.user)
        homepage = {'username': 'jbalogh', 'email': 'jbalogh@mozilla.com',
                    'homepage': 'http://cbc.ca'}
        res = self.client.post(self.url, homepage)
        eq_(res.status_code, 302)

    def test_password_blacklisted(self):
        BlacklistedPassword.objects.create(password='password')
        bad = self.correct.copy()
        bad['password'] = 'password'
        res = self.client.post(self.url, bad)
        eq_(res.status_code, 200)
        eq_(res.context['form'].is_valid(), False)
        eq_(res.context['form'].errors['password'],
            [u'That password is not allowed.'])

    def test_password_short(self):
        bad = self.correct.copy()
        bad['password'] = 'short'
        res = self.client.post(self.url, bad)
        eq_(res.status_code, 200)
        eq_(res.context['form'].is_valid(), False)
        eq_(res.context['form'].errors['password'],
            [u'Must be 8 characters or more.'])

    def test_email_change_mail_sent(self):
        data = {'username': 'jbalogh',
                'email': 'jbalogh.changed@mozilla.com',
                'display_name': 'DJ SurfNTurf', }

        r = self.client.post(self.url, data, follow=True)
        self.assertRedirects(r, self.url)
        self.assertContains(r, "An email has been sent to %s" % data['email'])

        # The email shouldn't change until they confirm, but the name should
        u = User.objects.get(id='4043307').get_profile()
        self.assertEquals(u.name, 'DJ SurfNTurf')
        self.assertEquals(u.email, 'jbalogh@mozilla.com')

        eq_(len(mail.outbox), 1)
        assert mail.outbox[0].subject.find('Please confirm your email') == 0
        assert mail.outbox[0].body.find('%s/emailchange/' % self.user.id) > 0

    def test_edit_bio(self):
        eq_(self.get_profile().bio, None)

        data = {'username': 'jbalogh',
                'email': 'jbalogh.changed@mozilla.com',
                'bio': 'xxx unst unst'}

        r = self.client.post(self.url, data, follow=True)
        self.assertRedirects(r, self.url)
        self.assertContains(r, data['bio'])
        eq_(unicode(self.get_profile().bio), data['bio'])

        data['bio'] = 'yyy unst unst'
        r = self.client.post(self.url, data, follow=True)
        self.assertRedirects(r, self.url)
        self.assertContains(r, data['bio'])
        eq_(unicode(self.get_profile().bio), data['bio'])

    def test_edit_notifications(self):
        post = self.correct.copy()
        post['notifications'] = [2, 4, 6]

        # Make jbalogh a developer
        addon = Addon.objects.create(type=amo.ADDON_EXTENSION)
        AddonUser.objects.create(user=self.user, addon=addon)

        res = self.client.post(self.url, post)
        eq_(res.status_code, 302)

        mandatory = [n.id for n in email.NOTIFICATIONS if n.mandatory]
        total = len(post['notifications'] + mandatory)
        eq_(UserNotification.objects.count(), len(email.NOTIFICATION))
        eq_(UserNotification.objects.filter(enabled=True).count(), total)

        res = self.client.get(self.url, post)
        doc = pq(res.content)
        eq_(doc('[name=notifications]:checked').length, total)

        eq_(doc('.more-none').length, len(email.NOTIFICATION_GROUPS))
        eq_(doc('.more-all').length, len(email.NOTIFICATION_GROUPS))

    def test_edit_notifications_non_dev(self):
        post = self.correct.copy()
        post['notifications'] = [2, 4, 6]

        res = self.client.post(self.url, post)
        assert len(res.context['form'].errors['notifications'])


class TestEditAdmin(UserViewBase):
    fixtures = ['base/users']

    def setUp(self):
        self.client.login(username='admin@mozilla.com', password='password')
        self.regular = self.get_user()
        self.url = reverse('users.admin_edit', args=[self.regular.pk])

    def get_data(self):
        data = model_to_dict(self.regular)
        data['admin_log'] = 'test'
        for key in ['password', 'resetcode_expires']:
            del data[key]
        return data

    def get_user(self):
        # Using pk so that we can still get the user after anonymize.
        return UserProfile.objects.get(pk=999)

    def test_edit(self):
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
        data['nickname'] = ''
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


class TestPasswordAdmin(UserViewBase):
    fixtures = ['base/users']

    def setUp(self):
        self.client.login(username='editor@mozilla.com', password='password')
        self.url = reverse('users.edit')
        self.correct = {'username': 'editor',
                        'email': 'editor@mozilla.com',
                        'oldpassword': 'password', 'password': 'longenough',
                        'password2': 'longenough'}

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
        self.assertEqual(self.user_profile.email, 'jbalogh@mozilla.com')
        url = reverse('users.emailchange', args=[self.user.id, self.token,
                                                 self.hash])
        r = self.client.get(url, follow=True)
        eq_(r.status_code, 200)
        u = User.objects.get(id=self.user.id).get_profile()
        self.assertEqual(u.email, 'nobody@mozilla.org')


class TestLogin(UserViewBase):
    fixtures = ['users/test_backends', 'base/addon_3615']

    def setUp(self):
        super(TestLogin, self).setUp()
        self.url = reverse('users.login')
        self.data = {'username': 'jbalogh@mozilla.com', 'password': 'foo'}

    def test_client_login(self):
        """
        This is just here to make sure Test Client's login() works with
        our custom code.
        """
        assert not self.client.login(username='jbalogh@mozilla.com',
                                     password='wrong')
        assert self.client.login(**self.data)

    def test_double_login(self):
        r = self.client.post(self.url, self.data, follow=True)
        self.assertRedirects(r, '/en-US/firefox/')

        # If you go to the login page when you're already logged in we bounce
        # you.
        r = self.client.get(self.url, follow=True)
        self.assertRedirects(r, '/en-US/firefox/')

        r = self.client.get(self.url + '?to=/de/firefox/', follow=True)
        self.assertRedirects(r, '/de/firefox/')

        r = self.client.get(self.url + '?to=http://xx.com', follow=True)
        self.assertRedirects(r, '/en-US/firefox/')

    def test_login_ajax(self):
        url = reverse('users.login_modal')
        r = self.client.get(url)
        eq_(r.status_code, 200)

        res = self.client.post(url, data=self.data)
        eq_(res.status_code, 302)

    @patch.object(waffle, 'switch_is_active', lambda x: True)
    def test_login_paypal(self):
        addon = Addon.objects.all()[0]
        price = Price.objects.create(price='0.99')
        AddonPremium.objects.create(addon=addon, price=price)
        addon.update(premium_type=amo.ADDON_PREMIUM)

        url = reverse('addons.purchase.start', args=[addon.slug])
        r = self.client.get_ajax(url)
        eq_(r.status_code, 200)

        res = self.client.post_ajax(url, data=self.data)
        eq_(res.status_code, 200)

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

    @patch('ratelimit.backends.cachebe.CacheBackend.limit')
    def test_login_recaptcha(self, limit):
        raise SkipTest
        limit.return_value = True
        res = self.client.post(self.url, data=self.data)
        eq_(res.status_code, 403)

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
        # It increment even when the form is wrong.
        user = UserProfile.objects.filter(email=self.data['username'])
        eq_(user.get().failed_login_attempts, 3)
        self.client.post(self.url, data={'username': self.data['username']})
        eq_(user.get().failed_login_attempts, 4)

    @patch.object(waffle, 'switch_is_active', lambda x: True)
    @patch('httplib2.Http.request')
    def test_browserid_login_success(self, http_request):
        """
        A success response from BrowserID results in successful login.
        """
        url = reverse('users.browserid_login')
        http_request.return_value = (200, json.dumps({'status': 'okay',
                                          'email': 'jbalogh@mozilla.com'}))
        res = self.client.post(url, data=dict(assertion='fake-assertion',
                                              audience='fakeamo.org'))
        eq_(res.status_code, 200)

        # If they're already logged in we return fast.
        eq_(self.client.post(url).status_code, 200)

    def _make_admin_user(self, email):
        """
        Create a user with at least one admin privilege.
        """
        p = UserProfile(username='admin', email=email,
                        password='hunter2', created=datetime.now(), pk=998)
        p.create_django_user()
        admingroup = Group.objects.create(rules='Admin:EditAnyUser')
        GroupUser.objects.create(group=admingroup, user=p)

    @patch.object(waffle, 'switch_is_active', lambda x: True)
    @patch('httplib2.Http.request')
    def test_browserid_restricted_login(self, http_request):
        """
        A success response from BrowserID for accounts restricted to
        password login results in a 400 error, for which the frontend
        will display a message about the restriction.
        """
        email = 'admin@mozilla.com'
        http_request.return_value = (200, json.dumps({'status': 'okay',
                                          'email': email}))
        self._make_admin_user(email)
        res = self.client.post(reverse('users.browserid_login'),
                               data=dict(assertion='fake-assertion',
                                         audience='fakeamo.org'))
        eq_(res.status_code, 400)

    @patch.object(waffle, 'switch_is_active', lambda x: True)
    @patch('httplib2.Http.request')
    def test_browserid_no_account(self, http_request):
        """
        BrowserID login for an email address with no account creates a
        new account.
        """
        email = 'newuser@example.com'
        http_request.return_value = (200, json.dumps({'status': 'okay',
                                                      'email': email}))
        res = self.client.post(reverse('users.browserid_login'),
                               data=dict(assertion='fake-assertion',
                                         audience='fakeamo.org'))
        eq_(res.status_code, 200)
        profiles = UserProfile.objects.filter(email=email)
        eq_(len(profiles), 1)
        eq_(profiles[0].username, 'newuser')

    @patch.object(waffle, 'switch_is_active', lambda x: True)
    @patch('httplib2.Http.request')
    def test_browserid_login_failure(self, http_request):
        """
        A failure response from BrowserID results in login failure.
        """
        http_request.return_value = (200, json.dumps({'status': 'busted'}))
        res = self.client.post(reverse('users.browserid_login'),
                               data=dict(assertion='fake-assertion',
                                         audience='fakeamo.org'))
        eq_(res.status_code, 401)


class TestUnsubscribe(UserViewBase):
    fixtures = ['base/users']

    def setUp(self):
        self.user = User.objects.get(email='editor@mozilla.com')
        self.user_profile = self.user.get_profile()

    def test_correct_url_update_notification(self):
        # Make sure the user is subscribed
        perm_setting = email.NOTIFICATIONS[0]
        un = UserNotification.objects.create(notification_id=perm_setting.id,
                                             user=self.user_profile,
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
        user = User.objects.get(email='editor@mozilla.com').get_profile()
        self.token = [int_to_base36(user.id),
                      default_token_generator.make_token(user)]

    def test_reset_msg(self):
        res = self.client.get(reverse('users.pwreset_confirm',
                                       args=self.token))
        assert 'For your account' in res.content

    def test_reset_fails(self):
        res = self.client.post(reverse('users.pwreset_confirm',
                                       args=self.token),
                               data={'new_password1': 'spassword',
                                     'new_password2': 'spassword'})
        eq_(res.context['form'].errors['new_password1'][0],
            'Letters and numbers required.')


class TestLogout(UserViewBase):

    def test_success(self):
        user = UserProfile.objects.get(email='jbalogh@mozilla.com')
        self.client.login(username=user.email, password='foo')
        r = self.client.get('/', follow=True)
        eq_(pq(r.content.decode('utf-8'))('.account .user').text(),
            user.display_name)
        eq_(pq(r.content)('.account .user').attr('title'), user.email)

        r = self.client.get('/users/logout', follow=True)
        assert not pq(r.content)('.account .user')

    def test_redirect(self):
        self.client.login(username='jbalogh@mozilla.com', password='foo')
        self.client.get('/', follow=True)
        url = '/en-US/firefox/about'
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
        url = urlparams(reverse('users.logout'), to='/en-US/firefox/about',
                        domain='http://evil.com')
        r = self.client.get(url, follow=True)
        self.assertRedirects(r, '/en-US/firefox/about', status_code=302)


class TestRegistration(UserViewBase):

    def test_confirm(self):
        # User doesn't have a confirmation code
        url = reverse('users.confirm', args=[self.user.id, 'code'])
        r = self.client.get(url, follow=True)
        anon = pq(r.content)('body').attr('data-anonymous')
        self.assertTrue(anon)

        self.user_profile.confirmationcode = "code"
        self.user_profile.save()

        # URL has the wrong confirmation code
        url = reverse('users.confirm', args=[self.user.id, 'blah'])
        r = self.client.get(url, follow=True)
        self.assertContains(r, 'Invalid confirmation code!')

        # URL has the right confirmation code
        url = reverse('users.confirm', args=[self.user.id, 'code'])
        r = self.client.get(url, follow=True)
        self.assertContains(r, 'Successfully verified!')

    def test_confirm_resend(self):
        # User doesn't have a confirmation code
        url = reverse('users.confirm.resend', args=[self.user.id])
        r = self.client.get(url, follow=True)
        anon = pq(r.content)('body').attr('data-anonymous')
        self.assertTrue(anon)

        self.user_profile.confirmationcode = "code"
        self.user_profile.save()

        # URL has the wrong confirmation code
        url = reverse('users.confirm.resend', args=[self.user.id])
        r = self.client.get(url, follow=True)
        self.assertContains(r, 'An email has been sent to your address')


class TestProfileLinks(UserViewBase):
    fixtures = ['base/featured', 'users/test_backends']

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
        self.client.login(username='jbalogh@mozilla.com', password='foo')
        links = get_links(9945)
        eq_(links.length, 1)
        eq_(links.eq(0).attr('href'), reverse('users.abuse', args=[9945]))

        # Non-admin, own profile.
        links = get_links(self.user.id)
        eq_(links.length, 1)
        eq_(links.eq(0).attr('href'), reverse('users.edit'))

        # Admin, someone else's profile.
        admingroup = Group(rules='Admin:EditAnyUser')
        admingroup.save()
        GroupUser.objects.create(group=admingroup, user=self.user_profile)
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
        self.client.login(username='jbalogh@mozilla.com', password='foo')
        response = self.client.get(reverse('home'))
        request = response.context['request']
        assert hasattr(request.amo_user, 'mobile_addons')
        assert hasattr(request.user.get_profile(), 'mobile_addons')
        assert hasattr(request.amo_user, 'favorite_addons')
        assert hasattr(request.user.get_profile(), 'favorite_addons')


class TestProfileSections(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/users', 'base/addon_3615',
                'base/addon_5299_gcal', 'base/collections',
                'reviews/dev-reply.json']

    def setUp(self):
        self.user = UserProfile.objects.get(id=10482)
        self.url = reverse('users.profile', args=[self.user.id])

    def test_my_addons(self):
        AddonUser.objects.create(user=self.user, addon_id=3615)
        AddonUser.objects.create(user=self.user, addon_id=5299)

        r = self.client.get(self.url)
        a = r.context['addons'].object_list
        eq_(list(a), sorted(a, key=lambda x: x.weekly_downloads, reverse=True))

        doc = pq(r.content)
        eq_(doc('.num-addons a[href="#my-addons"]').length, 1)
        items = doc('#my-addons .item')
        eq_(items.length, 2)
        eq_(items('.install[data-addon=3615]').length, 1)
        eq_(items('.install[data-addon=5299]').length, 1)

    def test_my_reviews(self):
        r = Review.objects.filter(reply_to=None)[0]
        r.user_id = self.user.id
        r.save()
        cache.clear()
        eq_(list(self.user.reviews), [r])

        r = self.client.get(self.url)
        doc = pq(r.content)('#reviews')
        assert not doc.hasClass('full'), (
            'reviews should not have "full" class when there are collections')
        eq_(doc('.item').length, 1)
        eq_(doc('#review-218207').length, 1)

        # Edit Review form should be present.
        self.assertTemplateUsed(r, 'reviews/edit_review.html')

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
        eq_(list(r.context['own_coll']), list(coll))

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


class TestReportAbuse(amo.tests.TestCase):
    fixtures = ['base/users']

    def setUp(self):
        settings.RECAPTCHA_PRIVATE_KEY = 'something'
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


class TestPurchases(amo.tests.TestCase):
    fixtures = ['base/users']

    def setUp(self):
        waffle.models.Switch.objects.create(name='marketplace', active=True)

        self.url = reverse('users.purchases')
        self.client.login(username='regular@mozilla.com', password='password')
        self.user = User.objects.get(email='regular@mozilla.com')

        self.addon, self.con = None, None
        for x in range(1, 5):
            price = Price.objects.create(price=10 - x)
            addon = Addon.objects.create(type=amo.ADDON_EXTENSION,
                                         name='t%s' % x,
                                         guid='t%s' % x)
            AddonPremium.objects.create(price=price, addon=addon)
            con = Contribution.objects.create(user=self.user.get_profile(),
                                              addon=addon, amount='%s.00' % x,
                                              type=amo.CONTRIB_PURCHASE,
                                              created=datetime(2011, 10, 1))
            con.created = datetime.now() - timedelta(days=10 - x)
            con.save()
            if not self.addon and not self.con:
                self.addon, self.con = addon, con

    def test_in_menu(self):
        doc = pq(self.client.get(self.url).content)
        assert 'My Purchases' in doc('li.account li').text()

    def test_in_side_menu(self):
        raise SkipTest
        doc = pq(self.client.get(self.url).content)
        assert 'My Purchases' in doc('div.secondary li').text()

    def test_not_purchase(self):
        self.client.logout()
        eq_(self.client.get(self.url).status_code, 302)

    def test_no_purchases(self):
        Contribution.objects.all().delete()
        Installed.objects.all().delete()
        res = self.client.get(self.url)
        eq_(res.status_code, 200)

    def test_purchase_list(self):
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        eq_(len(res.context['addons'].object_list), 4)

    def get_order(self, order):
        res = self.client.get('%s?sort=%s' % (self.url, order))
        return [str(c.name) for c in
                res.context['addons'].object_list]

    def test_ordering(self):
        eq_(self.get_order('name'), ['t1', 't2', 't3', 't4'])
        eq_(self.get_order('price'), ['t4', 't3', 't2', 't1'])

    def test_price(self):
        res = self.client.get(self.url)
        assert '$1.00' in pq(res.content)('div.vitals').eq(0).text()

    def test_price_locale(self):
        res = self.client.get(self.url.replace('/en-US', '/fr'))
        assert u'1,00' in pq(res.content)('div.vitals').eq(0).text()

    def test_receipt(self):
        res = self.client.get(reverse('users.purchases.receipt',
                              args=[self.addon.pk]))
        eq_(len(res.context['addons'].object_list), 1)
        eq_(res.context['addons'].object_list[0].pk, self.addon.pk)

    def test_receipt_404(self):
        url = reverse('users.purchases.receipt', args=[545])
        eq_(self.client.get(url).status_code, 404)

    def test_receipt_view(self):
        res = self.client.get(reverse('users.purchases.receipt',
                              args=[self.addon.pk]))
        eq_(pq(res.content)('#sorter').text(), 'Show all purchases')

    def test_purchases_attribute(self):
        doc = pq(self.client.get(self.url).content)
        ids = list(Addon.objects.values_list('pk', flat=True).order_by('pk'))
        eq_(doc('body').attr('data-purchases'),
            ','.join([str(i) for i in ids]))

    def test_no_purchases_attribute(self):
        self.user.get_profile().addonpurchase_set.all().delete()
        doc = pq(self.client.get(self.url).content)
        eq_(doc('body').attr('data-purchases'), '')

    def test_refund_link(self):
        doc = pq(self.client.get(self.url).content)
        url = reverse('users.support', args=[self.con.pk])
        eq_(doc('div.vitals a').eq(0).attr('href'), url)

    def get_url(self, *args):
        return reverse('users.support', args=[self.con.pk] + list(args))

    def test_support_not_logged_in(self):
        self.client.logout()
        eq_(self.client.get(self.get_url()).status_code, 302)

    def test_support_not_mine(self):
        self.client.login(username='admin@mozilla.com', password='password')
        eq_(self.client.get(self.get_url()).status_code, 404)

    def test_support_page(self):
        doc = pq(self.client.get(self.get_url()).content)
        eq_(doc('section.primary a').attr('href'), self.get_url('author'))

    def test_support_page_other(self):
        self.addon.support_url = 'http://cbc.ca'
        self.addon.save()

        doc = pq(self.client.get(self.get_url()).content)
        eq_(doc('section.primary a').attr('href'), self.get_url('site'))

    def test_support_site(self):
        self.addon.support_url = 'http://cbc.ca'
        self.addon.save()

        doc = pq(self.client.get(self.get_url('site')).content)
        eq_(doc('section.primary a').attr('href'), self.addon.support_url)

    def test_contact(self):
        data = {'text': 'Lorem ipsum dolor sit amet, consectetur'}
        res = self.client.post(self.get_url('author'), data)
        eq_(res.status_code, 302)

    def test_contact_mails(self):
        self.addon.support_email = 'a@a.com'
        self.addon.save()

        data = {'text': 'Lorem ipsum dolor sit amet, consectetur'}
        self.client.post(self.get_url('author'), data)
        eq_(len(mail.outbox), 1)
        email = mail.outbox[0]
        eq_(email.to, ['a@a.com'])
        eq_(email.from_email, 'regular@mozilla.com')

    def test_contact_fails(self):
        res = self.client.post(self.get_url('author'), {'b': 'c'})
        assert 'text' in res.context['form'].errors

    def test_contact_mozilla(self):
        data = {'text': 'Lorem ipsum dolor sit amet, consectetur'}
        res = self.client.post(self.get_url('mozilla'), data)
        eq_(res.status_code, 302)

    def test_contact_mozilla_mails(self):
        data = {'text': 'Lorem ipsum dolor sit amet, consectetur'}
        self.client.post(self.get_url('mozilla'), data)
        eq_(len(mail.outbox), 1)
        email = mail.outbox[0]
        eq_(email.to, [settings.FLIGTAR])
        eq_(email.from_email, 'regular@mozilla.com')
        assert 'Lorem' in email.body

    def test_contact_mozilla_fails(self):
        res = self.client.post(self.get_url('mozilla'), {'b': 'c'})
        assert 'text' in res.context['form'].errors

    def test_refund_remove(self):
        res = self.client.post(self.get_url('request'), {'remove': 1})
        eq_(res.status_code, 302)

    def test_refund_remove_fails(self):
        res = self.client.post(self.get_url('request'), {})
        eq_(res.status_code, 200)

    def test_skip_fails(self):
        res = self.client.post(self.get_url('reason'), {})
        self.assertRedirects(res, self.get_url('request'))

    def test_request(self):
        self.client.post(self.get_url('request'), {'remove': 1})
        res = self.client.post(self.get_url('reason'), {'text': 'something'})
        eq_(res.status_code, 302)

    def test_request_mails(self):
        self.addon.support_email = 'a@a.com'
        self.addon.save()

        self.client.post(self.get_url('request'), {'remove': 1})
        self.client.post(self.get_url('reason'), {'text': 'something'})
        eq_(len(mail.outbox), 1)
        email = mail.outbox[0]
        eq_(email.to, ['a@a.com'])
        eq_(email.from_email, 'regular@mozilla.com')
        assert '$1.00' in email.body

    def test_request_fails(self):
        self.addon.support_email = 'a@a.com'
        self.addon.save()

        self.client.post(self.get_url('request'), {'remove': 1})
        res = self.client.post(self.get_url('reason'), {})
        eq_(res.status_code, 200)

    def test_free_shows_up(self):
        Contribution.objects.all().delete()
        res = self.client.get(self.url)
        eq_(res.context['addons'][0].pk, self.addon.pk)

    def test_others_free_dont(self):
        Contribution.objects.all().delete()
        other = UserProfile.objects.get(pk=10482)
        Installed.objects.all()[0].update(user=other)
        res = self.client.get(self.url)
        eq_(len(res.context['addons']), 3)

    def test_purchase_multiple(self):
        Contribution.objects.create(user=self.user.get_profile(),
                                    addon=self.addon, amount='1.00',
                                    type=amo.CONTRIB_PURCHASE)
        res = self.client.get(self.url)
        addon_vitals = pq(res.content)('div.vitals').eq(0)
        eq_(len(addon_vitals('div.purchase-byline')), 2)

    def make_contribution(self, addon, amt, type, day):
        return Contribution.objects.create(
            user=self.user.get_profile(), addon=addon,
            amount=amt, type=type, created=datetime(2011, 10, day))

    def test_refunded(self):
        addon = Addon.objects.get(type=amo.ADDON_EXTENSION,
                                  guid='t1')
        self.make_contribution(addon, "-1.00", amo.CONTRIB_REFUND, 2)
        doc = pq(self.client.get(self.url).content)
        firstitem = doc('.items')[0][0]
        assert 'refunded' in firstitem.get('class')
        eq_(firstitem[0].get('class'), 'refund-notice')

    def test_repurchased(self):
        addon = Addon.objects.get(type=amo.ADDON_EXTENSION,
                                  guid='t1')
        self.make_contribution(addon, "-1.00", amo.CONTRIB_REFUND, 2)
        self.make_contribution(addon, "1.00", amo.CONTRIB_PURCHASE, 3)
        doc = pq(self.client.get(self.url).content)
        firstitem = doc('.items')[0][0]
        assert 'refunded' not in firstitem.get('class')
        assert not doc('.items .refund-notice')
        purchaselines = doc('.vitals')[0]
        assert 'Request Support' in purchaselines.text_content()

    def test_rerefunded(self):
        addon = Addon.objects.get(type=amo.ADDON_EXTENSION,
                                  guid='t1')
        self.make_contribution(addon, "-1.00", amo.CONTRIB_REFUND, 2)
        self.make_contribution(addon, "1.00", amo.CONTRIB_PURCHASE, 3)
        self.make_contribution(addon, "-1.00", amo.CONTRIB_REFUND, 4)
        doc = pq(self.client.get(self.url).content)
        firstitem = doc('.items')[0][0]
        assert 'refunded' in firstitem.get('class')
        eq_(firstitem[0].get('class'), 'refund-notice')
        purchaselines = doc('.vitals')[0]
        assert 'Request Support' not in purchaselines.text_content()
