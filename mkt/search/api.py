import json

from django.http import HttpResponse

from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.generics import GenericAPIView

from translations.helpers import truncate

import mkt
from mkt.api.authentication import (RestSharedSecretAuthentication,
                                    RestOAuthAuthentication)
from mkt.api.base import CORSMixin, form_errors, MarketplaceView
from mkt.api.paginator import ESPaginator
from mkt.collections.constants import (COLLECTIONS_TYPE_BASIC,
                                       COLLECTIONS_TYPE_FEATURED,
                                       COLLECTIONS_TYPE_OPERATOR)
from mkt.collections.filters import CollectionFilterSetWithFallback
from mkt.collections.models import Collection
from mkt.collections.serializers import CollectionSerializer
from mkt.features.utils import get_feature_profile
from mkt.search.views import _filter_search
from mkt.search.forms import ApiSearchForm
from mkt.search.serializers import (ESAppSerializer, RocketbarESAppSerializer,
                                    SuggestionsESAppSerializer)
from mkt.webapps.models import Webapp


class SearchView(CORSMixin, MarketplaceView, GenericAPIView):
    cors_allowed_methods = ['get']
    authentication_classes = [RestSharedSecretAuthentication,
                              RestOAuthAuthentication]
    permission_classes = [AllowAny]
    serializer_class = ESAppSerializer
    form_class = ApiSearchForm
    paginator_class = ESPaginator

    def get_region(self, request):
        """
        Returns the REGION object for the passed request. If the GET param
        `region` is `'None'`, return `None`. Otherwise, return `request.REGION`
        which will have been set by the RegionMiddleware. If somehow we didn't
        go through the middleware and request.REGION is absent, we fall back to
        RESTOFWORLD.
        """
        region = request.GET.get('region')
        if region and region == 'None':
            return None
        return getattr(request, 'REGION', mkt.regions.RESTOFWORLD)

    def search(self, request):
        form_data = self.get_search_data(request)
        query = form_data.get('q', '')
        base_filters = {'type': form_data['type']}

        qs = self.get_query(request, base_filters=base_filters,
                            region=self.get_region(request))
        profile = get_feature_profile(request)
        qs = self.apply_filters(request, qs, data=form_data,
                                profile=profile)
        page = self.paginate_queryset(qs.values_dict())
        return self.get_pagination_serializer(page), query

    def get(self, request, *args, **kwargs):
        serializer, _ = self.search(request)
        return Response(serializer.data)

    def get_search_data(self, request):
        form = self.form_class(request.GET if request else None)
        if not form.is_valid():
            raise form_errors(form)
        return form.cleaned_data

    def get_query(self, request, base_filters=None, region=None):
        return Webapp.from_search(request, region=region, gaia=request.GAIA,
                                  mobile=request.MOBILE, tablet=request.TABLET,
                                  filter_overrides=base_filters)

    def apply_filters(self, request, qs, data=None, profile=None):
        # Build region filter.
        region = self.get_region(request)
        return _filter_search(request, qs, data, region=region,
                              profile=profile)


class FeaturedSearchView(SearchView):

    def collections(self, request, collection_type=None, limit=1):
        filters = request.GET.dict()
        region = self.get_region(request)
        if region:
            filters.setdefault('region', region.slug)
        if collection_type is not None:
            qs = Collection.public.filter(collection_type=collection_type)
        else:
            qs = Collection.public.all()
        qs = CollectionFilterSetWithFallback(filters, queryset=qs).qs
        preview_mode = filters.get('preview', False)
        serializer = CollectionSerializer(qs[:limit], many=True, context={
            'request': request,
            'view': self,
            'use-es-for-apps': not preview_mode
        })
        return serializer.data, getattr(qs, 'filter_fallback', None)

    def get(self, request, *args, **kwargs):
        serializer, _ = self.search(request)
        data, filter_fallbacks = self.add_featured_etc(request,
                                                       serializer.data)
        response = Response(data)
        for name, value in filter_fallbacks.items():
            response['API-Fallback-%s' % name] = ','.join(value)
        return response

    def add_featured_etc(self, request, data):
        types = (
            ('collections', COLLECTIONS_TYPE_BASIC),
            ('featured', COLLECTIONS_TYPE_FEATURED),
            ('operator', COLLECTIONS_TYPE_OPERATOR),
        )
        filter_fallbacks = {}
        for name, col_type in types:
            data[name], fallback = self.collections(request,
                                                    collection_type=col_type)
            if fallback:
                filter_fallbacks[name] = fallback

        return data, filter_fallbacks


class SuggestionsView(SearchView):
    cors_allowed_methods = ['get']
    authentication_classes = []
    permission_classes = [AllowAny]
    serializer_class = SuggestionsESAppSerializer

    def get(self, request, *args, **kwargs):
        results, query = self.search(request)

        names = []
        descs = []
        urls = []
        icons = []

        for base_data in results.data['objects']:
            names.append(base_data['name'])
            descs.append(truncate(base_data['description']))
            urls.append(base_data['absolute_url'])
            icons.append(base_data['icon'])
        # This results a list. Usually this is a bad idea, but we don't return
        # any user-specific data, it's fully anonymous, so we're fine.
        return HttpResponse(json.dumps([query, names, descs, urls, icons]),
                            content_type='application/x-suggestions+json')


class RocketbarView(SearchView):
    cors_allowed_methods = ['get']
    authentication_classes = []
    permission_classes = [AllowAny]
    serializer_class = RocketbarESAppSerializer

    def get(self, request, *args, **kwargs):
        results, query = self.search(request)
        # This results a list. Usually this is a bad idea, but we don't return
        # any user-specific data, it's fully anonymous, so we're fine.
        return HttpResponse(json.dumps(results.data['objects']),
                            content_type='application/x-rocketbar+json')
