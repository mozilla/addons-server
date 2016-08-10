from django.utils.translation import ugettext_lazy as _

from rest_framework import serializers

from olympia.users.serializers import BaseUserSerializer
from olympia.devhub.models import ActivityLog


class ActivityLogSerializer(serializers.ModelSerializer):
    action = serializers.SerializerMethodField()
    action_label = serializers.SerializerMethodField()
    comments = serializers.SerializerMethodField()
    date = serializers.DateTimeField(source='created')
    user = BaseUserSerializer()

    class Meta:
        model = ActivityLog
        fields = ('id', 'action', 'action_label', 'comments', 'user', 'date')

    def get_comments(self, obj):
        return obj.details['comments']

    def get_action_label(self, obj):
        log = obj.log()
        return _(u'Review note') if not hasattr(log, 'short') else log.short

    def get_action(self, obj):
        return self.get_action_label(obj).replace(' ', '-').lower()
