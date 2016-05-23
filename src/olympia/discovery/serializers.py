from rest_framework import serializers

from olympia.addons.models import Addon
from olympia.addons.serializers import AddonSerializer, VersionSerializer
from olympia.versions.models import Version


class DiscoveryVersionSerializer(VersionSerializer):
    class Meta:
        fields = ('compatibility', 'files',)
        model = Version


class DiscoveryAddonSerializer(AddonSerializer):
    current_version = DiscoveryVersionSerializer()

    class Meta:
        fields = ('id', 'current_version', 'guid', 'icon_url', 'name',
                  'theme_data', 'type', 'url',)
        model = Addon


class DiscoverySerializer(serializers.Serializer):
    heading = serializers.CharField()
    description = serializers.CharField()
    addon = DiscoveryAddonSerializer()

    def to_representation(self, instance):
        data = super(DiscoverySerializer, self).to_representation(instance)
        if data['heading'] is None:
            data['heading'] = unicode(instance.addon.name)
        return data
