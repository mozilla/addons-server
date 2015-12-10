from rest_framework import generics, serializers
from rest_framework.response import Response

from waffle.decorators import waffle_switch

import amo
from addons.models import Addon


class AddonSerializer(serializers.ModelSerializer):
    addon_type = serializers.SerializerMethodField('get_addon_type')
    description = serializers.CharField()
    download_url = serializers.SerializerMethodField('get_download_url')
    icons = serializers.SerializerMethodField('get_icons')
    name = serializers.CharField()
    rating = serializers.FloatField(source='average_rating')
    summary = serializers.CharField()

    class Meta:
        model = Addon
        fields = [
            'addon_type',
            'description',
            'download_url',
            'icons',
            'id',
            'guid',
            'name',
            'rating',
            'slug',
            'summary',
        ]

    def get_addon_type(self, instance):
        return unicode(amo.ADDON_TYPE[instance.type])

    def get_icons(self, instance):
        return {
            '32': instance.get_icon_url(32),
            '64': instance.get_icon_url(64),
        }

    def get_download_url(self, instance):
        return instance.current_version.all_files[0].get_url_path('mozlando')


class SearchView(generics.RetrieveAPIView):
    serializer_class = AddonSerializer

    @waffle_switch('frontend-prototype')
    def retrieve(self, request, *args, **kwargs):
        queryset = Addon.objects.filter(type__in=amo.GROUP_TYPE_ADDON)
        if 'q' in request.GET:
            queryset = queryset.filter(slug__contains=request.GET['q'])
        serializer = self.get_serializer(queryset[:20], many=True)
        return Response(serializer.data, headers={
            'Access-Control-Allow-Origin': '*',
        })
