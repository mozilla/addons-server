from django.conf import settings
from django.utils.encoding import force_text
from django.utils.http import urlquote

from olympia import amo
from olympia.amo.tests import TestCase, addon_factory, user_factory
from olympia.amo.urlresolvers import reverse
from olympia.amo.templatetags.jinja_helpers import user_media_url
from olympia.amo.utils import urlparams


class TestFileAdmin(TestCase):
    def setUp(self):
        self.list_url = reverse('admin:files_file_changelist')

    def test_can_list_files_with_admin_advanced_permission(self):
        addon = addon_factory()
        file_ = addon.current_version.all_files[0]
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Admin:Advanced')
        self.client.login(email=user.email)
        response = self.client.get(self.list_url, follow=True)
        assert response.status_code == 200
        assert str(file_.pk) in force_text(response.content)

    def test_can_edit_with_admin_advanced_permission(self):
        addon = addon_factory()
        file_ = addon.current_version.all_files[0]
        detail_url = reverse(
            'admin:files_file_change', args=(file_.pk,)
        )
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Admin:Advanced')
        self.client.login(email=user.email)
        response = self.client.get(detail_url, follow=True)
        assert response.status_code == 200
        assert str(file_.id) in force_text(response.content)

        assert not file_.is_webextension

        post_data = {
            'version': file_.version.pk,
            'platform': file_.platform,
            'filename': file_.filename,
            'size': file_.size,
            'hash': 'xxx',
            'original_hash': 'xxx',
            'status': file_.status,
            'original_status': file_.original_status,
        }
        post_data['is_webextension'] = 'on'
        response = self.client.post(detail_url, post_data, follow=True)
        assert response.status_code == 200
        file_.refresh_from_db()
        assert file_.is_webextension

    def test_can_not_list_without_admin_advanced_permission(self):
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.client.login(email=user.email)
        response = self.client.get(self.list_url, follow=True)
        assert response.status_code == 403

        # Just checking that simply changing the permission resolves
        # as wanted
        self.grant_permission(user, 'Admin:Advanced')
        response = self.client.get(self.list_url, follow=True)
        assert response.status_code == 200

    def test_detail_view_has_download_link(self):
        addon = addon_factory()
        file_ = addon.current_version.all_files[0]
        detail_url = reverse(
            'admin:files_file_change', args=(file_.pk,)
        )
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Admin:Advanced')
        self.client.login(email=user.email)
        response = self.client.get(detail_url, follow=True)
        assert response.status_code == 200

        expected_url = reverse('admin:files_file_download', args=(file_.pk,))
        assert expected_url in force_text(response.content)

    def test_download_view(self):
        """Regular listed files are served through the CDN"""
        addon = addon_factory()
        file_ = addon.current_version.all_files[0]
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Admin:Advanced')
        self.client.login(email=user.email)

        download_url = reverse('admin:files_file_download', args=(file_.pk,))
        response = self.client.get(download_url, follow=False)
        assert response.status_code == 302

        path = user_media_url('addons')

        assert response.url == (
            urlparams('%s%s/%s' % (
                path, addon.id, urlquote(file_.filename)
            ), filehash=file_.hash))
        assert response['X-Target-Digest'] == file_.hash

    def test_download_view_disabled_file(self):
        """Disabled files are not served through the CDN"""
        addon = addon_factory()
        file_ = addon.current_version.all_files[0]
        file_.update(status=amo.STATUS_DISABLED)
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Admin:Advanced')

        # The default add-on  created by `addon_factory` is listed
        # and we still require proper reviewers permission
        self.grant_permission(user, 'Addons:ReviewListed')
        self.grant_permission(user, 'Addons:Review')

        self.client.login(email=user.email)

        download_url = reverse('admin:files_file_download', args=(file_.pk,))
        response = self.client.get(download_url, follow=True)
        assert response.status_code == 200
        assert response[settings.XSENDFILE_HEADER]
        assert response['Content-Type'] == 'application/x-xpinstall'

    def test_download_view_disabled_file_permission_denied(self):
        """Disabled files are not served through the CDN"""
        addon = addon_factory()
        file_ = addon.current_version.all_files[0]
        file_.update(status=amo.STATUS_DISABLED)
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')

        self.client.login(email=user.email)

        download_url = reverse('admin:files_file_download', args=(file_.pk,))
        response = self.client.get(download_url, follow=True)
        assert response.status_code == 404

    def test_download_view_listed_public_file_permission_denied(self):
        """Disabled files are not served through the CDN"""
        addon = addon_factory()
        file_ = addon.current_version.all_files[0]
        file_.update()
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')

        self.client.login(email=user.email)

        download_url = reverse('admin:files_file_download', args=(file_.pk,))
        response = self.client.get(download_url, follow=True)
        assert response.status_code == 404
