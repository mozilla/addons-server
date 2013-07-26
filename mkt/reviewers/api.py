import json

from tastypie import http
from tower import ugettext as _

import amo
from access import acl
from amo.urlresolvers import reverse

from mkt.api.authentication import OAuthAuthentication
from mkt.api.authorization import PermissionAuthorization
from mkt.api.base import MarketplaceResource, http_error
from mkt.reviewers.utils import AppsReviewing
from mkt.reviewers.forms import ApiReviewersSearchForm
from mkt.search.api import SearchResource
from mkt.search.views import _get_query
from mkt.webapps.utils import update_with_reviewer_data


class Wrapper(object):
    def __init__(self, pk):
        self.pk = pk


class ReviewingResource(MarketplaceResource):

    class Meta(MarketplaceResource.Meta):
        authentication = OAuthAuthentication()
        authorization = PermissionAuthorization('Apps', 'Review')
        list_allowed_methods = ['get']
        resource_name = 'reviewing'

    def get_resource_uri(self, bundle):
        return reverse('api_dispatch_detail',
                       kwargs={'api_name': 'apps', 'resource_name': 'app',
                               'pk': bundle.obj.pk})

    def obj_get_list(self, request, **kwargs):
        return [Wrapper(r['app'].pk)
                for r in AppsReviewing(request).get_apps()]


class ReviewersSearchResource(SearchResource):

    class Meta(SearchResource.Meta):
        resource_name = 'search'
        authorization = PermissionAuthorization('Apps', 'Review')
        fields = ['device_types', 'id', 'is_packaged', 'latest_version',
                  'name', 'premium_type', 'price', 'slug', 'status']

    def get_search_data(self, request):
        form = ApiReviewersSearchForm(request.GET if request else None)
        if not form.is_valid():
            raise self.form_errors(form)
        return form.cleaned_data

    def get_feature_profile(self, request):
        # We don't want automatic feature profile filtering in the reviewers
        # API.
        return None

    def get_region(self, request):
        # We don't want automatic region filtering in the reviewers API.
        return None

    def apply_filters(self, request, qs, data=None):
        qs = super(ReviewersSearchResource, self).apply_filters(request, qs,
                                                                data=data)
        for k in ('is_privileged', 'has_info_request', 'has_editor_comment'):
            if data.get(k, None) is not None:
                qs = qs.filter(**{
                    'latest_version.%s' % k: data[k]
                })
        if data.get('is_escalated', None) is not None:
            qs = qs.filter(is_escalated=data['is_escalated'])
        return qs

    def get_query(self, request, base_filters=None):
        form_data = self.get_search_data(request)

        if base_filters is None:
            base_filters = {}
        base_filters['status'] = form_data.get('status')

        region = self.get_region(request)
        return _get_query(request, region, gaia=None, mobile=None, tablet=None,
                          new_idx=True, filters=base_filters)

    def dehydrate(self, bundle):
        bundle = super(ReviewersSearchResource, self).dehydrate(bundle)
        bundle = update_with_reviewer_data(bundle, using_es=True)
        # Filter out anything not present in Meta fields.
        bundle.data = dict(((k, v) for k, v in bundle.data.items()
            if k in self._meta.fields))
        return bundle
