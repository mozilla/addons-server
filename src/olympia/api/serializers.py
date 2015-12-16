from rest_framework import serializers

from olympia.amo.helpers import absolutify
from olympia.amo.urlresolvers import reverse
from olympia.addons.models import Addon
from olympia.users.models import UserProfile
from olympia.versions.models import Version


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


class VersionSerializer(serializers.ModelSerializer):

    class Meta:
        model = Version
        fields = ('id', 'version', 'created')
        depth = 0

    def to_native(self, obj):
        native = super(VersionSerializer, self).to_native(obj)

        # Add non-field data to the response.
        native.update({
            'current': obj.addon.current_version == obj,
            'release_notes': (unicode(obj.releasenotes) if obj.releasenotes
                              else None),
            'statuses': obj.statuses,
            'addon_id': obj.addon.id,
            'apps': [{
                'application': unicode(app.application),
                'min': app.min.version,
                'max': app.max.version,
            } for app in obj.apps.all()],
            'license': unicode(obj.license.name) if obj.license else '',
        })

        return native
