import socket

from django.conf import settings
from django.core.cache import parse_backend_uri
from django.views.decorators.cache import never_cache

import jingo


@never_cache
def monitor(request):

    # For each check, a boolean pass/fail status to show in the template
    status_summary = {}
    status = 200

    # Check all memcached servers
    scheme, servers, _ = parse_backend_uri(settings.CACHE_BACKEND)
    memcache_results = []
    status_summary['memcache'] = True
    if 'memcached' in scheme:
        hosts = servers.split(';')
        for host in hosts:
            ip, port = host.split(':')
            try:
                s = socket.socket()
                s.connect((ip, int(port)))
            except Exception, e:
                result = False
                status_summary['memcache'] = False
                status = 500
            else:
                result = True
            finally:
                s.close()

            memcache_results.append((ip, port, result))
        if len(memcache_results) < 2:
            status = 500
            status_summary['memcache'] = False

    return jingo.render(request, 'services/monitor.html',
                        {'memcache_results': memcache_results,
                         'status_summary': status_summary},
                        status=status)


def handler404(request):
    return jingo.render(request, 'amo/404.lhtml', status=404)


def handler500(request):
    return jingo.render(request, 'amo/500.lhtml')
