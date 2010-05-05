import logging

from django.db.models import Sum
from celery.decorators import task
from celery.messaging import establish_connection

from .models import (AddonCollectionCount,
                     CollectionCount)
from amo.utils import chunked
from bandwagon.models import Collection, CollectionAddon
import cronjobs

task_log = logging.getLogger('z.task')


@cronjobs.register
def update_addons_collections_downloads():
    """Update addons+collections download totals."""

    d = (AddonCollectionCount.objects.values('addon', 'collection')
         .annotate(sum=Sum('count')))

    with establish_connection() as conn:
        for chunk in chunked(d, 1000):
            _update_addons_collections_downloads.apply_async(args=[chunk],
                                                             connection=conn)


@task(rate_limit='15/m')
def _update_addons_collections_downloads(data, **kw):
    task_log.debug("[%s@%s] Updating addons+collections download totals." %
                  (len(data), _update_addons_collections_downloads.rate_limit))
    for var in data:
        (CollectionAddon.objects.filter(addon=var['addon'],
                                        collection=var['collection'])
                                .update(downloads=var['sum']))


@cronjobs.register
def update_collections_total():
    """Update collections downloads totals."""

    d = (CollectionCount.objects.values('collection_id')
                                .annotate(sum=Sum('count')))

    with establish_connection() as conn:
        for chunk in chunked(d, 1000):
            _update_collections_total.apply_async(args=[chunk],
                                                  connection=conn)


@task(rate_limit='15/m')
def _update_collections_total(data, **kw):
    task_log.debug("[%s@%s] Updating collections' download totals." %
                   (len(data), _update_collections_total.rate_limit))
    for var in data:
        (Collection.objects.filter(pk=var['collection_id'])
         .update(downloads=var['sum']))
