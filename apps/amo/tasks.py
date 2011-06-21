import datetime
import time

from django.conf import settings

import commonware.log
import celery.signals
import redisutils
from celeryutils import task
from hera.contrib.django_utils import flush_urls
from statsd import statsd


log = commonware.log.getLogger('z.task')


@task
def flush_front_end_cache_urls(urls, **kw):
    """Accepts a list of urls which will be sent through Hera to the front end
    cache.  This does no checking for success or failure or whether the URLs
    were in the cache to begin with."""

    if not urls:
        return

    log.info(u"Flushing %d URLs from front end cache: (%s)" % (len(urls),
                                                               urls))

    # Zeus is only interested in complete URLs.  We can't just pass a
    # prefix to Hera because some URLs will be on SAMO.
    for index, url in enumerate(urls):
        if not url.startswith('http'):
            if '/api/' in url:
                urls[index] = u"%s%s" % (settings.SERVICES_URL, url)
            else:
                urls[index] = u"%s%s" % (settings.SITE_URL, url)

    flush_urls(urls)


@task
def set_modified_on_object(obj, **kw):
    """Sets modified on one object at a time."""
    try:
        log.info('Setting modified on object: %s, %s' %
                 (obj.__class__.__name__, obj.pk))
        obj.update(modified=datetime.datetime.now())
    except Exception, e:
        log.error('Failed to set modified on: %s, %s - %s' %
                  (obj.__class__.__name__, obj.pk, e))


class TaskStats(object):
    prefix = 'celery:tasks:stats'
    pending = prefix + ':pending'
    failed = prefix + ':failed'
    run = prefix + ':run'
    timer = prefix + ':timer'

    @property
    def redis(self):
        # Keep this in a property so it's evaluated at runtime.
        return redisutils.connections['master']

    def on_sent(self, sender, **kw):
        # sender is the name of the task (like "amo.tasks.ok").
        # id in here.
        self.redis.hincrby(self.pending, sender, 1)
        self.redis.hset(self.timer, kw['id'], time.time())

    def on_postrun(self, sender, **kw):
        # sender is the task object. task_id in here.
        pending = self.redis.hincrby(self.pending, sender.name, -1)
        # Clamp pending at 0. Tasks could be coming in before we started
        # tracking.
        if pending < 0:
            self.redis.hset(self.pending, sender.name, 0)
        self.redis.hincrby(self.run, sender.name, 1)

        start = self.redis.hget(self.timer, kw['task_id'])
        if start:
            t = (time.time() - float(start)) * 1000
            statsd.timing('tasks.%s' % sender.name, int(t))

    def on_failure(self, sender, **kw):
        # sender is the task object.
        self.redis.hincrby(self.failed, sender.name, 1)

    def stats(self):
        get = self.redis.hgetall
        return get(self.pending), get(self.failed), get(self.run)

    def clear(self):
        for name in self.pending, self.failed, self.run, self.timer:
            self.redis.delete(name)


task_stats = TaskStats()
celery.signals.task_sent.connect(task_stats.on_sent)
celery.signals.task_postrun.connect(task_stats.on_postrun)
celery.signals.task_failure.connect(task_stats.on_failure)
