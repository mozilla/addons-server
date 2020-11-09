from django.db.transaction import non_atomic_requests

from django_statsd.clients import statsd
from elasticsearch_dsl import Q, query
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException
from rest_framework.response import Response

import olympia.core.logger
from olympia.addons.views import AddonSearchView
from olympia.api.pagination import ESPageNumberPagination
from olympia.constants.promoted import PROMOTED_GROUPS
from olympia.search.filters import ReviewedContentFilter

from .models import Shelf
from .serializers import ESSponsoredAddonSerializer, ShelfSerializer
from .utils import (
    get_addons_from_adzerk,
    get_signed_impression_blob_from_results,
    filter_adzerk_results_to_es_results_qs,
    send_event_ping,
    send_impression_pings)


log = olympia.core.logger.getLogger('z.shelves')

VALID_EVENT_TYPES = ('click', 'conversion')


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
        # reorder results to match adzerk order
        order = list(self.adzerk_results.keys())
        response.data['results'] = sorted(
            response.data.get('results', ()),
            key=lambda result: order.index(str(result.get('id'))))
        return response

    def filter_queryset(self, qs):
        qs = super().filter_queryset(qs)
        count = self.paginator.get_page_size(self.request)
        self.adzerk_results = get_addons_from_adzerk(count)
        ids = list(self.adzerk_results.keys())
        group_ids_to_allow = [
            group.id for group in PROMOTED_GROUPS
            if group.can_be_selected_by_adzerk]
        results_qs = qs.query(query.Bool(must=[
            Q('terms', id=ids),
            Q('terms', **{'promoted.group_id': group_ids_to_allow})]))
        results_qs.execute()  # To cache the results.
        extras = filter_adzerk_results_to_es_results_qs(
            self.adzerk_results, results_qs)
        if extras:
            group_names = '; '.join(
                str(group.name) for group in PROMOTED_GROUPS
                if group.can_be_selected_by_adzerk)
            for id_ in extras:
                log.error(
                    'Addon id [%s] returned from Adzerk, but not in a valid '
                    'Promoted group [%s]', id_, group_names)
            statsd.incr('services.adzerk.elasticsearch_miss', len(extras))
        return results_qs

    @action(detail=False, methods=['post'])
    def impression(self, request):
        signed_impressions = request.data.get('impression_data', '')
        try:
            send_impression_pings(signed_impressions)
        except APIException as e:
            return Response(
                f'Bad impression_data: {e}',
                status=status.HTTP_400_BAD_REQUEST)
        return Response(status=status.HTTP_202_ACCEPTED)

    @action(detail=False, methods=['post'])
    def click(self, request):
        signed_click = request.data.get('click_data', '')
        try:
            send_event_ping(signed_click, 'click')
        except APIException as e:
            return Response(
                f'Bad click_data: {e}',
                status=status.HTTP_400_BAD_REQUEST)
        return Response(status=status.HTTP_202_ACCEPTED)

    @action(detail=False, methods=['post'])
    def event(self, request):
        signed_data = request.data.get('data', '')
        data_type = request.data.get('type')
        if data_type not in VALID_EVENT_TYPES:
            return Response(
                f'Bad type: {data_type}',
                status=status.HTTP_400_BAD_REQUEST)
        try:
            send_event_ping(signed_data, data_type)
        except APIException as e:
            return Response(
                f'Bad data for {data_type}: {e}',
                status=status.HTTP_400_BAD_REQUEST)
        return Response(status=status.HTTP_202_ACCEPTED)
