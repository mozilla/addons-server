from django.template.defaultfilters import filesizeformat
from django.utils.translation import gettext

from rest_framework import serializers

from olympia import amo
from olympia.activity.models import ActivityLog, CommentLog
from olympia.amo.reverse import reverse
from olympia.api.serializers import AMOModelSerializer
from olympia.api.utils import is_gate_active


class ActivityLogSerializer(AMOModelSerializer):
    action = serializers.SerializerMethodField()
    action_label = serializers.SerializerMethodField()
    policies = serializers.SerializerMethodField()
    comments = serializers.SerializerMethodField()
    date = serializers.DateTimeField(source='created')
    user = serializers.SerializerMethodField()
    highlight = serializers.SerializerMethodField()
    attachment_url = serializers.SerializerMethodField()
    attachment_size = serializers.SerializerMethodField()

    class Meta:
        model = ActivityLog
        fields = (
            'id',
            'action',
            'action_label',
            'policies',
            'comments',
            'user',
            'date',
            'highlight',
            'attachment_url',
            'attachment_size',
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.to_highlight = kwargs.get('context', {}).get('to_highlight', [])

    def get_policies(self, obj):
        sanitize = getattr(obj.log(), 'sanitize', None)
        if sanitize is not None:
            return [sanitize]
        # Some activity logs might not have `policy_texts`
        policies = obj.details.get('policy_texts', []) if obj.details else []
        return policies

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

    def get_attachment_url(self, obj):
        if hasattr(obj, 'attachmentlog'):
            return reverse('activity.attachment', args=[obj.pk])
        return None

    def get_attachment_size(self, obj):
        if hasattr(obj, 'attachmentlog'):
            filesize = obj.attachmentlog.file.size
            return filesizeformat(filesize)
        return None


class ActivityLogSerializerForComments(serializers.Serializer):
    comments = serializers.CharField(
        required=True, max_length=CommentLog._meta.get_field('comments').max_length
    )


class FeedActivityLogSerializer(AMOModelSerializer):
    title = serializers.SerializerMethodField()
    date = serializers.DateTimeField(source='created')
    version = serializers.SerializerMethodField()
    comments = serializers.SerializerMethodField()

    class Meta:
        model = ActivityLog
        fields = (
            'id',
            'version',
            'title',
            'comments',
            'date',
        )

    def get_title(self, obj):
        return obj.to_string()

    def get_comments(self, obj):
        comments = obj.details['comments'] if obj.details else ''
        return getattr(obj.log(), 'sanitize', comments)

    def get_version(self, obj):
        return [
            {
                'version_id': version_log.version.id,
                'version': version_log.version.version,
                'channel': amo.CHANNEL_CHOICES_API[version_log.version.channel],
                'status': version_log.version.get_review_status_display(),
                'addon': {
                    'id': version_log.version.addon.id,
                    'slug': version_log.version.addon.slug,
                    'name': str(version_log.version.addon.name),
                    'disabled_by_user': version_log.version.addon.disabled_by_user,
                },
            }
            for version_log in obj.versionlog_set.all()
        ]
