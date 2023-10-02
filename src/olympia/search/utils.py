import datetime
import os
from copy import deepcopy

from django.conf import settings
from django.core.management.base import CommandError

from elasticsearch import Elasticsearch, TransportError, helpers, transport

from .models import Reindexing


class AlreadyVerifiedTransport(transport.Transport):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Pretend we've already done the verification request that would
        # normally be made by elasticsearch client 7.14+ once per connection
        # before the first request. We're using a genuine ES cluster but we
        # don't want the extra request.
        self._verified_elasticsearch = True


def get_es():
    """Create an ES object and return it."""
    return Elasticsearch(
        settings.ES_HOST,
        timeout=settings.ES_TIMEOUT,
        transport_class=AlreadyVerifiedTransport,
    )


def index_objects(*, queryset, indexer_class, index=None):
    """
    Index objects in provided queryset in ES using `indexer_class`. This is done in a
    single bulk action.

    Pass `index` to index on the specific index instead of the default index
    alias from the `indexed_class`.

    Unless an `index` is specified, if a reindexing is taking place for the
    default index then this function will index on both the old and new indices
    to allow indexing to still work while reindexing isn't complete yet.
    """
    if index is None:
        index = indexer_class.get_index_alias()
        # If we didn't have an index passed as argument, then we should index
        # on both old and new indexes during a reindex.
        indices = Reindexing.objects.get_indices(index)
    else:
        # If we did have an index passed then the caller wanted us to only
        # consider the index they specified, so we only consider that one.
        indices = [index]

    bulk = []
    es = get_es()

    for obj in queryset.order_by('pk'):
        data = indexer_class.extract_document(obj)
        for index in indices:
            item = {
                '_source': data,
                '_id': obj.id,
                '_index': index,
            }
            bulk.append(item)

    helpers.bulk(es, bulk)


def unindex_objects(ids, indexer_class):
    es = get_es()
    index = indexer_class.get_index_alias()
    for id_ in ids:
        try:
            es.delete(index=index, id=id_)
        except TransportError:
            # We ignore already deleted objects.
            pass


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


def create_index(*, index, mappings, index_settings=None):
    """Create an index if it's not present.

    Return the index name.

    Options:

    - index: name of the index.
    - mappings and index_settings: if provided, used when passing the
    configuration of the index to ES.
    """
    es = get_es()

    if index_settings is None:
        index_settings = {'index': {}}
    else:
        # Make a deepcopy of the settings that was passed, so that we can
        # modify it freely to add shards and replicas settings.
        index_settings = deepcopy(index_settings)

    index_settings['index'].update(
        {
            'number_of_shards': settings.ES_DEFAULT_NUM_SHARDS,
            'number_of_replicas': settings.ES_DEFAULT_NUM_REPLICAS,
            'max_result_window': settings.ES_MAX_RESULT_WINDOW,
        }
    )
    if not es.indices.exists(index=index):
        es.indices.create(index=index, mappings=mappings, settings=index_settings)

    return index
