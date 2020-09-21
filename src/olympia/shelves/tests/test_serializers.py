from urllib import parse

from rest_framework.settings import api_settings
from rest_framework.test import APIRequestFactory

from django.conf import settings
from django.contrib.auth.models import AnonymousUser

from olympia.addons.views import AddonSearchView
from olympia.amo.tests import TestCase, reverse_ns
from olympia.shelves.models import Shelf
from olympia.shelves.serializers import ShelfSerializer


class TestShelvesSerializer(TestCase):
    def setUp(self):
        self.search_shelf = Shelf.objects.create(
            title='Populâr themes',
            endpoint='search',
            criteria='?sort=users&type=statictheme',
            footer_text='See more populâr themes')

        self.collections_shelf = Shelf.objects.create(
            title='Enhanced privacy extensions',
            endpoint='collections',
            criteria='privacy-matters',
            footer_text='See more enhanced privacy extensions')

        # Set up the request to support drf_reverse
        api_version = api_settings.DEFAULT_VERSION
        self.request = APIRequestFactory().get('/api/%s/' % api_version)
        self.request.versioning_scheme = (
            api_settings.DEFAULT_VERSIONING_CLASS()
        )
        self.request.version = api_version
        self.request.user = AnonymousUser()

    def get_serializer(self, instance, **extra_context):
        extra_context['request'] = self.request
        return ShelfSerializer(instance=instance, context=extra_context)

    def serialize(self, instance, **extra_context):
        if instance.endpoint == 'search':
            self.request.query_params = dict(parse.parse_qsl(
                self.search_shelf.criteria))
        return self.get_serializer(instance, **extra_context).data

    def test_shelf_serializer_search(self):
        data = self.serialize(instance=self.search_shelf)
        search_url = reverse_ns('addon-search') + self.search_shelf.criteria
        assert data == {
            'title': 'Populâr themes',
            'url': search_url,
            'endpoint': self.search_shelf.endpoint,
            'criteria': self.search_shelf.criteria,
            'footer_text': 'See more populâr themes',
            'footer_pathname': '',
            'addons': AddonSearchView(request=self.request).data
        }

    def test_shelf_serializer_collections(self):
        data = self.serialize(instance=self.collections_shelf)
        collections_url = reverse_ns('collection-addon-list', kwargs={
            'user_pk': settings.TASK_USER_ID,
            'collection_slug': self.collections_shelf.criteria})
        assert data == {
            'title': 'Enhanced privacy extensions',
            'url': collections_url,
            'endpoint': self.collections_shelf.endpoint,
            'criteria': self.collections_shelf.criteria,
            'footer_text': 'See more enhanced privacy extensions',
            'footer_pathname': '',
            'addons': None
        }
