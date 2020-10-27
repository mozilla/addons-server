from urllib import parse

from django.conf import settings
from django.core.signing import TimestampSigner

from rest_framework import serializers
from rest_framework.reverse import reverse as drf_reverse

from olympia.addons.serializers import ESAddonSerializer
from olympia.addons.views import AddonSearchView

from .models import Shelf


class ShelfSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()
    addons = serializers.SerializerMethodField()

    class Meta:
        model = Shelf
        fields = ['title', 'url', 'endpoint', 'criteria', 'footer_text',
                  'footer_pathname', 'addons']

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
        else:
            url = None

        return url

    def get_addons(self, obj):
        if obj.endpoint == 'search':
            criteria = obj.criteria.strip('?')
            params = dict(parse.parse_qsl(criteria))
            request = self.context.get('request', None)
            tmp = request.GET
            request.GET = request.GET.copy()
            request.GET.update(params)
            addons = AddonSearchView(request=request).data
            request.GET = tmp
            return addons
        else:
            return None


class ESSponsoredAddonSerializer(ESAddonSerializer):
    click_url = serializers.SerializerMethodField()
    click_data = serializers.SerializerMethodField()
    event_data = serializers.SerializerMethodField()
    _signer = TimestampSigner()

    class Meta(ESAddonSerializer.Meta):
        fields = ESAddonSerializer.Meta.fields + (
            'click_url', 'click_data', 'event_data')

    def get_click_url(self, obj):
        return drf_reverse(
            'sponsored-shelf-click',
            request=self.context.get('request'))

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
