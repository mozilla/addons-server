import logging
import os

from django.db.models import Count

from celery.decorators import task
from easy_thumbnails import processors
from PIL import Image

from . import cron  # Pull in tasks run through cron.
from .models import Collection, CollectionVote

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


@task
def resize_icon(src, dest):
    """Resizes collection icons to 32x32"""
    try:
        im = Image.open(src)
        im = processors.scale_and_crop(im, (32, 32))
        im.save(dest)
        os.remove(src)
    except Exception, e:
        log.error("Error saving collection icon: %s" % e)
