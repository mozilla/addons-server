from rest_framework import serializers

from amo.helpers import absolutify
from amo.urlresolvers import reverse

from addons.models import Addon
from users.models import UserProfile


class UserSerializer(serializers.ModelSerializer):

    class Meta:
        model = UserProfile
        fields = ('email', 'id', 'username', 'display_name', 'homepage',
                  'created', 'modified', 'location', 'occupation')


class AddonSerializer(serializers.ModelSerializer):

    resource_uri = serializers.CharField(source='slug', read_only=True)

    class Meta:
        model = Addon
        fields = ('id', 'name', 'eula', 'guid', 'status', 'slug',
                  'resource_uri')

    def transform_name(self, obj, value):
        """
        Custom handler so translated text doesn't return the translation id.
        """
        if obj:
            return obj.name.localized_string if obj.name else ''

    def transform_resource_uri(self, obj, value):
        """
        Maintain backward-compatibility with piston.
        """
        return absolutify(reverse('addons.detail', args=[obj.slug]))
