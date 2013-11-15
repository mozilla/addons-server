# -*- coding: utf-8 -*-

from rest_framework import serializers

import amo
import amo.tests
from mkt.collections.constants import COLLECTIONS_TYPE_BASIC
from mkt.collections.models import Collection
from mkt.feed.serializers import FeedItemSerializer


class CollectionFeedMixin(object):
    collection_data = {
        'collection_type': COLLECTIONS_TYPE_BASIC,
        'name': {'en-US': u'A collection of my favourite gàmes'},
        'slug': 'my-favourite-games',
        'description': {'en-US': u'A collection of my favourite gamés'},
    }

    def setUp(self):
        self.collection = Collection.objects.create(**self.collection_data)
        super(CollectionFeedMixin, self).setUp()


class TestFeedItemSerializer(CollectionFeedMixin, amo.tests.TestCase):

    def serializer(self, item=None, **context):
        if not item:
            return FeedItemSerializer(context=context)
        return FeedItemSerializer(item, context=context)

    def validate(self, **attrs):
        return self.serializer().validate(attrs=attrs)

    def test_validate_passes(self):
        self.validate(collection=self.collection)

    def test_validate_fails_no_items(self):
        with self.assertRaises(serializers.ValidationError):
            self.validate(collection=None)
