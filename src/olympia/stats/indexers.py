from datetime import timedelta

from django.db.models import Max, Min

from celery import group

from olympia.lib.es.utils import create_index
from olympia.amo.celery import create_chunked_tasks_signatures
from olympia.amo.indexers import BaseSearchIndexer


class StatsIndexer(BaseSearchIndexer):
    # Number of elements to index at once in ES. The size of a dict to send to
    # ES should be less than 1000 bytes, and the max size of messages to send
    # to ES can be retrieved with the following command (look for
    # "max_content_length_in_bytes"): curl http://HOST:PORT/_nodes/?pretty
    CHUNK_SIZE = 5000

    # Number of days to process at once when doing a full reindex.
    FULL_REINDEX_DAYS_SLICE = 6

    @classmethod
    def es_dict(cls, items):
        if not items:
            return {}
        if hasattr(items, 'items'):
            items = items.items()
        return [{'k': key, 'v': value} for key, value in items]

    @classmethod
    def get_mapping(cls):
        return {
            'properties': {
                'id': {'type': 'long'},
                'boost': {'type': 'float', 'null_value': 1.0},
                'count': {'type': 'long'},
                'data': {
                    'dynamic': 'true',
                    'properties': {
                        'v': {'type': 'long'},
                        'k': {'type': 'keyword'}
                    }
                },
                'date': {
                    'format': 'dateOptionalTime',
                    'type': 'date'
                }
            }
        }

    @classmethod
    def create_new_index(cls, index_name):
        config = {
            'mappings': {
                cls.get_doctype_name(): cls.get_mapping()
            }
        }
        create_index(index_name, config)

    @classmethod
    def reindex_tasks_group(cls, index_name, addons=None, dates=None):
        """
        Return tasks group to execute to index statistics for the given
        index/dates/addons.
        """
        def get_indexing_tasks_for_qs(qs):
            index_data_tasks = create_chunked_tasks_signatures(
                cls.get_indexing_task(), qs, cls.CHUNK_SIZE,
                task_args=(index_name,))
            # Unwrap the tasks from the group create_chunked_tasks_signatures()
            # returned, we'll create our own flat group with all the tasks,
            # no need to create unnecessary nesting.
            return index_data_tasks.tasks

        qs = cls.get_model().objects.all()
        tasks = []

        if dates or addons:
            qs = qs.order_by('-date')

        qs = qs.values_list('id', flat=True)

        if addons:
            pks = [int(a.strip()) for a in addons.split(',')]
            qs = qs.filter(addon__in=pks)

        if dates:
            if ':' in dates:
                qs = qs.filter(date__range=dates.split(':'))
            else:
                qs = qs.filter(date=dates)

        if not (dates or addons):
            # We're loading the whole world. Do it in stages so we get most
            # recent stats first and don't do huge queries.
            limits = (qs.model.objects.filter(date__isnull=False)
                      .extra(where=['date <> "0000-00-00"'])
                      .aggregate(min=Min('date'), max=Max('date')))
            # If there isn't any data at all, skip over.
            if limits['max'] and limits['min']:
                num_days = (limits['max'] - limits['min']).days
                # We'll re-assign `qs` in each iteration of the loop, so keep a
                # copy around before that will be the base queryset to filter
                # from.
                base_qs = qs
                for start in range(0, num_days, cls.FULL_REINDEX_DAYS_SLICE):
                    stop = start + cls.FULL_REINDEX_DAYS_SLICE - 1
                    date_range = (limits['max'] - timedelta(days=stop),
                                  limits['max'] - timedelta(days=start))
                    qs = base_qs.filter(date__range=date_range)
                    if qs.exists():
                        tasks.extend(get_indexing_tasks_for_qs(qs))
        else:
            if qs.exists():
                tasks.extend(get_indexing_tasks_for_qs(qs))
        return group(tasks)


class DownloadCountIndexer(StatsIndexer):
    @classmethod
    def get_model(cls):
        from olympia.stats.models import DownloadCount
        return DownloadCount

    @classmethod
    def get_indexing_task(cls):
        from olympia.stats.tasks import index_download_counts
        return index_download_counts

    @classmethod
    def extract_document(cls, obj):
        return {
            'addon': obj.addon_id,
            'date': obj.date,
            'count': obj.count,
            'sources': cls.es_dict(obj.sources) if obj.sources else {},
            'id': obj.id,
            '_id': '{0}-{1}'.format(obj.addon_id, obj.date)
        }
