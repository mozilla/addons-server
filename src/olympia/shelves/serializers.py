from urllib import parse

from django.conf import settings

from rest_framework import serializers
from rest_framework.request import Request as DRFRequest
from rest_framework.reverse import reverse as drf_reverse

from olympia.addons.views import AddonSearchView
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.api.fields import (
    GetTextTranslationSerializerFieldFlat,
    OutgoingURLField,
)
from olympia.bandwagon.views import CollectionAddonViewSet

from .models import Shelf


class AbsoluteOutgoingURLField(OutgoingURLField):
    def to_representation(self, obj):
        return super().to_representation(absolutify(obj) if obj else obj)

class FooterField(serializers.Serializer):
    footer_url = AbsoluteOutgoingURLField()
    footer_text = GetTextTranslationSerializerFieldFlat()

    def to_representation(self, obj):
        if obj.footer_url and obj.footer_text:
            data = super().to_representation(obj)
            if isinstance(data.get('footer_url'), dict):
                return {
                    'url': data.get('footer_url', {}).get('url'),
                    'outgoing': data.get('footer_url', {}).get('outgoing'),
                    'text': data.get('footer_text'),
                }
            else:
                # when 'wrap-outgoing-parameter' is on footer_url is a flat string
                return {
                    'url': data.get('footer_url'),
                    'text': data.get('footer_text'),
                }
        else:
            return None

class ShelfSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()
    footer = FooterField(source='*')
    addons = serializers.SerializerMethodField()

    class Meta:
        model = Shelf
        fields = [
            'title',
            'url',
            'endpoint',
            'criteria',
            'footer',
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
