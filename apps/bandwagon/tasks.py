import logging
import os

from django.db.models import Count

from celery.decorators import task
# TODO(davedash): PIL needed
# from easy_thumbnails import processors
# from PIL import Image

import amo
from tags.models import AddonTag
from . import cron  # Pull in tasks run through cron.
from .models import Collection, CollectionAddon, CollectionVote

log = logging.getLogger('z.task')


@task
def collection_votes(*ids):
    log.info('[%s@%s] Updating collection votes.' %
             (len(ids), collection_votes.rate_limit))
    for collection in ids:
        v = CollectionVote.objects.filter(collection=collection)
        votes = dict(v.values_list('vote').annotate(Count('vote')))
        qs = Collection.objects.filter(id=collection)
        qs.update(upvotes=votes.get(1, 0), downvotes=votes.get(-1, 0))


#@task
#def resize_icon(src, dest):
#    """Resizes collection icons to 32x32"""
#    try:
#        im = Image.open(src)
#        im = processors.scale_and_crop(im, (32, 32))
#        im.save(dest)
#        os.remove(src)
#    except Exception, e:
#        log.error("Error saving collection icon: %s" % e)


@task
def collection_meta(*ids):
    log.info('[%s@%s] Updating collection metadata.' %
             (len(ids), collection_meta.rate_limit))
    qs = (CollectionAddon.objects.filter(collection__in=ids)
          .values_list('collection'))
    counts = dict(qs.annotate(Count('id')))
    persona_counts = dict(qs.filter(addon__type=amo.ADDON_PERSONA)
                          .annotate(Count('id')))
    tags = (AddonTag.objects.values_list('tag').annotate(cnt=Count('tag'))
            .filter(cnt__gt=1).order_by('-cnt'))
    for c in Collection.objects.filter(id__in=ids):
        c.addon_count = counts.get(c.id, 0)
        c.all_personas = c.addon_count == persona_counts.get(c.id, None)
        addons = list(c.addons.values_list('id', flat=True))
        c.top_tags = [t for t, _ in tags.filter(addon__in=addons)[:5]]
        c.save()


@task(rate_limit='10/m')
def cron_collection_meta(*addons):
    collection_meta(*addons)
