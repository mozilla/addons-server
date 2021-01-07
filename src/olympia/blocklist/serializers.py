from rest_framework import serializers

from olympia.api.fields import OutgoingURLField, TranslationSerializerField

from .models import Block


class BlockSerializer(serializers.ModelSerializer):
    addon_name = TranslationSerializerField(source='addon.name')
    url = OutgoingURLField()

    class Meta:
        model = Block
        fields = (
            'id',
            'created',
            'modified',
            'addon_name',
            'guid',
            'min_version',
            'max_version',
            'reason',
            'url',
        )
