import re

from django.core.exceptions import ValidationError as DjangoValidationError
from django.urls import reverse

import jsonschema
from rest_framework import serializers

from olympia import amo
from olympia.addons.models import Addon
from olympia.addons.serializers import (
    AddonSerializer,
    VersionSerializer,
)
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.api.fields import ReverseChoiceField
from olympia.constants.scanners import (
    NEW,
    QUERY_RULE_STATES_CHOICES_API,
    SCANNER_CHOICES_API,
    YARA,
)
from olympia.versions.models import Version

from .models import ScannerQueryResult, ScannerQueryRule, rule_schema


# Same pattern the admin's change-form JS uses to infer the rule name from a
# yara definition (`rule some_rule {`).
YARA_RULE_NAME_RE = re.compile(r'rule\s+(.+?)\s+{')


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
    definition is frozen and a new rule should be created to iterate. ``name``
    and ``scanner`` are also frozen after creation, matching the admin.

    For yara rules, ``name`` is inferred from the definition (the ``rule
    <name>`` identifier) and any value provided by the client is ignored, again
    matching the admin. For narc rules, ``name`` is required."""

    scanner = ReverseChoiceField(choices=list(SCANNER_CHOICES_API.items()))
    state = ReverseChoiceField(
        choices=list(QUERY_RULE_STATES_CHOICES_API.items()), read_only=True
    )
    run_on_specific_channels = serializers.ListField(
        child=ReverseChoiceField(choices=list(amo.CHANNEL_CHOICES_API.items())),
        required=False,
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
            'definition',
            'configuration',
            'run_on_disabled_addons',
            'run_on_current_version_only',
            'run_on_specific_channels',
            'exclude_promoted_addons',
            'state',
            'task_count',
            'completed',
            'completion_rate',
            'results_count',
            'created',
            'modified',
        )
        read_only_fields = (
            'id',
            'state',
            'task_count',
            'completed',
            'completion_rate',
            'results_count',
            'created',
            'modified',
        )
        # Not required at the field level: for yara it is derived from the
        # definition, for narc it is enforced in validate().
        extra_kwargs = {'name': {'required': False}}
        # Drop the auto (name, scanner) UniqueTogetherValidator: it runs before
        # validate() and would require `name` up-front, before we get a chance
        # to derive it from the definition for yara. Uniqueness is enforced via
        # instance.validate_unique() in validate() instead.
        validators = []

    def get_fields(self):
        fields = super().get_fields()
        # `name` and `scanner` are only editable at creation time, like in the
        # admin (they are part of the rule's identity and change its schema).
        if self.instance is not None:
            fields['name'].read_only = True
            fields['scanner'].read_only = True
        return fields

    def get_completion_rate(self, obj):
        return obj.completion_rate()

    def get_results_count(self, obj):
        return obj.results.count()

    def validate_configuration_against_schema(self, instance, configuration):
        """Validate the configuration against the schema for the rule's scanner
        (only NARC has options; anything else expects an empty object)."""
        allowed = rule_schema(instance).get('keys', {})
        unknown = sorted(set(configuration) - set(allowed))
        if unknown:
            raise serializers.ValidationError(
                {'configuration': f'Unknown configuration keys: {unknown}.'}
            )
        for key, value in configuration.items():
            if allowed[key].get('type') == 'boolean' and not isinstance(value, bool):
                raise serializers.ValidationError(
                    {'configuration': f'"{key}" must be a boolean.'}
                )

    def validate_name_for_scanner(self, data):
        """On creation, derive the name from the definition for yara (ignoring
        any client-provided value, like the admin does), and require an explicit
        name for narc."""
        if data.get('scanner') == YARA:
            match = YARA_RULE_NAME_RE.search(data.get('definition') or '')
            if match:
                data['name'] = match.group(1)
            # If it didn't match, leave name as-is; clean() will surface a
            # helpful error about the definition.
        elif not data.get('name'):
            raise serializers.ValidationError(
                {'name': 'This field is required for this scanner.'}
            )

    def validate(self, data):
        # Build/patch the instance and call the model's clean(), which compiles
        # the YARA/NARC definition and checks the name matches. We deliberately
        # call clean() and not full_clean(): field-level constraints are already
        # enforced by the serializer fields. We do call validate_unique() to
        # enforce the (name, scanner) uniqueness constraint (see Meta.validators).
        if self.instance is None:
            self.validate_name_for_scanner(data)
            instance = ScannerQueryRule(**data)
        else:
            if self.instance.state != NEW:
                raise serializers.ValidationError(
                    'A scanner query rule can only be modified while it is in '
                    'the "new" state. Create a new rule to iterate on it.'
                )
            instance = self.instance
            for attr, value in data.items():
                setattr(instance, attr, value)

        try:
            instance.clean()
            instance.validate_unique()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(
                exc.message_dict if hasattr(exc, 'error_dict') else exc.messages
            ) from exc

        if 'configuration' in data:
            self.validate_configuration_against_schema(instance, data['configuration'])

        return data


class ScannerQueryResultAddonSerializer(serializers.ModelSerializer):
    """Minimal add-on representation for a scanner query result."""

    class Meta:
        model = Addon
        fields = ('id', 'guid', 'average_daily_users')
        read_only_fields = fields


class ScannerQueryResultVersionSerializer(serializers.ModelSerializer):
    """Minimal version representation for a scanner query result."""

    addon = ScannerQueryResultAddonSerializer(read_only=True)
    channel = ReverseChoiceField(
        choices=list(amo.CHANNEL_CHOICES_API.items()), read_only=True
    )

    class Meta:
        model = Version
        fields = ('id', 'version', 'channel', 'created', 'addon')
        read_only_fields = fields


class ScannerQueryResultSerializer(serializers.ModelSerializer):
    """Read-only serializer exposing the matches of a ScannerQueryRule.

    ``matches`` is the structured, per-file view of the hits produced by
    ``get_files_and_data_by_matched_rules()`` (the same representation the
    admin surfaces), which is the convenient shape for iterating on a rule."""

    version = ScannerQueryResultVersionSerializer(read_only=True)
    matches = serializers.SerializerMethodField()

    class Meta:
        model = ScannerQueryResult
        fields = (
            'id',
            'was_blocked',
            'was_promoted',
            'version',
            'matches',
            'created',
        )
        read_only_fields = fields

    def get_matches(self, obj):
        return dict(obj.get_files_and_data_by_matched_rules())
