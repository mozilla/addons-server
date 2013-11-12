from django.conf.urls import url

from tastypie.authorization import ReadOnlyAuthorization
from tastypie.exceptions import ImmediateHttpResponse
from tastypie.http import HttpForbidden
from tastypie.serializers import Serializer
from tastypie.utils import trailing_slash

from translations.helpers import truncate

from amo.urlresolvers import reverse

import mkt
from access import acl
from mkt.api.authentication import (SharedSecretAuthentication,
                                    OptionalOAuthAuthentication)
from mkt.api.base import CORSResource, MarketplaceResource
from mkt.api.serializers import SuggestionsSerializer
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


class SearchResource(CORSResource, MarketplaceResource):

    class Meta:
        resource_name = 'search'
        allowed_methods = []
        detail_allowed_methods = []
        list_allowed_methods = ['get']
        authorization = ReadOnlyAuthorization()
        authentication = (SharedSecretAuthentication(),
                          OptionalOAuthAuthentication())
        slug_lookup = None
        queryset = Webapp.objects.all()  # Gets overriden in dispatch.
        fields = ['categories', 'description', 'device_types', 'homepage',
                  'id', 'name', 'payment_account', 'premium_type',
                  'status', 'support_email', 'support_url']
        always_return_data = True
        serializer = Serializer(formats=['json'])

    def get_resource_uri(self, bundle):
        # Link to the AppViewSet URI.
        return reverse('app-detail', kwargs={'pk': bundle.obj.pk})

    def get_search_data(self, request):
        form = ApiSearchForm(request.GET if request else None)
        if not form.is_valid():
            raise self.form_errors(form)
        return form.cleaned_data

    def get_region(self, request):
        """
        Returns the REGION object for the passed request. Rules:

        1. If the GET param `region` is `None`, return `None`. If a request
           attempts to do this without authentication and one of the
           'Regions:BypassFilters' permission or curator-level access to a
           collection, return a 403.
        2. If the GET param `region` is set and not empty, attempt to return the
           region with the specified slug.
        3. If request.REGION is set, return it. (If the GET param `region` is
           either not set or set and empty, RegionMiddleware will attempt to
           determine the region via IP address).
        4. Return the worldwide region.

        This method is overridden by the reviewers search api to completely
        disable region filtering.
        """
        region = request.GET.get('region')
        if region and region == 'None':
            collection_curator = (Collection.curators.through.objects.filter(
                                  userprofile=request.amo_user).exists())
            has_permission = acl.action_allowed(request, 'Regions',
                                                'BypassFilters')
            if not (collection_curator or has_permission):
                raise ImmediateHttpResponse(response=HttpForbidden())
            return None

        elif region:
            try:
                return REGIONS_DICT[region]
            except KeyError:
                raise self.non_form_errors([('region', 'Invalid region.')])

        return getattr(request, 'REGION', mkt.regions.WORLDWIDE)

    def get_feature_profile(self, request):
        # Overridden by reviewers search api to disable profile filtering.
        return get_feature_profile(request)

    def get_query(self, request, base_filters=None):
        region = self.get_region(request)
        return Webapp.from_search(request, region=region, gaia=request.GAIA,
                                  mobile=request.MOBILE, tablet=request.TABLET,
                                  filter_overrides=base_filters)

    def apply_filters(self, request, qs, data=None):
        # Build device features profile filter.
        profile = self.get_feature_profile(request)

        # Build region filter.
        region = self.get_region(request)

        return _filter_search(request, qs, data, region=region,
                              profile=profile)

    def paginate_results(self, request, qs):
        paginator = self._meta.paginator_class(request.GET, qs,
            resource_uri=self.get_resource_list_uri(),
            limit=self._meta.limit)
        page = paginator.page()
        page['objects'] = self.rehydrate_results(request, page['objects'])
        return page

    def rehydrate_results(self, request, qs):
        # Rehydrate the results as per tastypie.
        objs = []
        for obj in qs:
            obj.pk = obj.id
            objs.append(self.build_bundle(obj=obj, request=request))
        return [self.full_dehydrate(bundle) for bundle in objs]

    def get_list(self, request=None, **kwargs):
        form_data = self.get_search_data(request)

        base_filters = {
            'type': form_data['type'],
        }

        qs = self.get_query(request, base_filters=base_filters)
        qs = self.apply_filters(request, qs, data=form_data)
        page = self.paginate_results(request, qs)

        # This isn't as quite a full as a full TastyPie meta object,
        # but at least it's namespaced that way and ready to expand.
        to_be_serialized = self.alter_list_data_to_serialize(request, page)
        return self.create_response(request, to_be_serialized)

    def dehydrate(self, bundle):
        obj = bundle.obj
        amo_user = getattr(bundle.request, 'amo_user', None)

        bundle.data.update(es_app_to_dict(obj, region=bundle.request.REGION.id,
                                          profile=amo_user,
                                          request=bundle.request))

        return bundle

    def override_urls(self):
        return [
            url(r'^(?P<resource_name>%s)/featured%s$' %
                (self._meta.resource_name, trailing_slash()),
                self.wrap_view('with_featured'), name='api_with_featured'),
        ]

    def with_featured(self, request, **kwargs):
        return WithFeaturedResource().dispatch('list', request, **kwargs)


class WithFeaturedResource(SearchResource):

    class Meta(SearchResource.Meta):
        authorization = ReadOnlyAuthorization()
        authentication = OptionalOAuthAuthentication()
        detail_allowed_methods = []
        fields = SearchResource.Meta.fields + ['id', 'cat']
        list_allowed_methods = ['get']
        resource_name = 'search/featured'
        slug_lookup = None

    def create_response(self, *args, **kwargs):
        response = super(WithFeaturedResource, self).create_response(
            *args, **kwargs)
        filter_fallbacks = getattr(self, 'filter_fallbacks', {})
        for name, value in filter_fallbacks.items():
            response['API-Fallback-%s' % name] = ','.join(value)
        return response

    def collections(self, request, collection_type=None, limit=1):
        filters = request.GET.dict()
        filters.setdefault('region', self.get_region(request).slug)
        if collection_type is not None:
            qs = Collection.public.filter(collection_type=collection_type)
        else:
            qs = Collection.public.all()
        qs = CollectionFilterSetWithFallback(filters, queryset=qs).qs
        serializer = CollectionSerializer(qs[:limit],
                                          context={'request': request,
                                                   'search_resource': self})
        return serializer.data, getattr(qs, 'filter_fallback', None)

    def alter_list_data_to_serialize(self, request, data):
        types = (
            ('collections', COLLECTIONS_TYPE_BASIC),
            ('featured', COLLECTIONS_TYPE_FEATURED),
            ('operator', COLLECTIONS_TYPE_OPERATOR),
        )
        self.filter_fallbacks = {}
        for name, col_type in types:
            data[name], fallback = self.collections(request,
                collection_type=col_type)
            if fallback:
                self.filter_fallbacks[name] = fallback

        # Alter the _view_name so that statsd logs seperately from search.
        request._view_name = 'featured'

        return data


class SuggestionsResource(SearchResource):

    class Meta(SearchResource.Meta):
        authorization = ReadOnlyAuthorization()
        fields = ['name', 'manifest_url']
        resource_name = 'suggest'
        limit = 10
        serializer = SuggestionsSerializer(['suggestions+json'])

    def determine_format(self, request):
        return 'application/x-suggestions+json'

    def get_search_data(self, request):
        data = super(SuggestionsResource, self).get_search_data(request)
        self.query = data.get('q', '')
        return data

    def alter_list_data_to_serialize(self, request, data):
        return data

    def paginate_results(self, request, qs):
        return self.rehydrate_results(request, qs[:self._meta.limit])

    def rehydrate_results(self, request, qs):
        names = []
        descriptions = []
        urls = []
        icons = []
        for obj in qs:
            # Tastypie expects obj.pk to be present, so set it manually.
            obj.pk = obj.id
            data = self.full_dehydrate(self.build_bundle(obj=obj,
                                                         request=request))
            names.append(data['name'])
            descriptions.append(data['description'])
            urls.append(data['absolute_url'])
            icons.append(data['icon'])
        return [self.query, names, descriptions, urls, icons]

    def dehydrate(self, bundle):
        data = super(SuggestionsResource, self).dehydrate(bundle).data
        return {
            'description': truncate(data['description']),
            'name': data['name'],
            'absolute_url': data['absolute_url'],
            'icon': data['icons'][64],
        }
