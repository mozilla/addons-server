from django.utils.translation import gettext

from rest_framework import serializers

from olympia.activity.models import ActivityLog
from olympia.api.utils import is_gate_active


class ActivityLogSerializer(serializers.ModelSerializer):
    action = serializers.SerializerMethodField()
    action_label = serializers.SerializerMethodField()
    comments = serializers.SerializerMethodField()
    date = serializers.DateTimeField(source='created')
    user = serializers.SerializerMethodField()
    highlight = serializers.SerializerMethodField()

    class Meta:
        model = ActivityLog
        fields = (
            'id',
            'action',
            'action_label',
            'comments',
            'user',
            'date',
            'highlight',
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.to_highlight = kwargs.get('context', []).get('to_highlight', [])

    def get_comments(self, obj):
        comments = obj.details['comments'] if obj.details else ''
        return getattr(obj.log(), 'sanitize', comments)

    def get_action_label(self, obj):
        log = obj.log()
        default = gettext('Review note')
        return default if not hasattr(log, 'short') else log.short

    def get_action(self, obj):
        return self.get_action_label(obj).replace(' ', '-').lower()

    def get_highlight(self, obj):
        return obj.pk in self.to_highlight

    def get_user(self, obj):
        """Return minimal user information from ActivityLog.

        id, username and url are present for backwards-compatibility in v3 API
        only."""
        data = {
            'name': obj.user.name,
        }
        request = self.context.get('request')
        if request and is_gate_active(request, 'activity-user-shim'):
            data.update({'id': None, 'username': None, 'url': None})
        return data
