from datetime import date

from django.db import connection
from django.db.models import Count

from celery import group

import olympia.core.logger

from olympia import amo
from olympia.amo.celery import task
from olympia.amo.utils import chunked
from olympia.bandwagon.models import (
    Collection,
    CollectionVote,
    CollectionWatcher,
)


task_log = olympia.core.logger.getLogger('z.task')


def update_collections_subscribers():
    """Update collections subscribers totals."""

    d = (
        CollectionWatcher.objects.values('collection_id')
        .annotate(count=Count('collection'))
        .extra(where=['DATE(created)=%s'], params=[date.today()])
    )

    ts = [
        _update_collections_subscribers.subtask(args=[chunk])
        for chunk in chunked(d, 1000)
    ]
    group(ts).apply_async()


@task(rate_limit='15/m')
def _update_collections_subscribers(data, **kw):
    task_log.info(
        "[%s@%s] Updating collections' subscribers totals."
        % (len(data), _update_collections_subscribers.rate_limit)
    )

    today = date.today()

    statement = """
        REPLACE INTO
          stats_collections(`date`, `name`, `collection_id`, `count`)
        VALUES
          (%s, %s, %s, %s)
    """

    statements_data = [
        (today, 'new_subscribers', var['collection_id'], var['count'])
        for var in data
    ]

    with connection.cursor() as cursor:
        cursor.executemany(statement, statements_data)


def update_collections_votes():
    """Update collection's votes."""

    up = (
        CollectionVote.objects.values('collection_id')
        .annotate(count=Count('collection'))
        .filter(vote=1)
        .extra(where=['DATE(created)=%s'], params=[date.today()])
    )

    down = (
        CollectionVote.objects.values('collection_id')
        .annotate(count=Count('collection'))
        .filter(vote=-1)
        .extra(where=['DATE(created)=%s'], params=[date.today()])
    )

    ts = [
        _update_collections_votes.subtask(args=[chunk, 'new_votes_up'])
        for chunk in chunked(up, 1000)
    ]
    group(ts).apply_async()

    ts = [
        _update_collections_votes.subtask(args=[chunk, 'new_votes_down'])
        for chunk in chunked(down, 1000)
    ]
    group(ts).apply_async()


@task(rate_limit='15/m')
def _update_collections_votes(data, stat, **kw):
    task_log.info(
        "[%s@%s] Updating collections' votes totals."
        % (len(data), _update_collections_votes.rate_limit)
    )

    today = date.today()

    statement = (
        'REPLACE INTO stats_collections(`date`, `name`, '
        '`collection_id`, `count`) VALUES (%s, %s, %s, %s)'
    )

    statements_data = [
        (today, stat, x['collection_id'], x['count']) for x in data
    ]

    with connection.cursor() as cursor:
        cursor.executemany(statement, statements_data)


def reindex_collections(index=None):
    from . import tasks

    ids = Collection.objects.exclude(
        type=amo.COLLECTION_SYNCHRONIZED
    ).values_list('id', flat=True)
    taskset = [
        tasks.index_collections.subtask(args=[chunk], kwargs=dict(index=index))
        for chunk in chunked(sorted(list(ids)), 150)
    ]
    group(taskset).apply_async()
