import logging

from django.db import transaction
from django.db.models import Sum
from celery.decorators import task
from celery.messaging import establish_connection

from .models import CollectionCount
from amo.utils import chunked
from bandwagon.models import Collection
import cronjobs

task_log = logging.getLogger('z.task')


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
                   (len(data), '15/m'))
    for var in data:
        (Collection.objects.filter(pk=var['collection_id'])
         .update(downloads=var['sum']))
