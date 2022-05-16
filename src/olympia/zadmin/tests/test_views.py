from unittest import mock

from django.http import HttpResponseRedirect
from django.urls import reverse

from pyquery import PyQuery as pq

from olympia.access.models import Group, GroupUser
from olympia.addons.models import Addon
from olympia.amo.tests import TestCase, user_factory, version_factory
from olympia.files.models import File
from olympia.users.models import UserProfile


class TestHomeAndIndex(TestCase):
    fixtures = ['base/users']

    def setUp(self):
        super().setUp()
        self.client.login(email='admin@mozilla.com')

    def test_get_home(self):
        url = reverse('admin:index')
        response = self.client.get(url, follow=True)
        assert response.status_code == 200
        assert response.context['user'].username == 'admin'
        assert response.context['user'].email == 'admin@mozilla.com'

    def test_django_index(self):
        # Can access with full admin.
        url = reverse('admin:index')
        response = self.client.get(url)
        assert response.status_code == 200
        doc = pq(response.content)
        modules = [x.text for x in doc('a.section')]
        assert len(modules) == 20  # Increment as we add new admin modules.

        # Redirected because no permissions if not logged in.
        self.client.logout()
        response = self.client.get(url)
        self.assert3xx(response, '/en-US/admin/models/login/?next=/en-US/admin/models/')

        # Redirected when logged in without enough permissions.
        user = user_factory(username='staffperson', email='staffperson@m.c')
        self.client.login(email=user.email)
        response = self.client.get(url)
        self.assert3xx(response, '/en-US/admin/models/login/?next=/en-US/admin/models/')

        # Can access with a "is_staff" user.
        user.update(email='someone@mozilla.com')
        self.client.login(email=user.email)
        response = self.client.get(url)
        assert response.status_code == 200
        doc = pq(response.content)
        modules = [x.text for x in doc('a.section')]
        # Admin:Something doesn't give access to anything, so they can log in
        # but they don't see any modules.
        assert len(modules) == 0

    @mock.patch('olympia.zadmin.admin.redirect_for_login')
    def test_django_login_page(self, redirect_for_login):
        login_url = 'https://example.com/fxalogin'
        redirect_for_login.return_value = HttpResponseRedirect(login_url)
        # Check we can actually access the /login page - django admin uses it.
        url = reverse('admin:login')
        response = self.client.get(url)
        # if you're already logged in, redirect to the index
        self.assert3xx(response, '/en-US/admin/models/')

        # Redirected to fxa because no permissions if not logged in.
        self.client.logout()
        response = self.client.get(url)
        self.assert3xx(response, login_url)

        # But if logged in and not enough permissions return a 403.
        user = user_factory(username='staffperson', email='staffperson@m.c')
        self.client.login(email=user.email)
        response = self.client.get(url)
        assert response.status_code == 403

        # But can access with a "is_staff" user.
        user.update(email='someone@mozilla.com')
        response = self.client.get(url)
        self.assert3xx(response, '/en-US/admin/models/')

    @mock.patch('olympia.zadmin.admin.redirect_for_login')
    def test_django_login_page_with_next(self, redirect_for_login):
        login_url = 'https://example.com/fxalogin'
        redirect_for_login.return_value = HttpResponseRedirect(login_url)

        # if django admin passes on a next param, check we use it.
        url = reverse('admin:login') + '?next=/en-US/admin/models/addon/'
        response = self.client.get(url)
        # redirect to the correct page
        self.assert3xx(response, '/en-US/admin/models/addon/')

        # Same with an "is_staff" user.
        user = user_factory(email='someone@mozilla.com')
        self.client.login(email=user.email)
        response = self.client.get(url)
        self.assert3xx(response, '/en-US/admin/models/addon/')

    def test_django_admin_logout(self):
        url = reverse('admin:logout')
        response = self.client.get(url, follow=False)
        self.assert3xx(response, '/', status_code=302)


class TestRecalculateHash(TestCase):
    fixtures = ['base/addon_3615', 'base/users']

    def setUp(self):
        super().setUp()
        self.addon = Addon.objects.get(pk=3615)
        self.client.login(email='admin@mozilla.com')

    def test_regenerate_hash(self):
        file = version_factory(
            addon=self.addon, file_kw={'filename': 'https-everywhere.xpi'}
        ).file

        response = self.client.post(reverse('zadmin.recalc_hash', args=[file.id]))
        assert response.json()['success'] == 1

        file = File.objects.get(pk=file.id)

        assert file.size, 'File size should not be zero'
        assert file.hash, 'File hash should not be empty'

    def test_regenerate_hash_get(self):
        """Don't allow GET"""
        file = version_factory(
            addon=self.addon, file_kw={'filename': 'https-everywhere.xpi'}
        ).file
        response = self.client.get(reverse('zadmin.recalc_hash', args=[file.id]))
        assert response.status_code == 405  # GET out of here


class TestPerms(TestCase):
    fixtures = ['base/users']

    FILE_ID = '1234567890abcdef1234567890abcdef'

    def assert_status(self, view, status, follow=False, **kw):
        """Check that requesting the named view returns the expected status."""

        assert (
            self.client.get(reverse(view, kwargs=kw), follow=follow).status_code
            == status
        )

    def test_admin_user(self):
        # Admin should see views with Django's perm decorator and our own.
        assert self.client.login(email='admin@mozilla.com')
        self.assert_status('admin:index', 200, follow=True)

    def test_staff_user(self):
        # Staff users have some privileges.
        user = UserProfile.objects.get(email='regular@mozilla.com')
        group = Group.objects.create(name='Staff', rules='Admin:*')
        GroupUser.objects.create(group=group, user=user)
        assert self.client.login(email='regular@mozilla.com')
        self.assert_status('admin:index', 200, follow=True)

    def test_unprivileged_user(self):
        # Unprivileged user.
        assert self.client.login(email='clouserw@gmail.com')
        self.assert_status('admin:index', 403, follow=True)
        # Anonymous users should get a login redirect.
        self.client.logout()
        self.assert3xx(
            self.client.get(reverse('admin:index')),
            '/en-US/admin/models/login/?next=/en-US/admin/models/',
        )
