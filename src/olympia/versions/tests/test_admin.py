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
        install_origin1 = InstallOrigin.objects.create(
            version=addon_factory().current_version,
            origin='https://one.example.com',
            base_domain='one.example.com',
        )
        install_origin2 = InstallOrigin.objects.create(
            version=addon_factory().current_version,
            origin='https://two.example.com',
            base_domain='two.example.com',
        )
        install_origin3 = InstallOrigin.objects.create(
            version=addon_factory().current_version,
            origin='https://three.example.com',
            base_domain='three.example.com',
        )
        list_url = reverse('admin:versions_installorigin_changelist')
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, '*:*')
        self.client.login(email=user.email)
        with self.assertNumQueries(7):
            # - 2 SAVEPOINTs
            # - 2 user & groups
            # - 2 counts (total + pagination)
            # - 1 install origins
            response = self.client.get(list_url, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        assert len(doc('#result_list tbody tr')) == 3
        assert doc('#result_list tbody tr:eq(2)').text() == '\n'.join(
            [
                str(install_origin1.id),
                install_origin1.version.addon.guid,
                install_origin1.version.version,
                install_origin1.origin,
                install_origin1.base_domain,
            ]
        )
        assert doc('#result_list tbody tr:eq(1)').text() == '\n'.join(
            [
                str(install_origin2.id),
                install_origin2.version.addon.guid,
                install_origin2.version.version,
                install_origin2.origin,
                install_origin2.base_domain,
            ]
        )
        assert doc('#result_list tbody tr:eq(0)').text() == '\n'.join(
            [
                str(install_origin3.id),
                install_origin3.version.addon.guid,
                install_origin3.version.version,
                install_origin3.origin,
                install_origin3.base_domain,
            ]
        )

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
