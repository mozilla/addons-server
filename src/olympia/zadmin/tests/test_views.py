# -*- coding: utf-8 -*-
import json
import os


from django.conf import settings

from unittest import mock

from pyquery import PyQuery as pq

import olympia

from olympia import amo
from olympia.access.models import Group, GroupUser
from olympia.activity.models import ActivityLog
from olympia.addons.models import Addon
from olympia.amo.tests import TestCase, user_factory, version_factory
from olympia.amo.tests.test_helpers import get_image_path
from olympia.amo.urlresolvers import reverse
from olympia.amo.utils import urlparams
from olympia.files.models import File, FileUpload
from olympia.users.models import UserProfile
from olympia.versions.models import Version


SHORT_LIVED_CACHE_PARAMS = settings.CACHES.copy()
SHORT_LIVED_CACHE_PARAMS['default']['TIMEOUT'] = 2


ZADMIN_TEST_FILES = os.path.join(
    os.path.dirname(olympia.__file__),
    'zadmin', 'tests', 'resources')


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


class TestLookup(TestCase):
    fixtures = ['base/users']

    def setUp(self):
        super(TestLookup, self).setUp()
        assert self.client.login(email='admin@mozilla.com')
        self.user = UserProfile.objects.get(pk=999)
        self.url = reverse('zadmin.search', args=['users', 'userprofile'])

    def test_logged_out(self):
        self.client.logout()
        assert self.client.get('%s?q=admin' % self.url).status_code == 403

    def check_results(self, q, expected):
        res = self.client.get(urlparams(self.url, q=q))
        assert res.status_code == 200
        content = json.loads(res.content)
        assert len(content) == len(expected)
        ids = [int(c['value']) for c in content]
        emails = [u'%s' % c['label'] for c in content]
        for d in expected:
            id = d['value']
            email = u'%s' % d['label']
            assert id in ids, (
                'Expected user ID "%s" not found' % id)
            assert email in emails, (
                'Expected username "%s" not found' % email)

    def test_lookup_wrong_model(self):
        self.url = reverse('zadmin.search', args=['doesnt', 'exist'])
        res = self.client.get(urlparams(self.url, q=''))
        assert res.status_code == 404

    def test_lookup_empty(self):
        users = UserProfile.objects.values('id', 'email')
        self.check_results('', [dict(
            value=u['id'], label=u['email']) for u in users])

    def test_lookup_by_id(self):
        self.check_results(self.user.id, [dict(value=self.user.id,
                                               label=self.user.email)])

    def test_lookup_by_email(self):
        self.check_results(self.user.email, [dict(value=self.user.id,
                                                  label=self.user.email)])

    def test_lookup_by_username(self):
        self.check_results(self.user.username, [dict(value=self.user.id,
                                                     label=self.user.email)])


class TestAddonSearch(amo.tests.ESTestCase):
    fixtures = ['base/users', 'base/addon_3615']

    def setUp(self):
        super(TestAddonSearch, self).setUp()
        self.reindex(Addon)
        assert self.client.login(email='admin@mozilla.com')
        self.url = reverse('zadmin.addon-search')

    def test_lookup_addon(self):
        res = self.client.get(urlparams(self.url, q='delicious'))
        # There's only one result, so it should just forward us to that page.
        assert res.status_code == 302


class TestAddonAdmin(TestCase):
    fixtures = ['base/users', 'base/addon_3615']

    def setUp(self):
        super(TestAddonAdmin, self).setUp()
        assert self.client.login(email='admin@mozilla.com')
        self.url = reverse('admin:addons_addon_changelist')

    def test_basic(self):
        res = self.client.get(self.url)
        doc = pq(res.content)
        rows = doc('#result_list tbody tr')
        assert rows.length == 1
        assert rows.find('a').attr('href') == (
            '/en-US/admin/models/addons/addon/3615/change/')


class TestAddonManagement(TestCase):
    fixtures = ['base/addon_3615', 'base/users']

    def setUp(self):
        super(TestAddonManagement, self).setUp()
        self.addon = Addon.objects.get(pk=3615)
        self.url = reverse('zadmin.addon_manage', args=[self.addon.slug])
        self.client.login(email='admin@mozilla.com')

    def test_can_manage_unlisted_addons(self):
        """Unlisted addons can be managed too."""
        self.make_addon_unlisted(self.addon)
        assert self.client.get(self.url).status_code == 200

    def test_addon_mixed_channels(self):
        first_version = self.addon.current_version
        second_version = version_factory(
            addon=self.addon, channel=amo.RELEASE_CHANNEL_UNLISTED)
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)

        first_expected_review_link = reverse(
            'reviewers.review', args=(self.addon.slug,))
        elms = doc('a[href="%s"]' % first_expected_review_link)
        assert len(elms) == 1
        assert elms[0].attrib['title'] == str(first_version.pk)
        assert elms[0].text == first_version.version

        second_expected_review_link = reverse(
            'reviewers.review', args=('unlisted', self.addon.slug,))
        elms = doc('a[href="%s"]' % second_expected_review_link)
        assert len(elms) == 1
        assert elms[0].attrib['title'] == str(second_version.pk)
        assert elms[0].text == second_version.version

    def _form_data(self, data=None):
        initial_data = {
            'status': '4',
            'form-0-status': '4',
            'form-0-id': '67442',
            'form-TOTAL_FORMS': '1',
            'form-INITIAL_FORMS': '1',
        }
        if data:
            initial_data.update(data)
        return initial_data

    def test_addon_status_change(self):
        data = self._form_data({'status': '3'})
        r = self.client.post(self.url, data, follow=True)
        assert r.status_code == 200
        addon = Addon.objects.get(pk=3615)
        assert addon.status == 3

    def test_addon_file_status_change(self):
        data = self._form_data({'form-0-status': '1'})
        r = self.client.post(self.url, data, follow=True)
        assert r.status_code == 200
        file = File.objects.get(pk=67442)
        assert file.status == 1

    def test_addon_deleted_file_status_change(self):
        file = File.objects.get(pk=67442)
        file.version.update(deleted=True)
        data = self._form_data({'form-0-status': '1'})
        r = self.client.post(self.url, data, follow=True)
        # Form errors are silently suppressed.
        assert r.status_code == 200
        # But no change.
        assert file.status == 4


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
        self.assert_status('zadmin.addon-search', 200)

    def test_staff_user(self):
        # Staff users have some privileges.
        user = UserProfile.objects.get(email='regular@mozilla.com')
        group = Group.objects.create(name='Staff', rules='Admin:Tools')
        GroupUser.objects.create(group=group, user=user)
        assert self.client.login(email='regular@mozilla.com')
        self.assert_status('zadmin.index', 200)
        self.assert_status(
            'zadmin.download_file_upload', 404, uuid=self.FILE_ID)
        self.assert_status('zadmin.addon-search', 200)

    def test_unprivileged_user(self):
        # Unprivileged user.
        assert self.client.login(email='regular@mozilla.com')
        self.assert_status('zadmin.index', 403)
        self.assert_status(
            'zadmin.download_file_upload', 403, uuid=self.FILE_ID)
        self.assert_status('zadmin.addon-search', 403)
        # Anonymous users should also get a 403.
        self.client.logout()
        self.assertLoginRedirects(
            self.client.get(reverse('zadmin.index')), to='/en-US/admin/')
