# -*- coding: utf-8 -*-
from olympia import amo
from olympia.discovery.models import DiscoveryItem
from olympia.amo.tests import TestCase, addon_factory, user_factory
from olympia.amo.urlresolvers import django_reverse, reverse


class TestDiscoveryAdmin(TestCase):
    def setUp(self):
        self.list_url = reverse('admin:discovery_discoveryitem_changelist')

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
        DiscoveryItem.objects.create(addon=addon_factory(name=u'FooBâr'))
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
            self.detail_url, {
                'addon': unicode(addon.pk),
                'custom_addon_name': u'Xäxâxàxaxaxa !',
                'custom_heading': u'This heading is totally custom.',
                'custom_description': u'This description is as well!',
            }, follow=True)
        assert response.status_code == 200
        item.reload()
        assert DiscoveryItem.objects.count() == 1
        assert item.addon == addon
        assert item.custom_addon_name == u'Xäxâxàxaxaxa !'
        assert item.custom_heading == u'This heading is totally custom.'
        assert item.custom_description == u'This description is as well!'

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
            self.detail_url, {'addon': unicode(addon2.slug)}, follow=True)
        assert response.status_code == 200
        item.reload()
        assert DiscoveryItem.objects.count() == 1
        # assert item.addon == addon2

        # Change add-on using the id.
        response = self.client.post(
            self.detail_url, {'addon': unicode(addon.pk)}, follow=True)
        assert response.status_code == 200
        item.reload()
        assert DiscoveryItem.objects.count() == 1
        assert item.addon == addon

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
            self.detail_url, {'addon': u'gârbage'}, follow=True)
        assert response.status_code == 200
        assert not response.context_data['adminform'].form.is_valid()
        assert 'addon' in response.context_data['adminform'].form.errors
        item.reload()
        assert item.addon == addon

        # Try changing using an unknown id.
        response = self.client.post(
            self.detail_url, {'addon': unicode(addon2.pk + 666)}, follow=True)
        assert response.status_code == 200
        assert not response.context_data['adminform'].form.is_valid()
        assert 'addon' in response.context_data['adminform'].form.errors
        item.reload()
        assert item.addon == addon

        # Try changing using a non-public add-on id.
        addon3 = addon_factory(status=amo.STATUS_DISABLED)
        response = self.client.post(
            self.detail_url, {'addon': unicode(addon3.pk)}, follow=True)
        assert response.status_code == 200
        assert not response.context_data['adminform'].form.is_valid()
        assert 'addon' in response.context_data['adminform'].form.errors
        item.reload()
        assert item.addon == addon

        # Try changing to an add-on that is already used by another item.
        item2 = DiscoveryItem.objects.create(addon=addon2)
        response = self.client.post(
            self.detail_url, {'addon': unicode(addon2.pk)}, follow=True)
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
            self.delete_url, data={'post': 'yes'}, follow=True)
        assert response.status_code == 200
        assert not DiscoveryItem.objects.filter(pk=item.pk).exists()

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
            self.add_url, {
                'addon': unicode(addon.pk),
                'custom_addon_name': u'Xäxâxàxaxaxa !',
                'custom_heading': u'This heading is totally custom.',
                'custom_description': u'This description is as well!',
            }, follow=True)
        assert response.status_code == 200
        assert DiscoveryItem.objects.count() == 1
        item = DiscoveryItem.objects.get()
        assert item.addon == addon
        assert item.custom_addon_name == u'Xäxâxàxaxaxa !'
        assert item.custom_heading == u'This heading is totally custom.'
        assert item.custom_description == u'This description is as well!'

    def test_can_not_add_without_discovery_edit_permission(self):
        addon = addon_factory(name=u'BarFöo')
        self.add_url = reverse('admin:discovery_discoveryitem_add')
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.client.login(email=user.email)
        response = self.client.get(self.add_url, follow=True)
        assert response.status_code == 403
        response = self.client.post(
            self.add_url, {
                'addon': unicode(addon.pk),
            }, follow=True)
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
                'addon': unicode(addon.pk),
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
