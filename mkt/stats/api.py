from functools import partial

from django import http

import commonware
import waffle
from rest_framework.exceptions import ParseError
from rest_framework.response import Response
from rest_framework.views import APIView

from lib.metrics import get_monolith_client

from mkt.api.authentication import (RestOAuthAuthentication,
                                    RestSharedSecretAuthentication)
from mkt.api.authorization import PermissionAuthorization
from mkt.api.base import CORSMixin
from mkt.api.exceptions import NotImplemented

from .forms import GlobalStatsForm


log = commonware.log.getLogger('z.stats')


# Map of URL metric name to monolith metric name. Future home of where we can
# put other properties (e.g. auth rules) about the stats.
STATS = {
    'total_visits': {'metric': 'visits'},
    'total_developers': {'metric': 'total_dev_count'},
}


class GlobalStats(CORSMixin, APIView):
    authentication_classes = (RestOAuthAuthentication,
                              RestSharedSecretAuthentication)
    cors_allowed_methods = ['get']
    permission_classes = (partial(PermissionAuthorization, 'Stats', 'View'),)

    def get(self, request, metric):
        if metric not in STATS:
            raise http.Http404('No metric by that name.')

        if not waffle.switch_is_active('stats-api'):
            raise NotImplemented('Stats not enabled for this host.')

        # Perform form validation.
        form = GlobalStatsForm(request.GET)
        if not form.is_valid():
            raise ParseError(dict(form.errors.items()))

        data = form.cleaned_data
        client = get_monolith_client()

        try:
            metric_data = list(client(STATS[metric]['metric'],
                                      data.get('start'), data.get('end'),
                                      data.get('interval')))
        except ValueError:
            # This occurs if monolith doesn't have our metric and we get an
            # elasticsearch SearchPhaseExecutionException error.
            log.info('Monolith ValueError for metric {0}'.format(
                STATS[metric]['metric']))
            raise ParseError('Invalid metric at this time. Try again later.')

        return Response({'objects': metric_data})
