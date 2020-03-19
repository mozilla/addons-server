from rest_framework import serializers

from olympia.amo.urlresolvers import get_outgoing_url

from .models import Block


class BlockSerializer(serializers.ModelSerializer):
    class Meta:
        model = Block
        fields = (
            'id', 'created', 'modified', 'guid', 'min_version', 'max_version',
            'reason', 'url')

    def to_representation(self, obj):
        data = super().to_representation(obj)

        if ('request' in self.context and
                'wrap_outgoing_links' in self.context['request'].GET and
                'url' in data):
            data['url'] = get_outgoing_url(data['url'])

        return data
