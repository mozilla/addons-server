"""Test addon performance.

For more information on the parameters and values that the performance
testing service accepts, see
https://intranet.mozilla.org/Anodelman:doc:TriggerSendchange
"""
import logging
import urllib
from urllib2 import urlopen

from django.conf import settings

import amo


log = logging.getLogger('z.devhub.task')


# These are all the apps available for a file to be tested against:
ALL_APPS = ('firefox3.6', 'firefox6.0')

# This translates AMO platforms into performance service platforms:
PLATFORM_MAP = {amo.PLATFORM_LINUX.id: ('linux',),
                amo.PLATFORM_WIN.id: ('win32',),
                amo.PLATFORM_MAC.id: ('macosx64',)}
PLATFORM_MAP[amo.PLATFORM_ALL.id] = (PLATFORM_MAP[amo.PLATFORM_LINUX.id] +
                                     PLATFORM_MAP[amo.PLATFORM_WIN.id] +
                                     PLATFORM_MAP[amo.PLATFORM_MAC.id])


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
                  url=file_.get_url_path('perftest'),
                  addon=file_.version.addon_id)
    url = '%s?%s' % (settings.PERF_TEST_URL, urllib.urlencode(params))
    res = None
    try:
        res = urlopen(url, None, settings.PERF_TEST_TIMEOUT)
        ok = False
        for line in res:
            log.debug('PERF TEST line: %s' % line)
            if line.startswith('ERROR'):
                raise BadResponse(line)
            if line.startswith('SENDCHANGE: change sent successfully'):
                ok = True
        if not ok:
            raise BadResponse('no SENDCHANGE found in response')
    except Exception, exc:
        log.info('perf test exception %s: %s at URL %s'
                 % (exc.__class__.__name__, exc, url))
        raise
    finally:
        if res:
            res.close()


start_perf_test.__test__ = False  # not for Nose
