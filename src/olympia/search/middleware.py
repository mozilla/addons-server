from django.utils.deprecation import MiddlewareMixin

from elasticsearch import TransportError

import olympia.core.logger
from olympia.amo.utils import render


log = olympia.core.logger.getLogger('z.es')


class ElasticsearchExceptionMiddleware(MiddlewareMixin):

    def process_exception(self, request, exception):
        if issubclass(exception.__class__, TransportError):
            log.exception(u'Elasticsearch error')
            return render(request, 'search/down.html', status=503)
