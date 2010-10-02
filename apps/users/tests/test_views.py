import json

from django.core import mail
from django.core.cache import cache
from django.contrib.auth.models import User
from django.test.client import Client

import test_utils
from nose.tools import eq_

from access.models import Group, GroupUser
from amo.helpers import urlparams
from amo.pyquery_wrapper import PyQuery
from amo.urlresolvers import reverse
from users.utils import EmailResetCode


class UserViewBase(test_utils.TestCase):
    fixtures = ['users/test_backends']

    def setUp(self):
        self.client = Client()
        self.client.get('/')
        self.user = User.objects.get(id='4043307')
        self.user_profile = self.user.get_profile()


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

    def test_email_change_mail_sent(self):
        self.client.login(username='jbalogh@mozilla.com', password='foo')

        data = {'username': 'jbalogh',
                'email': 'jbalogh.changed@mozilla.com',
                'display_name': 'DJ SurfNTurf', }

        r = self.client.post('/en-US/firefox/users/edit', data, follow=True)
        self.assertContains(r, "An email has been sent to %s" % data['email'])

        # The email shouldn't change until they confirm, but the name should
        u = User.objects.get(id='4043307').get_profile()
        self.assertEquals(u.name, 'DJ SurfNTurf')
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

    def test_redirect(self):
        self.client.login(username='jbalogh@mozilla.com', password='foo')
        self.client.get('/', follow=True)
        url = '/en-US/firefox/about'
        r = self.client.get(urlparams(reverse('users.logout'), to=url),
                            follow=True)
        self.assertRedirects(r, url, status_code=302)


class TestRegistration(UserViewBase):

    def test_confirm(self):
        # User doesn't have a confirmation code
        url = reverse('users.confirm', args=[self.user.id, 'code'])
        r = self.client.get(url, follow=True)
        anon = PyQuery(r.content)('body').attr('data-anonymous')
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
        anon = PyQuery(r.content)('body').attr('data-anonymous')
        self.assertTrue(anon)

        self.user_profile.confirmationcode = "code"
        self.user_profile.save()

        # URL has the wrong confirmation code
        # TODO XXX: Bug 593055
        #url = reverse('users.confirm.resend', args=[self.user.id])
        #r = self.client.get(url, follow=True)
        #self.assertContains(r, 'An email has been sent to your address')


class TestProfile(UserViewBase):

    def test_edit_buttons(self):
        """Ensure admin/user edit buttons are shown."""

        def get_links(id):
            """Grab profile, return edit links."""
            url = reverse('users.profile', args=[id])
            r = self.client.get(url)
            return PyQuery(r.content)('p.editprofile a')

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
