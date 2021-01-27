from urllib import parse

from django.conf import settings

from rest_framework import serializers
from rest_framework.request import Request as DRFRequest
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
        request = self.context.get('request')
        if isinstance(request, DRFRequest):
            # rest framework wraps the underlying Request
            real_request = request._request
        else:
            real_request = request
        orginal_get = real_request.GET
        real_request.GET = real_request.GET.copy()

        if obj.endpoint in ('search', 'search-themes'):
            criteria = obj.criteria.strip('?')
            params = dict(parse.parse_qsl(criteria))
            request.GET.update(params)
            addons = AddonSearchView(request=request).get_data(obj.get_count())
        elif obj.endpoint == 'collections':
            kwargs = {
                'user_pk': str(settings.TASK_USER_ID),
                'collection_slug': obj.criteria,
            }
            collection_addons = CollectionAddonViewSet(
                request=request, action='list', kwargs=kwargs
            ).get_data(obj.get_count())
            addons = [item['addon'] for item in collection_addons if 'addon' in item]
        else:
            addons = None

        real_request.GET = orginal_get
        return addons
