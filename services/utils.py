import logging
import logging.config
import os
import posixpath
import re
import sys

import MySQLdb as mysql
import sqlalchemy.pool as pool

from urllib.parse import urlencode

from services.settings import settings

import olympia.core.logger


# This is not DRY: it's a copy of amo.helpers.user_media_path, to avoid an
# import (which should triggers an import loop).
# See bug 1055654.
def user_media_path(what):
    """Make it possible to override storage paths in settings.

    By default, all storage paths are in the MEDIA_ROOT.

    This is backwards compatible.

    """
    default = os.path.join(settings.MEDIA_ROOT, what)
    key = f'{what.upper()}_PATH'
    return getattr(settings, key, default)


# This is not DRY: it's a copy of amo.helpers.user_media_url, to avoid an
# import (which should be avoided, according to the comments above, and which
# triggers an import loop).
# See bug 1055654.
def user_media_url(what):
    """
    Generate default media url, and make possible to override it from
    settings.
    """
    default = f'{settings.MEDIA_URL}{what}/'
    key = '{}_URL'.format(what.upper().replace('-', '_'))
    return getattr(settings, key, default)


version_re = re.compile(
    r"""(?P<major>\d+)         # major (x in x.y)
                            \.(?P<minor1>\d+)      # minor1 (y in x.y)
                            \.?(?P<minor2>\d+|\*)? # minor2 (z in x.y.z)
                            \.?(?P<minor3>\d+|\*)? # minor3 (w in x.y.z.w)
                            (?P<alpha>[a|b]?)      # alpha/beta
                            (?P<alpha_ver>\d*)     # alpha/beta version
                            (?P<pre>pre)?          # pre release
                            (?P<pre_ver>\d)?       # pre release version
                          """,
    re.VERBOSE,
)


def get_cdn_url(id, row):
    host = user_media_url('addons')
    url = posixpath.join(host, str(id), row['filename'])
    params = urlencode({'filehash': row['hash']})
    return f'{url}?{params}'


def getconn():
    db = settings.SERVICES_DATABASE
    return mysql.connect(
        host=db['HOST'],
        user=db['USER'],
        passwd=db['PASSWORD'],
        db=db['NAME'],
        charset=db['OPTIONS']['charset'],
    )


mypool = pool.QueuePool(getconn, max_overflow=10, pool_size=5, recycle=300)


def log_configure():
    """You have to call this to explicitly configure logging."""
    cfg = {
        'version': 1,
        'filters': {},
        'handlers': {
            'mozlog': {
                'level': 'DEBUG',
                'class': 'logging.StreamHandler',
                'formatter': 'json',
            },
        },
        'formatters': {
            'json': {
                '()': olympia.core.logger.JsonFormatter,
                'logger_name': 'http_app_addons',
            },
        },
    }
    logging.config.dictConfig(cfg)


def log_exception(data):
    # Note: although this logs exceptions, it logs at the info level so that
    # on prod, we log at the error level and result in no logs on prod.
    typ, value, discard = sys.exc_info()
    error_log = olympia.core.logger.getLogger('z.update')
    error_log.exception(f'Type: {typ}, {value}. Data: {data}')
