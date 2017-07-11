from importlib import import_module
import logging
import logging.config
import os
import urllib

# get the right settings module
settingmodule = os.environ.get('DJANGO_SETTINGS_MODULE', 'settings_local')
if settingmodule.startswith(('zamboni',  # typical git clone destination
                             'workspace',  # Jenkins
                             'freddo')):
    settingmodule = settingmodule.split('.', 1)[1]


import posixpath
import re
import sys

import MySQLdb as mysql
import sqlalchemy.pool as pool

settings = import_module(settingmodule)

import olympia.core.logger
from olympia.lib.log_settings_base import formatters, handlers

# Ugh. But this avoids any olympia models or django imports at all.
# Perhaps we can import these without any problems and we can
# remove all this.
from olympia.constants.applications import APPS_ALL
from olympia.constants.platforms import PLATFORMS


# This is not DRY: it's a copy of amo.helpers.user_media_path, to avoid an
# import (which should triggers an import loop).
# See bug 1055654.
def user_media_path(what):
    """Make it possible to override storage paths in settings.

    By default, all storage paths are in the MEDIA_ROOT.

    This is backwards compatible.

    """
    default = os.path.join(settings.MEDIA_ROOT, what)
    key = "{0}_PATH".format(what.upper())
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
    default = '%s%s/' % (settings.MEDIA_URL, what)
    key = "{0}_URL".format(what.upper().replace('-', '_'))
    return getattr(settings, key, default)


APP_GUIDS = dict([(app.guid, app.id) for app in APPS_ALL.values()])
PLATFORMS = dict([(plat.api_name, plat.id) for plat in PLATFORMS.values()])

ADDON_SLUGS_UPDATE = {
    1: 'extension',
    2: 'theme',
    3: 'extension',
    4: 'search',
    5: 'item',
    6: 'extension',
    7: 'plugin'}


version_re = re.compile(r"""(?P<major>\d+)         # major (x in x.y)
                            \.(?P<minor1>\d+)      # minor1 (y in x.y)
                            \.?(?P<minor2>\d+|\*)? # minor2 (z in x.y.z)
                            \.?(?P<minor3>\d+|\*)? # minor3 (w in x.y.z.w)
                            (?P<alpha>[a|b]?)      # alpha/beta
                            (?P<alpha_ver>\d*)     # alpha/beta version
                            (?P<pre>pre)?          # pre release
                            (?P<pre_ver>\d)?       # pre release version
                          """, re.VERBOSE)


def get_cdn_url(id, row):
    host = user_media_url('addons')
    url = posixpath.join(host, str(id), row['filename'])
    params = urllib.urlencode({'filehash': row['hash']})
    return '{0}?{1}'.format(url, params)


def getconn():
    db = settings.SERVICES_DATABASE
    return mysql.connect(host=db['HOST'], user=db['USER'],
                         passwd=db['PASSWORD'], db=db['NAME'], charset='utf8')


mypool = pool.QueuePool(getconn, max_overflow=10, pool_size=5, recycle=300)


def log_configure():
    """You have to call this to explicitly configure logging."""
    cfg = {
        'version': 1,
        'filters': {},
        'formatters': dict(prod=formatters['prod']),
        'handlers': dict(syslog=handlers['syslog']),
        'loggers': {
            'z': {'handlers': ['syslog'], 'level': logging.INFO},
        },
        'root': {},
        # Since this configuration is applied at import time
        # in verify.py we don't want it to clobber other logs
        # when imported into the marketplace Django app.
        'disable_existing_loggers': False,
    }
    logging.config.dictConfig(cfg)


def log_exception(data):
    # Note: although this logs exceptions, it logs at the info level so that
    # on prod, we log at the error level and result in no logs on prod.
    typ, value, discard = sys.exc_info()
    error_log = olympia.core.logger.getLogger('z.update')
    error_log.exception(u'Type: %s, %s. Data: %s' % (typ, value, data))
