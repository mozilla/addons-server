from django.utils.translation import ugettext

from rest_framework import serializers

from olympia.addons.models import Addon
from olympia.addons.serializers import AddonSerializer
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.discovery.serializers import DiscoveryAddonSerializer

from .models import PrimaryHero, SecondaryHero, SecondaryHeroModule


class ExternalAddonSerializer(AddonSerializer):
    class Meta:
        fields = ('id', 'guid', 'homepage', 'name', 'type',)
        model = Addon


class PrimaryHeroShelfSerializer(serializers.ModelSerializer):
    description = serializers.CharField(source='disco_addon.description_text')
    featured_image = serializers.CharField(source='image_url')
    addon = DiscoveryAddonSerializer(source='disco_addon.addon')
    external = ExternalAddonSerializer(source='disco_addon.addon')

    class Meta:
        model = PrimaryHero
        fields = ('addon', 'description', 'external', 'featured_image',
                  'gradient')

    def to_representation(self, instance):
        rep = super().to_representation(instance)
        rep.pop('addon' if instance.is_external else 'external')
        return rep


class CTAMixin():

    def get_cta(self, obj):
        if obj.cta_url and obj.cta_text:
            return {
                'url': absolutify(obj.cta_url),
                'text': ugettext(obj.cta_text),
            }
        else:
            return None


class SecondaryHeroShelfModuleSerializer(CTAMixin,
                                         serializers.ModelSerializer):
    icon = serializers.CharField(source='icon_url')
    description = serializers.SerializerMethodField()
    cta = serializers.SerializerMethodField()

    class Meta:
        model = SecondaryHeroModule
        fields = ('icon', 'description', 'cta')

    def get_description(self, obj):
        return ugettext(obj.description)


class SecondaryHeroShelfSerializer(CTAMixin, serializers.ModelSerializer):
    headline = serializers.SerializerMethodField()
    description = serializers.SerializerMethodField()
    cta = serializers.SerializerMethodField()
    modules = SecondaryHeroShelfModuleSerializer(many=True)

    class Meta:
        model = SecondaryHero
        fields = ('headline', 'description', 'cta', 'modules')

    def get_headline(self, obj):
        return ugettext(obj.headline)

    def get_description(self, obj):
        return ugettext(obj.description)
