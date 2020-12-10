from pyquery import PyQuery as pq

from olympia.amo.tests import TestCase, addon_factory, user_factory
from olympia.amo.urlresolvers import reverse


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
