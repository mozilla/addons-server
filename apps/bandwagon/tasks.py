import logging
import math

from django.core.files.storage import default_storage as storage
from django.db.models import Count

from celeryutils import task

import amo
from amo.decorators import set_modified_on
from amo.helpers import user_media_path
from amo.utils import attach_trans_dict, resize_image
from tags.models import Tag
from lib.es.utils import index_objects
from . import search
from .models import (Collection, CollectionAddon, CollectionVote,
                     CollectionWatcher)

log = logging.getLogger('z.task')


@task
def collection_votes(*ids, **kw):
    log.info('[%s@%s] Updating collection votes.' %
             (len(ids), collection_votes.rate_limit))
    using = kw.get('using')
    for collection in ids:
        v = CollectionVote.objects.filter(collection=collection).using(using)
        votes = dict(v.values_list('vote').annotate(Count('vote')))
        c = Collection.objects.get(id=collection)
        c.upvotes = up = votes.get(1, 0)
        c.downvotes = down = votes.get(-1, 0)
        try:
            # Use log to limit the effect of the multiplier.
            c.rating = (up - down) * math.log(up + down)
        except ValueError:
            c.rating = 0
        c.save()


@task
@set_modified_on
def resize_icon(src, dst, locally=False, **kw):
    """Resizes collection icons to 32x32"""
    log.info('[1@None] Resizing icon: %s' % dst)

    try:
        resize_image(src, dst, (32, 32), locally=locally)
        return True
    except Exception, e:
        log.error("Error saving collection icon: %s" % e)


@task
def delete_icon(dst, **kw):
    log.info('[1@None] Deleting icon: %s.' % dst)

    if not dst.startswith(user_media_path('collection_icons')):
        log.error("Someone tried deleting something they shouldn't: %s" % dst)
        return

    try:
        storage.delete(dst)
    except Exception, e:
        log.error("Error deleting icon: %s" % e)


@task
def collection_meta(*ids, **kw):
    log.info('[%s@%s] Updating collection metadata.' %
             (len(ids), collection_meta.rate_limit))
    using = kw.get('using')
    qs = (CollectionAddon.objects.filter(collection__in=ids)
          .using(using).values_list('collection'))
    counts = dict(qs.annotate(Count('id')))
    persona_counts = dict(qs.filter(addon__type=amo.ADDON_PERSONA)
                          .annotate(Count('id')))
    tags = (Tag.objects.not_blacklisted().values_list('id')
            .annotate(cnt=Count('id')).filter(cnt__gt=1).order_by('-cnt'))
    for c in Collection.objects.no_cache().filter(id__in=ids):
        addon_count = counts.get(c.id, 0)
        all_personas = addon_count == persona_counts.get(c.id, None)
        addons = list(c.addons.values_list('id', flat=True))
        c.top_tags = [t for t, _ in tags.filter(addons__in=addons)[:5]]
        Collection.objects.filter(id=c.id).update(addon_count=addon_count,
                                                  all_personas=all_personas)


@task
def collection_watchers(*ids, **kw):
    log.info('[%s@%s] Updating collection watchers.' %
             (len(ids), collection_watchers.rate_limit))
    using = kw.get('using')
    for pk in ids:
        try:
            watchers = (CollectionWatcher.objects.filter(collection=pk)
                                         .using(using).count())
            Collection.objects.filter(pk=pk).update(subscribers=watchers)
            log.info('Updated collection watchers: %s' % pk)
        except Exception, e:
            log.error('Updating collection watchers failed: %s, %s' % (pk, e))


@task
def index_collections(ids, **kw):
    log.debug('Indexing collections %s-%s [%s].' % (ids[0], ids[-1], len(ids)))
    index = kw.pop('index', None)
    index_objects(ids, Collection, search, index, [attach_translations])


def attach_translations(collections):
    """Put all translations into a translations dict."""
    attach_trans_dict(Collection, collections)


@task
def unindex_collections(ids, **kw):
    for id in ids:
        log.debug('Removing collection [%s] from search index.' % id)
        Collection.unindex(id)
