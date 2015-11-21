from rest_framework import serializers

from apps.users.models import UserProfile


class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = (
            'username', 'display_name', 'email',
            'bio', 'deleted', 'display_collections',
            'display_collections_fav', 'homepage',
            'location', 'notes', 'notifycompat',
            'notifyevents', 'occupation', 'picture_type',
            'read_dev_agreement', 'last_login_ip',
            'last_login_attempt', 'last_login_attempt_ip',
            'failed_login_attempts', 'is_verified',
            'region', 'lang', 't_shirt_requested'
        )
