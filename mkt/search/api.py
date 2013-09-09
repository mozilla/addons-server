from django.conf.urls import url

import waffle
from tastypie.authorization import ReadOnlyAuthorization
from tastypie.throttle import BaseThrottle
from tastypie.utils import trailing_slash

from translations.helpers import truncate

import mkt
from mkt.api.authentication import (SharedSecretAuthentication,
                                    OptionalOAuthAuthentication)
from mkt.api.base import CORSResource, MarketplaceResource
from mkt.api.resources import AppResource
from mkt.api.serializers import SuggestionsSerializer
from mkt.collections.constants import (COLLECTIONS_TYPE_BASIC,
                                       COLLECTIONS_TYPE_FEATURED,
                                       COLLECTIONS_TYPE_OPERATOR)
from mkt.collections.filters import (CollectionFilterSet,
                                     CollectionFilterSetWithFallback)
from mkt.collections.models import Collection
from mkt.collections.serializers import CollectionSerializer
from mkt.constants.features import FeatureProfile
from mkt.search.views import _filter_search
from mkt.search.forms import ApiSearchForm
from mkt.webapps.models import Webapp
from mkt.webapps.utils import es_app_to_dict


class SearchResource(CORSResource, MarketplaceResource):

    class Meta(AppResource.Meta):
        resource_name = 'search'
        allowed_methods = []
        detail_allowed_methods = []
        list_allowed_methods = ['get']
        authorization = ReadOnlyAuthorization()
        authentication = (SharedSecretAuthentication(),
                          OptionalOAuthAuthentication())
        slug_lookup = None
        # Override CacheThrottle with a no-op.
        throttle = BaseThrottle()

    def get_resource_uri(self, bundle):
        # Link to the AppResource URI.
        return AppResource().get_resource_uri(bundle.obj)

    def get_search_data(self, request):
        form = ApiSearchForm(request.GET if request else None)
        if not form.is_valid():
            raise self.form_errors(form)
        return form.cleaned_data

    def get_feature_profile(self, request):
        profile = None
        if request.GET.get('dev') in ('firefoxos', 'android'):
            sig = request.GET.get('pro')
            if sig:
                profile = FeatureProfile.from_signature(sig)
        return profile

    def get_region(self, request):
        return getattr(request, 'REGION', mkt.regions.WORLDWIDE)

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

    def collections(self, request, collection_type=None, limit=1):
        filters = request.GET.dict()
        filters.setdefault('region', self.get_region(request).slug)
        if collection_type is not None:
            qs = Collection.public.filter(collection_type=collection_type)
        else:
            qs = Collection.public.all()
        if collection_type == COLLECTIONS_TYPE_FEATURED:
            filterset_class = CollectionFilterSet
        else:
            filterset_class = CollectionFilterSetWithFallback
        qs = filterset_class(filters, queryset=qs)
        serializer = CollectionSerializer(qs[:limit],
                                          context={'request': request})
        return serializer.data

    def alter_list_data_to_serialize(self, request, data):

        if waffle.switch_is_active('rocketfuel'):
            types = (
                ('collections', COLLECTIONS_TYPE_BASIC),
                ('featured', COLLECTIONS_TYPE_FEATURED),
                ('operator', COLLECTIONS_TYPE_OPERATOR),
            )
            for name, col_type in types:
                data[name] = self.collections(request,
                    collection_type=col_type)
        else:
            form_data = self.get_search_data(request)
            region = getattr(request, 'REGION', mkt.regions.WORLDWIDE)
            cat_slug = form_data.get('cat')
            if cat_slug:
                cat_slug = [cat_slug]

            # Filter by device feature profile.
            profile = self.get_feature_profile(request)

            qs = Webapp.featured(cat=cat_slug, region=region, profile=profile)

            bundles = (self.build_bundle(obj=obj, request=request) for obj in
                       qs)
            data['featured'] = [AppResource().full_dehydrate(bundle)
                                for bundle in bundles]

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
