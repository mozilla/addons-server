from django.utils.html import format_html
from django.utils.translation import gettext

from rest_framework import serializers

from olympia.addons.models import Addon
from olympia.addons.serializers import AddonSerializer, VersionSerializer
from olympia.api.fields import (
    FallbackField,
    GetTextTranslationSerializerFieldFlat,
    TranslationSerializerFieldFlat,
)
from olympia.api.utils import is_gate_active
from olympia.discovery.models import DiscoveryItem
from olympia.versions.models import Version


class DiscoveryEditorialContentSerializer(serializers.ModelSerializer):
    """
    Serializer used to fetch editorial-content only, for internal use when
    generating the .po files containing all editorial content to be translated
    or for internal consumption by the TAAR team.
    """

    addon = serializers.SerializerMethodField()

    class Meta:
        model = DiscoveryItem
        # We only need fields that require a translation, that's
        # custom_description, plus a guid to identify the add-on.
        fields = ('addon', 'custom_description')

    def get_addon(self, obj):
        return {
            # Note: we select_related() the addon, so we don't have extra
            # queries. But that also means the Addon transformers don't run!
            # It's fine (and better for perf) as long as we don't need more
            # complex fields.
            'guid': obj.addon.guid,
        }


class DiscoveryVersionSerializer(VersionSerializer):
    class Meta:
        fields = (
            'id',
            'compatibility',
            'is_strict_compatibility_enabled',
            'file',
        )
        model = Version


class DiscoveryAddonSerializer(AddonSerializer):
    current_version = DiscoveryVersionSerializer()

    class Meta:
        fields = (
            'id',
            'authors',
            'average_daily_users',
            'current_version',
            'guid',
            'icon_url',
            'name',
            'previews',
            'ratings',
            'slug',
            'type',
            'url',
        )
        model = Addon


class DiscoverySerializer(serializers.ModelSerializer):
    heading = serializers.SerializerMethodField()
    description = serializers.SerializerMethodField()
    description_text = FallbackField(
        GetTextTranslationSerializerFieldFlat(source='custom_description'),
        TranslationSerializerFieldFlat(source='addon_summary_fallback'),
    )
    addon = DiscoveryAddonSerializer()
    is_recommendation = serializers.SerializerMethodField()

    class Meta:
        fields = (
            'heading',
            'description',
            'description_text',
            'addon',
            'is_recommendation',
        )
        model = DiscoveryItem

    def get_is_recommendation(self, obj):
        # If an object is ever returned without having a position set, that
        # means it's coming from the recommendation server, it wasn't an
        # editorial choice.
        view = self.context.get('view')
        if view and view.get_edition() == 'china':
            position_field = 'position_china'
        else:
            position_field = 'position'
        position_value = getattr(obj, position_field)
        return position_value is None or position_value < 1

    def get_heading(self, obj):
        return format_html(
            '{0} <span>{1} <a href="{2}">{3}</a></span>',
            obj.addon.name,
            gettext('by'),
            obj.addon.get_absolute_url(),
            ', '.join(author.name for author in obj.addon.listed_authors),
        )

    def get_description(self, obj):
        description = (
            gettext(obj.custom_description) or obj.addon_summary_fallback or ''
        )
        return format_html('<blockquote>{}</blockquote>', description)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get('request', None)
        if request and not is_gate_active(
            request, 'disco-heading-and-description-shim'
        ):
            data.pop('heading', None)
            data.pop('description', None)

        return data
