from rest_framework import serializers

from olympia import amo
from olympia.access import acl
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.users.models import UserProfile


class BaseUserSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = UserProfile
        fields = ('id', 'name', 'url')

    def get_url(self, obj):
        def is_developer():
            return (
                self.context['is_developer'] if 'is_developer' in self.context
                else obj.is_developer)

        def is_adminish(user):
            return (user and
                    acl.action_allowed_user(user, amo.permissions.USERS_EDIT))

        request = self.context.get('request', None)
        current_user = getattr(request, 'user', None) if request else None
        # Only return your own profile url, and for developers.
        if obj == current_user or is_adminish(current_user) or is_developer():
            return absolutify(obj.get_url_path())


class AddonDeveloperSerializer(BaseUserSerializer):
    picture_url = serializers.SerializerMethodField()

    class Meta(BaseUserSerializer.Meta):
        fields = ('id', 'name', 'url', 'picture_url')
        read_only_fields = fields

    def get_picture_url(self, obj):
        return absolutify(obj.picture_url)
