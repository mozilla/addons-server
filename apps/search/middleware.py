import logging

from django.shortcuts import render

from elasticsearch import TransportError


log = logging.getLogger('z.es')


class ElasticsearchExceptionMiddleware(object):

    def process_exception(self, request, exception):
        if issubclass(exception.__class__, TransportError):
            log.error(u'Elasticsearch error: %s' % exception)
            return render(request, 'search/down.html', status=503)
