from rest_framework import serializers
from rest_framework.reverse import reverse as drf_reverse

from django.conf import settings

from olympia.shelves.models import Shelf


class ShelfSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = Shelf
        fields = ['title', 'url', 'footer_text', 'footer_pathname']

    def get_url(self, obj):
        if obj.endpoint == 'search':
            api = drf_reverse(
                'addon-search',
                request=self.context.get('request'))
            url = api + obj.criteria
        elif obj.endpoint == 'collections':
            url = drf_reverse(
                'collection-addon-list',
                request=self.context.get('request'),
                kwargs={
                    'user_pk': settings.TASK_USER_ID,
                    'collection_slug': obj.criteria})
        return url
