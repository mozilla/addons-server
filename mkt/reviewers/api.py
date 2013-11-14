from rest_framework.generics import ListAPIView

from mkt.api.authentication import (RestOAuthAuthentication,
                                    RestSharedSecretAuthentication)
from mkt.api.authorization import GroupPermission, PermissionAuthorization
from mkt.reviewers.forms import ApiReviewersSearchForm
from mkt.reviewers.serializers import ReviewingSerializer
from mkt.reviewers.utils import AppsReviewing
from mkt.search.api import SearchResource
from mkt.search.utils import S
from mkt.webapps.models import WebappIndexer


class ReviewingView(ListAPIView):
    authentication_classes = [RestOAuthAuthentication,
                              RestSharedSecretAuthentication]
    permission_classes = [GroupPermission('Apps', 'Review')]
    serializer_class = ReviewingSerializer

    def get_queryset(self):
        return [row['app'] for row in AppsReviewing(self.request).get_apps()]


class ReviewersSearchResource(SearchResource):

    class Meta(SearchResource.Meta):
        resource_name = 'search'
        authorization = PermissionAuthorization('Apps', 'Review')
        fields = ['device_types', 'id', 'is_escalated', 'is_packaged',
                  'latest_version', 'name', 'premium_type', 'price', 'slug',
                  'status']

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
        for k in ('has_info_request', 'has_editor_comment'):
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
        if form_data.get('status') != 'any':
            base_filters['status'] = form_data.get('status')
        return S(WebappIndexer).filter(**base_filters)

    def dehydrate(self, bundle):
        bundle = super(ReviewersSearchResource, self).dehydrate(bundle)

        # Add reviewer-specific stuff that's not in the standard dehydrate.
        bundle.data['latest_version'] = bundle.obj.latest_version
        bundle.data['is_escalated'] = bundle.obj.is_escalated

        # Throw away anything not in _meta.fields.
        filtered_data = {}
        for k in self._meta.fields:
            filtered_data[k] = bundle.data[k]
        bundle.data = filtered_data

        return bundle
