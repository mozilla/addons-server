import datetime
import itertools

from django.db import connection, transaction
from django.db.models import Count

import commonware.log
from celery.messaging import establish_connection
from celeryutils import task

import amo
from amo.utils import chunked, slugify
from bandwagon.models import (CollectionWatcher,
                              CollectionVote, Collection, CollectionUser)
import cronjobs

task_log = commonware.log.getLogger('z.task')


# TODO(davedash): remove when EB is fully in place.
# Migration tasks

@cronjobs.register
def migrate_collection_users():
    """For all non-anonymous collections with no author, populate the author
    with the first CollectionUser.  Set all other CollectionUsers to
    publishers."""
    # Don't touch the modified date.
    Collection._meta.get_field('modified').auto_now = False
    collections = (Collection.objects.no_cache().using('default')
                   .exclude(type=amo.COLLECTION_ANONYMOUS)
                   .filter(author__isnull=True))

    task_log.info('Fixing users for %s collections.' % len(collections))
    for collection in collections:
        users = (collection.collectionuser_set
                 .order_by('id'))
        if users:
            collection.author_id = users[0].user_id
            try:
                collection.save()
                users[0].delete()
            except:
                task_log.warning("No author found for collection: %d"
                               % collection.id)

        else:
            task_log.warning('No users for collection %s. DELETING' %
                             collection.id)
            collection.delete()

    # TODO(davedash): We can just remove this from the model altogether.
    CollectionUser.objects.all().update(role=amo.COLLECTION_ROLE_PUBLISHER)

# /Migration tasks


@cronjobs.register
def update_collections_subscribers():
    """Update collections subscribers totals."""

    d = (CollectionWatcher.objects.values('collection_id')
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
def collection_meta():
    from . import tasks
    collections = Collection.objects.values_list('id', flat=True)
    with establish_connection() as conn:
        for chunk in chunked(collections, 1000):
            tasks.cron_collection_meta.apply_async(args=chunk, connection=conn)


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


# TODO: remove this once zamboni enforces slugs.
@cronjobs.register
def collections_add_slugs():
    """Give slugs to any slugless collections."""
    # Don't touch the modified date.
    Collection._meta.get_field('modified').auto_now = False
    q = Collection.objects.filter(slug=None)
    ids = q.values_list('id', flat=True)
    task_log.info('%s collections without names' % len(ids))
    max_length = Collection._meta.get_field('slug').max_length
    cnt = itertools.count()
    # Chunk it so we don't do huge queries.
    for chunk in chunked(ids, 300):
        for c in q.no_cache().filter(id__in=chunk):
            c.slug = c.nickname or slugify(c.name)[:max_length]
            if not c.slug:
                c.slug = 'collection'
            c.save(force_update=True)
            task_log.info(u'%s. %s => %s' % (next(cnt), c.name, c.slug))
