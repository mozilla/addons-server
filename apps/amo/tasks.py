from django.conf import settings

import commonware.log
import celery.task
from celeryutils import task
from hera.contrib.django_utils import flush_urls

log = commonware.log.getLogger('z.task')


# We use celery.task.ping in /monitor, so we need it to return results.
celery.task.PingTask.ignore_result = False


@task
def flush_front_end_cache_urls(urls):
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
