import datetime
import os

from copy import deepcopy

from django.conf import settings
from django.core.management.base import CommandError

from elasticsearch import helpers

import olympia.core.logger

from olympia.amo import search as amo_search

from .models import Reindexing


log = olympia.core.logger.getLogger('z.es')


def get_major_version(es):
    return int(es.info()['version']['number'].split('.')[0])


def index_objects(
    *, ids, indexer_class, index=None, transforms=None, manager_name=None
):
    if index is None:
        index = indexer_class.get_index_alias()
    if manager_name is None:
        manager_name = 'objects'

    manager = getattr(indexer_class.get_model(), manager_name)
    indices = Reindexing.objects.get_indices(index)

    if transforms is None:
        transforms = []

    qs = manager.filter(id__in=ids)
    for transform in transforms:
        qs = qs.transform(transform)

    bulk = []
    es = amo_search.get_es()

    major_version = get_major_version(es)
    for obj in qs:
        data = indexer_class.extract_document(obj)
        for index in indices:
            item = {
                '_source': data,
                '_id': obj.id,
                '_index': index,
            }
            if major_version < 7:
                # While on 6.x, we use the `addons` type when creating indices
                # and when bulk-indexing. We completely ignore it on searches.
                # When on 7.x, we don't pass type at all at creation or
                # indexing, and continue to ignore it on searches.
                # That should ensure we're compatible with both transparently.
                item['_type'] = 'addons'
            bulk.append(item)

    return helpers.bulk(es, bulk)


def raise_if_reindex_in_progress(site):
    """Checks if the database indexation flag is on for the given site.

    If it's on, and if no "FORCE_INDEXING" variable is present in the env,
    raises a CommandError.
    """
    already_reindexing = Reindexing.objects.is_reindexing(site)
    if already_reindexing and 'FORCE_INDEXING' not in os.environ:
        raise CommandError(
            'Indexation already occurring. Add a '
            'FORCE_INDEXING variable in the environ '
            'to force it'
        )


def timestamp_index(index):
    """Return index-YYYYMMDDHHMMSS with the current time."""
    return '{}-{}'.format(index, datetime.datetime.now().strftime('%Y%m%d%H%M%S'))


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
        config['settings'] = {'index': {}}
    else:
        # Make a deepcopy of the settings in the config that was passed, so
        # that we can modify it freely to add shards and replicas settings.
        config['settings'] = deepcopy(config['settings'])

    config['settings']['index'].update(
        {
            'number_of_shards': settings.ES_DEFAULT_NUM_SHARDS,
            'number_of_replicas': settings.ES_DEFAULT_NUM_REPLICAS,
            'max_result_window': settings.ES_MAX_RESULT_WINDOW,
        }
    )
    major_version = get_major_version(es)
    if not es.indices.exists(index):
        # See above, while on 6.x the mapping needs to include the `addons` doc
        # type.
        if major_version < 7:
            config['mappings'] = {'addons': config['mappings']}
        es.indices.create(index, body=config)

    return index
