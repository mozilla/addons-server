from rest_framework import fields

from olympia.api.fields import OutgoingURLField, TranslationSerializerField
from olympia.api.serializers import AMOModelSerializer

from .models import Block


class BlockSerializer(AMOModelSerializer):
    addon_name = TranslationSerializerField(source='addon.name')
    url = OutgoingURLField()
    min_version = fields.SerializerMethodField()
    max_version = fields.SerializerMethodField()
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

    def get_min_version(self, obj):
        return versions[0] if (versions := self.get_versions(obj)) else ''

    def get_max_version(self, obj):
        return versions[-1] if (versions := self.get_versions(obj)) else ''
