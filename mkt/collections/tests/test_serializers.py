# -*- coding: utf-8 -*-
import os

from nose.tools import eq_, ok_
from tastypie.bundle import Bundle
from test_utils import RequestFactory

import amo.tests
from amo.urlresolvers import reverse

from mkt.api.resources import AppResource
from mkt.collections.constants import COLLECTIONS_TYPE_BASIC
from mkt.constants.features import FeatureProfile
from mkt.collections.models import Collection, CollectionMembership
from mkt.collections.serializers import (CollectionMembershipField,
                                         CollectionSerializer,
                                         DataURLImageField)


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
        self.membership = CollectionMembership.objects.all()[0]
        self.request = RequestFactory()
        self.profile = FeatureProfile(apps=True).to_signature()

    def test_to_native(self):
        resource = AppResource().full_dehydrate(Bundle(obj=self.app))
        native = self.field.to_native(self.membership)
        for key, value in native.iteritems():
            if key == 'resource_uri':
                eq_(value, self.app.get_api_url(pk=self.app.pk))
            else:
                eq_(value, resource.data[key])

    def test_field_to_native(self):
        self.field.parent = self.collection
        self.field.source = 'collectionmembership_set'
        self.field.context = {
            'request': self.request.get('/', {'pro': self.profile})
        }

        # Ensure that the one app is included in the default response.
        native = self.field.field_to_native(self.collection,
                                           'collectionmembership_set')
        eq_(len(native), 1)
        eq_(int(native[0]['id']), self.app.id)

        # ...but is not included when there is a feature profile mismatch.
        self.app.current_version.features.update(has_geolocation=True)
        native_without = self.field.field_to_native(self.collection,
                                                    'collectionmembership_set')
        eq_(len(native_without), 0)

    def test_field_to_native_invalid_profile(self):
        self.field.parent = self.collection
        self.field.source = 'collectionmembership_set'
        self.field.context = {
            'request': self.request.get('/', {'pro': 'muahaha'})
        }

        # Ensure that no exceptions were raised.
        native = self.field.field_to_native(self.collection,
                                            'collectionmembership_set')

        # Ensure that no filtering took place.
        eq_(len(native), 1)
        eq_(int(native[0]['id']), self.app.id)


class TestCollectionSerializer(CollectionDataMixin, amo.tests.TestCase):

    def setUp(self):
        minimal_context = {
            'request': RequestFactory().get('/whatever')
        }
        self.collection = Collection.objects.create(**self.collection_data)
        self.serializer = CollectionSerializer(context=minimal_context)

    def test_to_native(self, apps=None):
        if apps:
            for app in apps:
                self.collection.add_app(app)
        else:
            apps = []

        data = self.serializer.to_native(self.collection)
        for name, value in self.collection_data.iteritems():
            eq_(self.collection_data[name], data[name])
        self.assertSetEqual(data.keys(), ['apps', 'author', 'background_color',
                                          'carrier', 'category',
                                          'collection_type', 'default_language',
                                          'description', 'id', 'image',
                                          'is_public', 'name', 'region',
                                          'slug', 'text_color'])
        for order, app in enumerate(apps):
            eq_(data['apps'][order]['slug'], app.app_slug)
        return data

    def test_image(self):
        data = self.serializer.to_native(self.collection)
        eq_(data['image'], None)
        self.collection.update(has_image=True)
        data = self.serializer.to_native(self.collection)
        eq_(data['image'], reverse('collection-image-detail',
                                   kwargs={'pk': self.collection.id}))

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

    def test_empty_choice_deserialization(self):
        # Build data from existing object.
        data = self.serializer.to_native(self.collection)
        data.pop('id')
        # Emulate empty values passed via POST.
        data.update({'carrier': '', 'region': ''})

        instance = self.serializer.from_native(data, None)
        eq_(self.serializer.errors, {})
        ok_(self.serializer.is_valid())
        eq_(instance.region, None)
        eq_(instance.carrier, None)

    def test_to_native_with_apps(self):
        apps = [amo.tests.app_factory() for n in xrange(1, 5)]
        data = self.test_to_native(apps=apps)
        keys = data['apps'][0].keys()
        ok_('name' in keys)
        ok_('id' in keys)


IMAGE_DATA = """
R0lGODlhKAAoAPMAAP////vzBf9kA90JB/IIhEcApQAA0wKr6h+3FABkElYsBZBxOr+/v4CAgEBA
QAAAACH/C05FVFNDQVBFMi4wAwEAAAAh/h1HaWZCdWlsZGVyIDAuMiBieSBZdmVzIFBpZ3VldAAh
+QQECgD/ACwAAAAAKAAoAEMEx5DJSSt9z+rNcfgf5oEBxlVjWIreQ77wqqWrW8e4fKJ2ru9ACS2U
CW6GIBaSOOu9lMknK2dqrog2pYhp7Dir3fAIHN4tk8XyBKmFkU9j0tQnT6+d2K2qrnen2W10MW93
WIZogGJ4dIRqZ41qTZCRXpOUPHWXXjiWioKdZniBaI6LNX2ZQS1aLnOcdhYpPaOfsAxDrXOiqKlL
rL+0mb5Qg7ypQru5Z1S2yIiHaK9Aq1lfxFxGLYe/P2XLUprOzOGY4ORW3edNkREAIfkEBAoA/wAs
AAAAACgAKABDBMqQyUkrfc/qzXH4YBhiXOWNAaZ6q+iS1vmps1y3Y1aaj/vqu6DEVhN2einfipgC
XpA/HNRHbW5YSFpzmXUaY1PYd3wSj3fM3JlXrZpLsrIc9wNHW71pGyRmcpM0dHUaczc5WnxeaHp7
b2sMaVaPQSuTZCqWQjaOmUOMRZ2ee5KTkVSci22CoJRQiDeviXBhh1yfrBNEWH+jspC3S3y9dWnB
sb1muru1x6RshlvMeqhP0U3Sal8s0LZ5ikamItTat7ihft+hv+bqYI8RADs=
"""


class TestDataURLImageField(CollectionDataMixin, amo.tests.TestCase):

    def test_from_native(self):
        d = DataURLImageField().from_native('data:image/gif;base64,' + IMAGE_DATA)
        eq_(d.read(), IMAGE_DATA.decode('base64'))
