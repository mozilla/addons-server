import json

from django.conf.urls import url
from django.core.exceptions import ObjectDoesNotExist

import waffle
from tastypie import http
from tastypie.authorization import ReadOnlyAuthorization
from tastypie.throttle import BaseThrottle
from tastypie.utils import trailing_slash
from tower import ugettext as _

import amo
from access import acl
from addons.models import Category
from amo.helpers import absolutify
from editors.models import EscalationQueue
from versions.models import Version

import mkt
from mkt.api.authentication import OptionalOAuthAuthentication
from mkt.api.base import CORSResource, MarketplaceResource
from mkt.api.resources import AppResource
from mkt.constants.features import FeatureProfile
from mkt.search.views import _filter_search, _get_query
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
        authentication = OptionalOAuthAuthentication()
        slug_lookup = None
        # Override CacheThrottle with a no-op.
        throttle = BaseThrottle()

    def get_resource_uri(self, bundle):
        # Link to the AppResource URI.
        return AppResource().get_resource_uri(bundle.obj)

    def search_form(self, request):
        form = ApiSearchForm(request.GET if request else None)
        if not form.is_valid():
            raise self.form_errors(form)
        return form.cleaned_data

    def get_list(self, request=None, **kwargs):
        form_data = self.search_form(request)
        is_admin = acl.action_allowed(request, 'Admin', '%')
        is_reviewer = acl.action_allowed(request, 'Apps', 'Review')

        uses_es = waffle.switch_is_active('search-api-es')

        # Pluck out status and addon type first since it forms part of the base
        # query, but only for privileged users.
        status = form_data['status']
        addon_type = form_data['type']

        base_filters = {
            'type': addon_type,
        }

        # Allow reviewers and admins to search by statuses other than PUBLIC.
        if status and (status == 'any' or status != amo.STATUS_PUBLIC):
            if is_admin or is_reviewer:
                base_filters['status'] = status
            else:
                return http.HttpUnauthorized(
                    content=json.dumps(
                        {'reason': _('Unauthorized to filter by status.')}))

        # Filter by device feature profile.
        profile = None
        # TODO: Remove uses_es conditional with 'search-api-es' waffle.
        if uses_es and request.GET.get('dev') in ('firefoxos', 'android'):
            sig = request.GET.get('pro')
            if sig:
                profile = FeatureProfile.from_signature(sig)

        # Filter by region.
        region = getattr(request, 'REGION', mkt.regions.WORLDWIDE)

        qs = _get_query(request, region, gaia=request.GAIA,
                        mobile=request.MOBILE, tablet=request.TABLET,
                        filters=base_filters, new_idx=True)
        qs = _filter_search(request, qs, form_data, region=region,
                            profile=profile)
        paginator = self._meta.paginator_class(request.GET, qs,
            resource_uri=self.get_resource_list_uri(),
            limit=self._meta.limit)
        page = paginator.page()

        # Rehydrate the results as per tastypie.
        objs = []
        for obj in page['objects']:
            obj.pk = obj.id
            objs.append(self.build_bundle(obj=obj, request=request))

        page['objects'] = [self.full_dehydrate(bundle) for bundle in objs]

        # This isn't as quite a full as a full TastyPie meta object,
        # but at least it's namespaced that way and ready to expand.
        to_be_serialized = self.alter_list_data_to_serialize(request, page)
        return self.create_response(request, to_be_serialized)

    def dehydrate(self, bundle):
        obj = bundle.obj
        amo_user = getattr(bundle.request, 'amo_user', None)

        uses_es = waffle.switch_is_active('search-api-es')

        if uses_es:
            bundle.data.update(es_app_to_dict(
                obj, region=bundle.request.REGION.id,
                profile=amo_user))
        else:
            bundle = AppResource().dehydrate(bundle)
            bundle.data['absolute_url'] = absolutify(
                bundle.obj.get_detail_url())

        # Add extra data for reviewers. Used in reviewer tool search.
        # TODO: Reviewer flags in ES (bug 848446)
        if acl.action_allowed(bundle.request, 'Apps', 'Review'):
            addon_id = bundle.obj._id if uses_es else bundle.obj.id
            version = Version.objects.filter(addon_id=addon_id).latest()
            escalated = EscalationQueue.objects.filter(
                addon_id=addon_id).exists()

            if uses_es:
                bundle.data['latest_version_status'] = (
                    obj.latest_version_status)
            else:
                try:
                    file_ = version and version.files.latest()
                    bundle.data['latest_version_status'] = (
                        file_.status if file_ else None)
                except ObjectDoesNotExist:
                    bundle.data['latest_version_status'] = None

            bundle.data['reviewer_flags'] = {
                'has_comment': version.has_editor_comment,
                'has_info_request': version.has_info_request,
                'is_escalated': escalated,
            }

        return bundle

    def override_urls(self):
        return [
            url(r'^(?P<resource_name>%s)/featured%s$' %
                (self._meta.resource_name, trailing_slash()),
                self.wrap_view('with_featured'), name='api_with_featured')
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

    def alter_list_data_to_serialize(self, request, data):
        form_data = self.search_form(request)
        region = getattr(request, 'REGION', mkt.regions.WORLDWIDE)
        if form_data['cat']:
            category = Category.objects.get(pk=form_data['cat'])
        else:
            category = None

        # Filter by device feature profile.
        profile = None
        if request.GET.get('dev') in ('firefoxos', 'android'):
            sig = request.GET.get('pro')
            if sig:
                profile = FeatureProfile.from_signature(sig)

        qs = Webapp.featured(cat=category, region=region, profile=profile)

        bundles = [self.build_bundle(obj=obj, request=request) for obj in qs]
        data['featured'] = [AppResource().full_dehydrate(bundle)
                            for bundle in bundles]
        return data
