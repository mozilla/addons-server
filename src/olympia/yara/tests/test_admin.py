from django.contrib.admin.sites import AdminSite

from pyquery import PyQuery as pq

from olympia.amo.tests import TestCase, addon_factory, user_factory
from olympia.amo.urlresolvers import reverse
from olympia.yara.admin import YaraResultAdmin, MatchesFilter
from olympia.yara.models import YaraResult


class TestYaraResultAdmin(TestCase):
    def setUp(self):
        super().setUp()

        self.user = user_factory()
        self.grant_permission(self.user, 'Admin:Advanced')
        self.client.login(email=self.user.email)
        self.list_url = reverse('admin:yara_yararesult_changelist')

        self.admin = YaraResultAdmin(model=YaraResult, admin_site=AdminSite())

    def test_list_view(self):
        response = self.client.get(self.list_url)
        assert response.status_code == 200

    def test_list_view_is_restricted(self):
        user = user_factory()
        self.grant_permission(user, 'Admin:Curation')
        self.client.login(email=user.email)
        response = self.client.get(self.list_url)
        assert response.status_code == 403

    def test_has_add_permission(self):
        assert self.admin.has_add_permission(request=None) is False

    def test_list_queries(self):
        YaraResult.objects.create(version=addon_factory().current_version)
        YaraResult.objects.create(version=addon_factory().current_version)
        YaraResult.objects.create(version=addon_factory().current_version)

        with self.assertNumQueries(9):
            # 9 queries:
            # - 2 transaction savepoints because of tests
            # - 2 user and groups
            # - 2 COUNT(*) on yara results for pagination and total display
            # - 1 yara results and versions in one query
            # - 1 all add-ons in one query
            # - 1 all add-ons translations in one query
            response = self.client.get(self.list_url, {
                MatchesFilter.parameter_name: 'all',
            })
        assert response.status_code == 200
        html = pq(response.content)
        expected_length = YaraResult.objects.count()
        assert html('#result_list tbody tr').length == expected_length
