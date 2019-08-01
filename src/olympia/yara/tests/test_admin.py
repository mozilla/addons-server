import json

from django.contrib.admin.sites import AdminSite
from django.utils.html import format_html

from olympia import amo
from olympia.amo.tests import (TestCase, addon_factory, user_factory,
                               version_factory)
from olympia.amo.urlresolvers import reverse
from olympia.yara.admin import YaraResultAdmin
from olympia.yara.models import YaraResult


class TestYaraResultAdmin(TestCase):
    def setUp(self):
        super().setUp()

        self.user = user_factory()
        self.grant_permission(self.user, '*:*')
        self.client.login(email=self.user.email)
        self.list_url = reverse('admin:yara_yararesult_changelist')

        self.admin = YaraResultAdmin(model=YaraResult, admin_site=AdminSite())

    def test_list_view(self):
        response = self.client.get(self.list_url)
        assert response.status_code == 200

    def test_has_add_permission(self):
        assert self.admin.has_add_permission(request=None) is False

    def test_has_delete_permission(self):
        assert self.admin.has_delete_permission(request=None) is False

    def test_has_change_permission(self):
        assert self.admin.has_change_permission(request=None) is False

    def test_formatted_addon(self):
        addon = addon_factory()
        version = version_factory(
            addon=addon,
            channel=amo.RELEASE_CHANNEL_LISTED
        )
        r = YaraResult(version=version)

        assert self.admin.formatted_addon(r) == (
            '<a href="{}">{} (version: {})</a>'.format(
                reverse('reviewers.review', args=[addon.slug]),
                addon.name,
                version.id
            )
        )

    def test_formatted_addon_without_version(self):
        r = YaraResult(version=None)

        assert self.admin.formatted_addon(r) == '-'

    def test_listed_channel(self):
        version = version_factory(
            addon=addon_factory(),
            channel=amo.RELEASE_CHANNEL_LISTED
        )
        r = YaraResult(version=version)

        assert self.admin.channel(r) == 'listed'

    def test_unlisted_channel(self):
        version = version_factory(
            addon=addon_factory(),
            channel=amo.RELEASE_CHANNEL_UNLISTED
        )
        r = YaraResult(version=version)

        assert self.admin.channel(r) == 'unlisted'

    def test_channel_without_version(self):
        r = YaraResult(version=None)

        assert self.admin.channel(r) == '-'

    def test_formatted_matches(self):
        r = YaraResult()
        r.add_match(rule='some-rule')

        assert self.admin.formatted_matches(r) == format_html(
            '<pre>{}</pre>',
            json.dumps(r.matches, indent=4)
        )

    def test_formatted_matches_without_matches(self):
        r = YaraResult()

        assert self.admin.formatted_matches(r) == '<pre>[]</pre>'
