# -*- coding: utf-8 -*-
import json

import django.test

from django.conf import settings
from django.test.utils import override_settings

from rest_framework.fields import empty

from olympia import amo
from olympia.amo.tests import (
    APITestClient, TestCase, addon_factory, collection_factory, reverse_ns,
    user_factory)
from olympia.amo.urlresolvers import get_outgoing_url
from olympia.bandwagon.models import Collection, CollectionAddon


class TestCollectionViewSetList(TestCase):
    client_class = APITestClient

    def setUp(self):
        self.user = user_factory()
        self.url = reverse_ns(
            'collection-list', kwargs={'user_pk': self.user.pk})
        super(TestCollectionViewSetList, self).setUp()

    def test_basic(self):
        collection_factory(author=self.user)
        collection_factory(author=self.user)
        collection_factory(author=self.user)
        collection_factory(author=user_factory())  # Not our collection.
        Collection.objects.all().count() == 4

        self.client.login_api(self.user)
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert len(response.data['results']) == 3

    def test_no_auth(self):
        collection_factory(author=self.user)
        response = self.client.get(self.url)
        assert response.status_code == 401

    def test_different_user(self):
        random_user = user_factory()
        other_url = reverse_ns('collection-list',
                               kwargs={'user_pk': random_user.pk})
        collection_factory(author=random_user)

        self.client.login_api(self.user)
        response = self.client.get(other_url)
        assert response.status_code == 403

    def test_admin(self):
        random_user = user_factory()
        other_url = reverse_ns('collection-list',
                               kwargs={'user_pk': random_user.pk})
        collection_factory(author=random_user)

        self.grant_permission(self.user, 'Collections:Edit')
        self.client.login_api(self.user)
        response = self.client.get(other_url)
        assert response.status_code == 403

        self.grant_permission(self.user, 'Collections:Contribute')
        self.client.login_api(self.user)
        response = self.client.get(other_url)
        assert response.status_code == 403

        self.grant_permission(self.user, 'Admin:Curation')
        response = self.client.get(other_url)
        assert response.status_code == 403

    def test_404(self):
        # Invalid user.
        url = reverse_ns(
            'collection-list', kwargs={'user_pk': self.user.pk + 66})

        # Not logged in.
        response = self.client.get(url)
        assert response.status_code == 401

        # Logged in
        self.client.login_api(self.user)
        response = self.client.get(url)
        assert response.status_code == 404

    def test_sort(self):
        col_a = collection_factory(author=self.user)
        col_b = collection_factory(author=self.user)
        col_c = collection_factory(author=self.user)
        col_a.update(modified=self.days_ago(3), _signal=False)
        col_b.update(modified=self.days_ago(1), _signal=False)
        col_c.update(modified=self.days_ago(6), _signal=False)

        self.client.login_api(self.user)
        response = self.client.get(self.url)
        assert response.status_code == 200
        # should be b a c because 1, 3, 6 days ago.
        assert response.data['results'][0]['uuid'] == col_b.uuid.hex
        assert response.data['results'][1]['uuid'] == col_a.uuid.hex
        assert response.data['results'][2]['uuid'] == col_c.uuid.hex

    def test_with_addons_is_ignored(self):
        collection_factory(author=self.user)
        self.client.login_api(self.user)
        response = self.client.get(self.url + '?with_addons')
        assert response.status_code == 200, response.data
        assert 'addons' not in response.data['results'][0]


class TestCollectionViewSetDetail(TestCase):
    client_class = APITestClient

    def setUp(self):
        self.user = user_factory()
        self.collection = collection_factory(author=self.user)
        self.url = self._get_url(self.user, self.collection)
        super(TestCollectionViewSetDetail, self).setUp()

    def _get_url(self, user, collection):
        return reverse_ns(
            'collection-detail', api_version='v5', kwargs={
                'user_pk': user.pk, 'slug': collection.slug})

    def test_basic(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert response.data['id'] == self.collection.id

    def test_no_id_lookup(self):
        collection = collection_factory(author=self.user, slug='999')
        id_url = reverse_ns(
            'collection-detail', kwargs={
                'user_pk': self.user.pk, 'slug': collection.id})
        response = self.client.get(id_url)
        assert response.status_code == 404
        slug_url = reverse_ns(
            'collection-detail', kwargs={
                'user_pk': self.user.pk, 'slug': collection.slug})
        response = self.client.get(slug_url)
        assert response.status_code == 200
        assert response.data['id'] == collection.id

    def test_not_listed(self):
        self.collection.update(listed=False)

        # not logged in
        response = self.client.get(self.url)
        assert response.status_code == 401

        # logged in
        random_user = user_factory()
        self.client.login_api(random_user)
        response = self.client.get(self.url)
        assert response.status_code == 403

    def test_not_listed_self(self):
        self.collection.update(listed=False)

        self.client.login_api(self.user)
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert response.data['id'] == self.collection.id

    def test_not_listed_admin(self):
        random_user = user_factory()
        collection = collection_factory(author=random_user, listed=False)

        self.grant_permission(self.user, 'Collections:Edit')
        self.client.login_api(self.user)
        response = self.client.get(self._get_url(random_user, collection))
        assert response.status_code == 403

        self.grant_permission(self.user, 'Collections:Contribute')
        self.client.login_api(self.user)
        response = self.client.get(self._get_url(random_user, collection))
        assert response.status_code == 403

        self.grant_permission(self.user, 'Admin:Curation')
        response = self.client.get(self._get_url(random_user, collection))
        assert response.status_code == 403

        with override_settings(TASK_USER_ID=random_user.id):
            response = self.client.get(self._get_url(random_user, collection))
        assert response.status_code == 200
        assert response.data['id'] == collection.pk

    def test_not_listed_contributor(self):
        self.collection.update(listed=False)

        random_user = user_factory()
        setting_key = 'COLLECTION_FEATURED_THEMES_ID'
        with override_settings(**{setting_key: self.collection.id}):
            self.client.login_api(random_user)
            # Not their collection so not allowed.
            response = self.client.get(self.url)
            assert response.status_code == 403

            self.grant_permission(random_user, 'Collections:Contribute')
            # Now they can access it.
            response = self.client.get(self.url)
            assert response.status_code == 200
            assert response.data['id'] == self.collection.id

        # Double check only the COLLECTION_FEATURED_THEMES_ID is allowed.
        response = self.client.get(self.url)
        assert response.status_code == 403

        # Even on a mozilla-owned collection.
        with override_settings(TASK_USER_ID=random_user.id):
            response = self.client.get(self.url)
        assert response.status_code == 403

    def test_404(self):
        # Invalid user.
        response = self.client.get(reverse_ns(
            'collection-detail', kwargs={
                'user_pk': self.user.pk + 66, 'slug': self.collection.slug}))
        assert response.status_code == 404
        # Invalid collection.
        response = self.client.get(reverse_ns(
            'collection-detail', kwargs={
                'user_pk': self.user.pk, 'slug': 'hello'}))
        assert response.status_code == 404

    def test_with_addons(self):
        addon = addon_factory()
        self.collection.add_addon(addon)
        response = self.client.get(self.url + '?with_addons')
        assert response.status_code == 200
        assert response.data['id'] == self.collection.id
        addon_data = response.data['addons'][0]['addon']
        assert addon_data['id'] == addon.id
        assert isinstance(addon_data['name'], dict)
        assert addon_data['name'] == {'en-US': str(addon.name)}

        # Now test the limit of addons returned
        self.collection.add_addon(addon_factory())
        self.collection.add_addon(addon_factory())
        self.collection.add_addon(addon_factory())
        response = self.client.get(self.url + '?with_addons')
        assert len(response.data['addons']) == 4
        patched_drf_setting = dict(settings.REST_FRAMEWORK)
        patched_drf_setting['PAGE_SIZE'] = 3
        with django.test.override_settings(REST_FRAMEWORK=patched_drf_setting):
            response = self.client.get(self.url + '?with_addons')
            assert len(response.data['addons']) == 3

    def test_with_addons_and_wrap_outgoing_links_and_lang(self):
        addon = addon_factory(
            support_url='http://support.example.com',
            homepage='http://homepage.example.com')
        self.collection.add_addon(addon)
        response = self.client.get(
            self.url + '?with_addons&lang=en-US&wrap_outgoing_links')
        assert response.status_code == 200
        assert response.data['id'] == self.collection.id
        addon_data = response.data['addons'][0]['addon']
        assert addon_data['id'] == addon.id
        assert isinstance(addon_data['name']['en-US'], str)
        assert addon_data['name'] == {'en-US': str(addon.name)}
        assert isinstance(addon_data['homepage']['en-US'], str)
        assert addon_data['homepage'] == {
            'en-US': get_outgoing_url(str(addon.homepage))}
        assert isinstance(addon_data['support_url']['en-US'], str)
        assert addon_data['support_url'] == {
            'en-US': get_outgoing_url(str(addon.support_url))}

        overridden_api_gates = {
            'v5': ('l10n_flat_input_output',)}
        with override_settings(DRF_API_GATES=overridden_api_gates):
            response = self.client.get(
                self.url + '?with_addons&lang=en-US&wrap_outgoing_links')
            assert response.status_code == 200
            assert response.data['id'] == self.collection.id
            addon_data = response.data['addons'][0]['addon']
            assert addon_data['id'] == addon.id
            assert isinstance(addon_data['name'], str)
            assert addon_data['name'] == str(addon.name)
            assert isinstance(addon_data['homepage'], str)
            assert addon_data['homepage'] == get_outgoing_url(
                str(addon.homepage))
            assert isinstance(addon_data['support_url'], str)
            assert addon_data['support_url'] == get_outgoing_url(
                str(addon.support_url))


class CollectionViewSetDataMixin(object):
    client_class = APITestClient
    data = {
        'name': {'fr': u'lé $túff', 'en-US': u'$tuff'},
        'description': {'fr': u'Un dis une dát', 'en-US': u'dis n dat'},
        'slug': u'stuff',
        'public': True,
        'default_locale': 'fr',
    }

    def setUp(self):
        self.url = self.get_url(self.user)
        super(CollectionViewSetDataMixin, self).setUp()

    def send(self, url=None, data=None):
        raise NotImplementedError

    def get_url(self, user):
        raise NotImplementedError

    @property
    def user(self):
        if not hasattr(self, '_user'):
            self._user = user_factory()
        return self._user

    def check_data(self, collection, data, json):
        for prop, value in data.items():
            assert json[prop] == value

        with self.activate('fr'):
            collection = collection.reload()
            assert collection.name == data['name']['fr']
            assert collection.description == data['description']['fr']
            assert collection.slug == data['slug']
            assert collection.listed == data['public']
            assert collection.default_locale == data['default_locale']

    def test_no_auth(self):
        response = self.send()
        assert response.status_code == 401

    def test_update_name_invalid(self):
        self.client.login_api(self.user)
        data = dict(self.data)
        # Sending a single value for localized field is now forbidden.
        data.update(name=u'   ')
        response = self.send(data=data)
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'name': ['You must provide an object of {lang-code:value}.']}

        # Passing a dict of localised values
        data.update(name={'en-US': u'   '})
        response = self.send(data=data)
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'name': ['Name cannot be empty.']}

    @override_settings(DRF_API_GATES={
        'v5': ('l10n_flat_input_output',)})
    def test_update_name_invalid_flat_input(self):
        self.client.login_api(self.user)
        data = dict(self.data)
        data.update(name=u'   ')
        response = self.send(data=data)
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'name': ['Name cannot be empty.']}

        # Passing a dict of localised values
        data.update(name={'en-US': u'   '})
        response = self.send(data=data)
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'name': ['Name cannot be empty.']}

    def test_biography_no_links(self):
        self.client.login_api(self.user)
        data = dict(self.data)
        data.update(description='<a href="https://google.com">google</a>')
        response = self.send(data=data)
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'description': [
                'You must provide an object of {lang-code:value}.']}

        data.update(description={
            'en-US': '<a href="https://google.com">google</a>'})
        response = self.send(data=data)
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'description': ['No links are allowed.']}

    @override_settings(DRF_API_GATES={
        'v5': ('l10n_flat_input_output',)})
    def test_biography_no_links_flat_input(self):
        self.client.login_api(self.user)
        data = dict(self.data)
        data.update(description='<a href="https://google.com">google</a>')
        response = self.send(data=data)
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'description': ['No links are allowed.']}

        data.update(description={
            'en-US': '<a href="https://google.com">google</a>'})
        response = self.send(data=data)
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'description': ['No links are allowed.']}

    def test_slug_valid(self):
        self.client.login_api(self.user)
        data = dict(self.data)
        data.update(slug=u'£^@')
        response = self.send(data=data)
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'slug': [u'The custom URL must consist of letters, numbers, '
                     u'underscores or hyphens.']}

    def test_slug_unique(self):
        collection_factory(author=self.user, slug='edam')
        self.client.login_api(self.user)
        data = dict(self.data)
        data.update(slug=u'edam')
        response = self.send(data=data)
        assert response.status_code == 400
        assert u'This custom URL is already in use' in (
            ','.join(json.loads(response.content)['non_field_errors']))


class TestCollectionViewSetCreate(CollectionViewSetDataMixin, TestCase):

    def send(self, url=None, data=None):
        return self.client.post(url or self.url, data or self.data)

    def get_url(self, user):
        return reverse_ns(
            'collection-list', api_version='v5',
            kwargs={'user_pk': user.pk})

    def test_basic_create(self):
        self.client.login_api(self.user)
        response = self.send()
        assert response.status_code == 201, response.content
        collection = Collection.objects.get()
        self.check_data(collection, self.data, json.loads(response.content))
        assert collection.author.id == self.user.id
        assert collection.uuid

    def test_create_minimal(self):
        self.client.login_api(self.user)
        data = {
            'name': {'en-US': u'this'},
            'slug': u'minimal',
        }
        response = self.send(data=data)
        assert response.status_code == 201, response.content
        collection = Collection.objects.get()
        assert collection.name == data['name']['en-US']
        assert collection.slug == data['slug']

        # Double-check trying to create with a non-dict name now fails
        data = {
            'name': u'this',
            'slug': u'minimal',
        }
        response = self.send(data=data)
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'name': ['You must provide an object of {lang-code:value}.']}

    @override_settings(DRF_API_GATES={
        'v5': ('l10n_flat_input_output',)})
    def test_create_minimal_flat_input(self):
        self.client.login_api(self.user)
        data = {
            'name': u'this',
            'slug': u'minimal',
        }
        response = self.send(data=data)
        assert response.status_code == 201, response.content
        collection = Collection.objects.get()
        assert collection.name == data['name']
        assert collection.slug == data['slug']

    def test_create_cant_set_readonly(self):
        self.client.login_api(self.user)
        data = {
            'name': {'en-US': u'this'},
            'slug': u'minimal',
            'addon_count': 99,  # In the serializer but read-only.
        }
        response = self.send(data=data)
        assert response.status_code == 201, response.content
        collection = Collection.objects.get()
        assert collection.addon_count != 99

    def test_different_account(self):
        self.client.login_api(self.user)
        different_user = user_factory()
        url = self.get_url(different_user)
        response = self.send(url=url)
        assert response.status_code == 403

    def test_admin_create_fails(self):
        self.grant_permission(self.user, 'Collections:Edit')
        self.client.login_api(self.user)
        random_user = user_factory()
        url = self.get_url(random_user)
        response = self.send(url=url)
        assert response.status_code == 403

        self.grant_permission(self.user, 'Collections:Contribute')
        response = self.send(url=url)
        assert response.status_code == 403

        self.grant_permission(self.user, 'Admin:Curation')
        response = self.send(url=url)
        assert response.status_code == 403

    def test_create_numeric_slug(self):
        self.client.login_api(self.user)
        data = {
            'name': {'en-US': u'this'},
            'slug': u'1',
        }
        response = self.send(data=data)
        assert response.status_code == 201, response.content
        collection = Collection.objects.get()
        assert collection.name == data['name']['en-US']
        assert collection.slug == data['slug']


class TestCollectionViewSetPatch(CollectionViewSetDataMixin, TestCase):

    def setUp(self):
        self.collection = collection_factory(author=self.user)
        super(TestCollectionViewSetPatch, self).setUp()

    def send(self, url=None, data=None):
        return self.client.patch(url or self.url, data or self.data)

    def get_url(self, user):
        return reverse_ns(
            'collection-detail', api_version='v5', kwargs={
                'user_pk': user.pk, 'slug': self.collection.slug})

    def test_basic_patch(self):
        self.client.login_api(self.user)
        original = self.client.get(self.url).content
        response = self.send()
        assert response.status_code == 200
        assert response.content != original
        self.collection = self.collection.reload()
        self.check_data(self.collection, self.data,
                        json.loads(response.content))

    def test_different_account(self):
        self.client.login_api(self.user)
        different_user = user_factory()
        self.collection.update(author=different_user)
        url = self.get_url(different_user)
        response = self.send(url=url)
        assert response.status_code == 403

    def test_admin_patch(self):
        self.grant_permission(self.user, 'Collections:Edit')
        self.client.login_api(self.user)
        random_user = user_factory()
        self.collection.update(author=random_user)
        url = self.get_url(random_user)
        original = self.client.get(url).content
        response = self.send(url=url)
        assert response.status_code == 403

        self.grant_permission(self.user, 'Collections:Contribute')
        response = self.send(url=url)
        assert response.status_code == 403

        self.grant_permission(self.user, 'Admin:Curation')
        response = self.send(url=url)
        assert response.status_code == 403

        with override_settings(TASK_USER_ID=random_user.id):
            response = self.send(url=url)
        assert response.status_code == 200

        assert response.content != original
        self.collection = self.collection.reload()
        self.check_data(self.collection, self.data,
                        json.loads(response.content))
        # Just double-check we didn't steal their collection
        assert self.collection.author.id == random_user.id

    def test_contributor_patch_fails(self):
        self.client.login_api(self.user)
        random_user = user_factory()
        self.collection.update(author=random_user)
        self.grant_permission(random_user, 'Collections:Contribute')
        url = self.get_url(random_user)
        setting_key = 'COLLECTION_FEATURED_THEMES_ID'
        with override_settings(**{setting_key: self.collection.id}):
            # Check setup is good and we can access the collection okay.
            get_response = self.client.get(url)
            assert get_response.status_code == 200
            # But can't patch it.
            response = self.send(url=url)
            assert response.status_code == 403


class TestCollectionViewSetDelete(TestCase):
    client_class = APITestClient

    def setUp(self):
        self.user = user_factory()
        self.collection = collection_factory(author=self.user)
        self.url = self.get_url(self.user)
        super(TestCollectionViewSetDelete, self).setUp()

    def get_url(self, user):
        return reverse_ns(
            'collection-detail', kwargs={
                'user_pk': user.pk, 'slug': self.collection.slug})

    def test_delete(self):
        self.client.login_api(self.user)
        response = self.client.delete(self.url)
        assert response.status_code == 204
        assert not Collection.objects.filter(id=self.collection.id).exists()

    def test_no_auth(self):
        response = self.client.delete(self.url)
        assert response.status_code == 401

    def test_different_account_fails(self):
        self.client.login_api(self.user)
        different_user = user_factory()
        self.collection.update(author=different_user)
        url = self.get_url(different_user)
        response = self.client.delete(url)
        assert response.status_code == 403

    def test_admin_delete(self):
        self.grant_permission(self.user, 'Collections:Edit')
        self.client.login_api(self.user)
        random_user = user_factory()
        self.collection.update(author=random_user)
        url = self.get_url(random_user)
        response = self.client.delete(url)
        assert response.status_code == 403

        self.grant_permission(self.user, 'Collections:Contribute')
        response = self.client.delete(url)
        assert response.status_code == 403

        self.grant_permission(self.user, 'Admin:Curation')
        response = self.client.delete(url)
        assert response.status_code == 403
        assert Collection.objects.filter(id=self.collection.id).exists()

        # Curators can't delete collections even owned by mozilla.
        with override_settings(TASK_USER_ID=random_user.id):
            response = self.client.delete(url)
        assert response.status_code == 403
        assert Collection.objects.filter(id=self.collection.id).exists()

    def test_contributor_fails(self):
        self.client.login_api(self.user)
        different_user = user_factory()
        self.collection.update(author=different_user)
        self.grant_permission(different_user, 'Collections:Contribute')
        url = self.get_url(different_user)
        setting_key = 'COLLECTION_FEATURED_THEMES_ID'
        with override_settings(**{setting_key: self.collection.id}):
            # Check setup is good and we can access the collection okay.
            get_response = self.client.get(url)
            assert get_response.status_code == 200
            # But can't delete it.
            response = self.client.delete(url)
            assert response.status_code == 403


class CollectionAddonViewSetMixin(object):
    def check_response(self, response):
        raise NotImplementedError

    def send(self, url):
        # List and Detail do this.  Override for other verbs.
        return self.client.get(url)

    def test_basic(self):
        self.check_response(self.send(self.url))

    def test_not_listed_not_logged_in(self):
        self.collection.update(listed=False)
        response = self.send(self.url)
        assert response.status_code == 401

    def test_not_listed_different_user(self):
        self.collection.update(listed=False)
        different_user = user_factory()
        self.client.login_api(different_user)
        response = self.send(self.url)
        assert response.status_code == 403

    def test_not_listed_self(self):
        self.collection.update(listed=False)
        self.client.login_api(self.user)
        self.check_response(self.send(self.url))

    def test_not_listed_admin(self):
        self.collection.update(listed=False)
        admin_user = user_factory()
        self.grant_permission(admin_user, 'Collections:Edit')
        self.client.login_api(admin_user)
        response = self.send(self.url)
        assert response.status_code == 403

        self.grant_permission(admin_user, 'Collections:Contribute')
        response = self.send(self.url)
        assert response.status_code == 403

        self.grant_permission(admin_user, 'Admin:Curation')
        response = self.send(self.url)
        assert response.status_code == 403

        with override_settings(TASK_USER_ID=self.collection.author.id):
            self.check_response(self.send(self.url))

    def test_contributor(self):
        self.collection.update(listed=False)
        random_user = user_factory()
        self.grant_permission(random_user, 'Collections:Contribute')
        self.client.login_api(random_user)
        # should fail as self.collection isn't special
        response = self.send(self.url)
        assert response.status_code == 403
        # But now with special collection will work
        setting_key = 'COLLECTION_FEATURED_THEMES_ID'
        with override_settings(**{setting_key: self.collection.id}):
            self.check_response(self.send(self.url))


class TestCollectionAddonViewSetList(CollectionAddonViewSetMixin, TestCase):
    client_class = APITestClient

    def setUp(self):
        self.user = user_factory()
        self.collection = collection_factory(author=self.user)
        self.addon_a = addon_factory(name=u'anteater')
        self.addon_b = addon_factory(name=u'baboon')
        self.addon_c = addon_factory(name=u'cheetah')
        self.addon_disabled = addon_factory(name=u'antelope_disabled')
        self.addon_deleted = addon_factory(name=u'buffalo_deleted')
        self.addon_pending = addon_factory(name=u'pelican_pending')

        # Set a few more languages on our add-ons to test sorting
        # a bit better. https://github.com/mozilla/addons-server/issues/8354
        self.addon_a.name = {'de': u'Ameisenbär'}
        self.addon_a.save()

        self.addon_b.name = {'de': u'Pavian'}
        self.addon_b.save()

        self.addon_c.name = {'de': u'Gepard'}
        self.addon_c.save()

        self.collection.add_addon(self.addon_a)
        self.collection.add_addon(self.addon_disabled)
        self.collection.add_addon(self.addon_b)
        self.collection.add_addon(self.addon_deleted)
        self.collection.add_addon(self.addon_c)
        self.collection.add_addon(self.addon_pending)

        # Set up our filtered-out-by-default addons
        self.addon_disabled.update(disabled_by_user=True)
        self.addon_deleted.delete()
        self.addon_pending.current_version.all_files[0].update(
            status=amo.STATUS_AWAITING_REVIEW)

        self.url = reverse_ns(
            'collection-addon-list', kwargs={
                'user_pk': self.user.pk,
                'collection_slug': self.collection.slug})
        super(TestCollectionAddonViewSetList, self).setUp()

    def check_response(self, response):
        assert response.status_code == 200, self.url
        assert len(response.data['results']) == 3

    def test_404(self):
        # Invalid user.
        response = self.client.get(reverse_ns(
            'collection-addon-list', kwargs={
                'user_pk': self.user.pk + 66,
                'collection_slug': self.collection.slug}))
        assert response.status_code == 404
        # Invalid collection.
        response = self.client.get(reverse_ns(
            'collection-addon-list', kwargs={
                'user_pk': self.user.pk,
                'collection_slug': 'hello'}))
        assert response.status_code == 404

    def check_result_order(self, response, first, second, third):
        results = response.data['results']
        assert results[0]['addon']['id'] == first.id
        assert results[1]['addon']['id'] == second.id
        assert results[2]['addon']['id'] == third.id
        assert len(response.data['results']) == 3

    def test_sorting(self):
        self.addon_a.update(weekly_downloads=500)
        self.addon_b.update(weekly_downloads=1000)
        self.addon_c.update(weekly_downloads=100)

        self.client.login_api(self.user)

        # First default sort
        self.check_result_order(
            self.client.get(self.url),
            self.addon_b, self.addon_a, self.addon_c)

        # Popularity ascending
        self.check_result_order(
            self.client.get(self.url + '?sort=popularity'),
            self.addon_c, self.addon_a, self.addon_b)

        # Popularity descending (same as default)
        self.check_result_order(
            self.client.get(self.url + '?sort=-popularity'),
            self.addon_b, self.addon_a, self.addon_c)

        CollectionAddon.objects.get(
            collection=self.collection, addon=self.addon_a).update(
            created=self.days_ago(1))
        CollectionAddon.objects.get(
            collection=self.collection, addon=self.addon_b).update(
            created=self.days_ago(3))
        CollectionAddon.objects.get(
            collection=self.collection, addon=self.addon_c).update(
            created=self.days_ago(2))

        # Added ascending
        self.check_result_order(
            self.client.get(self.url + '?sort=added'),
            self.addon_b, self.addon_c, self.addon_a)

        # Added descending
        self.check_result_order(
            self.client.get(self.url + '?sort=-added'),
            self.addon_a, self.addon_c, self.addon_b)

        # Name ascending
        self.check_result_order(
            self.client.get(self.url + '?sort=name'),
            self.addon_a, self.addon_b, self.addon_c)

        # Name descending
        self.check_result_order(
            self.client.get(self.url + '?sort=-name'),
            self.addon_c, self.addon_b, self.addon_a)

        # Name ascending, German
        self.check_result_order(
            self.client.get(self.url + '?sort=name&lang=de'),
            self.addon_a, self.addon_c, self.addon_b)

        # Name descending, German
        self.check_result_order(
            self.client.get(self.url + '?sort=-name&lang=de'),
            self.addon_b, self.addon_c, self.addon_a)

    def test_name_sorting_no_english(self):
        CollectionAddon.objects.get(
            collection=self.collection, addon=self.addon_a).update(
            created=self.days_ago(1))
        CollectionAddon.objects.get(
            collection=self.collection, addon=self.addon_b).update(
            created=self.days_ago(3))
        CollectionAddon.objects.get(
            collection=self.collection, addon=self.addon_c).update(
            created=self.days_ago(2))

        # Change all english translations to be Spanish instead, making sure we
        # don't have translations in settings.LANGUAGE_CODE (en-US).
        from olympia.translations.models import Translation
        Translation.objects.filter(locale=settings.LANGUAGE_CODE, id__in=(
            self.addon_a.name_id,
            self.addon_b.name_id,
            self.addon_c.name_id)).update(locale='es')

        # Then give a valid default_locale to the addons, 'de' (they already
        # all have a german translation)
        self.addon_a.update(default_locale='de')
        self.addon_b.update(default_locale='de')
        self.addon_c.update(default_locale='de')

        # Sort by name ascending, in French (should fall back to their
        # default_locale, # German).
        self.check_result_order(
            self.client.get(self.url + '?sort=name&lang=fr'),
            self.addon_a, self.addon_c, self.addon_b)

    def test_only_one_sort_parameter_supported(self):
        response = self.client.get(self.url + '?sort=popularity,name')

        assert response.status_code == 400
        assert response.data == [
            'You can only specify one "sort" argument. Multiple orderings '
            'are not supported']

    def test_with_deleted_or_with_hidden(self):
        response = self.send(self.url)
        assert response.status_code == 200
        # Normal
        assert len(response.data['results']) == 3

        response = self.send(self.url + '?filter=all')
        assert response.status_code == 200
        # Now there should be 2 extra
        assert len(response.data['results']) == 5

        response = self.send(self.url + '?filter=all_with_deleted')
        assert response.status_code == 200
        # And one more still - with_deleted gets you with_hidden too.
        assert len(response.data['results']) == 6
        all_addons_ids = {
            self.addon_a.id, self.addon_b.id, self.addon_c.id,
            self.addon_disabled.id, self.addon_deleted.id,
            self.addon_pending.id}
        result_ids = {
            result['addon']['id'] for result in response.data['results']}
        assert all_addons_ids == result_ids


class TestCollectionAddonViewSetDetail(CollectionAddonViewSetMixin, TestCase):
    client_class = APITestClient

    def setUp(self):
        self.user = user_factory()
        self.collection = collection_factory(author=self.user)
        self.addon = addon_factory()
        self.collection.add_addon(self.addon)
        self.url = reverse_ns(
            'collection-addon-detail', kwargs={
                'user_pk': self.user.pk,
                'collection_slug': self.collection.slug,
                'addon': self.addon.id})
        super(TestCollectionAddonViewSetDetail, self).setUp()

    def check_response(self, response):
        assert response.status_code == 200, self.url
        assert response.data['addon']['id'] == self.addon.id

    def test_with_slug(self):
        self.url = reverse_ns(
            'collection-addon-detail', kwargs={
                'user_pk': self.user.pk,
                'collection_slug': self.collection.slug,
                'addon': self.addon.slug})
        self.test_basic()

    def test_deleted(self):
        self.addon.delete()
        self.test_basic()


class TestCollectionAddonViewSetCreate(CollectionAddonViewSetMixin, TestCase):
    client_class = APITestClient

    def setUp(self):
        self.user = user_factory()
        self.collection = collection_factory(author=self.user)
        self.url = reverse_ns(
            'collection-addon-list', api_version='v5', kwargs={
                'user_pk': self.user.pk,
                'collection_slug': self.collection.slug})
        self.addon = addon_factory()
        super(TestCollectionAddonViewSetCreate, self).setUp()

    def check_response(self, response):
        assert response.status_code == 201, response.content
        assert CollectionAddon.objects.filter(
            collection=self.collection.id, addon=self.addon.id).exists()

    def send(self, url, data=None):
        data = data or {'addon': self.addon.pk}
        return self.client.post(url, data=data)

    def test_basic(self):
        assert not CollectionAddon.objects.filter(
            collection=self.collection.id).exists()
        self.client.login_api(self.user)
        response = self.send(self.url)
        self.check_response(response)

    def test_add_with_comments(self):
        self.client.login_api(self.user)
        response = self.send(self.url,
                             data={'addon': self.addon.pk,
                                   'notes': {'en-US': 'its good!'}})
        self.check_response(response)
        collection_addon = CollectionAddon.objects.get(
            collection=self.collection.id, addon=self.addon.id)
        assert collection_addon.addon == self.addon
        assert collection_addon.collection == self.collection
        assert collection_addon.comments == 'its good!'

        # Double-check trying to create with a non-dict name now fails
        response = self.send(self.url,
                             data={'addon': self.addon.pk,
                                   'notes': 'its good!'})
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'notes': ['You must provide an object of {lang-code:value}.']}

    @override_settings(DRF_API_GATES={
        'v5': ('l10n_flat_input_output',)})
    def test_add_with_comments_flat_input(self):
        self.client.login_api(self.user)
        response = self.send(self.url,
                             data={'addon': self.addon.pk,
                                   'notes': 'its good!'})
        self.check_response(response)
        collection_addon = CollectionAddon.objects.get(
            collection=self.collection.id, addon=self.addon.id)
        assert collection_addon.addon == self.addon
        assert collection_addon.collection == self.collection
        assert collection_addon.comments == 'its good!'

    def test_fail_when_no_addon(self):
        self.client.login_api(self.user)
        response = self.send(self.url, data={'notes': {'en-US': ''}})
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'addon': [u'This field is required.']}

    def test_fail_when_not_public_addon(self):
        self.client.login_api(self.user)
        self.addon.update(status=amo.STATUS_NULL)
        response = self.send(self.url)
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'addon': ['Invalid pk or slug "%s" - object does not exist.' %
                      self.addon.pk]}

    def test_fail_when_invalid_addon(self):
        self.client.login_api(self.user)
        response = self.send(self.url, data={'addon': 3456})
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'addon': ['Invalid pk or slug "%s" - object does not exist.' %
                      3456]}

    def test_with_slug(self):
        self.client.login_api(self.user)
        response = self.send(self.url, data={'addon': self.addon.slug})
        self.check_response(response)

    def test_uniqueness_message(self):
        CollectionAddon.objects.create(
            collection=self.collection, addon=self.addon)
        self.client.login_api(self.user)
        response = self.send(self.url, data={'addon': self.addon.slug})
        assert response.status_code == 400
        assert response.data == {
            u'non_field_errors':
                [u'This add-on already belongs to the collection']
        }


class TestCollectionAddonViewSetPatch(CollectionAddonViewSetMixin, TestCase):
    client_class = APITestClient

    def setUp(self):
        self.user = user_factory()
        self.collection = collection_factory(author=self.user)
        self.addon = addon_factory()
        self.collection.add_addon(self.addon)
        self.url = reverse_ns(
            'collection-addon-detail', api_version='v5', kwargs={
                'user_pk': self.user.pk,
                'collection_slug': self.collection.slug,
                'addon': self.addon.id})
        super(TestCollectionAddonViewSetPatch, self).setUp()

    def check_response(self, response, notes=empty):
        notes = notes if notes != empty else u'it does things'
        assert response.status_code == 200, response.content
        collection_addon = CollectionAddon.objects.get(
            collection=self.collection.id)
        assert collection_addon.addon == self.addon
        assert collection_addon.collection == self.collection
        assert collection_addon.comments == notes

    def send(self, url, data=None):
        data = data or {'notes': {'en-US': 'it does things'}}
        return self.client.patch(url, data=data)

    def test_basic(self):
        self.client.login_api(self.user)
        response = self.send(self.url)
        self.check_response(response)

    def test_flat_input(self):
        self.client.login_api(self.user)
        data = {'notes': 'it does things'}
        # By default this should be rejected
        response = self.send(self.url, data)
        assert response.status_code == 400
        assert json.loads(response.content) == {
            'notes': ['You must provide an object of {lang-code:value}.']}
        # But with the correct api gate, we can use the old behavior
        overridden_api_gates = {
            'v5': ('l10n_flat_input_output',)}
        with override_settings(DRF_API_GATES=overridden_api_gates):
            response = self.send(self.url, data)
            self.check_response(response)

    def test_cant_change_addon(self):
        self.client.login_api(self.user)
        new_addon = addon_factory()
        response = self.send(self.url,
                             data={'addon': new_addon.id})
        self.check_response(response, notes=None)

    def test_deleted(self):
        self.addon.delete()
        self.test_basic()


class TestCollectionAddonViewSetDelete(CollectionAddonViewSetMixin, TestCase):
    client_class = APITestClient

    def setUp(self):
        self.user = user_factory()
        self.collection = collection_factory(author=self.user)
        self.addon = addon_factory()
        self.collection.add_addon(self.addon)
        self.url = reverse_ns(
            'collection-addon-detail', kwargs={
                'user_pk': self.user.pk,
                'collection_slug': self.collection.slug,
                'addon': self.addon.id})
        super(TestCollectionAddonViewSetDelete, self).setUp()

    def check_response(self, response):
        assert response.status_code == 204
        assert not CollectionAddon.objects.filter(
            collection=self.collection.id, addon=self.addon).exists()

    def send(self, url):
        return self.client.delete(url)

    def test_basic(self):
        assert CollectionAddon.objects.filter(
            collection=self.collection.id, addon=self.addon).exists()
        self.client.login_api(self.user)
        response = self.send(self.url)
        self.check_response(response)

    def test_deleted(self):
        self.addon.delete()
        self.test_basic()
