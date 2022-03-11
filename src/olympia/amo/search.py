from django.conf import settings

from elasticsearch import Elasticsearch


def get_es():
    """Create an ES object and return it."""
    return Elasticsearch(
        settings.ES_HOSTS, timeout=settings.ES_TIMEOUT, send_get_body_as='POST'
    )
