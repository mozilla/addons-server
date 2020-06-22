# -*- coding: utf-8 -*-
from pyquery import PyQuery as pq

from olympia.amo.tests import TestCase, addon_factory, user_factory
from olympia.amo.urlresolvers import django_reverse, reverse
from olympia.discovery.models import DiscoveryItem
from olympia.hero.models import (
    PrimaryHero, PrimaryHeroImage, SecondaryHero, SecondaryHeroModule)


class TestDiscoveryAdmin(TestCase):
    def setUp(self):
        self.list_url = reverse('admin:discovery_discoveryitem_changelist')

    def _get_heroform(self, item_id):
        return {
            "primaryhero-TOTAL_FORMS": "1",
            "primaryhero-INITIAL_FORMS": "0",
            "primaryhero-MIN_NUM_FORMS": "0",
            "primaryhero-MAX_NUM_FORMS": "1",
            "primaryhero-0-image": "",
            "primaryhero-0-gradient_color": "",
            "primaryhero-0-id": "",
            "primaryhero-0-disco_addon": item_id,
            "primaryhero-__prefix__-image": "",
            "primaryhero-__prefix__-gradient_color": "",
            "primaryhero-__prefix__-id": "",
            "primaryhero-__prefix__-disco_addon": item_id,
        }

    def test_can_see_discovery_module_in_admin_with_discovery_edit(self):
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Discovery:Edit')
        self.client.login(email=user.email)
        url = reverse('admin:index')
        response = self.client.get(url)
        assert response.status_code == 200

        # Use django's reverse, since that's what the admin will use. Using our
        # own would fail the assertion because of the locale that gets added.
        self.list_url = django_reverse(
            'admin:discovery_discoveryitem_changelist')
        assert self.list_url in response.content.decode('utf-8')

    def test_can_list_with_discovery_edit_permission(self):
        itm = DiscoveryItem.objects.create(addon=addon_factory(name=u'FooBâr'))
        PrimaryHero.objects.create(disco_addon=itm)
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Discovery:Edit')
        self.client.login(email=user.email)
        response = self.client.get(self.list_url, follow=True)
        assert response.status_code == 200
        assert u'FooBâr' in response.content.decode('utf-8')

    def test_list_filtering_position_yes(self):
        DiscoveryItem.objects.create(
            addon=addon_factory(name=u'FooBâr'), position=1)
        DiscoveryItem.objects.create(addon=addon_factory(name=u'Âbsent'))
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Discovery:Edit')
        self.client.login(email=user.email)
        response = self.client.get(
            self.list_url + '?position=yes', follow=True)
        assert response.status_code == 200
        assert u'FooBâr' in response.content.decode('utf-8')
        assert u'Âbsent' not in response.content.decode('utf-8')

    def test_list_filtering_position_no(self):
        DiscoveryItem.objects.create(
            addon=addon_factory(name=u'FooBâr'), position_china=42)
        DiscoveryItem.objects.create(
            addon=addon_factory(name=u'Âbsent'), position=1)
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Discovery:Edit')
        self.client.login(email=user.email)
        response = self.client.get(self.list_url + '?position=no', follow=True)
        assert response.status_code == 200
        assert u'FooBâr' in response.content.decode('utf-8')
        assert u'Âbsent' not in response.content.decode('utf-8')

    def test_list_filtering_position_yes_china(self):
        DiscoveryItem.objects.create(
            addon=addon_factory(name=u'FooBâr'), position_china=1)
        DiscoveryItem.objects.create(addon=addon_factory(name=u'Âbsent'))
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Discovery:Edit')
        self.client.login(email=user.email)
        response = self.client.get(
            self.list_url + '?position_china=yes', follow=True)
        assert response.status_code == 200
        assert u'FooBâr' in response.content.decode('utf-8')
        assert u'Âbsent' not in response.content.decode('utf-8')

    def test_list_filtering_position_no_china(self):
        DiscoveryItem.objects.create(
            addon=addon_factory(name=u'FooBâr'), position=42)
        DiscoveryItem.objects.create(
            addon=addon_factory(name=u'Âbsent'), position_china=1)
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Discovery:Edit')
        self.client.login(email=user.email)
        response = self.client.get(
            self.list_url + '?position_china=no', follow=True)
        assert response.status_code == 200
        assert u'FooBâr' in response.content.decode('utf-8')
        assert u'Âbsent' not in response.content.decode('utf-8')

    def test_can_edit_with_discovery_edit_permission(self):
        addon = addon_factory(name=u'BarFöo')
        item = DiscoveryItem.objects.create(addon=addon)
        self.detail_url = reverse(
            'admin:discovery_discoveryitem_change', args=(item.pk,)
        )
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Discovery:Edit')
        self.client.login(email=user.email)
        response = self.client.get(self.detail_url, follow=True)
        assert response.status_code == 200
        content = response.content.decode('utf-8')
        assert u'BarFöo' in content
        assert DiscoveryItem._meta.get_field('addon').help_text in content

        response = self.client.post(
            self.detail_url,
            dict(self._get_heroform(str(item.id)), **{
                'addon': str(addon.pk),
                'custom_addon_name': u'Xäxâxàxaxaxa !',
                'custom_heading': u'This heading is totally custom.',
                'custom_description': u'This description is as well!',
                'recommendable': True,
            }),
            follow=True)
        assert response.status_code == 200
        item.reload()
        assert DiscoveryItem.objects.count() == 1
        assert item.addon == addon
        assert item.custom_addon_name == u'Xäxâxàxaxaxa !'
        assert item.custom_heading == u'This heading is totally custom.'
        assert item.custom_description == u'This description is as well!'
        assert item.recommendable is True
        assert PrimaryHero.objects.count() == 0  # check we didn't add one.

    def test_translations_interpolation(self):
        addon = addon_factory(
            name='{bar}', users=[user_factory(display_name='{foo}')]
        )
        item = DiscoveryItem.objects.create(addon=addon)
        self.detail_url = reverse(
            'admin:discovery_discoveryitem_change', args=(item.pk,)
        )
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Discovery:Edit')
        self.client.login(email=user.email)
        response = self.client.get(self.detail_url, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        previews_content = doc('.field-previews').text()
        assert '{bar}' in previews_content
        assert '{foo}' in previews_content

        item.update(custom_addon_name='{abc}')
        self.client.login(email=user.email)
        response = self.client.get(self.detail_url, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        previews_content = doc('.field-previews').text()
        assert '{bar}' in previews_content  # in description
        assert '{foo}' in previews_content  # in heading
        assert '{abc}' in previews_content  # in heading

        item.update(custom_heading='{def}', custom_description='{ghi}')
        self.client.login(email=user.email)
        response = self.client.get(self.detail_url, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        previews_content = doc('.field-previews').text()
        assert '{bar}' not in previews_content  # overridden
        assert '{foo}' not in previews_content  # overridden
        assert '{abc}' not in previews_content  # overridden
        assert '{def}' in previews_content
        assert '{ghi}' in previews_content

    def test_can_change_addon_with_discovery_edit_permission(self):
        addon = addon_factory(name=u'BarFöo')
        addon2 = addon_factory(name=u'Another ône', slug='another-addon')
        item = DiscoveryItem.objects.create(addon=addon)
        self.detail_url = reverse(
            'admin:discovery_discoveryitem_change', args=(item.pk,)
        )
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Discovery:Edit')
        self.client.login(email=user.email)
        response = self.client.get(self.detail_url, follow=True)
        assert response.status_code == 200
        assert u'BarFöo' in response.content.decode('utf-8')

        # Change add-on using the slug.
        response = self.client.post(
            self.detail_url,
            dict(self._get_heroform(str(item.id)), **{
                'addon': str(addon2.slug)}),
            follow=True)
        assert response.status_code == 200
        item.reload()
        assert DiscoveryItem.objects.count() == 1
        # assert item.addon == addon2

        # Change add-on using the id.
        response = self.client.post(
            self.detail_url,
            dict(self._get_heroform(str(item.id)), **{'addon': str(addon.pk)}),
            follow=True)
        assert response.status_code == 200
        item.reload()
        assert DiscoveryItem.objects.count() == 1
        assert item.addon == addon
        assert PrimaryHero.objects.count() == 0  # check we didn't add one.

    def test_can_edit_primary_hero_with_discovery_edit_permission(self):
        addon = addon_factory(name=u'BarFöo')
        item = DiscoveryItem.objects.create(addon=addon)
        hero = PrimaryHero.objects.create(
            disco_addon=item, gradient_color='#592ACB')
        self.detail_url = reverse(
            'admin:discovery_discoveryitem_change', args=(item.pk,)
        )
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Discovery:Edit')
        self.client.login(email=user.email)
        response = self.client.get(self.detail_url, follow=True)
        assert response.status_code == 200
        content = response.content.decode('utf-8')
        assert 'BarFöo' in content
        assert '#592ACB' in content

        response = self.client.post(
            self.detail_url, {
                'addon': str(addon.pk),
                'custom_addon_name': 'Xäxâxàxaxaxa !',
                'recommendable': True,
                'primaryhero-TOTAL_FORMS': '1',
                'primaryhero-INITIAL_FORMS': '1',
                'primaryhero-MIN_NUM_FORMS': '0',
                'primaryhero-MAX_NUM_FORMS': '1',
                'primaryhero-0-id': str(hero.pk),
                'primaryhero-0-disco_addon': str(item.pk),
                'primaryhero-0-gradient_color': '#054096',
                'primaryhero-0-image': 'Ubo@2x.jpg',
            }, follow=True)
        assert response.status_code == 200
        item.reload()
        hero.reload()
        assert DiscoveryItem.objects.count() == 1
        assert PrimaryHero.objects.count() == 1
        assert item.addon == addon
        assert item.custom_addon_name == 'Xäxâxàxaxaxa !'
        assert item.recommendable is True
        assert hero.gradient_color == '#054096'

    def test_can_add_primary_hero_with_discovery_edit_permission(self):
        addon = addon_factory(name=u'BarFöo')
        item = DiscoveryItem.objects.create(addon=addon)
        image = PrimaryHeroImage.objects.create(custom_image='foo.jpg')
        self.detail_url = reverse(
            'admin:discovery_discoveryitem_change', args=(item.pk,)
        )
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Discovery:Edit')
        self.client.login(email=user.email)
        response = self.client.get(self.detail_url, follow=True)
        assert response.status_code == 200
        content = response.content.decode('utf-8')
        assert 'BarFöo' in content
        assert 'No image selected' in content
        assert PrimaryHero.objects.count() == 0

        response = self.client.post(
            self.detail_url,
            dict(self._get_heroform(str(item.pk)), **{
                'addon': str(addon.pk),
                'custom_addon_name': 'Xäxâxàxaxaxa !',
                'recommendable': True,
                'primaryhero-0-gradient_color': '#054096',
                'primaryhero-0-image': 'Ubo@2x.jpg',
                'primaryhero-0-select_image': image.pk,
            }),
            follow=True)
        assert response.status_code == 200
        item.reload()
        assert DiscoveryItem.objects.count() == 1
        assert PrimaryHero.objects.count() == 1
        assert item.addon == addon
        assert item.custom_addon_name == 'Xäxâxàxaxaxa !'
        assert item.recommendable is True
        hero = PrimaryHero.objects.last()
        hero.select_image == PrimaryHeroImage.objects.last()
        assert hero.image == 'Ubo@2x.jpg'
        assert hero.select_image.pk == image.pk
        assert hero.gradient_color == '#054096'
        assert hero.disco_addon == item

    def test_change_addon_errors(self):
        addon = addon_factory(name=u'BarFöo')
        addon2 = addon_factory(name=u'Another ône', slug='another-addon')
        item = DiscoveryItem.objects.create(addon=addon)
        self.detail_url = reverse(
            'admin:discovery_discoveryitem_change', args=(item.pk,)
        )
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Discovery:Edit')
        self.client.login(email=user.email)

        # Try changing using an unknown slug.
        response = self.client.post(
            self.detail_url,
            dict(self._get_heroform(str(item.id)), **{'addon': u'gârbage'}),
            follow=True)
        assert response.status_code == 200
        assert not response.context_data['adminform'].form.is_valid()
        assert 'addon' in response.context_data['adminform'].form.errors
        item.reload()
        assert item.addon == addon

        # Try changing using an unknown id.
        response = self.client.post(
            self.detail_url,
            dict(self._get_heroform(str(item.id)), **{
                'addon': str(addon2.pk + 666)}),
            follow=True)
        assert response.status_code == 200
        assert not response.context_data['adminform'].form.is_valid()
        assert 'addon' in response.context_data['adminform'].form.errors
        item.reload()
        assert item.addon == addon

        # Try changing to an add-on that is already used by another item.
        item2 = DiscoveryItem.objects.create(addon=addon2)
        response = self.client.post(
            self.detail_url,
            dict(self._get_heroform(str(item.id)), **{
                'addon': str(addon2.pk)}),
            follow=True)
        assert response.status_code == 200
        assert not response.context_data['adminform'].form.is_valid()
        assert 'addon' in response.context_data['adminform'].form.errors
        item.reload()
        item2.reload()
        assert item.addon == addon
        assert item2.addon == addon2

    def test_can_delete_with_discovery_edit_permission(self):
        item = DiscoveryItem.objects.create(addon=addon_factory())
        self.delete_url = reverse(
            'admin:discovery_discoveryitem_delete', args=(item.pk,)
        )
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Discovery:Edit')
        self.client.login(email=user.email)
        # Can access delete confirmation page.
        response = self.client.get(self.delete_url, follow=True)
        assert response.status_code == 200
        assert DiscoveryItem.objects.filter(pk=item.pk).exists()

        # Can actually delete.
        response = self.client.post(
            self.delete_url,
            dict(self._get_heroform(str(item.id)), **{'post': 'yes'}),
            follow=True)
        assert response.status_code == 200
        assert not DiscoveryItem.objects.filter(pk=item.pk).exists()

    def test_can_delete_primary_hero_too(self):
        item = DiscoveryItem.objects.create(addon=addon_factory())
        shelf = PrimaryHero.objects.create(disco_addon=item)
        self.delete_url = reverse(
            'admin:discovery_discoveryitem_delete', args=(item.pk,)
        )
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Discovery:Edit')
        self.client.login(email=user.email)
        # Can access delete confirmation page.
        response = self.client.get(self.delete_url, follow=True)
        assert response.status_code == 200
        assert DiscoveryItem.objects.filter(pk=item.pk).exists()
        assert PrimaryHero.objects.filter(pk=shelf.pk).exists()

        # But not if the primary hero shelf is the only enabled shelf.
        shelf.update(enabled=True)
        response = self.client.get(self.delete_url, follow=True)
        assert response.status_code == 403

        # And can't actually delete either
        response = self.client.post(
            self.delete_url,
            dict(self._get_heroform(str(item.id)), **{'post': 'yes'}),
            follow=True)
        assert response.status_code == 403
        assert DiscoveryItem.objects.filter(pk=item.pk).exists()

        # But if there's another enabled shelf we can now access the page.
        PrimaryHero.objects.create(
            disco_addon=DiscoveryItem.objects.create(addon=addon_factory()),
            enabled=True)
        response = self.client.get(self.delete_url, follow=True)
        assert response.status_code == 200

        # Can actually delete too.
        response = self.client.post(
            self.delete_url,
            dict(self._get_heroform(str(item.id)), **{'post': 'yes'}),
            follow=True)
        assert response.status_code == 200
        assert not DiscoveryItem.objects.filter(pk=item.pk).exists()
        assert not PrimaryHero.objects.filter(pk=shelf.pk).exists()

    def test_can_add_with_discovery_edit_permission(self):
        addon = addon_factory(name=u'BarFöo')
        self.add_url = reverse('admin:discovery_discoveryitem_add')
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Discovery:Edit')
        self.client.login(email=user.email)
        response = self.client.get(self.add_url, follow=True)
        assert response.status_code == 200
        assert DiscoveryItem.objects.count() == 0
        response = self.client.post(
            self.add_url,
            dict(self._get_heroform(''), **{
                'addon': str(addon.pk),
                'custom_addon_name': u'Xäxâxàxaxaxa !',
                'custom_heading': u'This heading is totally custom.',
                'custom_description': u'This description is as well!',
            }),
            follow=True)
        assert response.status_code == 200
        assert DiscoveryItem.objects.count() == 1
        item = DiscoveryItem.objects.get()
        assert item.addon == addon
        assert item.custom_addon_name == u'Xäxâxàxaxaxa !'
        assert item.custom_heading == u'This heading is totally custom.'
        assert item.custom_description == u'This description is as well!'
        assert PrimaryHero.objects.count() == 0  # check we didn't add one.

    def test_can_not_add_without_discovery_edit_permission(self):
        addon = addon_factory(name=u'BarFöo')
        self.add_url = reverse('admin:discovery_discoveryitem_add')
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.client.login(email=user.email)
        response = self.client.get(self.add_url, follow=True)
        assert response.status_code == 403
        response = self.client.post(
            self.add_url,
            {'addon': str(addon.pk)},
            follow=True)
        assert response.status_code == 403
        assert DiscoveryItem.objects.count() == 0

    def test_can_not_edit_without_discovery_edit_permission(self):
        addon = addon_factory(name=u'BarFöo')
        item = DiscoveryItem.objects.create(addon=addon)
        self.detail_url = reverse(
            'admin:discovery_discoveryitem_change', args=(item.pk,)
        )
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.client.login(email=user.email)
        response = self.client.get(self.detail_url, follow=True)
        assert response.status_code == 403

        response = self.client.post(
            self.detail_url, {
                'addon': str(addon.pk),
                'custom_addon_name': u'Noooooô !',
                'custom_heading': u'I should not be able to do this.',
                'custom_description': u'This is wrong.',
            }, follow=True)
        assert response.status_code == 403
        item.reload()
        assert DiscoveryItem.objects.count() == 1
        assert item.addon == addon
        assert item.custom_addon_name == u''
        assert item.custom_heading == u''
        assert item.custom_description == u''

    def test_can_not_delete_without_discovery_edit_permission(self):
        item = DiscoveryItem.objects.create(addon=addon_factory())
        self.delete_url = reverse(
            'admin:discovery_discoveryitem_delete', args=(item.pk,)
        )
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.client.login(email=user.email)
        # Can not access delete confirmation page.
        response = self.client.get(self.delete_url, follow=True)
        assert response.status_code == 403
        assert DiscoveryItem.objects.filter(pk=item.pk).exists()

        # Can not actually delete either.
        response = self.client.post(
            self.delete_url, data={'post': 'yes'}, follow=True)
        assert response.status_code == 403
        assert DiscoveryItem.objects.filter(pk=item.pk).exists()

    def test_query_count(self):
        DiscoveryItem.objects.create(addon=addon_factory(name=u'FooBâr'))
        DiscoveryItem.objects.create(addon=addon_factory(name=u'FooBâr 2'))
        DiscoveryItem.objects.create(addon=addon_factory(name=u'FooBâr 3'))
        DiscoveryItem.objects.create(addon=addon_factory(name=u'FooBâr 4'))
        DiscoveryItem.objects.create(addon=addon_factory(name=u'FooBâr 5'))
        DiscoveryItem.objects.create(addon=addon_factory(name=u'FooBâr 6'))

        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Discovery:Edit')
        self.client.login(email=user.email)

        # 1. select current user
        # 2. savepoint (because we're in tests)
        # 3. select groups
        # 4. pagination count
        # 5. pagination count (double…)
        # 6. select list of discovery items, ordered
        # 7. prefetch add-ons
        # 8. select translations for add-ons from 7.
        # 9. savepoint (because we're in tests)
        with self.assertNumQueries(9):
            response = self.client.get(self.list_url, follow=True)

        DiscoveryItem.objects.create(addon=addon_factory(name=u'FooBâr 5'))
        DiscoveryItem.objects.create(addon=addon_factory(name=u'FooBâr 6'))

        # Ensure the count is stable
        with self.assertNumQueries(9):
            response = self.client.get(self.list_url, follow=True)

        assert response.status_code == 200


class TestSecondaryHeroShelfAdmin(TestCase):
    def setUp(self):
        self.list_url = reverse(
            'admin:discovery_secondaryheroshelf_changelist')
        self.detail_url_name = 'admin:discovery_secondaryheroshelf_change'

    def _get_moduleform(self, item, module_data, initial=0):
        count = str(len(module_data))
        out = {
            "modules-TOTAL_FORMS": count,
            "modules-INITIAL_FORMS": initial,
            "modules-MIN_NUM_FORMS": count,
            "modules-MAX_NUM_FORMS": count,
            "modules-__prefix__-icon": "",
            "modules-__prefix__-description": "",
            "modules-__prefix__-id": "",
            "modules-__prefix__-shelf": str(item),
        }
        for index in range(0, len(module_data)):
            out.update(**{
                f"modules-{index}-icon": str(module_data[index]['icon']),
                f"modules-{index}-description": str(
                    module_data[index]['description']),
                f"modules-{index}-id": str(module_data[index].get('id', '')),
                f"modules-{index}-shelf": str(item),

            })
        return out

    def test_can_see_secondary_hero_module_in_admin_with_discovery_edit(self):
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Discovery:Edit')
        self.client.login(email=user.email)
        url = reverse('admin:index')
        response = self.client.get(url)
        assert response.status_code == 200

        # Use django's reverse, since that's what the admin will use. Using our
        # own would fail the assertion because of the locale that gets added.
        self.list_url = django_reverse(
            'admin:discovery_secondaryheroshelf_changelist')
        assert self.list_url in response.content.decode('utf-8')

    def test_can_list_with_discovery_edit_permission(self):
        SecondaryHero.objects.create(headline='FooBâr')
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Discovery:Edit')
        self.client.login(email=user.email)
        response = self.client.get(self.list_url, follow=True)
        assert response.status_code == 200
        assert 'FooBâr' in response.content.decode('utf-8')

    def test_can_edit_with_discovery_edit_permission(self):
        item = SecondaryHero.objects.create(headline='BarFöo')
        modules = [
            SecondaryHeroModule.objects.create(shelf=item),
            SecondaryHeroModule.objects.create(shelf=item),
            SecondaryHeroModule.objects.create(shelf=item),
        ]
        detail_url = reverse(self.detail_url_name, args=(item.pk,))
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Discovery:Edit')
        self.client.login(email=user.email)
        response = self.client.get(detail_url, follow=True)
        assert response.status_code == 200
        content = response.content.decode('utf-8')
        assert 'BarFöo' in content
        assert 'Not selected' in content

        shelves = [
            {
                'id': modules[0].id,
                'description': 'foo',
                'icon': 'Audio.svg'
            },
            {
                'id': modules[1].id,
                'description': 'baa',
                'icon': 'Developer.svg',
            },
            {
                'id': modules[2].id,
                'description': 'ugh',
                'icon': 'Extensions.svg',
            },
        ]
        response = self.client.post(
            detail_url,
            dict(self._get_moduleform(item.id, shelves, initial=3), **{
                'headline': 'This headline is ... something.',
                'description': 'This description is as well!',
            }), follow=True)
        assert response.status_code == 200
        assert 'errors' not in response.context_data, (
            response.context_data['errors'])
        item.reload()
        assert SecondaryHero.objects.count() == 1
        assert item.headline == 'This headline is ... something.'
        assert item.description == 'This description is as well!'
        assert SecondaryHeroModule.objects.count() == 3
        (module.reload() for module in modules)
        module_values = list(
            SecondaryHeroModule.objects.all().values(
                'id', 'description', 'icon'))
        assert module_values == shelves

    def test_can_delete_with_discovery_edit_permission(self):
        item = SecondaryHero.objects.create()
        delete_url = reverse(
            'admin:discovery_secondaryheroshelf_delete', args=(item.pk,)
        )
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Discovery:Edit')
        self.client.login(email=user.email)
        # Can access delete confirmation page.
        response = self.client.get(delete_url, follow=True)
        assert response.status_code == 200
        assert SecondaryHero.objects.filter(pk=item.pk).exists()

        # But not if the shelf is the only enabled shelf
        item.update(enabled=True)
        response = self.client.get(delete_url, follow=True)
        assert response.status_code == 403

        # We can't actually delete either.
        response = self.client.post(
            delete_url,
            dict(self._get_moduleform(item.pk, {}), post='yes'),
            follow=True)
        assert response.status_code == 403
        assert SecondaryHero.objects.filter(pk=item.pk).exists()

        # Add another enabled shelf and we should be okay to delete again
        SecondaryHero.objects.create(enabled=True)
        response = self.client.get(delete_url, follow=True)
        assert response.status_code == 200

        # And can actually delete.
        response = self.client.post(
            delete_url,
            dict(self._get_moduleform(item.pk, {}), post='yes'),
            follow=True)
        assert response.status_code == 200
        assert not SecondaryHero.objects.filter(pk=item.pk).exists()
        assert not SecondaryHeroModule.objects.filter(shelf=item.pk).exists()

    def test_can_add_with_discovery_edit_permission(self):
        add_url = reverse('admin:discovery_secondaryheroshelf_add')
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Discovery:Edit')
        self.client.login(email=user.email)
        response = self.client.get(add_url, follow=True)
        assert response.status_code == 200
        assert SecondaryHero.objects.count() == 0
        assert SecondaryHeroModule.objects.count() == 0
        shelves = [
            {
                'description': 'foo',
                'icon': 'Audio.svg'
            },
            {
                'description': 'baa',
                'icon': 'Developer.svg',
            },
            {
                'description': 'ugh',
                'icon': 'Extensions.svg',
            },
        ]
        response = self.client.post(
            add_url,
            dict(self._get_moduleform('', shelves), **{
                'headline': 'This headline is ... something.',
                'description': 'This description is as well!',
            }),
            follow=True)
        assert response.status_code == 200
        assert 'errors' not in response.context_data
        assert SecondaryHero.objects.count() == 1
        item = SecondaryHero.objects.get()
        assert item.headline == 'This headline is ... something.'
        assert item.description == 'This description is as well!'
        assert SecondaryHeroModule.objects.count() == 3
        module_values = list(
            SecondaryHeroModule.objects.all().values('description', 'icon'))
        assert module_values == shelves

    def test_can_not_add_without_discovery_edit_permission(self):
        add_url = reverse('admin:discovery_secondaryheroshelf_add')
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.client.login(email=user.email)
        response = self.client.get(add_url, follow=True)
        assert response.status_code == 403
        response = self.client.post(
            add_url, {
                'headline': 'This headline is ... something.',
                'description': 'This description is as well!',
            },
            follow=True)
        assert response.status_code == 403
        assert SecondaryHero.objects.count() == 0

    def test_can_not_edit_without_discovery_edit_permission(self):
        item = SecondaryHero.objects.create()
        detail_url = reverse(
            'admin:discovery_secondaryheroshelf_change', args=(item.pk,)
        )
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.client.login(email=user.email)
        response = self.client.get(detail_url, follow=True)
        assert response.status_code == 403

        response = self.client.post(
            detail_url, {
                'headline': 'I should not be able to do this.',
                'description': 'This is wrong.',
            }, follow=True)
        assert response.status_code == 403
        item.reload()
        assert SecondaryHero.objects.count() == 1
        assert item.headline == ''
        assert item.description == ''

    def test_can_not_delete_without_discovery_edit_permission(self):
        item = SecondaryHero.objects.create()
        delete_url = reverse(
            'admin:discovery_secondaryheroshelf_delete', args=(item.pk,)
        )
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.client.login(email=user.email)
        # Can not access delete confirmation page.
        response = self.client.get(delete_url, follow=True)
        assert response.status_code == 403
        assert SecondaryHero.objects.filter(pk=item.pk).exists()

        # Can not actually delete either.
        response = self.client.post(
            delete_url, data={'post': 'yes'}, follow=True)
        assert response.status_code == 403
        assert SecondaryHero.objects.filter(pk=item.pk).exists()

    def test_need_3_modules(self):
        add_url = reverse('admin:discovery_secondaryheroshelf_add')
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Discovery:Edit')
        self.client.login(email=user.email)
        response = self.client.get(add_url, follow=True)
        assert response.status_code == 200
        assert SecondaryHero.objects.count() == 0
        response = self.client.post(
            add_url,
            dict(self._get_moduleform('', {}), **{
                'headline': 'This headline is ... something.',
                'description': 'This description is as well!',
            }),
            follow=True)
        assert response.status_code == 200
        assert 'There must be exactly 3 modules in this shelf.' in (
            response.context_data['errors'])
        assert SecondaryHero.objects.count() == 0
