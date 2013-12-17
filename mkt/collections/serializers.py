# -*- coding: utf-8 -*-
import os
import uuid

import waffle
from rest_framework import serializers
from rest_framework.fields import get_component
from rest_framework.reverse import reverse
from tower import ugettext_lazy as _

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.files.base import File
from django.core.files.storage import default_storage as storage

import amo
try:
    from build import BUILD_ID_IMG
    build_id = BUILD_ID_IMG
except ImportError:
    build_id = ''
import mkt
from addons.models import Category
from mkt.api.fields import (SlugChoiceField, SlugModelChoiceField,
                            TranslationSerializerField)
from mkt.features.utils import get_feature_profile
from mkt.webapps.api import AppSerializer
from mkt.webapps.models import Webapp
from users.models import UserProfile

from .models import Collection
from .constants import COLLECTIONS_TYPE_FEATURED, COLLECTIONS_TYPE_OPERATOR


class CollectionMembershipField(serializers.RelatedField):
    """
    RelatedField subclass that serializes apps in a Collection, taking into
    account feature profile and optionally relying on ElasticSearch to find
    the apps instead of making a DB query.

    Specifically created for use with CollectionSerializer; you probably don't
    want to use this elsewhere.
    """
    def to_native(self, value):
        return AppSerializer(value, context=self.context).data

    def to_native_es(self, value):
        return self.context['view'].serialize(self.context['request'], value)

    def field_to_native(self, obj, field_name):
        if not hasattr(self, 'context') or not 'request' in self.context:
            raise ImproperlyConfigured('Pass request in self.context when'
                                       ' using CollectionMembershipField.')

        request = self.context['request']

        # Having 'use-es-for-apps' in the context means the parent view wants us
        # to use ES to fetch the apps. If that key is present, check that we
        # have a view in the context and that the waffle flag is active. If
        # everything checks out, bypass the db and use ES to fetch apps for a
        # nice performance boost.
        if (self.context.get('use-es-for-apps') and self.context.get('view')
            and waffle.switch_is_active('collections-use-es-for-apps')):
            return self.field_to_native_es(obj, request)

        qs = get_component(obj, self.source)

        # Filter apps based on feature profiles.
        profile = get_feature_profile(request)
        if profile:
            qs = qs.filter(**profile.to_kwargs(
                prefix='_current_version__features__has_'))

        return [self.to_native(app) for app in qs]

    def field_to_native_es(self, obj, request):
        """
        A version of field_to_native that uses ElasticSearch to fetch the apps
        belonging to the collection instead of SQL.

        Relies on a FeaturedSearchView instance in self.context['view']
        to properly rehydrate results returned by ES.
        """
        profile = get_feature_profile(request)
        region = self.context['view'].get_region(request)

        qs = Webapp.from_search(request, region=region)
        filters = {'collection.id': obj.pk}
        if profile:
            filters.update(**profile.to_kwargs(prefix='features.has_'))
        qs = qs.filter(**filters).order_by('collection.order')

        return [self.to_native_es(app) for app in qs]


class HyperlinkedRelatedOrNullField(serializers.HyperlinkedRelatedField):
    read_only = True

    def __init__(self, *a, **kw):
        self.pred = kw.get('predicate', lambda x: True)
        if 'predicate' in kw:
            del kw['predicate']
        serializers.HyperlinkedRelatedField.__init__(self, *a, **kw)

    def get_url(self, obj, view_name, request, format):
        kwargs = {'pk': obj.pk}
        if self.pred(obj):
            url = reverse(view_name, kwargs=kwargs, request=request,
                          format=format)
            if build_id:
                url += '?' + build_id
            return url
        else:
            return None


class CollectionSerializer(serializers.ModelSerializer):
    name = TranslationSerializerField()
    description = TranslationSerializerField()
    slug = serializers.CharField(required=False)
    collection_type = serializers.IntegerField()
    apps = CollectionMembershipField(many=True, source='apps')
    image = HyperlinkedRelatedOrNullField(
        source='*',
        view_name='collection-image-detail',
        format='png',
        predicate=lambda o: o.has_image)
    carrier = SlugChoiceField(required=False, empty=None,
        choices_dict=mkt.carriers.CARRIER_MAP)
    region = SlugChoiceField(required=False, empty=None,
        choices_dict=mkt.regions.REGIONS_DICT)
    category = SlugModelChoiceField(required=False,
        queryset=Category.objects.filter(type=amo.ADDON_WEBAPP))

    class Meta:
        fields = ('apps', 'author', 'background_color', 'can_be_hero',
                  'carrier', 'category', 'collection_type', 'default_language',
                  'description', 'id', 'image', 'is_public', 'name', 'region',
                  'slug', 'text_color',)
        model = Collection

    def to_native(self, obj):
        """
        Remove `can_be_hero` from the serialization if this is not an operator
        shelf.
        """
        native = super(CollectionSerializer, self).to_native(obj)
        if native['collection_type'] != COLLECTIONS_TYPE_OPERATOR:
            del native['can_be_hero']
        return native

    def validate(self, attrs):
        """
        Prevent operator shelves from being associated with a category.
        """
        existing = getattr(self, 'object')
        exc = 'Operator shelves may not be associated with a category.'

        if (not existing and attrs['collection_type'] ==
            COLLECTIONS_TYPE_OPERATOR and attrs.get('category')):
            raise serializers.ValidationError(exc)

        elif existing:
            collection_type = attrs.get('collection_type',
                                        existing.collection_type)
            category = attrs.get('category', existing.category)
            if collection_type == COLLECTIONS_TYPE_OPERATOR and category:
                raise serializers.ValidationError(exc)

        return attrs

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
        qs = Collection.objects.filter(
            collection_type=instance.collection_type,
            category=instance.category,
            region=instance.region,
            carrier=instance.carrier)
        if instance.pk:
            qs = qs.exclude(pk=instance.pk)
        if (instance.collection_type in unique_collections_types and
            qs.exists()):
            self._errors['collection_uniqueness'] = _(
                u'You can not have more than one Featured Apps/Operator Shelf '
                u'collection for the same category/carrier/region combination.'
            )
        return instance


class CuratorSerializer(serializers.ModelSerializer):
    class Meta:
        fields = ('display_name', 'email', 'id')
        model = UserProfile


class DataURLImageField(serializers.CharField):
    def from_native(self, data):
        if not data.startswith('data:'):
            raise serializers.ValidationError('Not a data URI.')
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
            raise serializers.ValidationError('Not a base64 data URI.')

    def to_native(self, value):
        return value.name
