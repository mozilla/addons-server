from rest_framework import fields

from olympia import amo
from olympia.api.fields import OutgoingURLField, TranslationSerializerField
from olympia.api.serializers import AMOModelSerializer
from olympia.api.utils import is_gate_active
from olympia.versions.models import Version

from .models import Block, BlockType


class BlockSerializer(AMOModelSerializer):
    addon_name = TranslationSerializerField(source='addon.name')
    url = OutgoingURLField()
    blocked = fields.SerializerMethodField()
    soft_blocked = fields.SerializerMethodField()
    is_all_versions = fields.SerializerMethodField()

    class Meta:
        model = Block
        fields = (
            'id',
            'created',
            'modified',
            'addon_name',
            'blocked',
            'soft_blocked',
            'guid',
            'reason',
            'url',
            'is_all_versions',
        )

    def _get_blocked_for(self, obj, *, block_type):
        if not hasattr(obj, '_blockversion_set_qs_values_list'):
            obj._blockversion_set_qs_values_list = sorted(
                obj.blockversion_set.order_by('version__version').values_list(
                    'version__version', 'block_type'
                )
            )
        return [
            version
            for version, _block_type in obj._blockversion_set_qs_values_list
            if _block_type == block_type
        ]

    def get_blocked(self, obj):
        return self._get_blocked_for(obj, block_type=BlockType.BLOCKED)

    def get_soft_blocked(self, obj):
        return self._get_blocked_for(obj, block_type=BlockType.SOFT_BLOCKED)

    def get_is_all_versions(self, obj):
        cannot_upload_new_versions = not obj.addon or obj.addon.status in (
            amo.STATUS_DISABLED,
            amo.STATUS_DELETED,
        )
        unblocked_versions_qs = Version.unfiltered.filter(
            addon__addonguid__guid=obj.guid, file__is_signed=True
        ).exclude(blockversion__id__isnull=False)
        return cannot_upload_new_versions and not unblocked_versions_qs.exists()

    def to_representation(self, obj):
        data = super().to_representation(obj)
        request = self.context.get('request', None)
        if request and is_gate_active(request, 'block-min-max-versions-shim'):
            if data.get('is_all_versions', False):
                data['min_version'] = '0'
                data['max_version'] = '*'
            elif versions := data.get('blocked', []):
                data['min_version'] = versions[0]
                data['max_version'] = versions[-1]
            else:
                data['min_version'] = data['max_version'] = ''
        if request and is_gate_active(request, 'block-versions-list-shim'):
            data['versions'] = data.get('blocked', [])
        return data
