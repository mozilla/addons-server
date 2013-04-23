from django.conf.urls.defaults import url

import waffle
from tastypie import http
from tastypie.authorization import Authorization
from tastypie.exceptions import ImmediateHttpResponse
from tastypie.utils import trailing_slash
from tastypie.validation import CleanedDataFormValidation

from lib.metrics import get_monolith_client
from mkt.api.authentication import OptionalOAuthAuthentication
from mkt.api.base import GenericObject, MarketplaceResource

from .forms import GlobalStatsForm


# Map of URL metric name to monolith metric name. Future home of where we can
# put other properties (e.g. auth rules) about the stats.
STATS = {
    'total_visits': {
        'metric': 'visits',
    },
    'total_developers': {
        'metric': 'mmo_developer_count_total',
    },
}


class GlobalStatsResource(MarketplaceResource):
    """
    A resource for global stats.
    """
    class Meta(MarketplaceResource.Meta):
        resource_name = 'global'
        authentication = OptionalOAuthAuthentication()
        authorization = Authorization()
        detail_allowed_methods = ['get']
        list_allowed_methods = []
        object_class = GenericObject
        validation = CleanedDataFormValidation(form_class=GlobalStatsForm)

    def base_urls(self):
        """
        Stats are looked up by metric name.
        """
        return super(GlobalStatsResource, self).base_urls()[:2] + [
            url(r'^(?P<resource_name>%s)/(?P<metric>[^/]+)%s$' % (
                self._meta.resource_name, trailing_slash()),
                self.wrap_view('dispatch_detail'), name='api_dispatch_detail'),
        ]

    def dispatch(self, request_type, request, **kwargs):
        if not waffle.switch_is_active('stats-api'):
            raise ImmediateHttpResponse(response=http.HttpNotImplemented())

        return super(GlobalStatsResource, self).dispatch(request_type, request,
                                                         **kwargs)

    def get_detail(self, request, **kwargs):
        metric = kwargs.get('metric')
        if metric not in STATS:
            raise ImmediateHttpResponse(response=http.HttpNotFound())

        # Trigger form validation which doesn't normally happen for GETs.
        bundle = self.build_bundle(data=request.GET, request=request)
        self.is_valid(bundle, request)

        start = bundle.data.get('start')
        end = bundle.data.get('end')
        interval = bundle.data.get('interval')

        client = get_monolith_client()

        data = list(client(STATS[metric]['metric'], start, end, interval))
        to_be_serialized = self.alter_list_data_to_serialize(
            request, {'objects': data})

        return self.create_response(request, to_be_serialized)
