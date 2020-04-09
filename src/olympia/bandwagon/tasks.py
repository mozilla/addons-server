from datetime import datetime

from django.db.models import Count

import olympia.core.logger

from olympia.amo.celery import task
from olympia.amo.decorators import use_primary_db

from .models import Collection, CollectionAddon


log = olympia.core.logger.getLogger('z.task')


@task
@use_primary_db
def collection_meta(*ids, **kw):
    log.info('[%s@%s] Updating collection metadata.' %
             (len(ids), collection_meta.rate_limit))
    collections_counts = CollectionAddon.objects.filter(
        collection__in=ids).values_list('collection').annotate(Count('id'))
    now = datetime.now()
    for collection_id, addon_count in collections_counts:
        # We want to set addon_count & modified without triggering post_save
        # as it would cause an infinite loop (this task is called on
        # post_save). So we update queryset.update() and set modified ourselves
        # instead of relying on auto_now behaviour.
        Collection.objects.filter(id=collection_id).update(
            addon_count=addon_count, modified=now)
