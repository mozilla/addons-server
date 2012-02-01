from datetime import datetime, timedelta
import settings_local as settings
import posixpath
import re
import sys

import MySQLdb as mysql
import sqlalchemy.pool as pool

from django.core.management import setup_environ
import commonware.log

# Pyflakes will complain about these, but they are required for setup.
import settings_local as settings
setup_environ(settings)
from lib import log_settings_base

# Ugh. But this avoids any zamboni or django imports at all.
# Perhaps we can import these without any problems and we can
# remove all this.
from constants.applications import APPS_ALL
from constants.platforms import PLATFORMS
from constants.base import (STATUS_PUBLIC, STATUS_DISABLED, STATUS_BETA,
                            STATUS_LITE, STATUS_LITE_AND_NOMINATED)
from constants.payments import (CONTRIB_CHARGEBACK, CONTRIB_PURCHASE,
                                CONTRIB_REFUND)

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


STATUSES_PUBLIC = {'STATUS_PUBLIC': STATUS_PUBLIC,
                   'STATUS_LITE': STATUS_LITE,
                   'STATUS_LITE_AND_NOMINATED': STATUS_LITE_AND_NOMINATED}


version_re = re.compile(r"""(?P<major>\d+)         # major (x in x.y)
                            \.(?P<minor1>\d+)      # minor1 (y in x.y)
                            \.?(?P<minor2>\d+|\*)? # minor2 (z in x.y.z)
                            \.?(?P<minor3>\d+|\*)? # minor3 (w in x.y.z.w)
                            (?P<alpha>[a|b]?)      # alpha/beta
                            (?P<alpha_ver>\d*)     # alpha/beta version
                            (?P<pre>pre)?          # pre release
                            (?P<pre_ver>\d)?       # pre release version""",
                        re.VERBOSE)


def get_mirror(status, id, row):
    if row['datestatuschanged']:
        published = datetime.now() - row['datestatuschanged']
    else:
        published = timedelta(minutes=0)

    if row['disabled_by_user'] or status == STATUS_DISABLED:
        host = settings.PRIVATE_MIRROR_URL
    elif (status == STATUS_PUBLIC
          and not row['disabled_by_user']
          and row['file_status'] in (STATUS_PUBLIC, STATUS_BETA)
          and published > timedelta(minutes=settings.MIRROR_DELAY)
          and not settings.DEBUG):
        host = settings.MIRROR_URL
    else:
        host = settings.LOCAL_MIRROR_URL

    return posixpath.join(host, str(id), row['filename'])


def getconn():
    db = settings.SERVICES_DATABASE
    return mysql.connect(host=db['HOST'], user=db['USER'],
                         passwd=db['PASSWORD'], db=db['NAME'])


mypool = pool.QueuePool(getconn, max_overflow=10, pool_size=5, recycle=300)


error_log = commonware.log.getLogger('z.services')


def log_exception(data):
    (typ, value, discard) = sys.exc_info()
    error_log.error(u'Type: %s, %s. Data: %s' % (typ, value, data))


def log_info(data, msg):
    error_log.info(u'Msg: %s, Data: %s' % (msg, data))
