from rest_framework import serializers

from .models import ScannerResult


class ScannerResultSerializer(serializers.ModelSerializer):
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
