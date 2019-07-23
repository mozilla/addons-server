from rest_framework import serializers

from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.discovery.serializers import DiscoveryAddonSerializer

from .models import PrimaryHero


class PrimaryHeroShelfSerializer(serializers.ModelSerializer):
    description = serializers.CharField(source='disco_addon.description')
    featured_image = serializers.SerializerMethodField()
    heading = serializers.CharField(source='disco_addon.heading')
    addon = DiscoveryAddonSerializer(source='disco_addon.addon')

    class Meta:
        model = PrimaryHero
        fields = ('addon', 'description', 'featured_image', 'gradient',
                  'heading')

    def get_featured_image(self, obj):
        return absolutify(obj.image_path)
