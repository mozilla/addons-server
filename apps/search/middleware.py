import logging

from django.shortcuts import render

from pyes.exceptions import ElasticSearchException
from pyes.urllib3.connectionpool import HTTPError


log = logging.getLogger('z.es')


class ElasticsearchExceptionMiddleware(object):

    def process_exception(self, request, exception):
        if (issubclass(exception.__class__, (ElasticSearchException,
                                             HTTPError))):
            log.error(u'Elasticsearch error: %s' % exception)
            return render(request, 'search/down.html', status=503)
