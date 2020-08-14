# -*- coding: utf-8 -*-
import json

from unittest import mock

from pyquery import PyQuery as pq

from olympia import amo
from olympia.access.models import Group, GroupUser
from olympia.activity.models import ActivityLog
from olympia.amo.tests import TestCase, user_factory
from olympia.amo.tests.test_helpers import get_image_path
from olympia.amo.urlresolvers import reverse
from olympia.files.models import File, FileUpload
from olympia.users.models import UserProfile
from olympia.versions.models import Version


class TestHomeAndIndex(TestCase):
    fixtures = ['base/users']

    def setUp(self):
        super(TestHomeAndIndex, self).setUp()
        self.client.login(email='admin@mozilla.com')

    def test_get_home(self):
        url = reverse('zadmin.home')
        response = self.client.get(url, follow=True)
        assert response.status_code == 200
        assert response.context['user'].username == 'admin'
        assert response.context['user'].email == 'admin@mozilla.com'

    def test_get_index(self):
        # Add fake log that would be shown in the index page.
        user = UserProfile.objects.get(email='admin@mozilla.com')
        ActivityLog.create(
            amo.LOG.GROUP_USER_ADDED, user.groups.latest('pk'), user,
            user=user)
        url = reverse('zadmin.index')
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
        self.assert3xx(response, '/admin/models/login/?'
                                 'next=/en-US/admin/models/')

        # Redirected when logged in without enough permissions.
        user = user_factory(username='staffperson', email='staffperson@m.c')
        self.client.login(email='staffperson@m.c')
        response = self.client.get(url)
        self.assert3xx(response, '/admin/models/login/?'
                                 'next=/en-US/admin/models/')

        # Can access with a "is_staff" user.
        self.grant_permission(user, 'Admin:Something')
        response = self.client.get(url)
        assert response.status_code == 200
        doc = pq(response.content)
        modules = [x.text for x in doc('a.section')]
        # Admin:Something doesn't give access to anything, so they can log in
        # but they don't see any modules.
        assert len(modules) == 0

    @mock.patch('olympia.accounts.utils.default_fxa_login_url')
    def test_django_login_page(self, default_fxa_login_url):
        login_url = 'https://example.com/fxalogin'
        default_fxa_login_url.return_value = login_url
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
        self.client.login(email='staffperson@m.c')
        response = self.client.get(url)
        assert response.status_code == 403

        # But can access with a "is_staff" user.
        self.grant_permission(user, 'Admin:Tools')
        response = self.client.get(url)
        self.assert3xx(response, '/en-US/admin/models/')

    @mock.patch('olympia.accounts.utils.default_fxa_login_url')
    def test_django_login_page_with_next(self, default_fxa_login_url):
        login_url = 'https://example.com/fxalogin'
        default_fxa_login_url.return_value = login_url

        # if django admin passes on a next param, check we use it.
        url = reverse('admin:login') + '?next=/en-US/admin/models/addon/'
        response = self.client.get(url)
        # redirect to the correct page
        self.assert3xx(response, '/en-US/admin/models/addon/')

        # Same with an "is_staff" user.
        user = user_factory(username='staffperson', email='staffperson@m.c')
        self.client.login(email='staffperson@m.c')
        self.grant_permission(user, 'Admin:Tools')
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
        self.client.login(email='admin@mozilla.com')

    @mock.patch.object(File, 'file_path',
                       amo.tests.AMOPaths().file_fixture_path(
                           'delicious_bookmarks-2.1.106-fx.xpi'))
    def test_regenerate_hash(self):
        version = Version.objects.create(addon_id=3615)
        file = File.objects.create(
            filename='delicious_bookmarks-2.1.106-fx.xpi', version=version)

        r = self.client.post(reverse('zadmin.recalc_hash', args=[file.id]))
        assert json.loads(r.content)[u'success'] == 1

        file = File.objects.get(pk=file.id)

        assert file.size, 'File size should not be zero'
        assert file.hash, 'File hash should not be empty'

    @mock.patch.object(File, 'file_path',
                       amo.tests.AMOPaths().file_fixture_path(
                           'delicious_bookmarks-2.1.106-fx.xpi'))
    def test_regenerate_hash_get(self):
        """ Don't allow GET """
        version = Version.objects.create(addon_id=3615)
        file = File.objects.create(
            filename='delicious_bookmarks-2.1.106-fx.xpi', version=version)

        r = self.client.get(reverse('zadmin.recalc_hash', args=[file.id]))
        assert r.status_code == 405  # GET out of here


class TestFileDownload(TestCase):
    fixtures = ['base/users']

    def setUp(self):
        super(TestFileDownload, self).setUp()

        assert self.client.login(email='admin@mozilla.com')

        self.file = open(get_image_path('animated.png'), 'rb')
        resp = self.client.post(reverse('devhub.upload'),
                                {'upload': self.file})
        assert resp.status_code == 302

        self.upload = FileUpload.objects.get()
        self.url = reverse(
            'zadmin.download_file_upload', args=[self.upload.uuid.hex])

    def test_download(self):
        """Test that downloading file_upload objects works."""
        resp = self.client.get(self.url)
        assert resp.status_code == 200
        assert resp.content == self.file.read()


class TestPerms(TestCase):
    fixtures = ['base/users']

    FILE_ID = '1234567890abcdef1234567890abcdef'

    def assert_status(self, view, status, **kw):
        """Check that requesting the named view returns the expected status."""

        assert self.client.get(reverse(view, kwargs=kw)).status_code == status

    def test_admin_user(self):
        # Admin should see views with Django's perm decorator and our own.
        assert self.client.login(email='admin@mozilla.com')
        self.assert_status('zadmin.index', 200)
        self.assert_status(
            'zadmin.download_file_upload', 404, uuid=self.FILE_ID)

    def test_staff_user(self):
        # Staff users have some privileges.
        user = UserProfile.objects.get(email='regular@mozilla.com')
        group = Group.objects.create(name='Staff', rules='Admin:Tools')
        GroupUser.objects.create(group=group, user=user)
        assert self.client.login(email='regular@mozilla.com')
        self.assert_status('zadmin.index', 200)
        self.assert_status(
            'zadmin.download_file_upload', 404, uuid=self.FILE_ID)

    def test_unprivileged_user(self):
        # Unprivileged user.
        assert self.client.login(email='regular@mozilla.com')
        self.assert_status('zadmin.index', 403)
        self.assert_status(
            'zadmin.download_file_upload', 403, uuid=self.FILE_ID)
        # Anonymous users should also get a 403.
        self.client.logout()
        self.assertLoginRedirects(
            self.client.get(reverse('zadmin.index')), to='/en-US/admin/')
