"""
Miscellaneous helpers that make Django compatible with AMO.
"""
from product_details import product_details

import olympia.core.logger
from olympia.constants import permissions  # noqa
from olympia.constants.activity import (  # noqa
    LOG, LOG_BY_ID, LOG_ADMINS, LOG_REVIEWER_REVIEW_ACTION,
    LOG_RATING_MODERATION, LOG_HIDE_DEVELOPER, LOG_KEEP, LOG_REVIEW_QUEUE,
    LOG_REVIEW_QUEUE_DEVELOPER, LOG_REVIEW_EMAIL_USER)
from olympia.constants.applications import *  # noqa
from olympia.constants.base import *  # noqa
from olympia.constants.licenses import *  # noqa
from olympia.constants.platforms import *  # noqa
from olympia.constants.reviewers import *  # noqa
from olympia.constants.search import *  # noqa


# For unproven performance gains put firefox and thunderbird parsing
# here instead of constants
FIREFOX.latest_version = product_details.firefox_versions[
    'LATEST_FIREFOX_VERSION']
THUNDERBIRD.latest_version = product_details.thunderbird_versions[
    'LATEST_THUNDERBIRD_VERSION']
