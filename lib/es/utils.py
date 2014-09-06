import os
import datetime
import logging

from django.core.management.base import CommandError
from django.conf import settings

from elasticsearch import helpers

import amo.search

from .models import Reindexing

log = logging.getLogger('z.es')

# shortcut functions
is_reindexing_amo = Reindexing.objects.is_reindexing_amo
flag_reindexing_amo = Reindexing.objects.flag_reindexing_amo
unflag_reindexing_amo = Reindexing.objects.unflag_reindexing_amo
get_indices = Reindexing.objects.get_indices


def index_objects(ids, model, search, index=None, transforms=None):
    if index is None:
        index = model._get_index()

    indices = Reindexing.objects.get_indices(index)

    if transforms is None:
        transforms = []

    qs = model.objects.no_cache().filter(id__in=ids)
    for t in transforms:
        qs = qs.transform(t)

    bulk = []
    for ob in qs:
        data = search.extract(ob)
        for index in indices:
            bulk.append({
                "_source": data,
                "_id": ob.id,
                "_type": ob.get_mapping_type(),
                "_index": index
            })

    es = amo.search.get_es()
    return helpers.bulk(es, bulk)


def raise_if_reindex_in_progress(site):
    """Checks if the database indexation flag is on for the given site.

    If it's on, and if no "FORCE_INDEXING" variable is present in the env,
    raises a CommandError.
    """
    already_reindexing = Reindexing.objects._is_reindexing(site)
    if already_reindexing and 'FORCE_INDEXING' not in os.environ:
        raise CommandError("Indexation already occuring. Add a FORCE_INDEXING "
                           "variable in the environ to force it")


def timestamp_index(index):
    """Returns index-YYYYMMDDHHMMSS with the current time."""
    return '%s-%s' % (index, datetime.datetime.now().strftime('%Y%m%d%H%M%S'))


def create_index(index, config=None):
    """Creates an index if it's not present.

    Returns the index name.

    Options:

    - index: name of the index.
    - config: if provided, used as the settings option for the
      ES calls.
    """
    es = amo.search.get_es()

    if settings.IN_TEST_SUITE:
        if not config:
            config = {}
        # Be nice to ES running on ci.mozilla.org
        config.update({
            'number_of_shards': 3,
            'number_of_replicas': 0
        })

    if not es.indices.exists(index):
        es.indices.create(index, body=config, ignore=400)

    return index
