import logging

from django.core.management.base import BaseCommand

import redisutils
from graphite import graphite

from amo.tasks import task_stats

log = logging.getLogger('z.redis')


class Command(BaseCommand):
    help = "Subscribe to celery events and publish to graphite."

    def handle(self, *args, **kw):
        redis = redisutils.connections['master']
        # We don't want this socket to timeout.
        redis.connection.socket_timeout = None
        redis.connection.disconnect()
        while 1:
            stats = []
            d = zip(['pending', 'failed', 'total'], task_stats.stats())
            for key, dict_ in d:
                for name, value in dict_.items():
                    stats.append(('celery.tasks.%s.%s' % (key, name), value))
            graphite.sendall(*stats)

            # We don't care about the message, just block until the next one.
            redis.subscribe('celery.tasks.stats')
            listener = redis.listen()
            while 1:
                if listener.next()['type'] == 'message':
                    break

            # Unsubscribe so we can process the stats.
            redis.unsubscribe()
            while 1:
                if listener.next()['type'] == 'unsubscribe':
                    break
