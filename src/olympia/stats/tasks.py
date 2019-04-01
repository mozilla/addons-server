from elasticsearch.helpers import bulk as bulk_index

import olympia.core.logger

from olympia.amo import search as amo_search
from olympia.amo.celery import task

from . import search
from .models import DownloadCount, ThemeUserCount, UpdateCount


log = olympia.core.logger.getLogger('z.task')


@task
def index_update_counts(ids, index=None, **kw):
    index = index or search.get_alias()

    es = amo_search.get_es()
    qs = UpdateCount.objects.filter(id__in=ids)
    if qs.exists():
        log.info('Indexing %s updates for %s.' % (qs.count(), qs[0].date))
    data = []
    try:
        for update in qs:
            data.append(search.extract_update_count(update))
        bulk_index(es, data, index=index,
                   doc_type=UpdateCount.get_mapping_type(), refresh=True)
    except Exception as exc:
        index_update_counts.retry(args=[ids, index], exc=exc, **kw)
        raise


@task
def index_download_counts(ids, index=None, **kw):
    index = index or search.get_alias()

    es = amo_search.get_es()
    qs = DownloadCount.objects.filter(id__in=ids)

    if qs.exists():
        log.info('Indexing %s downloads for %s.' % (qs.count(), qs[0].date))
    try:
        data = []
        for dl in qs:
            data.append(search.extract_download_count(dl))
        bulk_index(es, data, index=index,
                   doc_type=DownloadCount.get_mapping_type(), refresh=True)
    except Exception as exc:
        index_download_counts.retry(args=[ids, index], exc=exc)
        raise


@task
def index_theme_user_counts(ids, index=None, **kw):
    index = index or search.get_alias()

    es = amo_search.get_es()
    qs = ThemeUserCount.objects.filter(id__in=ids)

    if qs.exists():
        log.info('Indexing %s theme user counts for %s.'
                 % (qs.count(), qs[0].date))
    data = []

    try:
        for user_count in qs:
            data.append(search.extract_theme_user_count(user_count))
        bulk_index(es, data, index=index,
                   doc_type=ThemeUserCount.get_mapping_type(), refresh=True)
    except Exception as exc:
        index_theme_user_counts.retry(args=[ids], exc=exc, **kw)
        raise
