from rest_framework import serializers

from users.models import UserProfile


class UserSerializer(serializers.ModelSerializer):

    class Meta:
        model = UserProfile
        fields = ('email', 'id', 'username', 'display_name', 'homepage',
                  'created', 'modified', 'location', 'occupation')
