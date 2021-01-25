from urllib import parse

from django.conf import settings
from django.core.signing import TimestampSigner

from rest_framework import serializers
from rest_framework.request import Request as DRFRequest
from rest_framework.reverse import reverse as drf_reverse

from olympia.addons.serializers import ESAddonSerializer
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


class ESSponsoredAddonSerializer(ESAddonSerializer):
    click_url = serializers.SerializerMethodField()
    click_data = serializers.SerializerMethodField()
    event_data = serializers.SerializerMethodField()
    _signer = TimestampSigner()

    class Meta(ESAddonSerializer.Meta):
        fields = ESAddonSerializer.Meta.fields + (
            'click_url',
            'click_data',
            'event_data',
        )

    def get_click_url(self, obj):
        return drf_reverse('sponsored-shelf-click', request=self.context.get('request'))

    def get_click_data(self, obj):
        view = self.context['view']
        click_data = view.adzerk_results.get(str(obj.id), {}).get('click')
        return self._signer.sign(click_data) if click_data else None

    def get_event_data(self, obj):
        view = self.context['view']
        event_data = view.adzerk_results.get(str(obj.id), {})
        events = {
            type_: self._signer.sign(data)
            for type_, data in event_data.items()
            if type_ != 'impression'  # we handle impression events seperately.
        }
        return events or None
