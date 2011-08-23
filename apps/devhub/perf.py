"""Test addon performance."""
import logging
import urllib
from urllib2 import urlopen

from django.conf import settings


log = logging.getLogger('z.devhub.task')


class BadResponse(Exception):
    """An error response was returned from the web service."""


def start_perf_test(file_, os_name, firefox):
    """Start performance tests for this addon file.

    Arguments

    *file*
        File object
    *os_name*
        Operating system to run performance tests on.
        See docs for recognized values.
    *firefox*
        The release of firefox to be tested against.
        See docs for recognized values.

    Documentation for the performance testing service:
    https://intranet.mozilla.org/Anodelman:doc:TriggerSendchange
    """
    params = dict(os=os_name, firefox=firefox,
                  url=file_.get_url_path('perftest'))
    url = '%s?%s' % (settings.PERF_TEST_URL, urllib.urlencode(params))
    timeout = 10
    res = urlopen(url, None, timeout)
    try:
        log.info('PERF TEST started for version %s at %s'
                 % (file_.version, url))
        ok = False
        for line in res:
            log.debug('PERF TEST line: %s' % line)
            if line.startswith('ERROR'):
                raise BadResponse(line)
            if line.startswith('SENDCHANGE: change sent successfully'):
                ok = True
        if not ok:
            raise BadResponse('no SENDCHANGE found in response')
    finally:
        res.close()


start_perf_test.__test__ = False  # not for Nose
