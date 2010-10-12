import logging
import math
import os

from django.conf import settings
from django.db.models import Count

from celeryutils import task

import amo
from amo.utils import resize_image
from tags.models import Tag
from . import cron  # Pull in tasks run through cron.
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
def resize_icon(src, dst):
    """Resizes collection icons to 32x32"""
    log.info('[1@None] Resizing icon: %s' % dst)

    try:
        resize_image(src, dst, (32, 32))
    except Exception, e:
        log.error("Error saving collection icon: %s" % e)


@task
def delete_icon(dst):
    log.info('[1@None] Deleting icon: %s.' % dst)

    if not dst.startswith(settings.COLLECTIONS_ICON_PATH):
        log.error("Someone tried deleting something they shouldn't: %s" % dst)
        return

    try:
        os.remove(dst)
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
        watchers = (CollectionWatcher.objects.filter(collection=pk)
                    .using(using).count())
        Collection.objects.get(pk=pk).update(subscribers=watchers)


@task(rate_limit='10/m')
def cron_collection_meta(*addons):
    collection_meta(*addons)
