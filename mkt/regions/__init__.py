from threading import local

from mkt.constants.regions import *


_local = local()


def get_region():
    return getattr(_local, 'region', RESTOFWORLD.slug)


def get_region_id():
    return REGIONS_DICT[get_region()].id


def set_region(slug):
    """
    Sets the slug of the region for the current request lifecycle.
    """
    _local.region = slug
