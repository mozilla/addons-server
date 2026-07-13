from django.core.exceptions import ValidationError as DjangoValidationError
from django.urls import reverse

import jsonschema
from rest_framework import serializers

from olympia.addons.models import Addon
from olympia.addons.serializers import (
    AddonSerializer,
    VersionSerializer,
)
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.constants.scanners import NEW
from olympia.versions.models import Version

from .models import ScannerQueryResult, ScannerQueryRule


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


class ScannerResultsValidationMixin:
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
        # Validate that no extra fields are present in the initial data.
        if hasattr(self, 'initial_data'):
            extra_fields = set(self.initial_data.keys()) - set(self.fields.keys())
            if extra_fields:
                raise serializers.ValidationError(
                    {field: 'Unexpected field.' for field in extra_fields}
                )

        return data


class PushScannerResultSerializer(
    ScannerResultsValidationMixin, serializers.Serializer
):
    version_id = serializers.IntegerField()
    results = serializers.JSONField()

    def validate_version_id(self, value):
        try:
            Version.unfiltered.get(pk=value)
        except Version.DoesNotExist as err:
            raise serializers.ValidationError('Version not found.') from err

        return value


class PatchScannerResultSerializer(
    ScannerResultsValidationMixin, serializers.Serializer
):
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


class ScannerQueryRuleSerializer(serializers.ModelSerializer):
    """Serializer to create, read and iterate on ScannerQueryRules.

    The rule can only be modified while it is still in the ``NEW`` state (the
    same invariant the admin enforces): once it has been scheduled or run, its
    definition is frozen and a new rule should be created to iterate."""

    state_display = serializers.CharField(source='get_state_display', read_only=True)
    scanner_display = serializers.CharField(
        source='get_scanner_display', read_only=True
    )
    completion_rate = serializers.SerializerMethodField()
    results_count = serializers.SerializerMethodField()

    class Meta:
        model = ScannerQueryRule
        fields = (
            'id',
            'name',
            'pretty_name',
            'description',
            'scanner',
            'scanner_display',
            'definition',
            'configuration',
            'run_on_disabled_addons',
            'run_on_current_version_only',
            'run_on_specific_channel',
            'exclude_promoted_addons',
            'state',
            'state_display',
            'task_count',
            'completed',
            'completion_rate',
            'results_count',
            'created',
            'modified',
        )
        read_only_fields = (
            'id',
            'scanner_display',
            'state',
            'state_display',
            'task_count',
            'completed',
            'completion_rate',
            'results_count',
            'created',
            'modified',
        )

    def get_completion_rate(self, obj):
        return obj.completion_rate()

    def get_results_count(self, obj):
        return obj.results.count()

    def validate(self, data):
        # Build/patch the instance and call the model's clean(), which compiles
        # the YARA/NARC definition and checks the name matches. We deliberately
        # call clean() and not full_clean(): field-level constraints are already
        # enforced by the serializer fields, and the (name, scanner) uniqueness
        # is handled by the UniqueTogetherValidator DRF adds automatically.
        if self.instance is None:
            instance = ScannerQueryRule(**data)
        else:
            if self.instance.state != NEW:
                raise serializers.ValidationError(
                    'A scanner query rule can only be modified while it is in '
                    'the "New" state. Create a new rule to iterate on it.'
                )
            instance = self.instance
            for attr, value in data.items():
                setattr(instance, attr, value)

        try:
            instance.clean()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(
                exc.message_dict if hasattr(exc, 'error_dict') else exc.messages
            ) from exc

        return data


class ScannerQueryResultSerializer(serializers.ModelSerializer):
    """Read-only serializer exposing the matches of a ScannerQueryRule.

    ``matches`` is the structured, per-file view of the hits produced by
    ``get_files_and_data_by_matched_rules()`` (the same representation the
    admin surfaces), which is the convenient shape for iterating on a rule."""

    scanner_display = serializers.CharField(
        source='get_scanner_display', read_only=True
    )
    addon_id = serializers.IntegerField(
        source='version.addon_id', read_only=True, allow_null=True
    )
    addon_guid = serializers.CharField(
        source='version.addon.guid', read_only=True, allow_null=True
    )
    version_string = serializers.CharField(
        source='version.version', read_only=True, allow_null=True
    )
    channel = serializers.CharField(
        source='version.get_channel_display', read_only=True, allow_null=True
    )
    matches = serializers.SerializerMethodField()

    class Meta:
        model = ScannerQueryResult
        fields = (
            'id',
            'scanner',
            'scanner_display',
            'matched_rule',
            'was_blocked',
            'was_promoted',
            'addon_id',
            'addon_guid',
            'version_id',
            'version_string',
            'channel',
            'matches',
            'created',
        )

    def get_matches(self, obj):
        return dict(obj.get_files_and_data_by_matched_rules())
