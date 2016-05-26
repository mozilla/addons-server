# -*- coding: utf-8 -*-
from olympia import amo
from olympia.discovery.data import discopane_items
from olympia.amo.urlresolvers import reverse
from olympia.amo.tests import addon_factory, TestCase, user_factory


class TestDiscoveryViewList(TestCase):
    def setUp(self):
        super(TestDiscoveryViewList, self).setUp()
        self.url = reverse('discovery-list')

    def test_reverse(self):
        assert self.url == '/api/v3/discovery/'

    def test_list(self):
        addons = {}
        for item in discopane_items:
            type_ = amo.ADDON_EXTENSION
            if not item.heading and not item.description:
                type_ = amo.ADDON_PERSONA
                author = user_factory()
            addons[item.addon_id] = addon_factory(id=item.addon_id, type=type_)
            if type_ == amo.ADDON_PERSONA:
                addons[item.addon_id].addonuser_set.create(user=author)

        response = self.client.get(self.url)
        assert response.data

        assert response.data['count'] == len(discopane_items)
        assert response.data['next'] is None
        assert response.data['previous'] is None
        assert response.data['results']

        for i, item in enumerate(discopane_items):
            result = response.data['results'][i]
            assert result['addon']['id'] == item.addon_id
            if item.heading:
                assert result['heading'] == item.heading
            else:
                assert result['heading'] == unicode(addons[item.addon_id].name)
            assert result['description'] == item.description
            assert result['addon']['current_version']
            assert result['addon']['slug'] == addons[item.addon_id].slug

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
