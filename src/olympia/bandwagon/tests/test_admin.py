from olympia import amo
from olympia.amo.tests import TestCase, user_factory
from olympia.amo.urlresolvers import reverse
from olympia.bandwagon.models import Collection


class TestCollectionAdmin(TestCase):
    def setUp(self):
        self.list_url = reverse('admin:bandwagon_collection_changelist')

    def test_can_list_with_collections_edit_permission(self):
        collection = Collection.objects.create(slug='floob')
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Collections:Edit')
        self.client.login(email=user.email)
        response = self.client.get(self.list_url, follow=True)
        assert response.status_code == 200
        assert collection.slug in response.content.decode('utf-8')

    def test_can_edit_with_collections_edit_permission(self):
        collection = Collection.objects.create(slug='floob')
        self.detail_url = reverse(
            'admin:bandwagon_collection_change', args=(collection.pk,)
        )
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Collections:Edit')
        self.client.login(email=user.email)
        response = self.client.get(self.detail_url, follow=True)
        assert response.status_code == 200
        assert collection.slug in response.content.decode('utf-8')

        post_data = {
            # Django wants the whole form to be submitted, unfortunately.
            'application': amo.FIREFOX.id,
            'type': collection.type,
            'default_locale': collection.default_locale,
            'author': user.pk,
        }
        post_data['slug'] = 'bar'
        response = self.client.post(self.detail_url, post_data, follow=True)
        assert response.status_code == 200
        collection.reload()
        assert collection.slug == 'bar'

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
