from django.urls import reverse

import jsonschema
from rest_framework import serializers

from olympia.addons.models import Addon
from olympia.addons.serializers import (
    AddonSerializer,
    VersionSerializer,
)
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.versions.models import Version


class WebhookAddonSerializer(AddonSerializer):
    class Meta:
        model = Addon
        excluded_fields = (
            'contributions_url',
            'current_version',
            'edit_url',
            'icon_url',
            'ratings_url',
            'review_url',
            'versions_url',
        )
        fields = tuple(set(AddonSerializer.Meta.fields) - set(excluded_fields))
        read_only_fields = fields

    def get_fields(self):
        fields = super().get_fields()
        # Make sure all fields are read-only, especially since we inherit from
        # AddonSerializer.
        for name in fields:
            fields[name].read_only = True
        return fields

    def get_url(self, obj):
        return absolutify(reverse('v5:addon-detail', kwargs={'pk': obj.id}))


class WebhookVersionSerializer(VersionSerializer):
    url = serializers.SerializerMethodField()
    download_source_url = serializers.SerializerMethodField()

    class Meta:
        model = Version
        excluded_fields = ('edit_url',)
        fields = tuple(set(VersionSerializer.Meta.fields) - set(excluded_fields)) + (
            'url',
            'download_source_url',
        )
        read_only_fields = fields

    def get_url(self, obj):
        return absolutify(
            reverse(
                'v5:addon-version-detail',
                kwargs={'addon_pk': obj.addon_id, 'pk': obj.id},
            )
        )

    def get_download_source_url(self, obj):
        if not obj.sources_provided:
            return None
        return absolutify(reverse('downloads.source', kwargs={'version_id': obj.id}))


class PushScannerResultSerializer(serializers.Serializer):
    RESULTS_SCHEMA = {
        'type': 'object',
        'required': ['version', 'matchedRules'],
        'properties': {
            'version': {'type': 'string'},
            'matchedRules': {
                'type': 'array',
                'items': {'type': 'string'},
            },
            'annotations': {
                'type': 'object',
                'additionalProperties': {
                    'type': 'array',
                    'items': {'type': 'object'},
                },
            },
        },
    }

    version_id = serializers.IntegerField()
    results = serializers.JSONField()

    def validate_version_id(self, value):
        try:
            Version.unfiltered.get(pk=value)
        except Version.DoesNotExist as err:
            raise serializers.ValidationError('Version not found.') from err

        return value

    def validate_results(self, value):
        try:
            jsonschema.validate(value, self.RESULTS_SCHEMA)
        except jsonschema.ValidationError as e:
            raise serializers.ValidationError(e.message) from e

        if 'annotations' in value:
            matched_rules = set(value['matchedRules'])
            unknown_keys = set(value['annotations'].keys()) - matched_rules
            if unknown_keys:
                raise serializers.ValidationError(
                    f'Annotation keys not in matchedRules: {sorted(unknown_keys)}'
                )

        return value

    def validate(self, data):
        if hasattr(self, 'initial_data'):
            extra_fields = set(self.initial_data.keys()) - set(self.fields.keys())
            if extra_fields:
                raise serializers.ValidationError(
                    {field: 'Unexpected field.' for field in extra_fields}
                )

        return data


class PatchScannerResultSerializer(serializers.Serializer):
    """Serializer for updating scanner result data via PATCH endpoint."""

    results = serializers.JSONField()

    def validate(self, data):
        # Validate that no extra fields are present in the initial data.
        if hasattr(self, 'initial_data'):
            extra_fields = set(self.initial_data.keys()) - set(self.fields.keys())
            if extra_fields:
                raise serializers.ValidationError(
                    {field: 'Unexpected field.' for field in extra_fields}
                )

        return data
