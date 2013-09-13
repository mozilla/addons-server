from functools import partial

from django import http

import commonware
import waffle
from rest_framework.exceptions import ParseError
from rest_framework.generics import ListAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from lib.metrics import get_monolith_client

from constants.base import ADDON_PREMIUM_API, ADDON_WEBAPP_TYPES

from mkt.api.authentication import (RestOAuthAuthentication,
                                    RestSharedSecretAuthentication)
from mkt.api.authorization import AllowAppOwner, PermissionAuthorization
from mkt.api.base import CORSMixin, SlugOrIdMixin
from mkt.api.exceptions import NotImplemented
from mkt.webapps.models import Webapp

from .forms import StatsForm


log = commonware.log.getLogger('z.stats')


# Map of URL metric name to monolith metric name.
#
# The 'dimensions' key is optional query string arguments with defaults that is
# passed to the monolith client and used in the facet filters. If the default
# is `None`, the dimension is excluded unless specified via the API.
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
    'apps_available_by_package': {
        'metric': 'apps_available_package_count',
        'dimensions': {'region': 'us'},
        'lines': lines('package_type', ADDON_WEBAPP_TYPES.values()),
    },
    'apps_available_by_premium': {
        'metric': 'apps_available_premium_count',
        'dimensions': {'region': 'us'},
        'lines': lines('premium_type', ADDON_PREMIUM_API.values()),
    },
    'apps_installed': {
        'metric': 'app_installs',
        'dimensions': {'region': None},
    },
    'total_developers': {
        'metric': 'total_dev_count'
    },
    'total_visits': {
        'metric': 'visits'
    },
}
APP_STATS = {
    'installs': {
        'metric': 'app_installs',
        'dimensions': {'region': None},
    }
}


def _get_monolith_data(stat, start, end, interval, dimensions):
    # If stat has a 'lines' attribute, it's a multi-line graph. Do a
    # request for each item in 'lines' and compose them in a single
    # response.
    client = get_monolith_client()
    try:
        data = {}
        if 'lines' in stat:
            for line_name, line_dimension in stat['lines'].items():
                dimensions.update(line_dimension)
                data[line_name] = list(client(stat['metric'], start, end,
                                              interval, **dimensions))

        else:
            data['objects'] = list(client(stat['metric'], start, end, interval,
                                          **dimensions))

    except ValueError as e:
        # This occurs if monolith doesn't have our metric and we get an
        # elasticsearch SearchPhaseExecutionException error.
        log.info('Monolith ValueError for metric {0}: {1}'.format(
            stat['metric'], e))
        raise ParseError('Invalid metric at this time. Try again later.')

    return data


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
        form = StatsForm(request.GET)
        if not form.is_valid():
            raise ParseError(dict(form.errors.items()))

        qs = form.cleaned_data

        dimensions = {}
        if 'dimensions' in stat:
            for key, default in stat['dimensions'].items():
                val = request.GET.get(key, default)
                if val is not None:
                    # Avoid passing kwargs to the monolith client when the
                    # dimension is None to avoid facet filters being applied.
                    dimensions[key] = request.GET.get(key, default)

        return Response(_get_monolith_data(stat, qs.get('start'),
                                           qs.get('end'), qs.get('interval'),
                                           dimensions))


class AppStats(CORSMixin, SlugOrIdMixin, ListAPIView):
    authentication_classes = (RestOAuthAuthentication,
                              RestSharedSecretAuthentication)
    cors_allowed_methods = ['get']
    permission_classes = (AllowAppOwner,)
    queryset = Webapp.objects.all()
    slug_field = 'app_slug'

    def get(self, request, pk, metric):
        if metric not in APP_STATS:
            raise http.Http404('No metric by that name.')

        if not waffle.switch_is_active('stats-api'):
            raise NotImplemented('Stats not enabled for this host.')

        app = self.get_object()

        stat = APP_STATS[metric]

        # Perform form validation.
        form = StatsForm(request.GET)
        if not form.is_valid():
            raise ParseError(dict(form.errors.items()))

        qs = form.cleaned_data

        dimensions = {'app-id': app.id}

        if 'dimensions' in stat:
            for key, default in stat['dimensions'].items():
                val = request.GET.get(key, default)
                if val is not None:
                    # Avoid passing kwargs to the monolith client when the
                    # dimension is None to avoid facet filters being applied.
                    dimensions[key] = request.GET.get(key, default)

        return Response(_get_monolith_data(stat, qs.get('start'),
                                           qs.get('end'), qs.get('interval'),
                                           dimensions))
