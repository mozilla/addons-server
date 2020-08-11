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
        baseUrl = settings.INTERNAL_SITE_URL
        if obj.endpoint == 'search':
            api = drf_reverse('v4:addon-search')
            url = baseUrl + api + obj.criteria
        elif obj.endpoint == 'collections':
            api = drf_reverse('v4:collection-addon-list', kwargs={
                'user_pk': settings.TASK_USER_ID,
                'collection_slug': obj.criteria})
            url = baseUrl + api
        return url
