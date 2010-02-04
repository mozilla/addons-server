import jingo
import socket

from django.conf import settings
from django.core.cache import parse_backend_uri
from django.views.decorators.cache import never_cache
from django.contrib import messages


@never_cache
def monitor(request):

    status = 200
    scheme, servers, _ = parse_backend_uri(settings.CACHE_BACKEND)

    if 'memcached' in scheme:
        hosts = servers.split(';')
        for host in hosts:
            ip, port = host.split(':')
            try:
                s = socket.socket()
                s.connect((ip, int(port)))
            except Exception, e:
                messages.error(request, ("[Memcached] Failed to connect"
                                         " (%s:%s): %s" % (ip, port, e)))
            else:
                messages.success(request, ("[Memcached] Successfully connected"
                                           " (%s:%s)" % (ip, port)))
            finally:
                s.close()

        if len(hosts) >= 2:
            messages.success(request, ("[Memcached] At least 2 servers? "
                                       "Yes: %s" % len(hosts)))
        else:
            messages.error(request, ("[Memcached] At least 2 servers? "
                                     "No: %s" % len(hosts)))

    else:
        messages.error(request, "Memcache is not configured!")

    storage = messages.get_messages(request)
    for message in storage:
        if "error" in message.tags:
            status = 500

    return jingo.render(request, 'services/monitor.html',
                        {}, status=status)
