from rest_framework import serializers

from apps.users.models import UserProfile


class UserProfileSerializer(serializers.ModelSerializer):
    picture_url = serializers.URLField(read_only=True, source='picture_url')

    class Meta:
        model = UserProfile
        fields = (
            'username', 'display_name', 'email',
            'bio', 'deleted', 'display_collections',
            'display_collections_fav', 'homepage',
            'location', 'notes', 'occupation', 'picture_type',
            'read_dev_agreement', 'is_verified',
            'region', 'lang', 'picture_url'
        )


class AccountSourceSerializer(serializers.ModelSerializer):
    source = serializers.CharField(source='source')

    class Meta:
        model = UserProfile
        fields = ['source']
