# -*- coding: utf-8 -*-
from olympia import amo
from olympia.discovery.data import discopane_items
from olympia.amo.helpers import absolutify
from olympia.amo.tests import addon_factory, TestCase, user_factory
from olympia.amo.urlresolvers import reverse


class TestDiscoveryViewList(TestCase):
    def setUp(self):
        super(TestDiscoveryViewList, self).setUp()
        self.url = reverse('discovery-list')

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
        assert '<a href="{0}">{1}</a>'.format(
            absolutify(addon.get_url_path()),
            unicode(addon.name)) in result['heading']
        assert '<span>' in result['heading']
        assert '</span>' in result['heading']
        assert result['description']

    def _check_disco_theme(self, result, item):
        addon = self.addons[item.addon_id]
        assert result['addon']['id'] == item.addon_id == addon.pk
        assert result['addon']['name'] == unicode(addon.name)
        assert result['addon']['slug'] == addon.slug
        assert '<a href="{0}">{1}</a>'.format(
            absolutify(addon.get_url_path()),
            unicode(addon.name)) == result['heading']
        assert '<span>' not in result['heading']
        assert '</span>' not in result['heading']
        assert not result['description']
        assert result['addon']['theme_data'] == addon.persona.theme_data

    def test_list(self):
        self.addons = {}
        for item in discopane_items:
            type_ = amo.ADDON_EXTENSION
            if not item.heading and not item.description:
                type_ = amo.ADDON_PERSONA
                author = user_factory()
            self.addons[item.addon_id] = addon_factory(
                id=item.addon_id, type=type_)
            if type_ == amo.ADDON_PERSONA:
                self.addons[item.addon_id].addonuser_set.create(user=author)

        response = self.client.get(self.url, {'lang': 'en-US'})
        assert response.data

        assert response.data['count'] == len(discopane_items)
        assert response.data['next'] is None
        assert response.data['previous'] is None
        assert response.data['results']

        for i, result in enumerate(response.data['results']):
            if 'theme_data' in result['addon']:
                self._check_disco_theme(result, discopane_items[i])
            else:
                self._check_disco_addon(result, discopane_items[i])

    def test_missing_addon(self):
        addon_factory(id=discopane_items[0].addon_id, type=amo.ADDON_PERSONA)
        addon_factory(id=discopane_items[1].addon_id, type=amo.ADDON_EXTENSION)
        addon_deleted = addon_factory(
            id=discopane_items[2].addon_id, type=amo.ADDON_EXTENSION)
        addon_deleted.delete()
        theme_disabled_by_user = addon_factory(
            id=discopane_items[3].addon_id, type=amo.ADDON_PERSONA)
        theme_disabled_by_user.update(disabled_by_user=True)
        addon_factory(
            id=discopane_items[4].addon_id, type=amo.ADDON_EXTENSION,
            status=amo.STATUS_UNREVIEWED)

        response = self.client.get(self.url)
        assert response.data
        # Only the first 2 add-ons exist and are public.
        assert response.data['count'] == 2
        assert response.data['next'] is None
        assert response.data['previous'] is None
        assert response.data['results']

        results = response.data['results']
        assert results[0]['addon']['id'] == discopane_items[0].addon_id
        assert results[1]['addon']['id'] == discopane_items[1].addon_id
