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

        # Represents a dummy version of `olympia.discovery.data`
        self.addons = {
            628864: addon_factory(
                id=628864, type=amo.ADDON_PERSONA,
                users=[user_factory(), user_factory()]),
            607454: addon_factory(id=607454, type=amo.ADDON_EXTENSION),
            674732: addon_factory(id=674732, type=amo.ADDON_EXTENSION),
            465609: addon_factory(
                id=465609, type=amo.ADDON_PERSONA,
                users=[user_factory(), user_factory()]),
            296534: addon_factory(id=296534, type=amo.ADDON_EXTENSION),
            328839: addon_factory(id=328839, type=amo.ADDON_EXTENSION),
            615472: addon_factory(
                id=615472, type=amo.ADDON_PERSONA,
                users=[user_factory(), user_factory()]),
        }

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

        assert u'<a href="{0}">{1} by {2}</a>'.format(
            absolutify(addon.get_url_path()),
            unicode(item.addon_name or addon.name),
            u', '.join(author.name for author in addon.listed_authors),
        ) in result['heading']
        assert '<span>' in result['heading']
        assert '</span>' in result['heading']
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
        addon_deleted = self.addons[674732]
        addon_deleted.delete()

        theme_disabled_by_user = self.addons[465609]
        theme_disabled_by_user.update(disabled_by_user=True)

        self.addons[296534].update(status=amo.STATUS_NOMINATED)

        response = self.client.get(self.url)
        assert response.data

        # Only 4 of all (7) add-ons exist and are public.
        assert response.data['count'] == 4
        assert response.data['next'] is None
        assert response.data['previous'] is None
        assert response.data['results']

        results = response.data['results']
        assert results[0]['addon']['id'] == discopane_items[0].addon_id
        assert results[1]['addon']['id'] == discopane_items[1].addon_id
