from urllib import parse

from django.conf import settings

from rest_framework import serializers
from rest_framework.request import Request as DRFRequest
from rest_framework.reverse import reverse as drf_reverse

from olympia import amo
from olympia.addons.views import AddonSearchView
from olympia.api.fields import (
    AbsoluteOutgoingURLField,
    GetTextTranslationSerializerField,
    ReverseChoiceField
)
from olympia.bandwagon.views import CollectionAddonViewSet
from olympia.hero.serializers import CTAField

from .models import Shelf


class ShelfFooterField(CTAField):
    url = AbsoluteOutgoingURLField(source='footer_pathname')
    text = GetTextTranslationSerializerField(source='footer_text')


class ShelfSerializer(serializers.ModelSerializer):
    title = GetTextTranslationSerializerField()
    url = serializers.SerializerMethodField()
    footer = ShelfFooterField(source='*')
    addons = serializers.SerializerMethodField()
    addon_type = ReverseChoiceField(choices=list(amo.ADDON_TYPE_CHOICES_API.items()))

    class Meta:
        model = Shelf
        fields = [
            'title',
            'url',
            'endpoint',
            'addon_type',
            'criteria',
            'footer',
            'addons',
        ]

    def get_url(self, obj):
        if obj.endpoint == 'search':
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

        if obj.endpoint == 'search':
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


class ShelfEditorialSerializer(ShelfSerializer):
    title = serializers.CharField()
    footer_text = serializers.CharField()
    addons = None  # we don't the results for this serializer

    class Meta:
        model = Shelf
        fields = [
            'title',
            'footer_text',
        ]
