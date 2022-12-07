# -*- coding: utf-8 -*-
from django.test.utils import override_settings

import mock
from waffle.testutils import override_switch

from olympia import amo
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.tests import TestCase, addon_factory, reverse_ns, user_factory
from olympia.discovery.models import DiscoveryItem
from olympia.discovery.utils import replace_extensions


class DiscoveryTestMixin(object):
    def _check_disco_addon_version(self, data, version):
        assert data['compatibility']
        assert len(data['compatibility']) == len(version.compatible_apps)
        for app, compat in version.compatible_apps.items():
            assert data['compatibility'][app.short] == {
                'min': compat.min.version,
                'max': compat.max.version
            }
        assert data['is_strict_compatibility_enabled'] is False
        assert data['files']
        assert len(data['files']) == 1

        result_file = data['files'][0]
        file_ = version.files.latest('pk')
        assert result_file['id'] == file_.pk
        assert result_file['created'] == (
            file_.created.replace(microsecond=0).isoformat() + 'Z')
        assert result_file['hash'] == file_.hash
        assert result_file['is_restart_required'] == file_.is_restart_required
        assert result_file['is_webextension'] == file_.is_webextension
        assert (
            result_file['is_mozilla_signed_extension'] ==
            file_.is_mozilla_signed_extension)

        assert result_file['size'] == file_.size
        assert result_file['status'] == amo.STATUS_CHOICES_API[file_.status]
        assert result_file['url'] == file_.get_url_path(src='')
        assert result_file['permissions'] == file_.webext_permissions_list

    def _check_disco_addon(self, result, item, flat_name=False):
        addon = item.addon
        assert result['addon']['id'] == item.addon_id == addon.pk
        if flat_name:
            assert result['addon']['name'] == unicode(addon.name)
        else:
            assert result['addon']['name'] == {'en-US': unicode(addon.name)}
        assert result['addon']['slug'] == addon.slug
        assert result['addon']['icon_url'] == absolutify(
            addon.get_icon_url(64))
        assert (result['addon']['current_version']['files'][0]['id'] ==
                addon.current_version.all_files[0].pk)

        assert result['heading'] == item.heading
        assert result['description'] == item.description
        assert result['heading_text'] == item.heading_text
        assert result['description_text'] == item.description_text

        self._check_disco_addon_version(
            result['addon']['current_version'], addon.current_version)

    def _check_disco_theme(self, result, item, flat_name=False):
        addon = item.addon
        assert result['addon']['id'] == item.addon_id == addon.pk
        if flat_name:
            assert result['addon']['name'] == unicode(addon.name)
        else:
            assert result['addon']['name'] == {'en-US': unicode(addon.name)}
        assert result['addon']['slug'] == addon.slug
        assert result['addon']['theme_data'] == addon.persona.theme_data

        assert result['heading'] == item.heading
        assert result['description'] == item.description
        assert result['heading_text'] == item.heading_text
        assert result['description_text'] == item.description_text


class TestDiscoveryViewList(DiscoveryTestMixin, TestCase):
    def setUp(self):
        super(TestDiscoveryViewList, self).setUp()
        self.url = reverse_ns('discovery-list', api_version='v4dev')
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
        with self.assertNumQueries(16):
            # 16? queries:
            # - 1 to fetch the waffle switch 'disco-recommendations'
            # - 1 to fetch the discovery items
            # - 1 to fetch the add-ons (can't be joined with the previous one
            #   because we want to hit the Addon transformer)
            # - 1 to fetch add-ons translations
            # - 1 to fetch add-ons categories
            # - 1 to fetch add-ons current_version
            # - 1 to fetch the versions translations
            # - 1 to fetch the versions applications_versions
            # - 1 to fetch the versions files
            # - 1 to fetch the add-ons authors
            # - 1 to fetch the add-ons user position (for previews)
            # - 1 to fetch the add-ons previews
            # I believe Version.transformer causes this repeat. Without the pre-fetch this gets looped per each add-on.
            # - 1 to fetch the versions translations
            # - 1 to fetch the versions applications_versions
            # - 1 to fetch the versions files
            # Intentional
            # - 1 to pre-fetch version previews
            response = self.client.get(self.url, {'lang': 'en-US'})
        assert response.data

        discopane_items = DiscoveryItem.objects.all().filter(
            position__gt=0).order_by('position')
        assert response.data['count'] == len(discopane_items)
        assert response.data['results']

        for i, result in enumerate(response.data['results']):
            assert result['is_recommendation'] is False
            if 'theme_data' in result['addon']:
                self._check_disco_theme(result, discopane_items[i])
            else:
                self._check_disco_addon(result, discopane_items[i])

    @override_settings(DRF_API_GATES={
        'v4dev': ('l10n_flat_input_output',)})
    def test_list_flat_output(self):
        response = self.client.get(self.url, {'lang': 'en-US'})
        assert response.data

        discopane_items = DiscoveryItem.objects.all().filter(
            position__gt=0).order_by('position')
        assert response.data['count'] == len(discopane_items)
        assert response.data['results']

        for i, result in enumerate(response.data['results']):
            assert result['is_recommendation'] is False
            if 'theme_data' in result['addon']:
                self._check_disco_theme(
                    result, discopane_items[i], flat_name=True)
            else:
                self._check_disco_addon(
                    result, discopane_items[i], flat_name=True)

    def test_list_unicode_locale(self):
        """Test that disco pane API still works in a locale with non-ascii
        chars, like russian."""
        response = self.client.get(self.url, {'lang': 'ru'})
        assert response.data

        discopane_items = DiscoveryItem.objects.all().filter(
            position__gt=0).order_by('position')
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

        discopane_items = DiscoveryItem.objects.all().filter(
            position__gt=0).order_by('position')
        results = response.data['results']
        assert results[0]['addon']['id'] == discopane_items[3].addon_id
        assert results[1]['addon']['id'] == discopane_items[4].addon_id
        assert results[2]['addon']['id'] == discopane_items[5].addon_id
        assert results[3]['addon']['id'] == discopane_items[6].addon_id

    def test_china_edition_list(self):
        response = self.client.get(
            self.url, {'lang': 'en-US', 'edition': 'china'})
        assert response.data

        discopane_items_china = DiscoveryItem.objects.all().filter(
            position_china__gt=0).order_by('position_china')
        assert response.data['count'] == len(discopane_items_china)
        assert response.data['results']

        for i, result in enumerate(response.data['results']):
            assert result['is_recommendation'] is False
            if 'theme_data' in result['addon']:
                self._check_disco_theme(result, discopane_items_china[i])
            else:
                self._check_disco_addon(result, discopane_items_china[i])

    def test_invalid_edition_returns_default(self):
        response = self.client.get(
            self.url, {'lang': 'en-US', 'edition': 'platinum'})
        assert response.data

        discopane_items = DiscoveryItem.objects.all().filter(
            position__gt=0).order_by('position')
        assert response.data['count'] == len(discopane_items)

        for i, result in enumerate(response.data['results']):
            assert result['is_recommendation'] is False
            if 'theme_data' in result['addon']:
                self._check_disco_theme(result, discopane_items[i])
            else:
                self._check_disco_addon(result, discopane_items[i])

    def test_with_wrap_outgoing_links(self):
        response = self.client.get(
            self.url, {'lang': 'en-US', 'wrap_outgoing_links': 'true'})
        assert response.data

        discopane_items = DiscoveryItem.objects.all().filter(
            position__gt=0).order_by('position')
        assert response.data['count'] == len(discopane_items)
        assert response.data['results']

        for i, result in enumerate(response.data['results']):
            assert result['is_recommendation'] is False
            if 'theme_data' in result['addon']:
                self._check_disco_theme(result, discopane_items[i])
            else:
                self._check_disco_addon(result, discopane_items[i])


@override_switch('disco-recommendations', active=True)
class TestDiscoveryRecommendations(DiscoveryTestMixin, TestCase):
    def setUp(self):
        super(TestDiscoveryRecommendations, self).setUp()

        self.addons = []

        # This one should not appear anywhere, position isn't set.
        DiscoveryItem.objects.create(addon=addon_factory())

        for i in range(1, 8):
            if i % 3:
                type_ = amo.ADDON_PERSONA
            else:
                type_ = amo.ADDON_EXTENSION
            addon = addon_factory(type=type_)
            self.addons.append(addon)
            DiscoveryItem.objects.create(addon=addon, position=i)

        for i in range(1, 8):
            if i % 3:
                type_ = amo.ADDON_PERSONA
            else:
                type_ = amo.ADDON_EXTENSION
            addon = addon_factory(type=type_)
            DiscoveryItem.objects.create(addon=addon, position_china=i)

        patcher = mock.patch(
            'olympia.discovery.views.get_disco_recommendations')
        self.get_disco_recommendations_mock = patcher.start()
        self.addCleanup(patcher.stop)
        # If no recommendations then results should be as before - tests from
        # the parent class check this.
        self.get_disco_recommendations_mock.return_value = []
        self.url = reverse_ns('discovery-list', api_version='v4dev')

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
            self.url, {'lang': 'en-US', 'telemetry-client-id': '666',
                       'platform': 'WINNT'})
        self.get_disco_recommendations_mock.assert_called_with('666', [])

        # should still be the same number of results.
        discopane_items = DiscoveryItem.objects.filter(
            position__gt=0).order_by('position')
        assert response.data['count'] == len(discopane_items)
        assert response.data['results']

        # personas aren't replaced by recommendations, so should be as before.
        new_discopane_items = replace_extensions(
            discopane_items, replacement_items)
        for i, result in enumerate(response.data['results']):
            if 'theme_data' in result['addon']:
                self._check_disco_theme(result, new_discopane_items[i])
                # There aren't any theme recommendations.
                assert result['is_recommendation'] is False
            else:
                self._check_disco_addon(result, new_discopane_items[i])
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
            u'666', [u'103@mozilla', u'101@mozilla'])

    def test_recommendations_with_garbage_telemetry_id(self):
        self.client.get(self.url, {'telemetry-client-id': u'gærbäge'})
        assert not self.get_disco_recommendations_mock.called

        self.client.get(self.url, {'telemetry-client-id': u''})
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
            self.url, {'lang': 'en-US', 'telemetry-client-id': '666',
                       'platform': 'WINNT', 'edition': 'china'})
        self.get_disco_recommendations_mock.assert_not_called()

        # should be normal results
        discopane_items_china = DiscoveryItem.objects.all().filter(
            position_china__gt=0).order_by('position_china')
        assert response.data['count'] == len(discopane_items_china)
        assert response.data['results']

        for i, result in enumerate(response.data['results']):
            assert result['is_recommendation'] is False
            if 'theme_data' in result['addon']:
                self._check_disco_theme(result, discopane_items_china[i])
            else:
                self._check_disco_addon(result, discopane_items_china[i])


class TestDiscoveryItemViewSet(TestCase):
    def setUp(self):
        self.items = [
            DiscoveryItem.objects.create(
                addon=addon_factory(),
                custom_addon_name=u'Fôoooo'),
            DiscoveryItem.objects.create(
                addon=addon_factory(),
                custom_heading=u'My Custöm Headîng',
                custom_description=u''),
            DiscoveryItem.objects.create(
                addon=addon_factory(),
                custom_heading=u'Änother custom heading',
                custom_description=u'This time with a custom description')
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
        assert result['custom_heading'] == u''
        assert result['custom_description'] == u''
        assert result['addon'] == {'guid': self.items[0].addon.guid}

        result = response.data['results'][1]
        assert result['custom_heading'] == u'My Custöm Headîng'
        assert result['custom_description'] == u''
        assert result['addon'] == {'guid': self.items[1].addon.guid}

        result = response.data['results'][2]
        assert result['custom_heading'] == u'Änother custom heading'
        assert result['custom_description'] == (
            u'This time with a custom description')
        assert result['addon'] == {'guid': self.items[2].addon.guid}
