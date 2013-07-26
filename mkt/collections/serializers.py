from rest_framework import serializers

from .models import Collection


class CollectionSerializer(serializers.ModelSerializer):
    name = serializers.CharField()
    description = serializers.CharField()
    collection_type = serializers.IntegerField(default=0)

    class Meta:
        fields = ('name', 'description', 'id',)
        model = Collection

    def to_native(self, obj):
        native = super(CollectionSerializer, self).to_native(obj)
        native['apps'] = obj.app_urls()
        return native
