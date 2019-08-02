from rest_framework import serializers

from olympia.addons.models import Addon
from olympia.addons.serializers import AddonSerializer
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.discovery.serializers import DiscoveryAddonSerializer

from .models import PrimaryHero


class ExternalAddonSerializer(AddonSerializer):
    class Meta:
        fields = ('id', 'guid', 'homepage', 'name', 'type',)
        model = Addon


class PrimaryHeroShelfSerializer(serializers.ModelSerializer):
    description = serializers.CharField(source='disco_addon.description')
    featured_image = serializers.SerializerMethodField()
    heading = serializers.CharField(source='disco_addon.heading')
    addon = DiscoveryAddonSerializer(source='disco_addon.addon')
    external = ExternalAddonSerializer(source='disco_addon.addon')

    class Meta:
        model = PrimaryHero
        fields = ('addon', 'description', 'external', 'featured_image',
                  'gradient', 'heading')

    def to_representation(self, instance):
        rep = super().to_representation(instance)
        rep.pop('addon' if instance.is_external else 'external')
        return rep

    def get_featured_image(self, obj):
        return absolutify(obj.image_path)
