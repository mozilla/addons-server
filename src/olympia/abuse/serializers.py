from rest_framework import serializers

from olympia.accounts.serializers import BaseUserSerializer
from olympia.abuse.models import AbuseReport


class AddonAbuseReportSerializer(serializers.ModelSerializer):
    addon = serializers.SerializerMethodField()
    reporter = BaseUserSerializer(read_only=True)

    class Meta:
        model = AbuseReport
        fields = ('reporter', 'addon', 'message')

    def get_addon(self, obj):
        addon = obj.addon
        if not addon and not obj.guid:
            return None
        return {
            'guid': addon.guid if addon else obj.guid,
            'id': addon.id if addon else None,
            'slug': addon.slug if addon else None,
        }


class UserAbuseReportSerializer(serializers.ModelSerializer):
    reporter = BaseUserSerializer(read_only=True)
    user = BaseUserSerializer()

    class Meta:
        model = AbuseReport
        fields = ('reporter', 'user', 'message')
