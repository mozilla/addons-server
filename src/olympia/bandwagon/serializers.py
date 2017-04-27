from rest_framework import serializers

from olympia.api.fields import TranslationSerializerField
from olympia.bandwagon.models import Collection


class SimpleCollectionSerializer(serializers.ModelSerializer):
    name = TranslationSerializerField()
    url = serializers.SerializerMethodField()

    class Meta:
        model = Collection
        fields = ('id', 'url', 'name', 'addon_count')

    def get_url(self, obj):
        return obj.get_abs_url()
