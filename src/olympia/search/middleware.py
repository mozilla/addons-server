from elasticsearch import TransportError

import olympia.core.logger

from olympia.amo.utils import render


class ElasticsearchExceptionMiddleware(object):

    def process_exception(self, request, exception):
        if issubclass(exception.__class__, TransportError):
            log.exception(u'Elasticsearch error')
            return render(request, 'search/down.html', status=503)
