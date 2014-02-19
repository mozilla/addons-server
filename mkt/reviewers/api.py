import commonware.log
from cache_nuggets.lib import Token
from rest_framework import serializers
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
from mkt.search.api import SearchView
from mkt.search.serializers import ESAppSerializer
from mkt.search.utils import S
from mkt.webapps.models import Webapp, WebappIndexer


log = commonware.log.getLogger('z.reviewers')


class ReviewingView(ListAPIView):
    authentication_classes = [RestOAuthAuthentication,
                              RestSharedSecretAuthentication]
    permission_classes = [GroupPermission('Apps', 'Review')]
    serializer_class = ReviewingSerializer

    def get_queryset(self):
        return [row['app'] for row in AppsReviewing(self.request).get_apps()]


SEARCH_FIELDS = [u'device_types', u'id', u'is_escalated', u'is_packaged',
                 u'name', u'premium_type', u'price', u'slug', u'status']


class ReviewersESAppSerializer(ESAppSerializer):
    latest_version = serializers.Field(source='es_data.latest_version')
    is_escalated = serializers.BooleanField()

    class Meta(ESAppSerializer.Meta):
        fields = SEARCH_FIELDS + ['latest_version', 'is_escalated']


class ReviewersSearchView(SearchView):
    cors_allowed_methods = ['get']
    authentication_classes = [RestSharedSecretAuthentication,
                              RestOAuthAuthentication]
    permission_classes = [GroupPermission('Apps', 'Review')]
    form_class = ApiReviewersSearchForm
    serializer_class = ReviewersESAppSerializer

    def search(self, request):
        form_data = self.get_search_data(request)
        query = form_data.get('q', '')
        base_filters = {'type': form_data['type']}
        if form_data.get('status') != 'any':
            base_filters['status'] = form_data.get('status')
        qs = S(WebappIndexer).filter(**base_filters)
        qs = self.apply_filters(request, qs, data=form_data)
        qs = apply_reviewer_filters(request, qs, data=form_data)
        page = self.paginate_queryset(qs)
        return self.get_pagination_serializer(page), query


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


class GenerateToken(SlugOrIdMixin, CreateAPIView):
    """
    This generates a short-lived token to be used by the APK factory service
    for authentication of requests to the reviewer mini-manifest and package.

    """
    authentication_classes = (RestOAuthAuthentication,
                              RestSharedSecretAuthentication)
    permission_classes = [GroupPermission('Apps', 'Review')]
    model = Webapp
    slug_field = 'app_slug'

    def post(self, request, pk, *args, **kwargs):
        app = self.get_object()
        token = Token(data={'app_id': app.id})
        token.save()

        log.info('Generated token on app:%s for user:%s' % (
            app.id, request.amo_user.id))

        return Response({'token': token.token})
