from rest_framework import serializers

from olympia.shelves.models import Shelf, ShelfManagement


class ShelfSerializer(serializers.ModelSerializer):
    class Meta:
        model = Shelf
        fields = ['id', 'title', 'endpoint', 'criteria',
                  'footer_text', 'footer_pathname']


class HomepageSerializer(serializers.ModelSerializer):
    shelf = ShelfSerializer(required=True)

    class Meta:
        model = ShelfManagement
        fields = ['position', 'shelf', 'enabled']
