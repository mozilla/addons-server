import datetime
import os

from copy import deepcopy

from django.conf import settings
from django.core.management.base import CommandError

from elasticsearch import helpers

import olympia.core.logger

from olympia.amo import search as amo_search

from .models import Reindexing


# shortcut functions
is_reindexing_amo = Reindexing.objects.is_reindexing_amo
flag_reindexing_amo = Reindexing.objects.flag_reindexing_amo
unflag_reindexing_amo = Reindexing.objects.unflag_reindexing_amo
get_indices = Reindexing.objects.get_indices


def index_objects(ids, model, extract_func, index=None, transforms=None,
                  objects=None):
    if index is None:
        index = model._get_index()
    if objects is None:
        objects = model.objects

    indices = Reindexing.objects.get_indices(index)

    if transforms is None:
        transforms = []

    if hasattr(objects, 'no_cache'):
        qs = objects.no_cache()
    else:
        qs = objects
    qs = qs.filter(id__in=ids)
    for t in transforms:
        qs = qs.transform(t)

    bulk = []
    for ob in qs:
        data = extract_func(ob)
        for index in indices:
            bulk.append({
                "_source": data,
                "_id": ob.id,
                "_type": ob.get_mapping_type(),
                "_index": index
            })

    es = amo_search.get_es()
    return helpers.bulk(es, bulk)


def raise_if_reindex_in_progress(site):
    """Checks if the database indexation flag is on for the given site.

    If it's on, and if no "FORCE_INDEXING" variable is present in the env,
    raises a CommandError.
    """
    already_reindexing = Reindexing.objects._is_reindexing(site)
    if already_reindexing and 'FORCE_INDEXING' not in os.environ:
        raise CommandError("Indexation already occurring. Add a "
                           "FORCE_INDEXING variable in the environ "
                           "to force it")


def timestamp_index(index):
    """Return index-YYYYMMDDHHMMSS with the current time."""
    return '%s-%s' % (index, datetime.datetime.now().strftime('%Y%m%d%H%M%S'))


def create_index(index, config=None):
    """Create an index if it's not present.

    Return the index name.

    Options:

    - index: name of the index.
    - config: if provided, used when passing the configuration of the index to
    ES.
    """
    es = amo_search.get_es()

    if config is None:
        config = {}

    if 'settings' not in config:
        config['settings'] = {
            'index': {}
        }
    else:
        # Make a deepcopy of the settings in the config that was passed, so
        # that we can modify it freely to add shards and replicas settings.
        config['settings'] = deepcopy(config['settings'])

    config['settings']['index'].update({
        'number_of_shards': settings.ES_DEFAULT_NUM_SHARDS,
        'number_of_replicas': settings.ES_DEFAULT_NUM_REPLICAS,
        'max_result_window': settings.ES_MAX_RESULT_WINDOW,
    })

    if not es.indices.exists(index):
        es.indices.create(index, body=config)

    return index
