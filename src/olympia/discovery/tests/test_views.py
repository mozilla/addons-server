# -*- coding: utf-8 -*-
from django.test.utils import override_settings

import mock
from rest_framework.settings import api_settings
from waffle.testutils import override_switch

from olympia import amo
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.tests import TestCase, addon_factory, reverse_ns, user_factory
from olympia.discovery.models import DiscoveryItem
from olympia.discovery.utils import replace_extensions


class DiscoveryTestMixin(object):
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


class TestDiscoveryViewList(DiscoveryTestMixin, TestCase):
    def setUp(self):
        super(TestDiscoveryViewList, self).setUp()
        self.url = reverse_ns('discovery-list')
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

    def test_reverse(self):
        assert self.url.endswith(
            '/api/%s/discovery/' % api_settings.DEFAULT_VERSION)

    def test_list(self):
        with self.assertNumQueries(26):
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
        api_settings.DEFAULT_VERSION: ('l10n_flat_input_output',)})
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
            'olympia.discovery.views.get_recommendations')
        self.get_recommendations = patcher.start()
        self.addCleanup(patcher.stop)
        # If no recommendations then results should be as before - tests from
        # the parent class check this.
        self.get_recommendations.return_value = []
        self.url = reverse_ns('discovery-list')

    def test_recommendations(self):
        author = user_factory()
        recommendations = [
            addon_factory(id=101, guid='101@mozilla', users=[author]),
            addon_factory(id=102, guid='102@mozilla', users=[author]),
            addon_factory(id=103, guid='103@mozilla', users=[author]),
            addon_factory(id=104, guid='104@mozilla', users=[author]),
        ]
        replacement_items = [
            DiscoveryItem(addon_id=101),
            DiscoveryItem(addon_id=102),
            DiscoveryItem(addon_id=103),
            DiscoveryItem(addon_id=104),
        ]
        self.addons.extend(recommendations)
        self.get_recommendations.return_value = replacement_items

        response = self.client.get(
            self.url, {'lang': 'en-US', 'telemetry-client-id': '666',
                       'platform': 'WINNT'})
        self.get_recommendations.assert_called_with(
            '666', {'locale': 'en-US', 'platform': 'WINNT'})

        # should still be the same number of results.
        discopane_items = DiscoveryItem.objects.all().order_by('position')
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

    def test_extra_params(self):
        author = user_factory()
        recommendations = [
            addon_factory(id=101, guid='101@mozilla', users=[author]),
        ]
        replacement_items = [DiscoveryItem(addon_id=101)]
        self.addons.extend(recommendations)
        self.get_recommendations.return_value = replacement_items

        # send known taar parameters
        known_params = {
            'lang': 'en-US', 'telemetry-client-id': '666', 'platform': 'WINNT',
            'branch': 'bob', 'study': 'sally'}
        response = self.client.get(self.url, known_params)
        self.get_recommendations.assert_called_with(
            '666', {'locale': 'en-US', 'platform': 'WINNT', 'branch': 'bob',
                    'study': 'sally'})
        assert response.data['results']

        # Sense check to make sure we're testing all known params in this test
        # strip out 'edition' as providing it means no taar.
        taar_allowed_params = [p for p in amo.DISCO_API_ALLOWED_PARAMETERS
                               if p != 'edition']
        assert sorted(known_params.keys()) == sorted(taar_allowed_params)

        # Send some extra unknown parameters to be ignored.
        with_unknown_params = {
            'lang': 'en-US', 'telemetry-client-id': '666', 'platform': 'WINNT',
            'extra': 'stuff', 'this': 'too'}
        response = self.client.get(self.url, with_unknown_params)
        self.get_recommendations.assert_called_with(
            '666', {'locale': 'en-US', 'platform': 'WINNT'})
        assert response.data['results']

    def test_no_recommendations_for_china_edition(self):
        author = user_factory()
        recommendations = [
            addon_factory(id=101, guid='101@mozilla', users=[author]),
        ]
        replacement_items = [DiscoveryItem(addon_id=101)]
        self.addons.extend(recommendations)
        self.get_recommendations.return_value = replacement_items

        response = self.client.get(
            self.url, {'lang': 'en-US', 'telemetry-client-id': '666',
                       'platform': 'WINNT', 'edition': 'china'})
        self.get_recommendations.assert_not_called()

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
        DiscoveryItem.objects.create(
            addon=addon_factory(),
            custom_addon_name=u'Fôoooo')
        DiscoveryItem.objects.create(
            addon=addon_factory(),
            custom_heading=u'My Custöm Headîng',
            custom_description=u'')
        DiscoveryItem.objects.create(
            addon=addon_factory(),
            custom_heading=u'Änother custom heading',
            custom_description=u'This time with a custom description as well')
        self.url = reverse_ns('discovery-editorial-list')

    def test_basic(self):
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

        result = response.data['results'][1]
        assert result['custom_heading'] == u'My Custöm Headîng'
        assert result['custom_description'] == u''

        result = response.data['results'][2]
        assert result['custom_heading'] == u'Änother custom heading'
        assert result['custom_description'] == (
            u'This time with a custom description as well')
