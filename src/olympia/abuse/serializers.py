from rest_framework import serializers

from olympia.abuse.models import AbuseReport
from olympia.users.serializers import BaseUserSerializer


class AbuseReportSerializer(serializers.ModelSerializer):
    addon = serializers.SerializerMethodField()
    reporter = BaseUserSerializer(read_only=True)
    user = BaseUserSerializer()

    class Meta:
        model = AbuseReport
        fields = ('reporter', 'ip_address', 'addon', 'user', 'message')

    def get_addon(self, obj):
        addon = obj.addon
        if not addon and not obj.guid:
            return None
        return {
            'guid': addon.guid if addon else obj.guid,
            'id': addon.id if addon else None,
            'slug': addon.slug if addon else None,
        }
