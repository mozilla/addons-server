from rest_framework import serializers

from olympia.amo.urlresolvers import get_outgoing_url
from olympia.api.fields import TranslationSerializerField

from .models import Block


class BlockSerializer(serializers.ModelSerializer):
    addon_name = TranslationSerializerField(source='addon.name')

    class Meta:
        model = Block
        fields = (
            'id', 'created', 'modified', 'addon_name', 'guid', 'min_version',
            'max_version', 'reason', 'url')

    def to_representation(self, obj):
        data = super().to_representation(obj)

        if ('request' in self.context and
                'wrap_outgoing_links' in self.context['request'].GET and
                data.get('url')):
            data['url'] = get_outgoing_url(data['url'])

        return data
