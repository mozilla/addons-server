# -*- coding: utf-8 -*-
from collections import OrderedDict

import mock

from waffle.testutils import override_switch

from olympia import amo
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.tests import TestCase, addon_factory, user_factory
from olympia.amo.urlresolvers import reverse
from olympia.discovery.data import DiscoItem, discopane_items as disco_data
from olympia.discovery.utils import replace_extensions


# Represents a dummy version of `olympia.discovery.data`
def get_dummy_addons():
    return OrderedDict([
        (16349, addon_factory(id=16349, type=amo.ADDON_PERSONA,
                              description=u'16349')),
        (9609, addon_factory(id=9609, type=amo.ADDON_EXTENSION)),
        (5890, addon_factory(id=5890, type=amo.ADDON_EXTENSION)),
        (46852, addon_factory(id=46852, type=amo.ADDON_PERSONA)),
        (954390, addon_factory(id=954390, type=amo.ADDON_EXTENSION)),
        (93451, addon_factory(id=93451, type=amo.ADDON_EXTENSION)),
        (963836, addon_factory(id=963836, type=amo.ADDON_PERSONA,
                               description=u'963836')),
        # And now the china edition addons
        (492244, addon_factory(id=492244, type=amo.ADDON_PERSONA,
                               description=u'492244')),
        (3006, addon_factory(id=3006, type=amo.ADDON_EXTENSION)),
        (626810, addon_factory(id=626810, type=amo.ADDON_EXTENSION)),
        (25725, addon_factory(id=25725, type=amo.ADDON_PERSONA)),
        (511962, addon_factory(id=511962, type=amo.ADDON_EXTENSION)),
        (287841, addon_factory(id=287841, type=amo.ADDON_EXTENSION)),
        (153659, addon_factory(id=153659, type=amo.ADDON_PERSONA,
                               description=u'153659')),
    ])


class DiscoveryTestMixin(object):
    def _check_disco_addon(self, result, item):
        addon = self.addons[item.addon_id]
        assert result['addon']['id'] == item.addon_id == addon.pk
        assert result['addon']['name'] == unicode(addon.name)
        assert result['addon']['slug'] == addon.slug
        assert result['addon']['icon_url'] == absolutify(
            addon.get_icon_url(64))
        assert (result['addon']['current_version']['files'][0]['id'] ==
                addon.current_version.all_files[0].pk)

        if item.heading:
            # Predefined discopane items have a different heading format.
            assert u'<a href="{0}">{1} by {2}</a>'.format(
                absolutify(addon.get_url_path()),
                unicode(item.addon_name or addon.name),
                u', '.join(author.name for author in addon.listed_authors),
            ) in result['heading']
            assert '<span>' in result['heading']
            assert '</span>' in result['heading']
        else:
            assert u'{1} <span>by <a href="{0}">{2}</a></span>'.format(
                absolutify(addon.get_url_path()),
                unicode(item.addon_name or addon.name),
                u', '.join(author.name for author in addon.listed_authors)
            ) == result['heading']
        assert result['description']

    def _check_disco_theme(self, result, item):
        addon = self.addons[item.addon_id]
        assert result['addon']['id'] == item.addon_id == addon.pk
        assert result['addon']['name'] == unicode(addon.name)
        assert result['addon']['slug'] == addon.slug

        assert u'{1} <span>by <a href="{0}">{2}</a></span>'.format(
            absolutify(addon.get_url_path()),
            unicode(item.addon_name or addon.name),
            u', '.join(author.name for author in addon.listed_authors)
        ) == result['heading']
        description_output = (
            (u'<blockquote>%s</blockquote>' % addon.description)
            if addon.description else None)
        assert result['description'] == description_output
        assert result['addon']['theme_data'] == addon.persona.theme_data


class TestDiscoveryViewList(DiscoveryTestMixin, TestCase):
    def setUp(self):
        super(TestDiscoveryViewList, self).setUp()
        self.url = reverse('discovery-list')

        self.addons = get_dummy_addons()

    def test_reverse(self):
        assert self.url == '/api/v3/discovery/'

    def test_list(self):
        response = self.client.get(self.url, {'lang': 'en-US'})
        assert response.data

        discopane_items = disco_data['default']
        assert response.data['count'] == len(discopane_items)
        assert response.data['next'] is None
        assert response.data['previous'] is None
        assert response.data['results']

        for i, result in enumerate(response.data['results']):
            assert result['is_recommendation'] is False
            if 'theme_data' in result['addon']:
                self._check_disco_theme(result, discopane_items[i])
            else:
                self._check_disco_addon(result, discopane_items[i])

    def test_list_unicode_locale(self):
        """Test that disco pane API still works in a locale with non-ascii
        chars, like russian."""
        response = self.client.get(self.url, {'lang': 'ru'})
        assert response.data

        discopane_items = disco_data['default']
        assert response.data['count'] == len(discopane_items)
        assert response.data['next'] is None
        assert response.data['previous'] is None
        assert response.data['results']

    def test_missing_addon(self):
        addon_deleted = self.addons.values()[0]
        addon_deleted.delete()

        disabled_by_user = self.addons.values()[1]
        disabled_by_user.update(disabled_by_user=True)

        nominated = self.addons.values()[2]
        nominated.update(status=amo.STATUS_NOMINATED)

        response = self.client.get(self.url)
        assert response.data

        # Only 4 of all (7) add-ons exist and are public.
        assert response.data['count'] == 4
        assert response.data['next'] is None
        assert response.data['previous'] is None
        assert response.data['results']

        discopane_items = disco_data['default']
        results = response.data['results']
        assert results[0]['addon']['id'] == discopane_items[3].addon_id
        assert results[1]['addon']['id'] == discopane_items[4].addon_id
        assert results[2]['addon']['id'] == discopane_items[5].addon_id
        assert results[3]['addon']['id'] == discopane_items[6].addon_id

    def test_china_edition_list(self):
        response = self.client.get(
            self.url, {'lang': 'en-US', 'edition': 'china'})
        assert response.data

        discopane_items_china = disco_data['china']
        assert response.data['count'] == len(discopane_items_china)
        assert response.data['next'] is None
        assert response.data['previous'] is None
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

        discopane_items = disco_data['default']
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

        discopane_items = disco_data['default']
        assert response.data['count'] == len(discopane_items)
        assert response.data['next'] is None
        assert response.data['previous'] is None
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
        # Represents a dummy version of `olympia.discovery.data`
        self.addons = get_dummy_addons()
        patcher = mock.patch(
            'olympia.discovery.views.get_recommendations')
        self.get_recommendations = patcher.start()
        self.addCleanup(patcher.stop)
        # If no recommendations then results should be as before - tests from
        # the parent class check this.
        self.get_recommendations.return_value = []
        self.url = reverse('discovery-list')

    def test_recommendations(self):
        author = user_factory()
        recommendations = {
            101: addon_factory(id=101, guid='101@mozilla', users=[author]),
            102: addon_factory(id=102, guid='102@mozilla', users=[author]),
            103: addon_factory(id=103, guid='103@mozilla', users=[author]),
            104: addon_factory(id=104, guid='104@mozilla', users=[author]),
        }
        replacement_items = [
            DiscoItem(addon_id=101, is_recommendation=True),
            DiscoItem(addon_id=102, is_recommendation=True),
            DiscoItem(addon_id=103, is_recommendation=True),
            DiscoItem(addon_id=104, is_recommendation=True),
        ]
        self.addons.update(recommendations)
        self.get_recommendations.return_value = replacement_items

        response = self.client.get(
            self.url, {'lang': 'en-US', 'telemetry-client-id': '666',
                       'platform': 'WINNT'})
        self.get_recommendations.assert_called_with(
            '666', {'locale': 'en-US', 'platform': 'WINNT'})

        # should still be the same number of results.
        discopane_items = disco_data['default']
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
        recommendations = {
            101: addon_factory(id=101, guid='101@mozilla', users=[author]),
        }
        replacement_items = [
            DiscoItem(addon_id=101, is_recommendation=True),
        ]
        self.addons.update(recommendations)
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
        recommendations = {
            101: addon_factory(id=101, guid='101@mozilla', users=[author]),
        }
        replacement_items = [
            DiscoItem(addon_id=101, is_recommendation=True),
        ]
        self.addons.update(recommendations)
        self.get_recommendations.return_value = replacement_items

        response = self.client.get(
            self.url, {'lang': 'en-US', 'telemetry-client-id': '666',
                       'platform': 'WINNT', 'edition': 'china'})
        self.get_recommendations.assert_not_called()

        # should be normal results
        discopane_items_china = disco_data['china']
        assert response.data['count'] == len(discopane_items_china)
        for i, result in enumerate(response.data['results']):
            assert result['is_recommendation'] is False
            if 'theme_data' in result['addon']:
                self._check_disco_theme(result, discopane_items_china[i])
            else:
                self._check_disco_addon(result, discopane_items_china[i])
