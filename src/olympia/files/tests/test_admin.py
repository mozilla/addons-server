from django.utils.encoding import force_text

from olympia.amo.tests import TestCase, addon_factory, user_factory
from olympia.amo.urlresolvers import reverse


class TestFileAdmin(TestCase):
    def setUp(self):
        self.list_url = reverse('admin:files_file_changelist')

    def test_can_list_files_with_admin_advanced_permission(self):
        addon = addon_factory()
        file_ = addon.current_version.all_files[0]
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Admin:Advanced')
        self.client.login(email=user.email)
        response = self.client.get(self.list_url, follow=True)
        assert response.status_code == 200
        assert str(file_.pk) in force_text(response.content)

    def test_can_edit_with_admin_advanced_permission(self):
        addon = addon_factory()
        file_ = addon.current_version.all_files[0]
        detail_url = reverse('admin:files_file_change', args=(file_.pk,))
        user = user_factory(email='someone@mozilla.com')
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
        file_ = addon.current_version.all_files[0]
        detail_url = reverse('admin:files_file_change', args=(file_.pk,))
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Admin:Advanced')
        self.client.login(email=user.email)
        response = self.client.get(detail_url, follow=True)
        assert response.status_code == 200

        expected_url = file_.get_absolute_url(attachment=True)
        assert expected_url in force_text(response.content)
