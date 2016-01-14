from datetime import date

from django.db import connection, transaction
from django.db.models import Count

import commonware.log
from celery.task.sets import TaskSet

import amo
from amo.celery import task
from amo.utils import chunked
from bandwagon.models import Collection, CollectionVote, CollectionWatcher
import cronjobs

task_log = commonware.log.getLogger('z.task')


@cronjobs.register
def update_collections_subscribers():
    """Update collections subscribers totals."""

    d = (CollectionWatcher.objects.values('collection_id')
         .annotate(count=Count('collection'))
         .extra(where=['DATE(created)=%s'], params=[date.today()]))

    ts = [_update_collections_subscribers.subtask(args=[chunk])
          for chunk in chunked(d, 1000)]
    TaskSet(ts).apply_async()


@task(rate_limit='15/m')
def _update_collections_subscribers(data, **kw):
    task_log.info("[%s@%s] Updating collections' subscribers totals." % (
                  len(data), _update_collections_subscribers.rate_limit))
    cursor = connection.cursor()
    today = date.today()
    for var in data:
        q = """REPLACE INTO
                    stats_collections(`date`, `name`, `collection_id`, `count`)
                VALUES
                    (%s, %s, %s, %s)"""
        p = [today, 'new_subscribers', var['collection_id'], var['count']]
        cursor.execute(q, p)


@cronjobs.register
def update_collections_votes():
    """Update collection's votes."""

    up = (CollectionVote.objects.values('collection_id')
          .annotate(count=Count('collection'))
          .filter(vote=1)
          .extra(where=['DATE(created)=%s'], params=[date.today()]))

    down = (CollectionVote.objects.values('collection_id')
            .annotate(count=Count('collection'))
            .filter(vote=-1)
            .extra(where=['DATE(created)=%s'], params=[date.today()]))

    ts = [_update_collections_votes.subtask(args=[chunk, 'new_votes_up'])
          for chunk in chunked(up, 1000)]
    TaskSet(ts).apply_async()

    ts = [_update_collections_votes.subtask(args=[chunk, 'new_votes_down'])
          for chunk in chunked(down, 1000)]
    TaskSet(ts).apply_async()


@task(rate_limit='15/m')
def _update_collections_votes(data, stat, **kw):
    task_log.info("[%s@%s] Updating collections' votes totals." % (
                  len(data), _update_collections_votes.rate_limit))
    cursor = connection.cursor()
    for var in data:
        q = ('REPLACE INTO stats_collections(`date`, `name`, '
             '`collection_id`, `count`) VALUES (%s, %s, %s, %s)')
        p = [date.today(), stat,
             var['collection_id'], var['count']]
        cursor.execute(q, p)


@cronjobs.register
def drop_collection_recs():
    _drop_collection_recs.delay()


@task(rate_limit='1/m')
@transaction.atomic
def _drop_collection_recs(**kw):
    task_log.info("[300@%s] Dropping recommended collections." % (
                  _drop_collection_recs.rate_limit))
    # Get the first 300 collections and delete them in smaller chunks.
    types = amo.COLLECTION_SYNCHRONIZED, amo.COLLECTION_RECOMMENDED
    ids = (Collection.objects.filter(type__in=types, author__isnull=True)
           .values_list('id', flat=True))[:300]

    for chunk in chunked(ids, 100):
        Collection.objects.filter(id__in=chunk).delete()

    # Go again if we found something to delete.
    if ids:
        _drop_collection_recs.delay()


@cronjobs.register
def reindex_collections(index=None):
    from . import tasks
    ids = (Collection.objects.exclude(type=amo.COLLECTION_SYNCHRONIZED)
           .values_list('id', flat=True))
    taskset = [tasks.index_collections.subtask(args=[chunk],
                                               kwargs=dict(index=index))
               for chunk in chunked(sorted(list(ids)), 150)]
    TaskSet(taskset).apply_async()
