from rest_framework import relations, serializers

import amo
import mkt.carriers
import mkt.regions
from addons.models import Category
from mkt.api.fields import SplitField, TranslationSerializerField
from mkt.api.serializers import URLSerializerMixin
from mkt.collections.serializers import (CollectionSerializer, SlugChoiceField,
                                         SlugModelChoiceField)
from mkt.ratings.serializers import RatingSerializer
from mkt.submit.serializers import PreviewSerializer
from mkt.webapps.api import AppSerializer

from .models import FeedApp, FeedItem


class FeedAppSerializer(URLSerializerMixin, serializers.ModelSerializer):
    app = SplitField(relations.PrimaryKeyRelatedField(required=True),
                     AppSerializer())
    description = TranslationSerializerField(required=False)
    preview = SplitField(relations.PrimaryKeyRelatedField(required=False),
                         PreviewSerializer())
    rating = SplitField(relations.PrimaryKeyRelatedField(required=False),
                        RatingSerializer())

    class Meta:
        fields = ('app', 'description', 'id', 'preview', 'rating', 'url')
        model = FeedApp
        url_basename = 'feedapp'


class FeedItemSerializer(URLSerializerMixin, serializers.ModelSerializer):
    carrier = SlugChoiceField(required=False,
        choices_dict=mkt.carriers.CARRIER_MAP)
    region = SlugChoiceField(required=False,
        choices_dict=mkt.regions.REGIONS_DICT)
    category = SlugModelChoiceField(required=False,
        queryset=Category.objects.filter(type=amo.ADDON_WEBAPP))
    item_type = serializers.SerializerMethodField('get_item_type')

    # Types of objects that are allowed to be a feed item.
    collection = SplitField(relations.PrimaryKeyRelatedField(required=False),
                            CollectionSerializer())

    class Meta:
        fields = ('carrier', 'category', 'collection', 'id', 'item_type',
                  'region', 'url')
        item_types = ('collection',)
        model = FeedItem
        url_basename = 'feeditem'

    def validate(self, attrs):
        """
        Ensure that at least one object type is specified.
        """
        item_changed = any(k for k in self.Meta.item_types if k in attrs.keys())
        num_defined = sum(1 for item in self.Meta.item_types if attrs.get(item))
        if item_changed and num_defined != 1:
            message = ('A valid value for exactly one of the following '
                       'parameters must be defined: %s' % ','.join(
                        self.Meta.item_types))
            raise serializers.ValidationError(message)
        return attrs

    def get_item_type(self, obj):
        for item_type in self.Meta.item_types:
            if getattr(obj, item_type):
                return item_type
        return
