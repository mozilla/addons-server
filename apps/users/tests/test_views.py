import json

from django.conf import settings
from django.core import mail
from django.core.cache import cache
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.test.client import Client
from django.utils.http import int_to_base36

import test_utils
from mock import patch
from nose.tools import eq_

from access.models import Group, GroupUser
from addons.models import Addon, AddonUser
import amo
from amo.helpers import urlparams
from amo.pyquery_wrapper import PyQuery as pq
from amo.urlresolvers import reverse
from amo.tests.test_helpers import AbuseBase
from users.models import BlacklistedPassword, UserProfile, UserNotification
import users.notifications as email
from users.utils import EmailResetCode


class UserViewBase(test_utils.TestCase):
    fixtures = ['users/test_backends']

    def setUp(self):
        self.client = Client()
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
        self.impala_url = reverse('users.edit_impala')
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

        res = self.client.post(self.impala_url, post)
        eq_(res.status_code, 302)

        eq_(UserNotification.objects.count(), len(email.NOTIFICATION))
        eq_(UserNotification.objects.filter(enabled=True).count(), 3)

        res = self.client.get(self.impala_url, post)
        doc = pq(res.content)
        eq_(doc('[name=notifications]:checked').length, 3)


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

    def test_login_no_recaptcha(self):
        res = self.client.post(self.url, data=self.data)
        eq_(res.status_code, 302)

    @patch('ratelimit.backends.cachebe.CacheBackend.limit')
    def test_login_recaptcha(self, limit):
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
        self.client.login(username='jbalogh@mozilla.com', password='foo')
        r = self.client.get('/', follow=True)
        self.assertContains(r, "Welcome, Jeff")

        r = self.client.get('/users/logout', follow=True)
        self.assertNotContains(r, "Welcome, Jeff")
        self.assertContains(r, "Log in")

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
        # TODO XXX POSTREMORA: Uncomment when remora goes away
        #url = reverse('users.confirm', args=[self.user.id, 'blah'])
        #r = self.client.get(url, follow=True)
        #self.assertContains(r, 'Invalid confirmation code!')

        # URL has the right confirmation code
        # TODO XXX POSTREMORA: Uncomment when remora goes away
        #url = reverse('users.confirm', args=[self.user.id, 'code'])
        #r = self.client.get(url, follow=True)
        #self.assertContains(r, 'Successfully verified!')

    def test_confirm_resend(self):
        # User doesn't have a confirmation code
        url = reverse('users.confirm.resend', args=[self.user.id])
        r = self.client.get(url, follow=True)
        anon = pq(r.content)('body').attr('data-anonymous')
        self.assertTrue(anon)

        self.user_profile.confirmationcode = "code"
        self.user_profile.save()

        # URL has the wrong confirmation code
        # TODO XXX: Bug 593055
        #url = reverse('users.confirm.resend', args=[self.user.id])
        #r = self.client.get(url, follow=True)
        #self.assertContains(r, 'An email has been sent to your address')


class TestProfile(UserViewBase):
    fixtures = ['base/featured',
                'users/test_backends']

    def test_edit_buttons(self):
        """Ensure admin/user edit buttons are shown."""

        def get_links(id):
            """Grab profile, return edit links."""
            url = reverse('users.profile', args=[id])
            r = self.client.get(url)
            return pq(r.content)('p.editprofile a')

        # Anonymous user.
        links = get_links(self.user.id)
        eq_(links.length, 0)

        # Non-admin, someone else's profile.
        self.client.login(username='jbalogh@mozilla.com', password='foo')
        links = get_links(9945)
        eq_(links.length, 0)

        # Non-admin, own profile.
        links = get_links(self.user.id)
        eq_(links.length, 1)
        eq_(links.eq(0).attr('href'), reverse('users.edit'))

        # Admin, someone else's profile.
        admingroup = Group(rules='Admin:EditAnyUser')
        admingroup.save()
        GroupUser.objects.create(group=admingroup, user=self.user_profile)
        cache.clear()

        # TODO XXX Uncomment this when zamboni can delete users. Bug 595035
        #links = get_links(9945)
        #eq_(links.length, 1)
        #eq_(links.eq(0).attr('href'),
        #reverse('admin:users_userprofile_change', args=[9945]))

        # TODO XXX Uncomment this when zamboni can delete users. Bug 595035
        # Admin, own profile.
        #links = get_links(self.user.id)
        #eq_(links.length, 2)
        #eq_(links.eq(0).attr('href'), reverse('users.edit'))
        #eq_(links.eq(1).attr('href'),
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

    def test_profile_addons_sort(self):
        u = UserProfile.objects.get(id=9945)

        for a in Addon.objects.public():
            AddonUser.objects.create(user=u, addon=a)

        r = self.client.get(reverse('users.profile', args=[9945]))
        addons = r.context['addons'].object_list
        assert all(addons[i].weekly_downloads >= addons[i + 1].weekly_downloads
                   for i in xrange(len(addons) - 1))


class TestReportAbuse(AbuseBase, test_utils.TestCase):
    fixtures = ['base/users']

    def setUp(self):
        settings.RECAPTCHA_PRIVATE_KEY = 'something'
        self.full_page = reverse('users.abuse', args=[10482])
