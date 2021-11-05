from django.urls import reverse

from pyquery import PyQuery as pq

from olympia.amo.tests import TestCase, addon_factory, user_factory
from olympia.versions.models import InstallOrigin


class TestVersionAdmin(TestCase):
    def test_authorized_user_has_access(self):
        addon = addon_factory()
        version = addon.current_version
        detail_url = reverse('admin:versions_version_change', args=(version.pk,))
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Admin:Advanced')
        self.client.login(email=user.email)
        response = self.client.get(detail_url, follow=True)
        assert response.status_code == 200

        doc = pq(response.content)
        assert doc('textarea#id_release_notes_0').length == 1

    def test_unauthorized_user_has_no_access(self):
        addon = addon_factory()
        version = addon.current_version
        detail_url = reverse('admin:versions_version_change', args=(version.pk,))
        user = user_factory(email='someone@mozilla.com')
        self.client.login(email=user.email)
        response = self.client.get(detail_url, follow=True)
        assert response.status_code == 403


class TestInstallOriginAdmin(TestCase):
    def test_list(self):
        list_url = reverse('admin:versions_installorigin_changelist')
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, '*:*')
        self.client.login(email=user.email)
        response = self.client.get(list_url, follow=True)
        assert response.status_code == 200

    def test_add_disabled(self):
        add_url = reverse('admin:versions_installorigin_add')
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, '*:*')
        self.client.login(email=user.email)
        response = self.client.get(add_url, follow=True)
        assert response.status_code == 403

    def test_delete_disabled(self):
        install_origin = InstallOrigin.objects.create(
            version=addon_factory().current_version,
            origin='https://example.com',
            base_domain='example.com',
        )
        delete_url = reverse(
            'admin:versions_installorigin_delete', args=(install_origin.pk,)
        )
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, '*:*')
        self.client.login(email=user.email)
        response = self.client.get(delete_url, follow=True)
        assert response.status_code == 403

    def test_only_readonly_fields(self):
        install_origin = InstallOrigin.objects.create(
            version=addon_factory().current_version,
            origin='https://example.com',
            base_domain='example.com',
        )
        detail_url = reverse(
            'admin:versions_installorigin_change', args=(install_origin.pk,)
        )
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, '*:*')
        self.client.login(email=user.email)
        response = self.client.get(detail_url, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#installorigin_form')
        assert not doc('#installorigin_form input:not([type=hidden])')
