from django.utils.translation import ugettext

from rest_framework import serializers

from olympia import amo
from olympia.addons.models import Addon
from olympia.addons.serializers import AddonSerializer
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.urlresolvers import get_outgoing_url
from olympia.discovery.serializers import DiscoveryAddonSerializer

from .models import PrimaryHero, SecondaryHero, SecondaryHeroModule


class ExternalAddonSerializer(AddonSerializer):
    class Meta:
        fields = ('id', 'guid', 'homepage', 'name', 'type',)
        model = Addon


class PrimaryHeroShelfSerializer(serializers.ModelSerializer):
    description = serializers.SerializerMethodField()
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

    def get_description(self, obj):
        if 'request' in self.context and 'raw' in self.context['request'].GET:
            return str(obj.description or '')
        elif obj.description:
            return ugettext(obj.description)
        else:
            addon = obj.disco_addon.addon
            return (str(addon.summary)
                    if addon.summary and addon.type == amo.ADDON_EXTENSION
                    else '')


class CTAMixin():

    def get_cta(self, obj):
        if obj.cta_url and obj.cta_text:
            url = absolutify(obj.cta_url)
            should_wrap = (
                'request' in self.context and
                'wrap_outgoing_links' in self.context['request'].GET)
            return {
                'url': get_outgoing_url(url) if should_wrap else url,
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
