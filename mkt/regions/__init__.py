from threading import local

from mkt.constants.regions import *


def get_region():
    return getattr(local(), 'region', WORLDWIDE.slug)


def get_region_id():
    return REGIONS_DICT[get_region()].id
