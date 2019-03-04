from pyquery import PyQuery as pq

from olympia.amo.tests import TestCase, addon_factory, user_factory
from olympia.amo.urlresolvers import reverse


class TestVersionAdmin(TestCase):

    def test_detail_view_has_download_link(self):
        addon = addon_factory()
        version = addon.current_version
        detail_url = reverse(
            'admin:versions_version_change', args=(version.pk,)
        )
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Admin:Advanced')
        self.client.login(email=user.email)
        response = self.client.get(detail_url, follow=True)
        assert response.status_code == 200

        doc = pq(response.content)
        assert doc('textarea#id_release_notes').length == 1
