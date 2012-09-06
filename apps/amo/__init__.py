"""
Miscellaneous helpers that make Django compatible with AMO.
"""
import re
import threading

from django.conf import settings

import commonware.log

from product_details import product_details

from constants.applications import *
from constants.base import *
from constants.licenses import *
from constants.payments import *
from constants.platforms import *
from constants.search import *
from .log import (LOG, LOG_BY_ID, LOG_ADMINS, LOG_EDITORS,
                  LOG_HIDE_DEVELOPER, LOG_KEEP, LOG_REVIEW_QUEUE,
                  LOG_REVIEW_EMAIL_USER, log)

logger_log = commonware.log.getLogger('z.amo')

_locals = threading.local()
_locals.user = None


def get_user():
    return _locals.user


def set_user(user):
    _locals.user = user


def cached_property(*args, **kw):
    # Handles invocation as a direct decorator or
    # with intermediate keyword arguments.
    if args:  # @cached_property
        return CachedProperty(args[0])
    else:     # @cached_property(name=..., writable=...)
        return lambda f: CachedProperty(f, **kw)


class CachedProperty(object):
    """
    A decorator that converts a function into a lazy property.  The
    function wrapped is called the first time to retrieve the result
    and than that calculated result is used the next time you access
    the value::

        class Foo(object):

            @cached_property
            def foo(self):
                # calculate something important here
                return 42

    Lifted from werkzeug.
    """

    def __init__(self, func, name=None, doc=None, writable=False):
        self.func = func
        self.writable = writable
        self.__name__ = name or func.__name__
        self.__doc__ = doc or func.__doc__

    def __get__(self, obj, type=None):
        if obj is None:
            return self
        _missing = object()
        value = obj.__dict__.get(self.__name__, _missing)
        if value is _missing:
            value = self.func(obj)
            obj.__dict__[self.__name__] = value
        return value

    def __set__(self, obj, value):
        if not self.writable:
            raise TypeError('read only attribute')
        obj.__dict__[self.__name__] = value

# For unproven performance gains put firefox and thunderbird parsing
# here instead of constants
FIREFOX.latest_version = product_details.firefox_versions['LATEST_FIREFOX_VERSION']
THUNDERBIRD.latest_version = product_details.thunderbird_versions['LATEST_THUNDERBIRD_VERSION']
MOBILE.latest_version = FIREFOX.latest_version


def get_addon_search_types():
    types = ADDON_SEARCH_TYPES[:]
    if not settings.SEARCH_EXCLUDE_PERSONAS:
        types.append(ADDON_PERSONA)
    return types


def get_admin_search_types():
    types = get_addon_search_types()
    types.append(ADDON_PLUGIN)
    return types
