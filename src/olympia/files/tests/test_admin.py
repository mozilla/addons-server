import json

from django.urls import reverse
from django.utils.encoding import force_str

from pyquery import PyQuery as pq

from olympia.amo.tests import TestCase, addon_factory, user_factory
from olympia.files.models import FileManifest, FileValidation, WebextPermission


class TestFileAdmin(TestCase):
    def setUp(self):
        self.list_url = reverse('admin:files_file_changelist')

    def test_can_list_files_with_admin_advanced_permission(self):
        addon = addon_factory()
        file_ = addon.current_version.file
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Admin:Advanced')
        self.client.force_login(user)
        response = self.client.get(self.list_url, follow=True)
        assert response.status_code == 200
        assert str(file_.pk) in force_str(response.content)

    def test_can_edit_with_admin_advanced_permission(self):
        addon = addon_factory(file_kw={'filename': 'webextension.xpi'})
        file_ = addon.current_version.file
        detail_url = reverse('admin:files_file_change', args=(file_.pk,))
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Admin:Advanced')
        self.client.force_login(user)
        response = self.client.get(detail_url, follow=True)
        assert response.status_code == 200
        assert str(file_.id) in force_str(response.content)

        assert file_.status == 4

        post_data = {
            'version': file_.version.pk,
            'size': file_.size,
            'hash': 'xxx',
            'original_hash': 'xxx',
            'status': 5,
            'original_status': file_.original_status,
            'status_disabled_reason': file_.status_disabled_reason,
            'manifest_version': 3,
            'validation-TOTAL_FORMS': '0',
            'validation-INITIAL_FORMS': '0',
            'validation-MIN_NUM_FORMS': '0',
            'validation-MAX_NUM_FORMS': '1000',
            'file_manifest-TOTAL_FORMS': '0',
            'file_manifest-INITIAL_FORMS': '0',
            'file_manifest-MIN_NUM_FORMS': '0',
            'file_manifest-MAX_NUM_FORMS': '1000',
            '_webext_permissions-TOTAL_FORMS': '0',
            '_webext_permissions-INITIAL_FORMS': '0',
            '_webext_permissions-MIN_NUM_FORMS': '0',
            '_webext_permissions-MAX_NUM_FORMS': '1000',
        }
        response = self.client.post(detail_url, post_data, follow=True)
        assert response.status_code == 200
        file_.refresh_from_db()
        assert file_.status == 5

    def test_can_not_list_without_admin_advanced_permission(self):
        user = user_factory(email='someone@mozilla.com')
        self.client.force_login(user)
        response = self.client.get(self.list_url, follow=True)
        assert response.status_code == 403

        # Just checking that simply changing the permission resolves
        # as wanted
        self.grant_permission(user, 'Admin:Advanced')
        response = self.client.get(self.list_url, follow=True)
        assert response.status_code == 200

    def test_detail_view_has_download_link(self):
        addon = addon_factory()
        file_ = addon.current_version.file
        detail_url = reverse('admin:files_file_change', args=(file_.pk,))
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Admin:Advanced')
        self.client.force_login(user)
        response = self.client.get(detail_url, follow=True)
        assert response.status_code == 200

        expected_url = file_.get_absolute_url(attachment=True)
        assert expected_url in force_str(response.content)

    def test_can_see_validation_manifest_and_permissions(self):
        addon = addon_factory()
        file_ = addon.current_version.file
        FileValidation.objects.create(file=file_, validation=json.dumps({'foo': 'bar'}))
        WebextPermission.objects.create(
            file=file_, permissions=['something', 'https://example.org']
        )
        FileManifest.objects.create(file=file_, manifest_data={'prop': 'value'})

        detail_url = reverse('admin:files_file_change', args=(file_.pk,))
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Admin:Advanced')
        self.client.force_login(user)
        response = self.client.get(detail_url, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#_webext_permissions-group .field-permissions').text() == (
            'Permissions:\n["something", "https://example.org"]'
        )
        assert doc('#validation-group .field-validation').text() == (
            'Validation:\n{"foo": "bar"}'
        )
        assert doc('#file_manifest-group .field-manifest_data').text() == (
            'Manifest data:\n{"prop": "value"}'
        )
