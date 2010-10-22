import contextlib
import socket
import urllib
import urlparse

from django.conf import settings
from django.utils.http import urlencode


def check_paypal_id(name):
    """
    Use the button API to check if name is a valid Paypal id.

    Returns bool(valid), str(msg).  msg will be None if there wasn't an error.
    """
    d = dict(user=settings.PAYPAL_USER,
             pwd=settings.PAYPAL_PASSWORD,
             signature=settings.PAYPAL_SIGNATURE,
             version=settings.PAYPAL_API_VERSION,
             buttoncode='cleartext',
             buttontype='donate',
             method='BMCreateButton',
             l_buttonvar0='business=%s' % name)
    with socket_timeout(10):
        r = urllib.urlopen(settings.PAYPAL_API_URL, urlencode(d))
    response = dict(urlparse.parse_qsl(r.read()))
    valid = response['ACK'] == 'Success'
    msg = None if valid else response['L_LONGMESSAGE0']
    return valid, msg


@contextlib.contextmanager
def socket_timeout(timeout):
    """Context manager to temporarily set the default socket timeout."""
    old = socket.getdefaulttimeout()
    try:
        yield
    finally:
        socket.setdefaulttimeout(old)
