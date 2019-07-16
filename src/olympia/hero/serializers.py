from rest_framework import serializers

from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.discovery.serializers import DiscoveryAddonSerializer

from .models import PrimaryHero


class PrimaryHeroShelfSerializer(serializers.ModelSerializer):
    featured_image = serializers.SerializerMethodField()
    heading = serializers.CharField(source='disco_addon.heading')
    description = serializers.CharField(source='disco_addon.description')
    addon = DiscoveryAddonSerializer(source='disco_addon.addon')

    class Meta:
        model = PrimaryHero
        fields = ('addon', 'background_color', 'featured_image', 'heading',
                  'description')

    def get_featured_image(self, obj):
        return absolutify(obj.image_path)
