from django.template.defaultfilters import filesizeformat
from django.utils.translation import gettext

from rest_framework import serializers

from olympia import amo
from olympia.activity.models import ActivityLog, CommentLog
from olympia.addons.models import Addon
from olympia.addons.serializers import MinimalVersionSerializer, SimpleAddonSerializer
from olympia.amo.reverse import reverse
from olympia.api.serializers import AMOModelSerializer
from olympia.api.utils import is_gate_active
from olympia.users.models import UserProfile
from olympia.versions.models import Version


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


class FeedActivityLogVersionsListSerializer(serializers.ListSerializer):
    def get_attribute(self, obj):
        return [argument for argument in obj.arguments if isinstance(argument, Version)]


class FeedActivityLogVersionSerializer(MinimalVersionSerializer):
    channel = serializers.SerializerMethodField()
    public_status = serializers.SerializerMethodField()

    class Meta:
        model = Version
        fields = ('id', 'version', 'channel', 'public_status', 'addon_id')
        list_serializer_class = FeedActivityLogVersionsListSerializer

    def get_channel(self, obj):
        return amo.CHANNEL_CHOICES_API[obj.channel]

    def get_public_status(self, obj):
        return obj.file.get_status_display()

    def get_addon_id(self, obj):
        return obj.addon.id


class FeedActivityLogAddonSerializer(SimpleAddonSerializer):
    class Meta:
        model = Addon
        fields = ('id', 'slug', 'name', 'disabled_by_user')

    def get_attribute(self, obj):
        return next(
            (argument for argument in obj.arguments if isinstance(argument, Addon)),
            None,
        )


class FeedActivityLogUserSerializer(AMOModelSerializer):
    class Meta:
        model = UserProfile
        fields = ('name',)


class FeedActivityLogSerializer(AMOModelSerializer):
    title = serializers.SerializerMethodField()
    comments = serializers.SerializerMethodField()
    date = serializers.DateTimeField(source='created')
    user = FeedActivityLogUserSerializer(read_only=True)
    addon = FeedActivityLogAddonSerializer(read_only=True)
    versions = FeedActivityLogVersionSerializer(read_only=True, many=True)

    class Meta:
        model = ActivityLog
        fields = ('id', 'addon', 'versions', 'title', 'comments', 'date', 'user')

    def get_title(self, obj):
        return obj.to_string()

    def get_comments(self, obj):
        comments = obj.details['comments'] if obj.details else ''
        return getattr(obj.log(), 'sanitize', comments)
