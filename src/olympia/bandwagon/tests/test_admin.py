from pyquery import PyQuery as pq

from django.conf import settings

from olympia import amo
from olympia.amo.tests import addon_factory, formset, TestCase, user_factory
from olympia.amo.urlresolvers import reverse
from olympia.bandwagon.models import Collection, CollectionAddon


class TestCollectionAdmin(TestCase):
    def setUp(self):
        self.admin_home_url = reverse('admin:index')
        self.list_url = reverse('admin:bandwagon_collection_changelist')

    def test_can_see_bandwagon_module_in_admin_with_collections_edit(self):
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Collections:Edit')
        self.client.login(email=user.email)
        response = self.client.get(self.admin_home_url, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        modules = [x.text for x in doc('a.section')]
        assert modules == ['Bandwagon']

    def test_can_see_bandwagon_module_in_admin_with_admin_curation(self):
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Admin:Curation')
        self.client.login(email=user.email)
        response = self.client.get(self.admin_home_url, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        modules = [x.text for x in doc('a.section')]
        # Curators can also see the Addons module, to edit addon replacements.
        assert modules == ['Addons', 'Bandwagon']

    def test_can_not_see_bandwagon_module_in_admin_without_permissions(self):
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.client.login(email=user.email)
        response = self.client.get(self.admin_home_url, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        modules = [x.text for x in doc('a.section')]
        assert modules == []

    def test_can_list_with_collections_edit_permission(self):
        collection = Collection.objects.create(slug='floob')
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Collections:Edit')
        self.client.login(email=user.email)
        response = self.client.get(self.list_url, follow=True)
        assert response.status_code == 200
        assert collection.slug in response.content.decode('utf-8')

    def test_can_list_with_admin_curation_permission(self):
        collection = Collection.objects.create(slug='floob')
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Admin:Curation')
        self.client.login(email=user.email)
        response = self.client.get(self.list_url, follow=True)
        assert response.status_code == 200
        assert collection.slug in response.content.decode('utf-8')

    def test_cant_list_without_special_permission(self):
        collection = Collection.objects.create(slug='floob')
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.client.login(email=user.email)
        response = self.client.get(self.list_url, follow=True)
        assert response.status_code == 403
        assert collection.slug not in response.content.decode('utf-8')

    def test_can_edit_with_collections_edit_permission(self):
        collection = Collection.objects.create(slug=u'floob')
        addon = addon_factory()
        addon2 = addon_factory()
        collection_addon = CollectionAddon.objects.create(
            addon=addon, collection=collection)
        self.detail_url = reverse(
            'admin:bandwagon_collection_change', args=(collection.pk,)
        )
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Collections:Edit')
        self.client.login(email=user.email)
        response = self.client.get(self.detail_url, follow=True)
        assert response.status_code == 200
        content = response.content.decode('utf-8')
        assert collection.slug in content
        assert unicode(addon.name) in content

        post_data = {
            # Django wants the whole form to be submitted, unfortunately.
            'application': amo.FIREFOX.id,
            'type': collection.type,
            'default_locale': collection.default_locale,
            'author': user.pk,
        }
        post_data['slug'] = 'bar'
        post_data.update(formset({
            'addon': addon2.pk,
            'id': collection_addon.pk,
            'collection': collection.pk,
            'ordering': 1,
        }, prefix='collectionaddon_set'))

        response = self.client.post(self.detail_url, post_data, follow=True)
        assert response.status_code == 200
        collection.reload()
        collection_addon.reload()
        assert collection.slug == 'bar'
        assert collection_addon.addon == addon2
        assert collection_addon.collection == collection
        assert CollectionAddon.objects.count() == 1

    def test_can_not_list_without_collections_edit_permission(self):
        collection = Collection.objects.create(slug='floob')
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.client.login(email=user.email)
        response = self.client.get(self.list_url, follow=True)
        assert response.status_code == 403
        assert collection.slug not in response.content.decode('utf-8')

    def test_can_not_edit_without_collections_edit_permission(self):
        collection = Collection.objects.create(slug='floob')
        self.detail_url = reverse(
            'admin:bandwagon_collection_change', args=(collection.pk,)
        )
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.client.login(email=user.email)
        response = self.client.get(self.detail_url, follow=True)
        assert response.status_code == 403
        assert collection.slug not in response.content.decode('utf-8')

        post_data = {
            # Django wants the whole form to be submitted, unfortunately.
            'application': amo.FIREFOX.id,
            'type': collection.type,
            'default_locale': collection.default_locale,
            'author': user.pk,
        }
        post_data['slug'] = 'bar'
        response = self.client.post(self.detail_url, post_data, follow=True)
        assert response.status_code == 403
        collection.reload()
        assert collection.slug == 'floob'

    def test_can_do_limited_editing_with_admin_curation_permission(self):
        collection = Collection.objects.create(slug='floob')
        addon = addon_factory()
        addon2 = addon_factory()
        collection_addon = CollectionAddon.objects.create(
            addon=addon, collection=collection)
        self.detail_url = reverse(
            'admin:bandwagon_collection_change', args=(collection.pk,)
        )
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Admin:Curation')
        self.client.login(email=user.email)
        response = self.client.get(self.detail_url, follow=True)
        assert response.status_code == 403
        assert collection.slug not in response.content.decode('utf-8')

        post_data = {
            # Django wants the whole form to be submitted, unfortunately.
            'application': amo.FIREFOX.id,
            'type': collection.type,
            'default_locale': collection.default_locale,
            'author': user.pk,
        }
        post_data['slug'] = 'bar'
        post_data.update(formset({
            'addon': addon2.pk,
            'id': collection_addon.pk,
            'collection': collection.pk,
            'ordering': 1,
        }, prefix='collectionaddon_set'))
        response = self.client.post(self.detail_url, post_data, follow=True)
        assert response.status_code == 403
        collection.reload()
        collection_addon.reload()
        assert collection.slug == 'floob'
        assert collection_addon.addon == addon

        # Now, if it's a mozilla collection, you can edit it.
        mozilla = user_factory(username='mozilla', id=settings.TASK_USER_ID)
        collection.update(author=mozilla)
        response = self.client.get(self.detail_url, follow=True)
        assert response.status_code == 200
        content = response.content.decode('utf-8')
        assert collection.slug in content
        assert unicode(addon.name) in content

        post_data = {
            # Django wants the whole form to be submitted, unfortunately.
            'application': amo.FIREFOX.id,
            'type': collection.type,
            'default_locale': collection.default_locale,
            'author': mozilla.pk,
        }
        post_data['slug'] = 'bar'
        post_data.update(formset({
            'addon': addon2.pk,
            'id': collection_addon.pk,
            'collection': collection.pk,
            'ordering': 1,
        }, prefix='collectionaddon_set'))
        response = self.client.post(self.detail_url, post_data, follow=True)
        assert response.status_code == 200
        collection.reload()
        assert collection.slug == 'bar'
        assert collection.author.pk == mozilla.pk
        collection_addon.reload()
        assert collection_addon.addon == addon2  # Editing the addon worked.

        # You can also edit it if it's your own (allowing you, amongst other
        # things, to transfer it to mozilla)
        collection.update(author=user)
        response = self.client.get(self.detail_url, follow=True)
        assert response.status_code == 200
        content = response.content.decode('utf-8')
        assert collection.slug in content
        assert unicode(addon2.name) in content
        assert CollectionAddon.objects.filter(
            collection=collection).count() == 1

        post_data = {
            # Django wants the whole form to be submitted, unfortunately.
            'application': amo.FIREFOX.id,
            'type': collection.type,
            'default_locale': collection.default_locale,
            'author': mozilla.pk,
        }
        post_data['slug'] = 'fox'
        post_data.update(formset({
            'addon': addon2.pk,
            'id': collection_addon.pk,
            'collection': collection.pk,
            'ordering': 1,
        }, {
            'addon': addon.pk,
            'id': '',  # Addition, no existing id.
            'collection': collection.pk,
            'ordering': 2,
        }, prefix='collectionaddon_set', initial_count=1))
        response = self.client.post(self.detail_url, post_data, follow=True)
        assert response.status_code == 200
        collection.reload()
        assert collection.slug == 'fox'
        assert collection.author.pk == mozilla.pk
        assert CollectionAddon.objects.filter(
            collection=collection).count() == 2  # Adding the addon worked.

        # Delete the first collection addon. We need to alter INITIAL-FORMS and
        # the id of the second one, now that this second CollectionAddon
        # instance was created.
        post_data['collectionaddon_set-INITIAL_FORMS'] = 2
        post_data['collectionaddon_set-0-DELETE'] = 'on'
        post_data['collectionaddon_set-1-id'] = CollectionAddon.objects.filter(
            collection=collection, addon=addon).get().pk
        response = self.client.post(self.detail_url, post_data, follow=True)
        assert response.status_code == 200
        assert CollectionAddon.objects.filter(
            collection=collection).count() == 1
        assert CollectionAddon.objects.filter(
            collection=collection, addon=addon).count() == 1
        assert CollectionAddon.objects.filter(
            collection=collection, addon=addon2).count() == 0

    def test_can_not_delete_with_collections_edit_permission(self):
        collection = Collection.objects.create(slug='floob')
        self.delete_url = reverse(
            'admin:bandwagon_collection_delete', args=(collection.pk,)
        )
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Collections:Edit')
        self.client.login(email=user.email)
        response = self.client.get(self.delete_url, follow=True)
        assert response.status_code == 403
        response = self.client.post(
            self.delete_url, data={'post': 'yes'}, follow=True)
        assert response.status_code == 403
        assert Collection.objects.filter(pk=collection.pk).exists()

    def test_can_not_delete_with_admin_curation_permission(self):
        collection = Collection.objects.create(slug='floob')
        self.delete_url = reverse(
            'admin:bandwagon_collection_delete', args=(collection.pk,)
        )
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Admin:Curation')
        self.client.login(email=user.email)
        response = self.client.get(self.delete_url, follow=True)
        assert response.status_code == 403
        response = self.client.post(
            self.delete_url, data={'post': 'yes'}, follow=True)
        assert response.status_code == 403
        assert Collection.objects.filter(pk=collection.pk).exists()

        # Even a mozilla one.
        mozilla = user_factory(username='mozilla', id=settings.TASK_USER_ID)
        collection.update(author=mozilla)
        response = self.client.get(self.delete_url, follow=True)
        assert response.status_code == 403
        response = self.client.post(
            self.delete_url, data={'post': 'yes'}, follow=True)
        assert response.status_code == 403
        assert Collection.objects.filter(pk=collection.pk).exists()

    def test_can_delete_with_admin_advanced_permission(self):
        collection = Collection.objects.create(slug='floob')
        self.delete_url = reverse(
            'admin:bandwagon_collection_delete', args=(collection.pk,)
        )
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Admin:Advanced')
        self.client.login(email=user.email)
        response = self.client.post(
            self.delete_url, data={'post': 'yes'}, follow=True)
        assert response.status_code == 200
        assert not Collection.objects.filter(pk=collection.pk).exists()
