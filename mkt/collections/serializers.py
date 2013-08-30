# -*- coding: utf-8 -*-
import os
import uuid

from rest_framework import serializers
from tastypie.bundle import Bundle
from tower import ugettext_lazy as _

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import File
from django.core.files.storage import default_storage as storage

from mkt.api.fields import TranslationSerializerField
from mkt.api.resources import AppResource

from .models import Collection
from .constants import COLLECTIONS_TYPE_FEATURED, COLLECTIONS_TYPE_OPERATOR


class CollectionMembershipField(serializers.RelatedField):
    def to_native(self, value):
        bundle = Bundle(obj=value.app)
        return AppResource().full_dehydrate(bundle).data


class CollectionSerializer(serializers.ModelSerializer):
    name = TranslationSerializerField()
    description = TranslationSerializerField()
    slug = serializers.CharField(required=False)
    collection_type = serializers.IntegerField()
    apps = CollectionMembershipField(many=True,
                                     source='collectionmembership_set')

    class Meta:
        fields = ('apps', 'author', 'background_color', 'carrier', 'category',
                  'collection_type', 'default_language', 'description', 'id',
                  'is_public', 'name', 'region', 'slug', 'text_color',)
        model = Collection

    def full_clean(self, instance):
        instance = super(CollectionSerializer, self).full_clean(instance)
        if not instance:
            return None
        # For featured apps and operator shelf collections, we need to check if
        # one already exists for the same region/category/carrier combination.
        #
        # Sadly, this can't be expressed as a db-level unique constaint,
        # because this doesn't apply to basic collections.
        #
        # We have to do it  ourselves, and we need the rest of the validation
        # to have already taken place, and have the incoming data and original
        # data from existing instance if it's an edit, so full_clean() is the
        # best place to do it.
        unique_collections_types = (COLLECTIONS_TYPE_FEATURED,
                                    COLLECTIONS_TYPE_OPERATOR)
        if (instance.collection_type in unique_collections_types and
            Collection.objects.filter(collection_type=instance.collection_type,
                                      category=instance.category,
                                      region=instance.region,
                                      carrier=instance.carrier).exists()):
            self._errors['collection_uniqueness'] = _(
                u'You can not have more than one Featured Apps/Operator Shelf '
                u'collection for the same category/carrier/region combination.'
            )
        return instance


class DataURLImageField(serializers.CharField):
    def from_native(self, data):
        if not data.startswith('data:'):
            raise ValidationError('Not a data URI.')
        metadata, encoded = data.rsplit(',', 1)
        parts = metadata.rsplit(';', 1)
        if parts[-1] == 'base64':
            content = encoded.decode('base64')
            tmp_dst = os.path.join(settings.TMP_PATH, 'icon', uuid.uuid4().hex)
            with storage.open(tmp_dst, 'wb') as f:
                f.write(content)
            tmp = File(storage.open(tmp_dst))
            return serializers.ImageField().from_native(tmp)
        else:
            raise ValidationError('Not a base64 data URI.')

    def to_native(self, value):
        return value.name
