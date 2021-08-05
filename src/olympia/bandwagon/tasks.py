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
    log.info(f'[{len(ids)}@{collection_meta.rate_limit}] Updating collection metadata.')
    qs = CollectionAddon.objects.filter(collection__in=ids).values_list('collection')
    counts = dict(qs.annotate(Count('id')))
    now = datetime.now()
    for collection_id, old_count in Collection.objects.filter(id__in=ids).values_list(
        'pk', 'addon_count'
    ):
        addon_count = counts.get(collection_id, 0)
        if addon_count == old_count:
            continue
        # We want to set addon_count & modified without triggering post_save
        # as it would cause an infinite loop (this task is called on
        # post_save). So we update queryset.update() and set modified ourselves
        # instead of relying on auto_now behaviour.
        Collection.objects.filter(id=collection_id).update(
            addon_count=addon_count, modified=now
        )
