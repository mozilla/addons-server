import time

from django.core.management.base import BaseCommand

import redisutils
from graphite import graphite

from amo.tasks import task_stats


class Command(BaseCommand):
    help = "Subscribe to celery events and publish to graphite."

    def handle(self, *args, **kw):
        redis = redisutils.connections['master']
        while 1:
            stats = []
            d = zip(['pending', 'failed', 'total'], task_stats.stats())
            for key, dict_ in d:
                for name, value in dict_.items():
                    stats.append(('celery.tasks.%s.%s' % (key, name), value))
            graphite.sendall(*stats)

            time.sleep(2)
