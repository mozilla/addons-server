from django.contrib.admin.sites import AdminSite

from pyquery import PyQuery as pq

from olympia.amo.tests import TestCase, addon_factory, user_factory
from olympia.amo.urlresolvers import reverse
from olympia.git.admin import GitExtractionEntryAdmin
from olympia.git.models import GitExtractionEntry


class TestGitExtractionEntryAdmin(TestCase):
    def setUp(self):
        super().setUp()

        self.user = user_factory()
        self.grant_permission(self.user, 'Admin:GitExtractionEdit')
        self.client.login(email=self.user.email)
        self.list_url = reverse('admin:git_gitextractionentry_changelist')

        self.admin = GitExtractionEntryAdmin(
            model=GitExtractionEntry, admin_site=AdminSite()
        )

    def test_has_add_permission(self):
        assert self.admin.has_add_permission(request=None) is False

    def test_has_change_permission(self):
        assert self.admin.has_change_permission(request=None) is False

    def test_list_view(self):
        GitExtractionEntry.objects.create(addon=addon_factory())

        # 9 queries:
        # - 2 transaction savepoints because of tests
        # - 2 request user and groups
        # - 2 COUNT(*) on extraction entries for pagination and total display
        # - 1 all git extraction entries in one query
        # - 1 all add-ons in one query
        # - 1 all add-ons translations in one query
        with self.assertNumQueries(9):
            response = self.client.get(self.list_url)

        assert response.status_code == 200
        html = pq(response.content)
        assert html('.column-id').length == 1

    def test_list_view_is_restricted(self):
        user = user_factory()
        self.grant_permission(user, 'Admin:Curation')
        self.client.login(email=user.email)
        response = self.client.get(self.list_url)
        assert response.status_code == 403

    def test_formatted_addon(self):
        addon = addon_factory()
        entry = GitExtractionEntry.objects.create(addon=addon)

        formatted_addon = self.admin.formatted_addon(entry)

        assert (
            reverse('admin:addons_addon_change', args=(addon.pk,))
            in formatted_addon
        )
        assert str(addon.name) in formatted_addon
