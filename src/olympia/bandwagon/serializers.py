from rest_framework import serializers

from olympia.addons.serializers import AddonSerializer
from olympia.api.fields import TranslationSerializerField
from olympia.bandwagon.models import Collection, CollectionAddon
from olympia.users.serializers import BaseUserSerializer


class SimpleCollectionSerializer(serializers.ModelSerializer):
    name = TranslationSerializerField()
    description = TranslationSerializerField()
    url = serializers.SerializerMethodField()
    author = BaseUserSerializer()

    class Meta:
        model = Collection
        fields = ('id', 'url', 'addon_count', 'author', 'description',
                  'modified', 'name')

    def get_url(self, obj):
        return obj.get_abs_url()


class CollectionAddonSerializer(serializers.ModelSerializer):
    addon = AddonSerializer()
    notes = TranslationSerializerField(source='comments')

    class Meta:
        model = CollectionAddon
        fields = ('addon', 'downloads', 'notes')
