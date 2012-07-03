import re
import threading

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

app = threading.local()
non_host_chars = re.compile(r'[^a-zA-Z0-9\.-]+')

__all__ = ['site_url', 'subdomain']


def site_url():
    """
    Gets the full subdomain of the host serving the request.

    Example: https://marketplace.mozilla.org
    """
    if settings.SITE_URL_OVERRIDE:
        if not settings.DEBUG:
            raise ImproperlyConfigured('Cannot set SITE_URL_OVERRIDE in '
                                       'production; it is set from HTTP_HOST')
        return settings.SITE_URL_OVERRIDE
    try:
        return app.site_url
    except AttributeError:
        raise RuntimeError('Cannot access site_url() on a thread before a '
                           'request has been made')


def subdomain():
    """
    Gets the top-most subdomain of the host serving the request.

    Example telefonica from telefonica.marketplace.mozilla.org
    """
    try:
        return app.subdomain
    except AttributeError:
        raise RuntimeError('Cannot access site_url() on a thread before a '
                           'request has been made')


def set_host_info(host):
    # In case someone is messing with the host header, scrub it.
    host = non_host_chars.sub('', host)
    app.site_url = 'https://%s' % host
    app.subdomain = host.split('.')[0]
