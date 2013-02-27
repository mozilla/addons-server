from threading import local

import mkt.constants.carriers
from mkt.constants.carriers import CARRIERS


__all__ = ['get_carrier', 'get_carrier_id', 'set_carrier']
_local = local()


def get_carrier():
    """
    Returns the name of the current carrier (or None) for the
    request lifecycle.

    Example: telefonica
    """
    return getattr(_local, 'carrier', None)


def get_carrier_id():
    """Returns the carrier ID for the request lifecycle."""
    carrier = get_carrier()
    if carrier is None:
        return carrier

    for carr in CARRIERS:
        if carr.slug == carrier:
            return carr.id

    return mkt.constants.carriers.UNKNOWN_CARRIER.id


def set_carrier(name):
    """
    Sets the name of the carrier for the current request lifecycle.
    """
    _local.carrier = name


class CarrierPrefixer:

    def __init__(self, request, carrier):
        self.request = request
        self.carrier = carrier

    def fix(self, path):
        url_parts = [self.request.META['SCRIPT_NAME'], self.carrier,
                     path.lstrip('/')]
        return '/'.join(url_parts)
