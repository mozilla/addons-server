from django.urls import reverse

from rest_framework import serializers

from olympia.addons.serializers import (
    CompactLicenseSerializer,
    MinimalFileSerializer,
    MinimalVersionSerializer,
)
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.api.serializers import AMOModelSerializer
from olympia.versions.models import Version

from .models import ScannerResult


class WebhookVersionSerializer(MinimalVersionSerializer):
    license = CompactLicenseSerializer(read_only=True)
    file = MinimalFileSerializer(read_only=True)
    url = serializers.SerializerMethodField()
    download_source_url = serializers.SerializerMethodField()

    class Meta:
        model = Version
        fields = (
            'id',
            'version',
            'file',
            'license',
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


class ScannerResultSerializer(AMOModelSerializer):
    scanner = serializers.SerializerMethodField()
    label = serializers.CharField(default=None)
    results = serializers.JSONField()

    class Meta:
        model = ScannerResult
        fields = (
            'id',
            'scanner',
            'label',
            'results',
            'created',
            'model_version',
        )

    def get_scanner(self, obj):
        return obj.get_scanner_name()


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
