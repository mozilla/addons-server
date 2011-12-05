from datetime import datetime, timedelta

from django.conf import settings
from django.db.models import Count
import logging

import cronjobs
from celery.task.sets import TaskSet
from celeryutils import task

import amo
from amo.utils import chunked
from addons.tasks import index_addons
from webapps.models import Installed

from .models import Webapp


task_log = logging.getLogger('z.task')


@cronjobs.register
def release_webapps():
    """
    Turn webapps from PENDING to LITE so they show up on the site.

    This should be run when WEBAPPS_RESTRICTED is flipped.
    """
    if settings.WEBAPPS_RESTRICTED:
        print 'You should set `WEBAPPS_RESTRICTED = False` first.'
        return
    flip_webapp_status(amo.STATUS_PENDING, amo.STATUS_PUBLIC)


@cronjobs.register
def restrict_webapps():
    """
    Turn webapps from LITE to PENDING so they don't show up on the site.

    This should be run if WEBAPPS_RESTRICTED gets rolled back.
    """
    if not settings.WEBAPPS_RESTRICTED:
        print 'You should set `WEBAPPS_RESTRICTED = True` first.'
        return
    flip_webapp_status(amo.STATUS_PUBLIC, amo.STATUS_PENDING)


def flip_webapp_status(from_, to):
    qs = Webapp.objects.filter(status=from_)
    # Grab the ids so we can get them reindexed.
    ids = list(qs.values_list('id', flat=True))
    qs.update(status=to)
    ts = [index_addons.subtask(args=[chunk])
          for chunk in chunked(ids, 150)]
    # Delay these tasks to avoid slave lag.
    TaskSet(ts).apply_async(countdown=30)


@cronjobs.register
def update_weekly_downloads():
    """Update the weekly "downloads" from the users_install table."""
    interval = datetime.today() - timedelta(days=7)
    counts = (Installed.objects.values('addon')
                               .filter(created__gte=interval,
                                       addon__type=amo.ADDON_WEBAPP)
                               .annotate(count=Count('addon')))

    ts = [_update_weekly_downloads.subtask(args=[chunk])
          for chunk in chunked(counts, 1000)]
    TaskSet(ts).apply_async()


@task(rate_limit='15/m')
def _update_weekly_downloads(data, **kw):
    task_log.info("[%s@%s] Update weekly downloads." %
                   (len(data), _update_weekly_downloads.rate_limit))

    for line in data:
        webapp = Webapp.objects.get(pk=line['addon'])
        webapp.update(weekly_downloads=line['count'])
