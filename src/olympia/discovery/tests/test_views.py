# -*- coding: utf-8 -*-
from collections import OrderedDict

import mock
from waffle.testutils import override_switch

from olympia import amo
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.tests import addon_factory, TestCase, user_factory
from olympia.amo.urlresolvers import reverse
from olympia.discovery.data import discopane_items, DiscoItem
from olympia.discovery.utils import replace_extensions


class TestDiscoveryViewList(TestCase):
    def setUp(self):
        super(TestDiscoveryViewList, self).setUp()
        self.url = reverse('discovery-list')

        # Represents a dummy version of `olympia.discovery.data`
        self.addons = OrderedDict([
            (44686, addon_factory(id=44686, type=amo.ADDON_PERSONA)),
            (607454, addon_factory(id=607454, type=amo.ADDON_EXTENSION)),
            (700308, addon_factory(id=700308, type=amo.ADDON_EXTENSION)),
            (376685, addon_factory(id=376685, type=amo.ADDON_PERSONA)),
            (455926, addon_factory(id=455926, type=amo.ADDON_EXTENSION)),
            (511962, addon_factory(id=511962, type=amo.ADDON_EXTENSION)),
            (208568, addon_factory(id=208568, type=amo.ADDON_PERSONA)),
        ])

    def test_reverse(self):
        assert self.url == '/api/v3/discovery/'

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
        assert not result['description']
        assert result['addon']['theme_data'] == addon.persona.theme_data

    def test_list(self):
        response = self.client.get(self.url, {'lang': 'en-US'})
        assert response.data

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

        results = response.data['results']
        assert results[0]['addon']['id'] == discopane_items[3].addon_id
        assert results[1]['addon']['id'] == discopane_items[4].addon_id
        assert results[2]['addon']['id'] == discopane_items[5].addon_id
        assert results[3]['addon']['id'] == discopane_items[6].addon_id


@override_switch('disco-recommendations', active=True)
class TestDiscoveryRecommendations(TestDiscoveryViewList):
    def setUp(self):
        super(TestDiscoveryRecommendations, self).setUp()
        patcher = mock.patch(
            'olympia.discovery.views.get_recommendations')
        self.get_recommendations = patcher.start()
        self.addCleanup(patcher.stop)
        # If no recommendations then results should be as before - tests from
        # the parent class check this.
        self.get_recommendations.return_value = []

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

        response = self.client.get(self.url, {'lang': 'en-US',
                                              'telemetry-client-id': '666'})
        # should still be the same number of results.
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
