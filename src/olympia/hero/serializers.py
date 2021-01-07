from django.utils.translation import ugettext

from rest_framework import serializers

from olympia.addons.models import Addon
from olympia.addons.serializers import AddonSerializer
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.api.fields import OutgoingURLField
from olympia.discovery.serializers import DiscoveryAddonSerializer

from .models import PrimaryHero, SecondaryHero, SecondaryHeroModule


class ExternalAddonSerializer(AddonSerializer):
    class Meta:
        fields = (
            'id',
            'guid',
            'homepage',
            'name',
            'type',
        )
        model = Addon


class HeroAddonSerializer(DiscoveryAddonSerializer):
    class Meta:
        fields = DiscoveryAddonSerializer.Meta.fields + ('promoted',)
        model = Addon


class PrimaryHeroShelfSerializer(serializers.ModelSerializer):
    description = serializers.SerializerMethodField()
    featured_image = serializers.CharField(source='image_url')
    addon = HeroAddonSerializer(source='promoted_addon.addon')
    external = ExternalAddonSerializer(source='promoted_addon.addon')

    class Meta:
        model = PrimaryHero
        fields = ('addon', 'description', 'external', 'featured_image', 'gradient')

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
            return str(obj.promoted_addon.addon.summary or '')


class AbsoluteOutgoingURLField(OutgoingURLField):
    def to_representation(self, obj):
        return super().to_representation(absolutify(obj) if obj else obj)


class CTAField(serializers.Serializer):
    cta_url = AbsoluteOutgoingURLField()
    cta_text = serializers.CharField()

    def to_representation(self, obj):
        if obj.cta_url and obj.cta_text:
            data = super().to_representation(obj)
            if isinstance(data.get('cta_url'), dict):
                return {
                    'url': data.get('cta_url', {}).get('url'),
                    'outgoing': data.get('cta_url', {}).get('outgoing'),
                    'text': data.get('cta_text'),
                }
            else:
                # when 'wrap-outgoing-parameter' is on cta_url is a flat string
                return {
                    'url': data.get('cta_url'),
                    'text': data.get('cta_text'),
                }
        else:
            return None


class SecondaryHeroShelfModuleSerializer(serializers.ModelSerializer):
    icon = serializers.CharField(source='icon_url')
    description = serializers.SerializerMethodField()
    cta = CTAField(source='*')

    class Meta:
        model = SecondaryHeroModule
        fields = ('icon', 'description', 'cta')

    def get_description(self, obj):
        return ugettext(obj.description)


class SecondaryHeroShelfSerializer(serializers.ModelSerializer):
    headline = serializers.SerializerMethodField()
    description = serializers.SerializerMethodField()
    cta = CTAField(source='*')
    modules = SecondaryHeroShelfModuleSerializer(many=True)

    class Meta:
        model = SecondaryHero
        fields = ('headline', 'description', 'cta', 'modules')

    def get_headline(self, obj):
        return ugettext(obj.headline)

    def get_description(self, obj):
        return ugettext(obj.description)
