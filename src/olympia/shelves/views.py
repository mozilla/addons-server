from django.db.transaction import non_atomic_requests

from elasticsearch_dsl import Q, query
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from olympia.addons.views import AddonSearchView
from olympia.api.pagination import ESPageNumberPagination
from olympia.constants.promoted import VERIFIED_ONE
from olympia.search.filters import ReviewedContentFilter

from .models import Shelf
from .serializers import ESSponsoredAddonSerializer, ShelfSerializer
from .utils import get_addons_from_adzerk


class ShelfViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    queryset = Shelf.objects.filter(
        shelfmanagement__enabled=True).order_by('shelfmanagement__position')
    permission_classes = []
    serializer_class = ShelfSerializer


class SponsoredShelfPagination(ESPageNumberPagination):
    page_size = 6


class SponsoredShelfViewSet(viewsets.ViewSetMixin, AddonSearchView):
    filter_backends = [ReviewedContentFilter]
    pagination_class = SponsoredShelfPagination
    serializer_class = ESSponsoredAddonSerializer

    @classmethod
    def as_view(cls, actions, **initkwargs):
        return non_atomic_requests(super().as_view(actions, **initkwargs))

    def get_impression_data(self):
        return None

    def get_paginated_response(self, data):
        response = super().get_paginated_response(data)
        response.data['impression_url'] = self.reverse_action('impression')
        response.data['impression_data'] = self.get_impression_data()
        return response

    def filter_queryset(self, qs):
        qs = super().filter_queryset(qs)
        count = self.paginator.get_page_size(self.request)
        results = get_addons_from_adzerk(count)
        ids = list(results.keys())
        results_qs = qs.query(query.Bool(must=[
            Q('terms', id=ids),
            Q('term', **{'promoted.group_id': VERIFIED_ONE.id})]))
        return results_qs

    @action(detail=False, methods=['post'])
    def impression(self, request):
        return Response()

    @action(detail=False, methods=['post'])
    def click(self, request):
        return Response()
