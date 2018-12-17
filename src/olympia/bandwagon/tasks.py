from django.db.models import Count

import olympia.core.logger

from olympia import amo
from olympia.amo.celery import task
from olympia.amo.decorators import use_primary_db

from .models import Collection, CollectionAddon


log = olympia.core.logger.getLogger('z.task')


@task
@use_primary_db
def collection_meta(*ids, **kw):
    log.info('[%s@%s] Updating collection metadata.' %
             (len(ids), collection_meta.rate_limit))
    qs = (CollectionAddon.objects.filter(collection__in=ids)
          .values_list('collection'))
    counts = dict(qs.annotate(Count('id')))
    persona_counts = dict(qs.filter(addon__type=amo.ADDON_PERSONA)
                          .annotate(Count('id')))
    for collection in Collection.objects.filter(id__in=ids):
        addon_count = counts.get(collection.id, 0)
        all_personas = addon_count == persona_counts.get(collection.id, None)
        # Update addon_count and all_personas, avoiding to hit the post_save
        # signal by using queryset.update().
        Collection.objects.filter(id=collection.id).update(
            addon_count=addon_count, all_personas=all_personas)
