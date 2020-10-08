from django.db.transaction import non_atomic_requests

from elasticsearch_dsl import Q, query
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException
from rest_framework.response import Response

from olympia.addons.views import AddonSearchView
from olympia.api.pagination import ESPageNumberPagination
from olympia.constants.promoted import VERIFIED_ONE
from olympia.search.filters import ReviewedContentFilter

from .models import Shelf
from .serializers import ESSponsoredAddonSerializer, ShelfSerializer
from .utils import (
    get_addons_from_adzerk,
    get_impression_data_from_signed_blob,
    get_signed_impression_blob_from_results,
    filter_adzerk_results_to_es_results_qs,
    send_impression_pings)


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

    def get_paginated_response(self, data):
        response = super().get_paginated_response(data)
        response.data['impression_url'] = self.reverse_action('impression')
        response.data['impression_data'] = (
            get_signed_impression_blob_from_results(self.adzerk_results))
        return response

    def filter_queryset(self, qs):
        qs = super().filter_queryset(qs)
        count = self.paginator.get_page_size(self.request)
        self.adzerk_results = get_addons_from_adzerk(count)
        ids = list(self.adzerk_results.keys())
        results_qs = qs.query(query.Bool(must=[
            Q('terms', id=ids),
            Q('term', **{'promoted.group_id': VERIFIED_ONE.id})]))
        results_qs.execute()  # To cache the results.
        filter_adzerk_results_to_es_results_qs(
            self.adzerk_results, results_qs)
        return results_qs

    @action(detail=False, methods=['post'])
    def impression(self, request):
        signed_impressions = request.data.get('impression_data', '')
        try:
            send_impression_pings(
                get_impression_data_from_signed_blob(signed_impressions))
        except APIException as e:
            return Response(
                f'Bad impression_data: {e}',
                status=status.HTTP_400_BAD_REQUEST)
        return Response(status=status.HTTP_202_ACCEPTED)

    @action(detail=False, methods=['post'])
    def click(self, request):
        return Response()
