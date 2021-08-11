from django.conf import settings

from rest_framework import serializers
from rest_framework.request import Request as DRFRequest
from rest_framework.reverse import reverse as drf_reverse

from olympia import amo
from olympia.addons.views import AddonSearchView
from olympia.amo.reverse import reverse
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.api.fields import (
    AbsoluteOutgoingURLField,
    GetTextTranslationSerializerField,
    ReverseChoiceField,
)
from olympia.api.utils import is_gate_active
from olympia.bandwagon.views import CollectionAddonViewSet

from .models import Shelf


class ShelfFooterField(serializers.Serializer):
    url = AbsoluteOutgoingURLField(source='footer_pathname')
    text = GetTextTranslationSerializerField(source='footer_text')

    def to_representation(self, obj):
        data = super().to_representation(obj)
        request = self.context.get('request', None)
        # when 'wrap-outgoing-parameter' is on url is a flat string already
        is_flat_url = request and is_gate_active(request, 'wrap-outgoing-parameter')

        url = data.get('url')
        if not url:
            if obj.endpoint in (Shelf.Endpoints.SEARCH, Shelf.Endpoints.RANDOM_TAG):
                search_url = reverse('search.search')
                query_string = '&'.join(
                    f'{key}={value}' for key, value in obj.get_param_dict().items()
                )
                fallback = absolutify(f'{search_url}?{query_string}')
            elif obj.endpoint == Shelf.Endpoints.COLLECTIONS:
                fallback = absolutify(
                    reverse(
                        'collections.detail',
                        kwargs={
                            'user_id': str(settings.TASK_USER_ID),
                            'slug': obj.criteria,
                        },
                    )
                )
            else:
                # shouldn't happen
                fallback = None
            url = (
                {'url': fallback, 'outgoing': fallback} if not is_flat_url else fallback
            )
        # text = data.get('text')

        if is_flat_url:
            return {
                **data,
                'url': url,
            }
        else:
            return {
                **data,
                'url': (url or {}).get('url'),
                'outgoing': (url or {}).get('outgoing'),
            }


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
            'footer',
            'addons',
        ]

    def to_representation(self, obj):
        data = super().to_representation(obj)
        if obj.endpoint == Shelf.Endpoints.RANDOM_TAG:
            # Replace {tag} token in title and footer text
            data['title'] = {
                locale: value.replace('{tag}', obj.tag)
                for locale, value in (data.get('title') or {}).items()
            } or None
            data['footer']['text'] = {
                locale: value.replace('{tag}', obj.tag)
                for locale, value in (
                    (data.get('footer') or {}).get('text') or {}
                ).items()
            } or None
        return data

    def get_url(self, obj):
        if obj.endpoint in (Shelf.Endpoints.SEARCH, Shelf.Endpoints.RANDOM_TAG):
            api = drf_reverse('addon-search', request=self.context.get('request'))
            params = obj.get_param_dict()
            url = f'{api}?{"&".join(f"{key}={value}" for key, value in params.items())}'
        elif obj.endpoint == Shelf.Endpoints.COLLECTIONS:
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

        if obj.endpoint in (Shelf.Endpoints.SEARCH, Shelf.Endpoints.RANDOM_TAG):
            request.GET.update(obj.get_param_dict())
            addons = AddonSearchView(request=request).get_data(obj.get_count())
        elif obj.endpoint == Shelf.Endpoints.COLLECTIONS:
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


class ShelfEditorialSerializer(serializers.ModelSerializer):
    title = serializers.CharField()
    footer_text = serializers.CharField()

    class Meta:
        model = Shelf
        fields = [
            'title',
            'footer_text',
        ]
