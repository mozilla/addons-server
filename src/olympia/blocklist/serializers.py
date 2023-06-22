from rest_framework import fields

from olympia import amo
from olympia.api.fields import OutgoingURLField, TranslationSerializerField
from olympia.api.serializers import AMOModelSerializer
from olympia.versions.models import Version

from .models import Block


class BlockSerializer(AMOModelSerializer):
    addon_name = TranslationSerializerField(source='addon.name')
    url = OutgoingURLField()
    min_version = fields.SerializerMethodField()
    max_version = fields.SerializerMethodField()
    versions = fields.SerializerMethodField()
    is_all_versions = fields.SerializerMethodField()

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
            'is_all_versions',
        )

    def get_versions(self, obj):
        if not hasattr(obj, '_blockversion_set_qs_values_list'):
            obj._blockversion_set_qs_values_list = sorted(
                obj.blockversion_set.order_by('version__version').values_list(
                    'version__version', flat=True
                )
            )
        return obj._blockversion_set_qs_values_list

    def get_min_version(self, obj):
        return versions[0] if (versions := self.get_versions(obj)) else ''

    def get_max_version(self, obj):
        return versions[-1] if (versions := self.get_versions(obj)) else ''

    def get_is_all_versions(self, obj):
        cannot_upload_new_versions = not obj.addon or obj.addon.status in (
            amo.STATUS_DISABLED,
            amo.STATUS_DELETED,
        )
        unblocked_versions_qs = Version.unfiltered.filter(
            addon__addonguid__guid=obj.guid, file__is_signed=True
        ).exclude(blockversion__id__isnull=False)
        return cannot_upload_new_versions and not unblocked_versions_qs.exists()
