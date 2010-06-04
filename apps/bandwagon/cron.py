import datetime

from django.db import connection, transaction
from django.db.models import Count

import commonware.log
from celery.decorators import task
from celery.messaging import establish_connection

from amo.utils import chunked
from bandwagon.models import (CollectionSubscription,
                              CollectionVote)
import cronjobs

task_log = commonware.log.getLogger('z.task')


@cronjobs.register
def update_collections_subscribers():
    """Update collections subscribers totals."""

    d = (CollectionSubscription.objects.values('collection_id')
         .annotate(count=Count('collection'))
         .extra(where=['DATE(created)=%s'], params=[datetime.date.today()]))

    with establish_connection() as conn:
        for chunk in chunked(d, 1000):
            _update_collections_subscribers.apply_async(args=[chunk],
                                                        connection=conn)


@task(rate_limit='15/m')
def _update_collections_subscribers(data, **kw):
    task_log.info("[%s@%s] Updating collections' subscribers totals." %
                   (len(data), _update_collections_subscribers.rate_limit))
    cursor = connection.cursor()
    today = datetime.date.today()
    for var in data:
        q = """REPLACE INTO
                    stats_collections(`date`, `name`, `collection_id`, `count`)
                VALUES
                    (%s, %s, %s, %s)"""
        p = [today, 'new_subscribers', var['collection_id'], var['count']]
        cursor.execute(q, p)
    transaction.commit_unless_managed()


@cronjobs.register
def update_collections_votes():
    """Update collection's votes."""

    up = (CollectionVote.objects.values('collection_id')
          .annotate(count=Count('collection'))
          .filter(vote=1)
          .extra(where=['DATE(created)=%s'], params=[datetime.date.today()]))

    down = (CollectionVote.objects.values('collection_id')
            .annotate(count=Count('collection'))
            .filter(vote=-1)
            .extra(where=['DATE(created)=%s'], params=[datetime.date.today()]))

    with establish_connection() as conn:
        for chunk in chunked(up, 1000):
            _update_collections_votes.apply_async(args=[chunk, "new_votes_up"],
                                                  connection=conn)
        for chunk in chunked(down, 1000):
            _update_collections_votes.apply_async(args=[chunk,
                                                        "new_votes_down"],
                                                  connection=conn)


@task(rate_limit='15/m')
def _update_collections_votes(data, stat, **kw):
    task_log.info("[%s@%s] Updating collections' votes totals." %
                   (len(data), _update_collections_votes.rate_limit))
    cursor = connection.cursor()
    for var in data:
        q = ('REPLACE INTO stats_collections(`date`, `name`, '
             '`collection_id`, `count`) VALUES (%s, %s, %s, %s)')
        p = [datetime.date.today(), stat,
             var['collection_id'], var['count']]
        cursor.execute(q, p)
    transaction.commit_unless_managed()
