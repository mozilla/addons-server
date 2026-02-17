from rest_framework import serializers

from olympia.api.serializers import AMOModelSerializer

from .models import ScannerResult


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
