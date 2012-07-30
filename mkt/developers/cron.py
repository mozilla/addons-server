from celery.task.sets import TaskSet
import cronjobs

from amo.utils import chunked

import mkt
from mkt.developers.tasks import region_email, region_exclude
from mkt.webapps.models import AddonExcludedRegion, Webapp


@cronjobs.register
def send_new_region_emails(regions):
    """Email app developers notifying them of new regions added."""
    excluded = AddonExcludedRegion.objects.values_list('addon', flat=True)
    ids = Webapp.objects.exclude(id__in=excluded).values_list('id', flat=True)

    ts = [region_email.subtask(args=[chunk, regions])
          for chunk in chunked(ids, 100)]
    TaskSet(ts).apply_async()


@cronjobs.register
def exclude_new_region(regions):
    """
    Update regional blacklist for app developers who opted out of being
    automatically added to new regions.
    """
    ids = (AddonExcludedRegion.objects.values_list('addon', flat=True)
           .filter(region=mkt.regions.FUTURE))

    ts = [region_exclude.subtask(args=[chunk, regions])
          for chunk in chunked(ids, 100)]
    TaskSet(ts).apply_async()
