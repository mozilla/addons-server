"""
Miscellaneous helpers that make Django compatible with AMO.
"""
import threading

import commonware.log
from caching.base import CachingQuerySet

from product_details import product_details

from apps.search.utils import floor_version
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
    return getattr(_locals, 'user', None)


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
FIREFOX.latest_version = product_details.firefox_versions['LATEST_FIREFOX_VERSION']
THUNDERBIRD.latest_version = product_details.thunderbird_versions['LATEST_THUNDERBIRD_VERSION']
MOBILE.latest_version = FIREFOX.latest_version


# This is a list of dictionaries that we should generate compat info for.
# app: should match FIREFOX.id.
# main: the app version we're generating compat info for.
# versions: version numbers to show in comparisons.
# previous: the major version before :main.

if FIREFOX.latest_version:
    COMPAT = {FIREFOX.id: (), THUNDERBIRD.id: (), SEAMONKEY.id: ()}

    for app in (FIREFOX, THUNDERBIRD):
        for v in range(int(float(floor_version(app.latest_version))), 5, -1):
            v_str = floor_version(str(v))
            COMPAT[app.id] += ({
                'app': app.id,
                'main': v_str,
                'versions': (v_str, v_str + 'a2', v_str + 'a1'),
                'previous': floor_version(str(v - 1))
            },)

    # This is because the oldest Thunderbird version is 6.0, and
    # we need to include these older Firefox versions.
    COMPAT[FIREFOX.id] += (
        {'app': FIREFOX.id, 'main': '5.0', 'versions': ('5.0', '5.0a2', '5.0a1'),
         'previous': '4.0'},
        {'app': FIREFOX.id, 'main': '4.0', 'versions': ('4.0', '4.0a1', '3.7a'),
         'previous': '3.6'},
    )

    COMPAT[SEAMONKEY.id] = ({
        'app': SEAMONKEY.id,
        'main': '2.3',
        'versions': ('2.3', '2.3b', '2.3a'),
        'previous': '2.2'
    },)

    COMPAT = COMPAT[FIREFOX.id] + COMPAT[THUNDERBIRD.id] + COMPAT[SEAMONKEY.id]
    # Latest nightly version of Firefox.
    NIGHTLY_VERSION = COMPAT[0]['main']

    # Default minimum version of Firefox/Thunderbird for Add-on Packager.
    DEFAULT_MINVER = COMPAT[4]['main']
else:
    # Why don't you have `product_details` like the rest of us?
    logger_log.warning('You are missing `product_details`. '
                       'Run `python manage.py update_product_details` now.')

    COMPAT = {}
    NIGHTLY_VERSION = '17.0'
    DEFAULT_MINVER = '13.0'


# We need to import waffle here to avoid a circular import with jingo which
# loads all INSTALLED_APPS looking for helpers.py files, but some of those apps
# import jingo.
import waffle
