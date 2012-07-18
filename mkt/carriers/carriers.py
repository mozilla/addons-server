from threading import local


__all__ = ['get_carrier', 'set_carrier']
_local = local()


def get_carrier():
    """
    Returns the name of the current carrier (or None) for the
    request lifecycle.

    Example: telefonica
    """
    return getattr(_local, 'carrier', None)


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
