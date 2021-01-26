from django.conf import settings
from django.utils.html import format_html
from django.utils.translation import gettext

from rest_framework import serializers

from olympia.addons.models import Addon
from olympia.addons.serializers import AddonSerializer, VersionSerializer
from olympia.api.fields import (
    GetTextTranslationSerializerField,
    TranslationSerializerField,
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
            'files',
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


class FieldAlwaysFlatWhenFlatGateActiveMixin:
    """Terribly named mixin to wrap around TranslationSerializerField (and subclasses)
    to always return a single flat string when 'l10n_flat_input_output' is enabled to
    replicate the v4 and earlier behavior in the discovery API."""

    def get_requested_language(self):
        # For l10n_flat_input_output, if the request didn't specify a `lang=xx` then
        # fake it as `lang=en-US` so we get a single (flat) result.
        requested = super().get_requested_language()
        if not requested:
            request = self.context.get('request', None)
            if is_gate_active(request, 'l10n_flat_input_output'):
                requested = settings.LANGUAGE_CODE
        return requested

    def get_attribute(self, obj):
        # For l10n_flat_input_output, make sure to always return a string as before.
        attribute = super().get_attribute(obj)
        if attribute is None:
            request = self.context.get('request', None)
            if is_gate_active(request, 'l10n_flat_input_output'):
                attribute = ''
        return attribute


class GetTextTranslationSerializerFieldFlat(
    FieldAlwaysFlatWhenFlatGateActiveMixin, GetTextTranslationSerializerField
):
    pass


class TranslationSerializerFieldFlat(
    FieldAlwaysFlatWhenFlatGateActiveMixin, TranslationSerializerField
):
    pass


class DiscoverySerializer(serializers.ModelSerializer):
    heading = serializers.SerializerMethodField()
    description = serializers.SerializerMethodField()
    description_text = GetTextTranslationSerializerFieldFlat(
        source='custom_description'
    )
    addon = DiscoveryAddonSerializer()
    addon_summary = TranslationSerializerFieldFlat(source='addon.summary')
    is_recommendation = serializers.SerializerMethodField()

    class Meta:
        fields = (
            'heading',
            'description',
            'description_text',
            'addon',
            'is_recommendation',
            'addon_summary',  # this isn't included in the response
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
            gettext(obj.custom_description)
            or (obj.should_fallback_to_addon_summary and obj.addon.summary)
            or ''
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

        # if there wasn't a custom description, swap it out for the addon summary
        addon_summary = data.pop('addon_summary', None)
        if (
            not data.get('description_text')
            and instance.should_fallback_to_addon_summary
            and addon_summary
        ):
            data['description_text'] = addon_summary

        return data
