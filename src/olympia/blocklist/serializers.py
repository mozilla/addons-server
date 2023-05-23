from olympia.api.fields import OutgoingURLField, TranslationSerializerField
from olympia.api.serializers import AMOModelSerializer

from .models import Block


class BlockSerializer(AMOModelSerializer):
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
