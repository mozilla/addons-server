from django import forms
from django.utils.translation import gettext, gettext_lazy as _

from rest_framework import serializers
from rest_framework.validators import UniqueTogetherValidator

from olympia import amo
from olympia.access.acl import action_allowed_for
from olympia.accounts.serializers import BaseUserSerializer
from olympia.addons.models import Addon
from olympia.addons.serializers import AddonSerializer
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.utils import clean_nl, has_urls, slug_validator, validate_name
from olympia.api.fields import (
    SlugOrPrimaryKeyRelatedField,
    SplitField,
    TranslationSerializerField,
)
from olympia.api.serializers import AMOModelSerializer
from olympia.api.utils import is_gate_active
from olympia.bandwagon.models import Collection, CollectionAddon
from olympia.users.models import DeniedName


def can_use_denied_names(request):
    return (
        request
        and request.user
        and action_allowed_for(request.user, amo.permissions.COLLECTIONS_EDIT)
    )


class CollectionSerializer(AMOModelSerializer):
    name = TranslationSerializerField()
    description = TranslationSerializerField(allow_blank=True, required=False)
    url = serializers.SerializerMethodField()
    # DRF's default=serializers.CurrentUserDefault() is necessary to pass
    # validation but we also need the custom create() below for the author to
    # be added to the created instance.
    author = BaseUserSerializer(
        read_only=True, default=serializers.CurrentUserDefault()
    )
    public = serializers.BooleanField(source='listed', default=True)
    uuid = serializers.UUIDField(format='hex', required=False, read_only=True)

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
        writeable_fields = (
            'description',
            'name',
            'slug',
            'public',
            'default_locale',
        )
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
        error_msg = gettext('This name cannot be used.')

        def check_function(normalized_name, variant):
            if not can_use_denied_names(
                self.context.get('request')
            ) and DeniedName.blocked(variant):
                raise serializers.ValidationError(error_msg)

        try:
            return validate_name(value, check_function, error_msg)
        except forms.ValidationError as exc:
            raise serializers.ValidationError(exc.messages)

    def validate_description(self, value):
        if has_urls(clean_nl(str(value))):
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
        error_msg = gettext('This custom URL cannot be used.')

        def check_function(normalized_name, variant):
            if not can_use_denied_names(
                self.context.get('request')
            ) and DeniedName.blocked(variant):
                raise serializers.ValidationError(error_msg)

        try:
            return validate_name(value, check_function, error_msg)
        except forms.ValidationError as exc:
            raise serializers.ValidationError(exc.messages)

    def create(self, validated_data):
        validated_data['author'] = self.context['request'].user
        return super().create(validated_data)


class ThisCollectionDefault:
    requires_context = True

    def __call__(self, serializer_field):
        viewset = serializer_field.context['view']
        return viewset.get_collection()


class CollectionAddonSerializer(AMOModelSerializer):
    addon = SplitField(
        # Only used for writes (this is input field), so there are no perf
        # concerns and we don't use any special caching.
        SlugOrPrimaryKeyRelatedField(queryset=Addon.objects.public()),
        AddonSerializer(),
    )
    notes = TranslationSerializerField(
        source='comments', required=False, allow_blank=True
    )
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
        writeable_fields = (
            # addon is technically writeable but we ignore updates in
            # validate() below.
            'addon',
            # collection is technically writeable but we should be ignoring any
            # incoming data to always use the collection from the viewset,
            # through HiddenField(default=ThisCollectionDefault()).
            'collection',
            'notes',
        )
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
