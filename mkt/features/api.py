from rest_framework import serializers

from mkt.webapps.models import AppFeatures


class AppFeaturesSerializer(serializers.ModelSerializer):

    class Meta:
        model = AppFeatures
        fields = []
        depth = 0

    def to_native(self, obj):
        return [f.replace('has_', '') for f in obj._fields() if getattr(obj, f)
                and f.startswith('has_')]
