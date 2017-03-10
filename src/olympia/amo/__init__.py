"""
Miscellaneous helpers that make Django compatible with AMO.
"""
from product_details import product_details

import olympia.core.logger
from olympia.constants.activity import (  # noqa
    LOG, LOG_BY_ID, LOG_ADMINS, LOG_EDITOR_REVIEW_ACTION,
    LOG_EDITORS, LOG_HIDE_DEVELOPER, LOG_KEEP, LOG_REVIEW_QUEUE,
    LOG_REVIEW_QUEUE_DEVELOPER, LOG_REVIEW_EMAIL_USER)
from olympia.constants.applications import *  # noqa
from olympia.constants.base import *  # noqa
from olympia.constants.editors import *  # noqa
from olympia.constants.licenses import *  # noqa
from olympia.constants.payments import *  # noqa
from olympia.constants.platforms import *  # noqa
from olympia.constants.search import *  # noqa


logger_log = olympia.core.logger.getLogger('z.amo')


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

    Originally lifted from werkzeug. It's slighly more useful than the one in
    django because you can write/delete to the property to overwrite it or
    force it to be re-calculated.
    """

    def __init__(self, func, writable=False):
        self.func = func
        self.writable = writable
        self.__name__ = func.__name__
        self.__doc__ = func.__doc__

    def __delete__(self, obj):
        if not self.writable:
            raise TypeError('read only attribute')
        obj.__dict__.pop(self.__name__, None)

    def __get__(self, obj, type=None):
        if obj is None:
            return self
        _missing = object()
        value = obj.__dict__.get(self.__name__, _missing)
        if value is _missing:
            value = self.func(obj)
            from caching.base import CachingQuerySet
            if isinstance(value, CachingQuerySet):
                # Work around a bug in django-cache-machine that
                # causes deadlock or infinite recursion if
                # CachingQuerySets are cached before they run their
                # query.
                value._fetch_all()
            obj.__dict__[self.__name__] = value
        return value

    def __set__(self, obj, value):
        if not self.writable:
            raise TypeError('read only attribute')
        obj.__dict__[self.__name__] = value


# For unproven performance gains put firefox and thunderbird parsing
# here instead of constants
FIREFOX.latest_version = product_details.firefox_versions[
    'LATEST_FIREFOX_VERSION']
THUNDERBIRD.latest_version = product_details.thunderbird_versions[
    'LATEST_THUNDERBIRD_VERSION']
MOBILE.latest_version = FIREFOX.latest_version


# We need to import waffle here to avoid a circular import with jingo which
# loads all INSTALLED_APPS looking for helpers.py files, but some of those apps
# import jingo.
import waffle  # noqa
