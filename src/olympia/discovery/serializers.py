from rest_framework import serializers

from olympia.addons.models import Addon
from olympia.addons.serializers import AddonSerializer, VersionSerializer
from olympia.discovery.models import DiscoveryItem
from olympia.versions.models import Version


class DiscoveryEditorialContentSerializer(serializers.ModelSerializer):
    """
    Serializer used to fetch editorial-content only, for internal use when
    generating the .po files containing all editorial content to be translated.
    """
    class Meta:
        model = DiscoveryItem
        # We only need fields that require a translation, that's custom_heading
        # and custom_description.
        fields = ('custom_heading', 'custom_description')


class DiscoveryVersionSerializer(VersionSerializer):
    class Meta:
        fields = ('compatibility', 'files',)
        model = Version


class DiscoveryAddonSerializer(AddonSerializer):
    current_version = DiscoveryVersionSerializer()

    class Meta:
        fields = ('id', 'current_version', 'guid', 'icon_url', 'name',
                  'previews', 'slug', 'theme_data', 'type', 'url',)
        model = Addon


class DiscoverySerializer(serializers.ModelSerializer):
    heading = serializers.CharField()
    description = serializers.CharField()
    addon = DiscoveryAddonSerializer()
    is_recommendation = serializers.SerializerMethodField()

    class Meta:
        fields = ('heading', 'description', 'addon', 'is_recommendation')
        model = DiscoveryItem

    def get_is_recommendation(self, obj):
        # If an object is ever returned without having a position set, that
        # means it's coming from the recommendation server, it wasn't an
        # editorial choice.
        request = self.context.get('request')
        if request and request.GET.get('edition') == 'china':
            position_field = 'position_china'
        else:
            position_field = 'position'
        position_value = getattr(obj, position_field)
        return position_value is None or position_value < 1
