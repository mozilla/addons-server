# -*- coding: utf-8 -*-
import os
import uuid

from rest_framework import serializers
from rest_framework.fields import get_component
from rest_framework.compat import smart_text
from rest_framework.reverse import reverse
from tastypie.bundle import Bundle
from tower import ugettext_lazy as _

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, ValidationError
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
from mkt.api.fields import TranslationSerializerField
from mkt.api.resources import AppResource
from mkt.constants.features import FeatureProfile
from users.models import UserProfile

from .models import Collection
from .constants import COLLECTIONS_TYPE_FEATURED, COLLECTIONS_TYPE_OPERATOR


class CollectionMembershipField(serializers.RelatedField):
    """
    RelatedField subclass that serializes an M2M to CollectionMembership into
    a list of apps, rather than a list of CollectionMembership objects.

    Specifically created for use with CollectionSerializer; you probably don't
    want to use this elsewhere.
    """
    def to_native(self, value):
        bundle = Bundle(obj=value.app)
        return AppResource().full_dehydrate(bundle).data

    def field_to_native(self, obj, field_name):
        value = get_component(obj, self.source)

        # Filter apps based on feature profiles.
        if hasattr(self, 'context') and 'request' in self.context:
            sig = self.context['request'].GET.get('pro')
            if sig:
                try:
                    profile = FeatureProfile.from_signature(sig)
                except ValueError:
                    pass
                else:
                    value = value.filter(**profile.to_kwargs(
                        prefix='app___current_version__features__has_'))

        return [self.to_native(item) for item in value.all()]


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


class SlugChoiceField(serializers.ChoiceField):
    """
    Companion to SlugChoiceFilter, this field accepts an id or a slug when
    de-serializing, but always return a slug for serializing.

    Like SlugChoiceFilter, it needs to be initialized with a choices_dict
    mapping the slugs to objects with id and slug properties. This will be used
    to overwrite the choices in the underlying code.
    """
    def __init__(self, *args, **kwargs):
        # Create a choice dynamically to allow None, slugs and ids. Also store
        # choices_dict and ids_choices_dict to re-use them later in to_native()
        # and from_native().
        self.choices_dict = kwargs.pop('choices_dict')
        slugs_choices = self.choices_dict.items()
        ids_choices = [(v.id, v) for v in self.choices_dict.values()]
        self.ids_choices_dict = dict(ids_choices)
        kwargs['choices'] = slugs_choices + ids_choices
        return super(SlugChoiceField, self).__init__(*args, **kwargs)

    def to_native(self, value):
        if value:
            choice = self.ids_choices_dict.get(value, None)
            if choice is not None:
                value = choice.slug
        return super(SlugChoiceField, self).to_native(value)

    def from_native(self, value):
        if isinstance(value, basestring):
            choice = self.choices_dict.get(value, None)
            if choice is not None:
                value = choice.id
        return super(SlugChoiceField, self).from_native(value)


class SlugModelChoiceField(serializers.PrimaryKeyRelatedField):
    def field_to_native(self, obj, field_name):
        attr = self.source or field_name
        value = getattr(obj, attr)
        return getattr(value, 'slug', None)

    def from_native(self, data):
        if isinstance(data, basestring):
            try:
                data = self.queryset.only('pk').get(slug=data).pk
            except ObjectDoesNotExist:
                msg = self.error_messages['does_not_exist'] % smart_text(data)
                raise ValidationError(msg)
        return super(SlugModelChoiceField, self).from_native(data)


class CollectionSerializer(serializers.ModelSerializer):
    name = TranslationSerializerField()
    description = TranslationSerializerField()
    slug = serializers.CharField(required=False)
    collection_type = serializers.IntegerField()
    apps = CollectionMembershipField(many=True,
                                     source='collectionmembership_set')
    image = HyperlinkedRelatedOrNullField(
        source='*',
        view_name='collection-image-detail',
        predicate=lambda o: o.has_image)
    carrier = SlugChoiceField(required=False,
        choices_dict=mkt.carriers.CARRIER_MAP)
    region = SlugChoiceField(required=False,
        choices_dict=mkt.regions.REGIONS_DICT)
    category = SlugModelChoiceField(required=False,
        queryset=Category.objects.filter(type=amo.ADDON_WEBAPP))

    class Meta:
        fields = ('apps', 'author', 'background_color', 'carrier', 'category',
                  'collection_type', 'default_language', 'description', 'id',
                  'image', 'is_public', 'name', 'region', 'slug',
                  'text_color',)
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
