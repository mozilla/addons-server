from rest_framework import fields

from olympia.api.fields import OutgoingURLField, TranslationSerializerField
from olympia.api.serializers import AMOModelSerializer

from .models import Block


class BlockSerializer(AMOModelSerializer):
    addon_name = TranslationSerializerField(source='addon.name')
    url = OutgoingURLField()
    versions = fields.SerializerMethodField()

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
            'versions',
        )

    def get_versions(self, obj):
        return list(
            obj.blockversion_set.order_by('version__version').values_list(
                'version__version', flat=True
            )
        )
