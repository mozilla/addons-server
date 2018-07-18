import math

from django.core.files.storage import default_storage as storage
from django.db.models import Count

import olympia.core.logger

from olympia import amo
from olympia.amo.celery import task
from olympia.amo.decorators import set_modified_on, use_primary_db
from olympia.amo.templatetags.jinja_helpers import user_media_path
from olympia.amo.utils import attach_trans_dict, resize_image
from olympia.tags.models import Tag

from .models import (
    Collection,
    CollectionAddon,
    CollectionVote,
    CollectionWatcher,
)


log = olympia.core.logger.getLogger('z.task')


@task
@use_primary_db
def collection_votes(*ids, **kw):
    log.info(
        '[%s@%s] Updating collection votes.'
        % (len(ids), collection_votes.rate_limit)
    )
    for collection_id in ids:
        qs = CollectionVote.objects.filter(collection=collection_id)
        votes = dict(qs.values_list('vote').annotate(Count('vote')))
        collection = Collection.objects.get(id=collection_id)
        collection.upvotes = up = votes.get(1, 0)
        collection.downvotes = down = votes.get(-1, 0)
        try:
            # Use log to limit the effect of the multiplier.
            collection.rating = (up - down) * math.log(up + down)
        except ValueError:
            collection.rating = 0
        collection.save()


@task
@set_modified_on
def resize_icon(src, dst, **kw):
    """Resizes collection icons to 32x32"""
    log.info('[1@None] Resizing icon: %s' % dst)

    try:
        resize_image(src, dst, (32, 32))
        return True
    except Exception as e:
        log.error("Error saving collection icon: %s" % e)


@task
def delete_icon(dst, **kw):
    log.info('[1@None] Deleting icon: %s.' % dst)

    if not dst.startswith(user_media_path('collection_icons')):
        log.error("Someone tried deleting something they shouldn't: %s" % dst)
        return

    try:
        storage.delete(dst)
    except Exception as e:
        log.error("Error deleting icon: %s" % e)


@task
@use_primary_db
def collection_meta(*ids, **kw):
    log.info(
        '[%s@%s] Updating collection metadata.'
        % (len(ids), collection_meta.rate_limit)
    )
    qs = CollectionAddon.objects.filter(collection__in=ids).values_list(
        'collection'
    )
    counts = dict(qs.annotate(Count('id')))
    persona_counts = dict(
        qs.filter(addon__type=amo.ADDON_PERSONA).annotate(Count('id'))
    )
    tags = (
        Tag.objects.not_denied()
        .values_list('id')
        .annotate(cnt=Count('id'))
        .filter(cnt__gt=1)
        .order_by('-cnt')
    )
    for collection in Collection.objects.filter(id__in=ids):
        addon_count = counts.get(collection.id, 0)
        all_personas = addon_count == persona_counts.get(collection.id, None)
        addons = list(collection.addons.values_list('id', flat=True))
        # top_tags is a special object that updates directly in cache when you
        # set it.
        collection.top_tags = [
            t for t, _ in tags.filter(addons__in=addons)[:5]
        ]
        # Update addon_count and all_personas, avoiding to hit the post_save
        # signal by using queryset.update().
        Collection.objects.filter(id=collection.id).update(
            addon_count=addon_count, all_personas=all_personas
        )


@task
@use_primary_db
def collection_watchers(*ids, **kw):
    log.info(
        '[%s@%s] Updating collection watchers.'
        % (len(ids), collection_watchers.rate_limit)
    )
    for pk in ids:
        try:
            watchers = CollectionWatcher.objects.filter(collection=pk).count()
            Collection.objects.filter(pk=pk).update(subscribers=watchers)
            log.info('Updated collection watchers: %s' % pk)
        except Exception as e:
            log.error('Updating collection watchers failed: %s, %s' % (pk, e))


def attach_translations(collections):
    """Put all translations into a translations dict."""
    attach_trans_dict(Collection, collections)
