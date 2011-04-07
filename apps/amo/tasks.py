import json

from django.conf import settings

import commonware.log
import celery.task
from celeryutils import task
from hera.contrib.django_utils import flush_urls

from addons.models import Addon
from devhub.models import ActivityLog
from editors.helpers import LOG_STATUSES


log = commonware.log.getLogger('z.task')


# We use celery.task.ping in /monitor, so we need it to return results.
celery.task.PingTask.ignore_result = False


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
def dedupe_approvals(items, **kw):
    log.info('[%s@%s] Deduping approval items starting with addon: %s' %
             (len(items), dedupe_approvals.rate_limit, items[0]))
    for addon in Addon.objects.filter(pk__in=items):
        last = {}
        for activity in (ActivityLog.objects.for_addons(addon)
                                    .order_by('-created')
                                    .filter(action__in=LOG_STATUSES)):
            arguments = json.loads(activity._arguments)
            current = {
                'action': activity.action,
                'created': activity.created.date(),
                'user': activity.user.pk,
                'addon': arguments[0]['addons.addon'],
                'version': arguments[1]['versions.version'],
            }
            if activity._details:
                details = json.loads(activity._details)
                current.update({
                    'reviewtype': details['reviewtype'],
                    'comments': details['comments'],
                })

            if last and last == current:
                log.info('Deleting duplicate activity log %s '
                         'from addon %s' % (activity.pk, addon.pk))
                activity.delete()
            else:
                last = current.copy()
