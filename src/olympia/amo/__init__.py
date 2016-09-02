"""
Miscellaneous helpers that make Django compatible with AMO.
"""
import threading

import commonware.log
from product_details import product_details

from olympia.constants.applications import *  # noqa
from olympia.constants.base import *  # noqa
from olympia.constants.licenses import *  # noqa
from olympia.constants.payments import *  # noqa
from olympia.constants.platforms import *  # noqa
from olympia.constants.search import *  # noqa

from .log import (LOG, LOG_BY_ID, LOG_ADMINS, LOG_EDITOR_REVIEW_ACTION,  # noqa
                  LOG_EDITORS, LOG_HIDE_DEVELOPER, LOG_KEEP, LOG_REVIEW_QUEUE,
                  LOG_REVIEW_QUEUE_DEVELOPER, LOG_REVIEW_EMAIL_USER, log)


logger_log = commonware.log.getLogger('z.amo')

_locals = threading.local()
_locals.user = None


def get_user():
    return getattr(_locals, 'user', None)


def set_user(user):
    _locals.user = user


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
