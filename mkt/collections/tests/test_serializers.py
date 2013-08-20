# -*- coding: utf-8 -*-
from nose.tools import eq_, ok_

import amo.tests
from mkt.collections.constants import COLLECTIONS_TYPE_BASIC
from mkt.collections.models import Collection
from mkt.collections.serializers import (CollectionMembershipField,
                                         CollectionSerializer,)
from mkt.webapps.utils import app_to_dict


class CollectionDataMixin(object):
    collection_data = {
        'collection_type': COLLECTIONS_TYPE_BASIC,
        'name': {'en-US': u'A collection of my favourite gàmes'},
        'slug': 'my-favourite-games',
        'description': {'en-US': u'A collection of my favourite gamés'},
    }


class TestCollectionMembershipField(CollectionDataMixin, amo.tests.TestCase):

    def setUp(self):
        self.collection = Collection.objects.create(**self.collection_data)
        self.app = amo.tests.app_factory()
        self.collection.add_app(self.app)
        self.field = CollectionMembershipField()

    def test_to_native(self):
        membership = self.collection.collectionmembership_set.all()[0]
        native = self.field.to_native(membership)
        eq_(native, app_to_dict(self.app))


class TestCollectionSerializer(CollectionDataMixin, amo.tests.TestCase):

    def setUp(self):
        self.collection = Collection.objects.create(**self.collection_data)
        self.serializer = CollectionSerializer()

    def test_to_native(self, apps=None):
        if apps:
            for app in apps:
                self.collection.add_app(app)
        else:
            apps = []

        data = self.serializer.to_native(self.collection)
        for name, value in self.collection_data.iteritems():
            eq_(self.collection_data[name], data[name])
        self.assertSetEqual(data.keys(), ['id', 'name', 'description', 'apps',
                                          'collection_type', 'category',
                                          'region', 'carrier', 'author',
                                          'slug', 'is_public',
                                          'default_language'])
        for order, app in enumerate(apps):
            eq_(data['apps'][order]['slug'], app.app_slug)

    def test_wrong_default_language_serialization(self):
        # The following is wrong because we only accept the 'en-us' form.
        data = {'default_language': u'en_US'}
        serializer = CollectionSerializer(instance=self.collection, data=data,
                                          partial=True)
        eq_(serializer.is_valid(), False)
        ok_('default_language' in serializer.errors)

    def test_translation_deserialization(self):
        data = {
            'name': u'¿Dónde está la biblioteca?'
        }
        serializer = CollectionSerializer(instance=self.collection, data=data,
                                          partial=True)
        eq_(serializer.errors, {})
        ok_(serializer.is_valid())

    def test_translation_deserialization_multiples_locales(self):
        data = {
            'name': {
                'fr': u'Chat grincheux…',
                'en-US': u'Grumpy Cat...'
            }
        }
        serializer = CollectionSerializer(instance=self.collection, data=data,
                                          partial=True)
        eq_(serializer.errors, {})
        ok_(serializer.is_valid())

    def test_to_native_with_apps(self):
        apps = [amo.tests.app_factory() for n in xrange(1, 5)]
        self.test_to_native(apps=apps)
