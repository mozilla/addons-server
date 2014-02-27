# -*- coding: utf-8 -*-
from mock import patch
from nose.tools import eq_, ok_
from rest_framework import serializers
from test_utils import RequestFactory

import amo
import amo.tests
from addons.models import AddonUser, Category
from users.models import UserProfile

import mkt
from mkt.collections.constants import (COLLECTIONS_TYPE_BASIC,
                                       COLLECTIONS_TYPE_OPERATOR)
from mkt.collections.models import Collection, CollectionMembership
from mkt.collections.serializers import (CollectionMembershipField,
                                         CollectionSerializer,
                                         DataURLImageField)
from mkt.constants.features import FeatureProfile
from mkt.search.api import FeaturedSearchView
from mkt.site.fixtures import fixture
from mkt.webapps.api import SimpleAppSerializer


class CollectionDataMixin(object):
    collection_data = {
        'collection_type': COLLECTIONS_TYPE_BASIC,
        'name': {'en-US': u'A collection of my favourite gàmes'},
        'slug': 'my-favourite-games',
        'description': {'en-US': u'A collection of my favourite gamés'},
    }


class BaseTestCollectionMembershipField(object):

    def setUp(self):
        self.collection = Collection.objects.create(**self.collection_data)
        self.app = amo.tests.app_factory()
        self.app.addondevicetype_set.get_or_create(
            device_type=amo.DEVICE_GAIA.id)
        self.collection.add_app(self.app, order=1)
        self.field = CollectionMembershipField()
        self.field.context = {}
        self.membership = CollectionMembership.objects.all()[0]
        self.profile = FeatureProfile(apps=True).to_signature()

    def get_request(self, data=None):
        if data is None:
            data = {}
        request = RequestFactory().get('/', data)
        request.REGION = mkt.regions.RESTOFWORLD
        request.API = True
        return request

    def test_to_native(self):
        self.app2 = amo.tests.app_factory()
        self.collection.add_app(self.app2)
        apps = [self.app, self.app2]
        request = self.get_request({})
        resource = SimpleAppSerializer(apps)
        resource.context = {'request': request}
        self.field.context['request'] = request
        data = self.field.to_native(self.collection.apps())
        eq_(len(data), 2)
        eq_(data[0]['id'], int(self.app.pk))
        eq_(data[0]['resource_uri'], self.app.get_api_url(pk=self.app.pk))
        eq_(data[1]['id'], int(self.app2.id))
        eq_(data[1]['resource_uri'], self.app2.get_api_url(pk=self.app2.pk))

    def _field_to_native_profile(self, profile='0.0', dev='firefoxos'):
        request = self.get_request({'pro': profile, 'dev': dev})
        self.field.parent = self.collection
        self.field.source = 'apps'
        self.field.context['request'] = request

        return self.field.field_to_native(self.collection, 'apps')

    def test_ordering(self):
        self.app2 = amo.tests.app_factory()
        self.app2.addondevicetype_set.get_or_create(
            device_type=amo.DEVICE_GAIA.id)
        self.collection.add_app(self.app2, order=0)
        self.app3 = amo.tests.app_factory()
        self.app3.addondevicetype_set.get_or_create(
            device_type=amo.DEVICE_GAIA.id)
        self.collection.add_app(self.app3)
        result = self._field_to_native_profile()
        eq_(len(result), 3)
        eq_(int(result[0]['id']), self.app2.id)
        eq_(int(result[1]['id']), self.app.id)
        eq_(int(result[2]['id']), self.app3.id)

    def test_app_delete(self):
        self.app.delete()
        result = self._field_to_native_profile()
        eq_(len(result), 0)

    def test_app_disable(self):
        self.app.update(disabled_by_user=True)
        result = self._field_to_native_profile()
        eq_(len(result), 0)

    def test_app_pending(self):
        self.app.update(status=amo.STATUS_PENDING)
        result = self._field_to_native_profile()
        eq_(len(result), 0)

    def test_field_to_native_profile(self):
        result = self._field_to_native_profile(self.profile)
        eq_(len(result), 1)
        eq_(int(result[0]['id']), self.app.id)

    def test_field_to_native_profile_mismatch(self):
        self.app.current_version.features.update(has_geolocation=True)
        result = self._field_to_native_profile(self.profile)
        eq_(len(result), 0)

    def test_field_to_native_invalid_profile(self):
        result = self._field_to_native_profile('muahahah')
        # Ensure that no filtering took place.
        eq_(len(result), 1)
        eq_(int(result[0]['id']), self.app.id)

    def test_field_to_native_device_filter(self):
        result = self._field_to_native_profile('muahahah', 'android-mobile')
        eq_(len(result), 0)


class TestCollectionMembershipField(BaseTestCollectionMembershipField,
                                    CollectionDataMixin, amo.tests.TestCase):
    pass


class TestCollectionMembershipFieldES(BaseTestCollectionMembershipField,
                                      CollectionDataMixin,
                                      amo.tests.ESTestCase):
    """
    Same tests as TestCollectionMembershipField above, but we need a
    different setUp and more importantly, we need to force a sync refresh
    in ES when we modify our app.
    """

    fixtures = fixture('user_2519')

    def setUp(self):
        super(TestCollectionMembershipFieldES, self).setUp()
        self.field.context['view'] = FeaturedSearchView()
        self.user = UserProfile.objects.get(pk=2519)
        AddonUser.objects.create(addon=self.app, user=self.user)
        self.refresh('webapp')

    def _field_to_native_profile(self, profile='0.0', dev='firefoxos'):
        """
        Like _field_to_native_profile in BaseTestCollectionMembershipField,
        but calling field_to_native_es directly.
        """
        request = self.get_request({'pro': profile, 'dev': dev})
        self.field.context['request'] = request
        return self.field.field_to_native_es(self.collection, request)

    def test_field_to_native_profile_mismatch(self):
        self.app.current_version.features.update(has_geolocation=True)
        # FIXME: a simple refresh() wasn't enough, don't we reindex apps when
        # feature profiles change ? Investigate.
        self.reindex(self.app.__class__, 'webapp')
        result = self._field_to_native_profile(self.profile)
        eq_(len(result), 0)

    def test_ordering(self):
        self.app2 = amo.tests.app_factory()
        self.collection.add_app(self.app2, order=0)
        self.app3 = amo.tests.app_factory()
        self.collection.add_app(self.app3)

        # Extra app not belonging to a collection.
        amo.tests.app_factory()

        # Extra collection that has the apps in different positions.
        extra_collection = Collection.objects.create(**self.collection_data)
        extra_collection.add_app(self.app3)
        extra_collection.add_app(self.app2)
        extra_collection.add_app(self.app)

        # Force refresh in ES.
        self.refresh('webapp')

        request = self.get_request()
        self.field.context['request'] = request
        result = self.field.field_to_native_es(self.collection, request)

        eq_(len(result), 3)
        eq_(int(result[0]['id']), self.app2.id)
        eq_(int(result[1]['id']), self.app.id)
        eq_(int(result[2]['id']), self.app3.id)

    def test_app_delete(self):
        self.app.delete()
        self.refresh('webapp')
        result = self._field_to_native_profile()
        eq_(len(result), 0)

    def test_app_disable(self):
        self.app.update(disabled_by_user=True)
        self.refresh('webapp')
        result = self._field_to_native_profile()
        eq_(len(result), 0)

    def test_app_pending(self):
        self.app.update(status=amo.STATUS_PENDING)
        self.refresh('webapp')
        result = self._field_to_native_profile()
        eq_(len(result), 0)


class TestCollectionSerializer(CollectionDataMixin, amo.tests.TestCase):

    def setUp(self):
        minimal_context = {
            'request': RequestFactory().get('/whatever')
        }
        self.collection = Collection.objects.create(**self.collection_data)
        self.serializer = CollectionSerializer(self.collection,
                                               context=minimal_context)

    def test_to_native(self, apps=None):
        if apps:
            for app in apps:
                self.collection.add_app(app)
        else:
            apps = []

        data = self.serializer.to_native(self.collection)
        for name, value in self.collection_data.iteritems():
            eq_(self.collection_data[name], data[name])
        self.assertSetEqual(data.keys(), [
            'apps', 'author', 'background_color', 'carrier', 'category',
            'collection_type', 'default_language', 'description', 'id',
            'image', 'is_public', 'name', 'region', 'slug', 'text_color'
        ])
        for order, app in enumerate(apps):
            eq_(data['apps'][order]['slug'], app.app_slug)
        return data

    def test_to_native_operator(self):
        self.collection.update(collection_type=COLLECTIONS_TYPE_OPERATOR)
        data = self.serializer.to_native(self.collection)
        ok_('can_be_hero' in data.keys())

    @patch('mkt.collections.serializers.build_id', 'bbbbbb')
    def test_image(self):
        data = self.serializer.to_native(self.collection)
        eq_(data['image'], None)
        self.collection.update(has_image=True)
        data = self.serializer.to_native(self.collection)
        self.assertApiUrlEqual(data['image'],
            '/rocketfuel/collections/%s/image.png?bbbbbb' % self.collection.pk)

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

    def validate(self, **kwargs):
        return self.serializer.validate(kwargs)

    def test_validation_operatorshelf_category(self):
        category = Category.objects.create(name='BastaCorp', slug='basta',
                                           type=amo.ADDON_WEBAPP)
        ok_(self.validate(collection_type=COLLECTIONS_TYPE_BASIC,
                          category=category))
        ok_(self.validate(collection_type=COLLECTIONS_TYPE_OPERATOR))
        with self.assertRaises(serializers.ValidationError):
            self.validate(collection_type=COLLECTIONS_TYPE_OPERATOR,
                          category=category)


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
        d = DataURLImageField().from_native(
            'data:image/gif;base64,' + IMAGE_DATA)
        eq_(d.read(), IMAGE_DATA.decode('base64'))
