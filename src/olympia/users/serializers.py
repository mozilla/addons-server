from rest_framework import serializers

from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.users.models import UserProfile


class BaseUserSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = UserProfile
        fields = ('id', 'name', 'url')

    def get_url(self, obj):
        return absolutify(obj.get_url_path())


class AddonDeveloperSerializer(BaseUserSerializer):
    picture_url = serializers.SerializerMethodField()

    class Meta(BaseUserSerializer.Meta):
        fields = ('id', 'name', 'url', 'picture_url')
        read_only_fields = fields

    def get_picture_url(self, obj):
        return absolutify(obj.picture_url)
