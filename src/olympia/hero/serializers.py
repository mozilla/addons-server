from rest_framework import serializers

from olympia.addons.models import Addon
from olympia.addons.serializers import AddonSerializer
from olympia.api.fields import (
    AbsoluteOutgoingURLField,
    FallbackField,
    GetTextTranslationSerializerFieldFlat,
    TranslationSerializerFieldFlat,
)
from olympia.api.serializers import AMOModelSerializer
from olympia.api.utils import is_gate_active
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


class PrimaryHeroShelfSerializer(AMOModelSerializer):
    description = FallbackField(
        GetTextTranslationSerializerFieldFlat(),
        TranslationSerializerFieldFlat(source='addon.summary'),
    )
    featured_image = serializers.CharField(source='image_url')
    addon = HeroAddonSerializer()
    external = ExternalAddonSerializer(source='addon')

    class Meta:
        model = PrimaryHero
        fields = (
            'addon',
            'description',
            'external',
            'featured_image',
            'gradient',
        )

    def to_representation(self, instance):
        rep = super().to_representation(instance)
        rep.pop('addon' if instance.is_external else 'external')

        if 'request' in self.context and 'raw' in self.context['request'].GET:
            rep['description'] = str(instance.description or '')
        return rep


class CTAField(serializers.Serializer):
    url = AbsoluteOutgoingURLField(source='cta_url')
    text = GetTextTranslationSerializerFieldFlat(source='cta_text')

    def to_representation(self, obj):
        data = super().to_representation(obj)
        if data.get('url') or data.get('text'):
            request = self.context.get('request', None)

            if request and is_gate_active(request, 'wrap-outgoing-parameter'):
                # when 'wrap-outgoing-parameter' is on url is a flat string already
                return data
            else:
                url = data.get('url') or {}
                return {
                    **data,
                    'url': url.get('url'),
                    'outgoing': url.get('outgoing'),
                }
        else:
            return None


class SecondaryHeroShelfModuleSerializer(AMOModelSerializer):
    icon = serializers.CharField(source='icon_url')
    description = GetTextTranslationSerializerFieldFlat()
    cta = CTAField(source='*')

    class Meta:
        model = SecondaryHeroModule
        fields = ('icon', 'description', 'cta')


class SecondaryHeroShelfSerializer(AMOModelSerializer):
    headline = GetTextTranslationSerializerFieldFlat()
    description = GetTextTranslationSerializerFieldFlat()
    cta = CTAField(source='*')
    modules = SecondaryHeroShelfModuleSerializer(many=True)

    class Meta:
        model = SecondaryHero
        fields = ('headline', 'description', 'cta', 'modules')
