from urllib import parse

from django.conf import settings

from rest_framework import serializers
from rest_framework.reverse import reverse as drf_reverse

from olympia.addons.views import AddonSearchView
from olympia.bandwagon.views import CollectionAddonViewSet

from .models import Shelf


class ShelfSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()
    addons = serializers.SerializerMethodField()

    class Meta:
        model = Shelf
        fields = [
            'title',
            'url',
            'endpoint',
            'criteria',
            'footer_text',
            'footer_pathname',
            'addons',
        ]

    def get_url(self, obj):
        if obj.endpoint in ('search', 'search-themes'):
            api = drf_reverse('addon-search', request=self.context.get('request'))
            url = api + obj.criteria
        elif obj.endpoint == 'collections':
            url = drf_reverse(
                'collection-addon-list',
                request=self.context.get('request'),
                kwargs={
                    'user_pk': str(settings.TASK_USER_ID),
                    'collection_slug': obj.criteria,
                },
            )
        else:
            url = None

        return url

    def get_addons(self, obj):
        if obj.endpoint in ('search', 'search-themes'):
            criteria = obj.criteria.strip('?')
            params = dict(parse.parse_qsl(criteria))
            request = self.context.get('request')
            tmp = request.GET
            request.GET = request.GET.copy()
            request.GET.update(params)
            addons = AddonSearchView(request=request).data
            request.GET = tmp
            return addons
        elif obj.endpoint == 'collections':
            request = self.context.get('request')
            kwargs = {
                'user_pk': str(settings.TASK_USER_ID),
                'collection_slug': obj.criteria,
            }
            collection_addons = CollectionAddonViewSet(
                request=request, action='list', kwargs=kwargs
            ).data
            return [item['addon'] for item in collection_addons if 'addon' in item]
        else:
            return None
