import threading

from django.conf import settings

import commonware.log

from mkt.monolith import record_stat


log = commonware.log.getLogger('z.metrics')


def record_action(action, request, data=None):
    """Records the given action by sending it to the metrics servers.

    Currently this is storing the data internally in the monolith temporary
    table.

    :param action: the action related to this request.
    :param request: the request that triggered this call.
    :param data: some optional additional data about this call.

    """
    if data is None:
        data = {}

    data['user-agent'] = request.META.get('HTTP_USER_AGENT')
    data['locale'] = request.LANG
    data['src'] = request.GET.get('src', '')
    record_stat(action, request, **data)


def get_monolith_client():
    _locals = threading.local()
    if not hasattr(_locals, 'monolith'):
        server = getattr(settings, 'MONOLITH_SERVER', None)
        index = getattr(settings, 'MONOLITH_INDEX', 'time_*')
        if server is None:
            raise ValueError('You need to configure MONOLITH_SERVER')

        statsd = {'statsd.host': getattr(settings, 'STATSD_HOST', 'localhost'),
                  'statsd.port': getattr(settings, 'STATSD_PORT', 8125)}

        from monolith.client import Client as MonolithClient
        _locals.monolith = MonolithClient(server, index, **statsd)

    return _locals.monolith
