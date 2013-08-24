from functools import partial

from django import http

import commonware
import waffle
from rest_framework.exceptions import ParseError
from rest_framework.response import Response
from rest_framework.views import APIView

from lib.metrics import get_monolith_client

from constants.base import ADDON_PREMIUM_API, ADDON_WEBAPP_TYPES

from mkt.api.authentication import (RestOAuthAuthentication,
                                    RestSharedSecretAuthentication)
from mkt.api.authorization import PermissionAuthorization
from mkt.api.base import CORSMixin
from mkt.api.exceptions import NotImplemented

from .forms import GlobalStatsForm


log = commonware.log.getLogger('z.stats')


# Map of URL metric name to monolith metric name.
#
# The 'dimensions' key is optional query string arguments with defaults that is
# passed to the monolith client and used in the facet filters.
#
# The 'lines' key is optional and used for multi-line charts. The format is:
#     {'<name>': {'<dimension-key>': '<dimension-value>'}}
# where <name> is what's returned in the JSON output and the dimension
# key/value is what's sent to Monolith similar to the 'dimensions' above.
lines = lambda name, vals: dict((val, {name: val}) for val in vals)
STATS = {
    'apps_added_by_package': {
        'metric': 'apps_added_package_count',
        'dimensions': {'region': 'us'},
        'lines': lines('package_type', ADDON_WEBAPP_TYPES.values()),
    },
    'apps_added_by_premium': {
        'metric': 'apps_added_premium_count',
        'dimensions': {'region': 'us'},
        'lines': lines('premium_type', ADDON_PREMIUM_API.values()),
    },
    'total_developers': {
        'metric': 'total_dev_count'
    },
    'total_visits': {
        'metric': 'visits'
    },
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

        stat = STATS[metric]

        # Perform form validation.
        form = GlobalStatsForm(request.GET)
        if not form.is_valid():
            raise ParseError(dict(form.errors.items()))

        qs = form.cleaned_data
        client = get_monolith_client()

        dimensions = {}
        if 'dimensions' in stat:
            for key, default in stat['dimensions'].items():
                dimensions[key] = request.GET.get(key, default)

        # If stat has a 'lines' attribute, it's a multi-line graph. Do a
        # request for each item in 'lines' and compose them in a single
        # response.
        try:
            data = {}
            if 'lines' in stat:
                for line_name, line_dimension in stat['lines'].items():
                    dimensions.update(line_dimension)
                    data[line_name] = list(
                        client(stat['metric'], qs.get('start'), qs.get('end'),
                               qs.get('interval'), **dimensions))

            else:
                data['objects'] = list(
                    client(stat['metric'], qs.get('start'), qs.get('end'),
                           qs.get('interval'), **dimensions))

        except ValueError as e:
            # This occurs if monolith doesn't have our metric and we get an
            # elasticsearch SearchPhaseExecutionException error.
            log.info('Monolith ValueError for metric {0}: {1}'.format(
                stat['metric'], e))
            raise ParseError('Invalid metric at this time. Try again later.')

        return Response(data)
