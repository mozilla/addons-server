from django.conf import settings as dj_settings

from elasticsearch import Elasticsearch

import olympia.core.logger


log = olympia.core.logger.getLogger('z.es')


DEFAULT_HOSTS = ['localhost:9200']
DEFAULT_TIMEOUT = 5


def get_es(hosts=None, timeout=None, **settings):
    """Create an ES object and return it."""
    # Cheap way of de-None-ifying things
    hosts = hosts or getattr(dj_settings, 'ES_HOSTS', DEFAULT_HOSTS)
    timeout = (
        timeout
        if timeout is not None
        else getattr(dj_settings, 'ES_TIMEOUT', DEFAULT_TIMEOUT)
    )

    return Elasticsearch(hosts, timeout=timeout, **settings)
