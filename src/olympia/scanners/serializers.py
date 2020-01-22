from rest_framework import serializers

from .models import ScannerResult


class ScannerResultSerializer(serializers.ModelSerializer):
    scanner = serializers.SerializerMethodField()
    results = serializers.JSONField()

    class Meta:
        model = ScannerResult
        fields = ('id', 'scanner', 'results')

    def get_scanner(self, obj):
        return obj.get_scanner_name()
