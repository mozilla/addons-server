from rest_framework.exceptions import ParseError
from rest_framework.generics import CreateAPIView, ListAPIView
from rest_framework.response import Response

from mkt.api.authentication import (RestOAuthAuthentication,
                                    RestSharedSecretAuthentication)
from mkt.api.authorization import GroupPermission
from mkt.api.base import SlugOrIdMixin
from mkt.regions.utils import parse_region
from mkt.reviewers.forms import ApiReviewersSearchForm, ApproveRegionForm
from mkt.reviewers.serializers import ReviewingSerializer
from mkt.reviewers.utils import AppsReviewing
from mkt.search.api import SearchResultSerializer, SearchView
from mkt.search.utils import S
from mkt.webapps.models import Webapp, WebappIndexer


class ReviewingView(ListAPIView):
    authentication_classes = [RestOAuthAuthentication,
                              RestSharedSecretAuthentication]
    permission_classes = [GroupPermission('Apps', 'Review')]
    serializer_class = ReviewingSerializer

    def get_queryset(self):
        return [row['app'] for row in AppsReviewing(self.request).get_apps()]

SEARCH_FIELDS = [u'device_types', u'id', u'is_escalated', u'is_packaged',
                 u'latest_version', u'name', u'premium_type', u'price', u'slug',
                 u'status']


class ReviewersSearchView(SearchView):
    cors_allowed_methods = ['get']
    authentication_classes = [RestSharedSecretAuthentication,
                              RestOAuthAuthentication]
    permission_classes = [GroupPermission('Apps', 'Review')]

    def get(self, request, *args, **kwargs):
        form_data = self.get_search_data(request, ApiReviewersSearchForm)
        base_filters = {'type': form_data['type']}
        if form_data.get('status') != 'any':
            base_filters['status'] = form_data.get('status')
        qs = S(WebappIndexer).filter(**base_filters)
        qs = self.apply_filters(request, qs, data=form_data)
        qs = apply_reviewer_filters(request, qs, data=form_data)
        page = self.paginate_queryset(qs)
        return Response(self.get_pagination_serializer(page).data)

    def serialize(self, request, app):
        full_data = SearchView.serialize(self, request, app)
        data = {}
        for k in SEARCH_FIELDS:
            data[k] = full_data.get(k)
        # Add reviewer-specific stuff that's not in the standard dehydrate.
        data['latest_version'] = app.latest_version
        data['is_escalated'] = app.is_escalated
        return data

def apply_reviewer_filters(request, qs, data=None):
    for k in ('has_info_request', 'has_editor_comment'):
        if data.get(k, None) is not None:
            qs = qs.filter(**{
                'latest_version.%s' % k: data[k]
            })
    if data.get('is_escalated', None) is not None:
        qs = qs.filter(is_escalated=data['is_escalated'])
    return qs


class ApproveRegion(SlugOrIdMixin, CreateAPIView):
    """
    TODO: Document this API.
    """
    authentication_classes = (RestOAuthAuthentication,
                              RestSharedSecretAuthentication)
    model = Webapp
    slug_field = 'app_slug'

    def get_permissions(self):
        region = parse_region(self.request.parser_context['kwargs']['region'])
        region_slug = region.slug.upper()
        return (GroupPermission('Apps', 'ReviewRegion%s' % region_slug),)

    def get_queryset(self):
        region = parse_region(self.request.parser_context['kwargs']['region'])
        return self.model.objects.pending_in_region(region)

    def post(self, request, pk, region, *args, **kwargs):
        app = self.get_object()
        region = parse_region(region)

        form = ApproveRegionForm(request.DATA, app=app, region=region)
        if not form.is_valid():
            raise ParseError(dict(form.errors.items()))
        form.save()

        return Response({'approved': bool(form.cleaned_data['approve'])})
