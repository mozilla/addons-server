from django.utils.translation import gettext, gettext_lazy as _

from rest_framework import serializers
from rest_framework.validators import UniqueTogetherValidator

from olympia.accounts.serializers import BaseUserSerializer
from olympia.addons.models import Addon
from olympia.addons.serializers import AddonSerializer
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.utils import clean_nl, has_links, slug_validator
from olympia.api.fields import (
    SlugOrPrimaryKeyRelatedField,
    SplitField,
    TranslationSerializerField,
)
from olympia.api.utils import is_gate_active
from olympia.bandwagon.models import Collection, CollectionAddon
from olympia.users.models import DeniedName


class CollectionSerializer(serializers.ModelSerializer):
    name = TranslationSerializerField()
    description = TranslationSerializerField(allow_blank=True, required=False)
    url = serializers.SerializerMethodField()
    author = BaseUserSerializer(default=serializers.CurrentUserDefault())
    public = serializers.BooleanField(source='listed', default=True)
    uuid = serializers.UUIDField(format='hex', required=False)

    class Meta:
        model = Collection
        fields = (
            'id',
            'uuid',
            'url',
            'addon_count',
            'author',
            'description',
            'modified',
            'name',
            'slug',
            'public',
            'default_locale',
        )
        writeable_fields = ('description', 'name', 'slug', 'public', 'default_locale')
        read_only_fields = tuple(set(fields) - set(writeable_fields))
        validators = [
            UniqueTogetherValidator(
                queryset=Collection.objects.all(),
                message=_(
                    'This custom URL is already in use by another one '
                    'of your collections.'
                ),
                fields=('slug', 'author'),
            ),
        ]

    def get_url(self, obj):
        return absolutify(obj.get_url_path())

    def validate_name(self, value):
        # if we have a localised dict of values validate them all.
        if isinstance(value, dict):
            return {
                locale: self.validate_name(sub_value)
                for locale, sub_value in value.items()
            }
        if DeniedName.blocked(value):
            raise serializers.ValidationError(gettext('This name cannot be used.'))
        return value

    def validate_description(self, value):
        if has_links(clean_nl(str(value))):
            # There's some links, we don't want them.
            raise serializers.ValidationError(gettext('No links are allowed.'))
        return value

    def validate_slug(self, value):
        slug_validator(
            value,
            message=gettext(
                'The custom URL must consist of letters, '
                'numbers, underscores or hyphens.'
            ),
        )
        if DeniedName.blocked(value):
            raise serializers.ValidationError(
                gettext('This custom URL cannot be used.')
            )

        return value


class ThisCollectionDefault:
    requires_context = True

    def __call__(self, serializer_field):
        viewset = serializer_field.context['view']
        self.collection = viewset.get_collection()
        return self.collection


class CollectionAddonSerializer(serializers.ModelSerializer):
    addon = SplitField(
        # Only used for writes (this is input field), so there are no perf
        # concerns and we don't use any special caching.
        SlugOrPrimaryKeyRelatedField(queryset=Addon.objects.public()),
        AddonSerializer(),
    )
    notes = TranslationSerializerField(source='comments', required=False)
    collection = serializers.HiddenField(default=ThisCollectionDefault())

    class Meta:
        model = CollectionAddon
        fields = ('addon', 'notes', 'collection')
        validators = [
            UniqueTogetherValidator(
                queryset=CollectionAddon.objects.all(),
                message=_('This add-on already belongs to the collection'),
                fields=('addon', 'collection'),
            ),
        ]
        writeable_fields = ('notes',)
        read_only_fields = tuple(set(fields) - set(writeable_fields))

    def validate(self, data):
        if self.partial:
            # addon is read_only but SplitField messes with the initialization.
            # DRF normally ignores updates to read_only fields, so do the same.
            data.pop('addon', None)
        return super().validate(data)

    def to_representation(self, instance):
        request = self.context.get('request')
        out = super().to_representation(instance)
        if request and is_gate_active(request, 'collections-downloads-shim'):
            out['downloads'] = 0
        return out


class CollectionWithAddonsSerializer(CollectionSerializer):
    addons = serializers.SerializerMethodField()

    class Meta(CollectionSerializer.Meta):
        fields = CollectionSerializer.Meta.fields + ('addons',)
        read_only_fields = tuple(
            set(fields) - set(CollectionSerializer.Meta.writeable_fields)
        )

    def get_addons(self, obj):
        addons_qs = self.context['view'].get_addons_queryset()
        return CollectionAddonSerializer(
            addons_qs, context=self.context, many=True
        ).data
