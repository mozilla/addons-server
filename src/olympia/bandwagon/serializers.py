from django.utils.translation import ugettext

from rest_framework import serializers
from rest_framework.validators import UniqueTogetherValidator

from olympia.addons.serializers import AddonSerializer
from olympia.amo.utils import clean_nl, has_links, slug_validator
from olympia.api.fields import TranslationSerializerField
from olympia.bandwagon.models import Collection, CollectionAddon
from olympia.users.models import DeniedName
from olympia.users.serializers import BaseUserSerializer


class SimpleCollectionSerializer(serializers.ModelSerializer):
    name = TranslationSerializerField()
    description = TranslationSerializerField()
    url = serializers.SerializerMethodField()
    author = BaseUserSerializer(required=False, default=None)
    public = serializers.BooleanField(source='listed')

    class Meta:
        model = Collection
        fields = ('id', 'url', 'addon_count', 'author', 'description',
                  'modified', 'name', 'slug', 'public')
        writeable_fields = (
            'description', 'name', 'slug', 'public'
        )
        read_only_fields = tuple(set(fields) - set(writeable_fields))
        validators = [
            UniqueTogetherValidator(
                queryset=Collection.objects.all(),
                message=ugettext(u'This slug is already in use by another one '
                                 u'of your collections.'),
                fields=('slug', 'author')
            )
        ]

    def get_url(self, obj):
        return obj.get_abs_url()

    def validate_name(self, value):
        # if we have a localised dict of values validate them all.
        if type(value) == dict:
            return {locale: self.validate_name(sub_value)
                    for locale, sub_value in value.iteritems()}
        if DeniedName.blocked(value):
            raise serializers.ValidationError(
                ugettext(u'This name cannot be used.'))
        return value

    def validate_description(self, value):
        if has_links(clean_nl(unicode(value))):
            # There's some links, we don't want them.
            raise serializers.ValidationError(
                ugettext(u'No links are allowed.'))
        return value

    def validate_slug(self, value):
        slug_validator(
            value, lower=False,
            message=ugettext(u'Enter a valid slug consisting of letters, '
                             u'numbers, underscores or hyphens.'))
        if DeniedName.blocked(value):
            raise serializers.ValidationError(
                ugettext(u'This slug cannot be used.'))

        return value

    def validate_author(self, value):
        if not self.partial:
            value = self.context['request'].user
        return value


class CollectionAddonSerializer(serializers.ModelSerializer):
    addon = AddonSerializer()
    notes = TranslationSerializerField(source='comments')

    class Meta:
        model = CollectionAddon
        fields = ('addon', 'downloads', 'notes')
