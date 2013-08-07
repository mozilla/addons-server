from rest_framework import serializers

from mkt.webapps.utils import app_to_dict

from .models import Collection


class CollectionMembershipField(serializers.RelatedField):
    def to_native(self, value):
        return app_to_dict(value.app)


class CollectionSerializer(serializers.ModelSerializer):
    name = serializers.CharField()
    description = serializers.CharField()
    collection_type = serializers.IntegerField()
    collectionmembership_set = CollectionMembershipField(many=True)

    class Meta:
        fields = ('collection_type', 'description', 'id', 'name',
                  'collectionmembership_set')
        model = Collection

    def to_native(self, obj):
        """
        `collectionmembership_set` is ugly; let's rename to `apps`.
        """
        native = super(CollectionSerializer, self).to_native(obj)
        native['apps'] = native['collectionmembership_set']
        del native['collectionmembership_set']
        return native
