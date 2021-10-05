from django.urls import reverse
from django.utils.encoding import force_str

from olympia.amo.tests import TestCase, addon_factory, user_factory


class TestFileAdmin(TestCase):
    def setUp(self):
        self.list_url = reverse('admin:files_file_changelist')

    def test_can_list_files_with_admin_advanced_permission(self):
        addon = addon_factory()
        file_ = addon.current_version.file
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Admin:Advanced')
        self.client.login(email=user.email)
        response = self.client.get(self.list_url, follow=True)
        assert response.status_code == 200
        assert str(file_.pk) in force_str(response.content)

    def test_can_edit_with_admin_advanced_permission(self):
        addon = addon_factory()
        file_ = addon.current_version.file
        detail_url = reverse('admin:files_file_change', args=(file_.pk,))
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Admin:Advanced')
        self.client.login(email=user.email)
        response = self.client.get(detail_url, follow=True)
        assert response.status_code == 200
        assert str(file_.id) in force_str(response.content)

        assert file_.manifest_version == 2

        post_data = {
            'version': file_.version.pk,
            'filename': file_.filename,
            'size': file_.size,
            'hash': 'xxx',
            'original_hash': 'xxx',
            'status': file_.status,
            'original_status': file_.original_status,
            'manifest_version': 3,
        }
        response = self.client.post(detail_url, post_data, follow=True)
        assert response.status_code == 200
        file_.refresh_from_db()
        assert file_.manifest_version == 3

    def test_can_not_list_without_admin_advanced_permission(self):
        user = user_factory(email='someone@mozilla.com')
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
        file_ = addon.current_version.file
        detail_url = reverse('admin:files_file_change', args=(file_.pk,))
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Admin:Advanced')
        self.client.login(email=user.email)
        response = self.client.get(detail_url, follow=True)
        assert response.status_code == 200

        expected_url = file_.get_absolute_url(attachment=True)
        assert expected_url in force_str(response.content)
