import json

from rest_framework.permissions import AllowAny
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.exceptions import ParseError, PermissionDenied
from rest_framework.generics import GenericAPIView
from rest_framework.serializers import Serializer

from amo.urlresolvers import reverse
from translations.helpers import truncate

import mkt
from access import acl
from mkt.api.authentication import (RestSharedSecretAuthentication,
                                    RestOAuthAuthentication)
from mkt.api.base import CORSMixin, form_errors, MarketplaceView
from mkt.collections.constants import (COLLECTIONS_TYPE_BASIC,
                                       COLLECTIONS_TYPE_FEATURED,
                                       COLLECTIONS_TYPE_OPERATOR)
from mkt.collections.filters import CollectionFilterSetWithFallback
from mkt.collections.models import Collection
from mkt.collections.serializers import CollectionSerializer
from mkt.constants.regions import REGIONS_DICT
from mkt.features.utils import get_feature_profile
from mkt.search.views import _filter_search
from mkt.search.forms import ApiSearchForm
from mkt.webapps.models import Webapp
from mkt.webapps.utils import es_app_to_dict


class SearchResultSerializer(Serializer):
    def field_to_native(self, obj, field_name):
        req = self.context['request']
        return [self.context['view'].serialize(req, app)
                for app in obj.object_list]


class SearchView(CORSMixin, MarketplaceView, GenericAPIView):
    cors_allowed_methods = ['get']
    authentication_classes = [RestSharedSecretAuthentication,
                              RestOAuthAuthentication]
    permission_classes = [AllowAny]
    serializer_class = SearchResultSerializer

    def serialize(self, req, app):
        amo_user = getattr(req, 'amo_user', None)
        data = es_app_to_dict(app, region=req.REGION.id,
                              profile=amo_user,
                              request=req)
        data['resource_uri'] = reverse('app-detail',
                                       kwargs={'pk': data['id']})
        return data

    def get_region(self, request):
        """
        Returns the REGION object for the passed request. Rules:

        1. If the GET param `region` is `None`, return `None`. If a request
           attempts to do this without authentication and one of the
           'Regions:BypassFilters' permission or curator-level access to a
           collection, return a 403.
        2. If the GET param `region` is set and not empty, attempt to return
           the region with the specified slug.
        3. If request.REGION is set, return it. (If the GET param `region` is
           either not set or set and empty, RegionMiddleware will attempt to
           determine the region via IP address).
        4. Return the worldwide region.
        """
        region = request.GET.get('region')
        if region and region == 'None':
            collection_curator = (Collection.curators.through.objects.filter(
                                  userprofile=request.amo_user).exists())
            has_permission = acl.action_allowed(request, 'Regions',
                                                'BypassFilters')
            if not (collection_curator or has_permission):
                raise PermissionDenied()
            return None

        elif region:
            try:
                return REGIONS_DICT[region]
            except KeyError:
                raise ParseError(json.dumps({'error_message':
                                             {'region': ['Invalid region.']}}))

        return getattr(request, 'REGION', mkt.regions.WORLDWIDE)

    def search(self, request):
        form_data = self.get_search_data(request, ApiSearchForm)

        base_filters = {'type': form_data['type']}

        qs = self.get_query(request, base_filters=base_filters,
                            region=self.get_region(request))
        profile = get_feature_profile(request)
        qs = self.apply_filters(request, qs, data=form_data,
                                profile=profile)
        page = self.paginate_queryset(qs)
        return self.get_pagination_serializer(page)

    def get(self, request, *args, **kwargs):
        serializer = self.search(request)
        return Response(serializer.data)

    def get_search_data(self, request, formclass):
        form = formclass(request.GET if request else None)
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
        filters.setdefault('region', self.get_region(request).slug)
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
        serializer = self.search(request)
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

        # Alter the _view_name so that statsd logs seperately from search.
        request._request._view_name = 'featured'

        return data, filter_fallbacks


class JSONSuggestionsRenderer(JSONRenderer):
    media_type = 'application/x-suggestions+json'


class SuggestionsView(SearchView):
    cors_allowed_methods = ['get']
    authentication_classes = [RestSharedSecretAuthentication,
                              RestOAuthAuthentication]
    permission_classes = [AllowAny]
    renderer_classes = [JSONSuggestionsRenderer, JSONRenderer]

    def get(self, request, *args, **kwargs):
        form_data = self.get_search_data(request, ApiSearchForm)
        query = form_data.get('q', '')
        base_filters = {'type': form_data['type']}

        qs = self.get_query(request, base_filters=base_filters,
                            region=self.get_region(request))
        profile = get_feature_profile(request)
        qs = self.apply_filters(request, qs, data=form_data, profile=profile)

        names = []
        descriptions = []
        urls = []
        icons = []

        for obj in qs:
            base_data = self.serialize(request, obj)
            names.append(base_data['name'])
            descriptions.append(truncate(base_data['description']))
            urls.append(base_data['absolute_url'])
            icons.append(base_data['icons'][64])
        return Response([query, names, descriptions, urls, icons],
                        content_type='application/x-suggestions+json')
