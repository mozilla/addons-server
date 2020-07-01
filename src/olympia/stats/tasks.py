from elasticsearch.helpers import bulk as bulk_index

import olympia.core.logger

from olympia.amo import search as amo_search
from olympia.amo.celery import task

from .indexers import DownloadCountIndexer
from .models import DownloadCount


log = olympia.core.logger.getLogger('z.task')


@task
def index_download_counts(ids, index=None, **kw):
    index = index or DownloadCountIndexer.get_index_alias()

    es = amo_search.get_es()
    qs = DownloadCount.objects.filter(id__in=ids)

    if qs.exists():
        log.info('Indexing %s downloads for %s.' % (qs.count(), qs[0].date))
    try:
        data = []
        for obj in qs:
            data.append(DownloadCountIndexer.extract_document(obj))
        bulk_index(es, data, index=index,
                   doc_type=DownloadCountIndexer.get_doctype_name(),
                   refresh=True)
    except Exception as exc:
        index_download_counts.retry(args=[ids, index], exc=exc)
        raise
