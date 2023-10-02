from unittest import mock

from django.test.utils import override_settings

from waffle import switch_is_active
from waffle.testutils import override_switch

from olympia import amo
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.tests import TestCase, addon_factory, reverse_ns, user_factory
from olympia.constants.promoted import RECOMMENDED
from olympia.discovery.models import DiscoveryItem
from olympia.discovery.utils import replace_extensions


class DiscoveryTestMixin:
    def _check_disco_addon_version(self, data, version):
        assert data['compatibility']
        assert len(data['compatibility']) == len(version.compatible_apps)
        for app, compat in version.compatible_apps.items():
            assert data['compatibility'][app.short] == {
                'min': compat.min.version,
                'max': compat.max.version,
            }
        assert data['is_strict_compatibility_enabled'] is False
        assert data['id'] == version.id

        result_file = data['file']
        file_ = version.file
        assert result_file['id'] == file_.pk
        assert result_file['created'] == (
            file_.created.replace(microsecond=0).isoformat() + 'Z'
        )
        assert result_file['hash'] == file_.hash
        assert (
            result_file['is_mozilla_signed_extension']
            == file_.is_mozilla_signed_extension
        )

        assert result_file['size'] == file_.size
        assert result_file['status'] == amo.STATUS_CHOICES_API[file_.status]
        assert result_file['url'] == file_.get_absolute_url()
        assert result_file['permissions'] == file_.permissions

    def _check_disco_addon(self, result, item, flat_l10n=False, heading=False):
        addon = item.addon
        assert result['addon']['id'] == item.addon_id == addon.pk
        if flat_l10n:
            assert result['addon']['name'] == str(addon.name)
        else:
            assert result['addon']['name'] == {'en-US': str(addon.name)}
        assert result['addon']['slug'] == addon.slug
        assert result['addon']['icon_url'] == absolutify(addon.get_icon_url(64))
        assert (
            result['addon']['current_version']['file']['id']
            == addon.current_version.file.pk
        )

        description_text = (
            item.custom_description
            or (addon.type == amo.ADDON_EXTENSION and str(addon.summary))
            or ''
        )
        if flat_l10n:
            assert result['description_text'] == description_text
        else:
            assert result['description_text'] == (
                {'en-US': description_text} if description_text else None
            )
        if heading:
            assert result['heading'] == (
                f'{addon.name} <span>by <a href="{addon.get_absolute_url()}">'
                f'{self.addon_user.name}</a></span>'
            )
            assert result['description'] == (
                f'<blockquote>{description_text}</blockquote>'
            )
        else:
            assert 'heading' not in result
            assert 'description' not in result

        self._check_disco_addon_version(
            result['addon']['current_version'], addon.current_version
        )


class TestDiscoveryViewList(DiscoveryTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.url = reverse_ns('discovery-list', api_version='v5')
        self.addons = []

        # This one should not appear anywhere, position isn't set.
        DiscoveryItem.objects.create(addon=addon_factory())

        for i in range(1, 8):
            if i % 3:
                type_ = amo.ADDON_STATICTHEME
            else:
                type_ = amo.ADDON_EXTENSION
            addon = addon_factory(type=type_)
            self.addons.append(addon)
            DiscoveryItem.objects.create(addon=addon, position=i)

        for i in range(1, 8):
            if i % 3:
                type_ = amo.ADDON_STATICTHEME
            else:
                type_ = amo.ADDON_EXTENSION
            addon = addon_factory(type=type_)
            DiscoveryItem.objects.create(addon=addon, position_china=i)

    def test_list(self):
        # Precache waffle-switch to not rely on switch caching behavior
        switch_is_active('disco-recommendations')

        with self.assertNumQueries(11):
            # 12 queries:
            # - 1 to fetch the discovery items
            # - 1 to fetch the add-ons (can't be joined with the previous one
            #   because we want to hit the Addon transformer)
            # - 1 to fetch add-ons translations
            # - 1 to fetch add-ons categories
            # - 1 to fetch add-ons current_version + file
            # - 1 to fetch the versions translations
            # - 1 to fetch the versions applications_versions
            # - 1 to fetch the add-ons authors
            # - 1 to fetch the add-ons version previews (for static themes)
            # - 1 to fetch the add-ons previews
            # - 1 to fetch the permissions for the files
            response = self.client.get(self.url, {'lang': 'en-US'})
        assert response.data

        discopane_items = (
            DiscoveryItem.objects.all().filter(position__gt=0).order_by('position')
        )
        assert response.data['count'] == len(discopane_items)
        assert response.data['results']

        for i, result in enumerate(response.data['results']):
            assert result['is_recommendation'] is False
            self._check_disco_addon(result, discopane_items[i])

    @override_settings(DRF_API_GATES={'v5': ('l10n_flat_input_output',)})
    def test_list_flat_output(self):
        response = self.client.get(self.url, {'lang': 'en-US'})
        assert response.data

        discopane_items = (
            DiscoveryItem.objects.all().filter(position__gt=0).order_by('position')
        )
        assert response.data['count'] == len(discopane_items)
        assert response.data['results']

        for i, result in enumerate(response.data['results']):
            assert result['is_recommendation'] is False
            self._check_disco_addon(result, discopane_items[i], flat_l10n=True)

    @override_settings(DRF_API_GATES={'v5': ('disco-heading-and-description-shim',)})
    def test_list_html_heading_and_description(self):
        self.addon_user = user_factory()
        for addon in self.addons:
            addon.addonuser_set.create(user=self.addon_user)
        response = self.client.get(self.url, {'lang': 'en-US'})
        assert response.data

        discopane_items = (
            DiscoveryItem.objects.all().filter(position__gt=0).order_by('position')
        )
        assert response.data['count'] == len(discopane_items)
        assert response.data['results']

        for i, result in enumerate(response.data['results']):
            assert result['is_recommendation'] is False
            self._check_disco_addon(result, discopane_items[i], heading=True)

    def test_list_unicode_locale(self):
        """Test that disco pane API still works in a locale with non-ascii
        chars, like russian."""
        response = self.client.get(self.url, {'lang': 'ru'})
        assert response.data

        discopane_items = (
            DiscoveryItem.objects.all().filter(position__gt=0).order_by('position')
        )
        assert response.data['count'] == len(discopane_items)
        assert response.data['results']

    def test_missing_addons(self):
        addon_deleted = self.addons[0]
        addon_deleted.delete()

        disabled_by_user = self.addons[1]
        disabled_by_user.update(disabled_by_user=True)

        nominated = self.addons[2]
        nominated.update(status=amo.STATUS_NOMINATED)

        response = self.client.get(self.url)
        assert response.data

        # Only 4 of all (7) add-ons exist and are public.
        assert response.data['count'] == 4
        assert response.data['results']

        discopane_items = (
            DiscoveryItem.objects.all().filter(position__gt=0).order_by('position')
        )
        results = response.data['results']
        assert results[0]['addon']['id'] == discopane_items[3].addon_id
        assert results[1]['addon']['id'] == discopane_items[4].addon_id
        assert results[2]['addon']['id'] == discopane_items[5].addon_id
        assert results[3]['addon']['id'] == discopane_items[6].addon_id

    def test_china_edition_list(self, edition='china'):
        response = self.client.get(self.url, {'lang': 'en-US', 'edition': edition})
        assert response.data

        discopane_items_china = (
            DiscoveryItem.objects.all()
            .filter(position_china__gt=0)
            .order_by('position_china')
        )
        assert response.data['count'] == len(discopane_items_china)
        assert response.data['results']

        for i, result in enumerate(response.data['results']):
            assert result['is_recommendation'] is False
            self._check_disco_addon(result, discopane_items_china[i])

    def test_china_edition_alias_list(self, edition='china'):
        self.test_china_edition_list(edition='MozillaOnline')
        self.test_china_edition_list(edition='mozillaonline')

    def test_invalid_edition_returns_default(self):
        response = self.client.get(self.url, {'lang': 'en-US', 'edition': 'platinum'})
        assert response.data

        discopane_items = (
            DiscoveryItem.objects.all().filter(position__gt=0).order_by('position')
        )
        assert response.data['count'] == len(discopane_items)

        for i, result in enumerate(response.data['results']):
            assert result['is_recommendation'] is False
            self._check_disco_addon(result, discopane_items[i])


@override_switch('disco-recommendations', active=True)
class TestDiscoveryRecommendations(DiscoveryTestMixin, TestCase):
    def setUp(self):
        super().setUp()

        self.addons = []

        # This one should not appear anywhere, position isn't set.
        DiscoveryItem.objects.create(addon=addon_factory())

        for i in range(1, 8):
            if i % 3:
                type_ = amo.ADDON_STATICTHEME
            else:
                type_ = amo.ADDON_EXTENSION
            addon = addon_factory(type=type_)
            self.addons.append(addon)
            DiscoveryItem.objects.create(addon=addon, position=i)

        for i in range(1, 8):
            if i % 3:
                type_ = amo.ADDON_STATICTHEME
            else:
                type_ = amo.ADDON_EXTENSION
            addon = addon_factory(type=type_)
            DiscoveryItem.objects.create(addon=addon, position_china=i)

        patcher = mock.patch('olympia.discovery.views.get_disco_recommendations')
        self.get_disco_recommendations_mock = patcher.start()
        self.addCleanup(patcher.stop)
        # If no recommendations then results should be as before - tests from
        # the parent class check this.
        self.get_disco_recommendations_mock.return_value = []
        self.url = reverse_ns('discovery-list', api_version='v5')

    def test_recommendations(self):
        author = user_factory()
        recommendations = [
            addon_factory(guid='101@mozilla', users=[author]),
            addon_factory(guid='102@mozilla', users=[author]),
            addon_factory(guid='103@mozilla', users=[author]),
            addon_factory(guid='104@mozilla', users=[author]),
        ]
        replacement_items = [
            DiscoveryItem(addon=recommendations[0]),
            DiscoveryItem(addon=recommendations[1]),
            DiscoveryItem(addon=recommendations[2]),
            DiscoveryItem(addon=recommendations[3]),
        ]
        self.addons.extend(recommendations)
        self.get_disco_recommendations_mock.return_value = replacement_items

        response = self.client.get(
            self.url,
            {'lang': 'en-US', 'telemetry-client-id': '666', 'platform': 'WINNT'},
        )
        self.get_disco_recommendations_mock.assert_called_with('666', [])

        # should still be the same number of results.
        discopane_items = DiscoveryItem.objects.filter(position__gt=0).order_by(
            'position'
        )
        assert response.data['count'] == len(discopane_items)
        assert response.data['results']

        # themes aren't replaced by recommendations, so should be as before.
        new_discopane_items = replace_extensions(discopane_items, replacement_items)
        for i, result in enumerate(response.data['results']):
            self._check_disco_addon(result, new_discopane_items[i])
            if result['addon']['type'] != 'extension':
                # There aren't any theme recommendations.
                assert result['is_recommendation'] is False
            else:
                assert result['is_recommendation'] is True

    def test_recommendations_with_override(self):
        author = user_factory()
        addon1 = addon_factory(guid='101@mozilla', users=[author])
        addon2 = addon_factory(guid='102@mozilla', users=[author])
        addon3 = addon_factory(guid='103@mozilla', users=[author])
        DiscoveryItem.objects.create(addon=addon1, position_override=4)
        DiscoveryItem.objects.create(addon=addon2)
        DiscoveryItem.objects.create(addon=addon3, position_override=1)

        self.client.get(self.url, {'telemetry-client-id': '666'})
        self.get_disco_recommendations_mock.assert_called_with(
            '666', ['103@mozilla', '101@mozilla']
        )

    def test_recommendations_with_garbage_telemetry_id(self):
        self.client.get(self.url, {'telemetry-client-id': 'gærbäge'})
        assert not self.get_disco_recommendations_mock.called

        self.client.get(self.url, {'telemetry-client-id': ''})
        assert not self.get_disco_recommendations_mock.called

    def test_no_recommendations_for_china_edition(self):
        author = user_factory()
        recommendations = [
            addon_factory(id=101, guid='101@mozilla', users=[author]),
        ]
        replacement_items = [DiscoveryItem(addon_id=101)]
        self.addons.extend(recommendations)
        self.get_disco_recommendations_mock.return_value = replacement_items

        response = self.client.get(
            self.url,
            {
                'lang': 'en-US',
                'telemetry-client-id': '666',
                'platform': 'WINNT',
                'edition': 'china',
            },
        )
        self.get_disco_recommendations_mock.assert_not_called()

        # should be normal results
        discopane_items_china = (
            DiscoveryItem.objects.all()
            .filter(position_china__gt=0)
            .order_by('position_china')
        )
        assert response.data['count'] == len(discopane_items_china)
        assert response.data['results']

        for i, result in enumerate(response.data['results']):
            assert result['is_recommendation'] is False
            self._check_disco_addon(result, discopane_items_china[i])


class TestDiscoveryItemViewSet(TestCase):
    def setUp(self):
        self.items = [
            DiscoveryItem.objects.create(
                addon=addon_factory(summary='This is the addon summary')
            ),
            DiscoveryItem.objects.create(addon=addon_factory(), custom_description=''),
            DiscoveryItem.objects.create(
                addon=addon_factory(),
                custom_description='This time with a custom description',
            ),
        ]
        self.url = reverse_ns('discovery-editorial-list')

    def test_basic(self):
        with self.assertNumQueries(1):
            response = self.client.get(self.url)
        assert response.status_code == 200
        assert 'count' not in response.data
        assert 'next' not in response.data
        assert 'previous' not in response.data
        assert 'count' not in response.data
        assert 'results' in response.data

        result = response.data['results'][0]
        assert result['custom_description'] == ''
        assert result['addon'] == {'guid': self.items[0].addon.guid}

        result = response.data['results'][1]
        assert result['custom_description'] == ''
        assert result['addon'] == {'guid': self.items[1].addon.guid}

        result = response.data['results'][2]
        assert result['custom_description'] == ('This time with a custom description')
        assert result['addon'] == {'guid': self.items[2].addon.guid}

    def test_recommended(self):
        with self.assertNumQueries(1):
            response = self.client.get(self.url + '?recommended=true')
        assert response.status_code == 200
        assert len(response.data['results']) == 0

        self.make_addon_promoted(
            addon=self.items[0].addon, group=RECOMMENDED, approve_version=True
        )
        self.make_addon_promoted(
            addon=self.items[2].addon, group=RECOMMENDED, approve_version=True
        )
        with self.assertNumQueries(1):
            response = self.client.get(self.url + '?recommended=true')
        assert response.status_code == 200
        assert len(response.data['results']) == 2
        assert response.data['results'][0]['addon']['guid'] == (
            self.items[0].addon.guid
        )
        assert response.data['results'][1]['addon']['guid'] == (
            self.items[2].addon.guid
        )
