from threading import local

from mkt.constants.regions import *
from mkt.regions.utils import parse_region


_local = local()


def get_region():
    """Get the region for the current request lifecycle."""
    return parse_region(getattr(_local, 'region', '')) or RESTOFWORLD


def set_region(region):
    """Set the region for the current request lifecycle."""
    _local.region = region
