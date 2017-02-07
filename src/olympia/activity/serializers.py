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
    highlight = serializers.SerializerMethodField()

    class Meta:
        model = ActivityLog
        fields = ('id', 'action', 'action_label', 'comments', 'user', 'date',
                  'highlight')

    def __init__(self, *args, **kwargs):
        super(ActivityLogSerializer, self).__init__(*args, **kwargs)
        self.to_highlight = kwargs.get('context', []).get('to_highlight', [])

    def get_comments(self, obj):
        # We have to do .unescape on the output of obj.to_string because the
        # 'string' it returns is supposed to be used in markup and doesn't get
        # serialized correctly unless we unescape it.
        comments = (obj.details['comments'] if obj.details
                    else obj.to_string().unescape())
        return getattr(obj.log(), 'sanitize', comments)

    def get_action_label(self, obj):
        log = obj.log()
        return _(u'Review note') if not hasattr(log, 'short') else log.short

    def get_action(self, obj):
        return self.get_action_label(obj).replace(' ', '-').lower()

    def get_highlight(self, obj):
        return obj in self.to_highlight
